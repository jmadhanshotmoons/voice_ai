"""CallSession -- orchestrates one call through the voice pipeline.

Audio in -> VAD -> ASR -> LLM (streamed) -> TTS (per sentence) -> audio out

Built for natural turn-taking:
- The call loop never blocks. A turn (transcribe, think, speak) runs as a
  background task, so the caller is heard the whole time.
- The model's reply is streamed and spoken sentence by sentence; speech starts
  when the first sentence is written, not when the whole reply is done.
- If the caller keeps talking before the agent has started to answer, the
  pending turn is dropped and merged into what they are still saying.
- If the caller cuts in while the agent is speaking, the agent stops at once
  and remembers only what it actually got to say.
- A short spoken acknowledgement covers the rare slow turn.
"""

import asyncio
import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import structlog
from fastapi import WebSocket

from src.enhance.rules import build_enhance_prompt
from src.models.schemas import AgentConfig
from src.pipeline.vad import EnergyVAD, VADConfig, VADEvent
from src.providers.llm import ConversationMessage
from src.providers.pool import get_asr, get_llm, get_tts
from src.providers.tts import TTSConfig
from src.utils.audio import b64_to_pcm16, pcm16_to_b64, split_audio_chunks

logger = structlog.get_logger()

_NON_SPEECH = re.compile("[🀀-🫿☀-➿️*_#`>]+")


def clean_for_speech(text: str) -> str:
    """Strip emoji/markdown the LLM sometimes adds; TTS would read them aloud."""
    return re.sub(r"\s+", " ", _NON_SPEECH.sub("", text)).strip()


LANGUAGE_NAMES = {
    "hi-IN": "Hindi", "te-IN": "Telugu", "ta-IN": "Tamil", "kn-IN": "Kannada",
    "ml-IN": "Malayalam", "mr-IN": "Marathi", "en-IN": "English",
}

# Short acknowledgements, pre-synthesised at call start and played only if a
# reply is slow. Native script so the voice pronounces them correctly.
FILLERS = {
    "te-IN": ["అవునండి.", "సరేనండి.", "ఓహో, అలాగా."],
    "hi-IN": ["हाँ जी।", "जी, बिल्कुल।", "अच्छा, ठीक है।"],
    "ta-IN": ["ஆமாம்.", "சரி.", "ஓ, அப்படியா."],
    "kn-IN": ["ಹೌದು.", "ಸರಿ.", "ಓ, ಹೌದಾ."],
    "ml-IN": ["അതെ.", "ശരി.", "ഓ, അങ്ങനെയാണോ."],
    "mr-IN": ["हो.", "बरोबर.", "अच्छा, ठीक आहे."],
    "en-IN": ["Right.", "I see.", "Sure."],
}

# Turn-taking knobs
SILENCE_END_MS = 400        # quiet needed to decide the caller has finished
MIN_SPEECH_MS = 270         # speech needed to count as the caller talking (also gates barge-in)
KEEP_TRAILING_SILENCE_MS = 150
PREROLL_FRAMES = 16         # 480 ms of audio kept from before speech was detected
MIN_UTTERANCE_MS = 300      # ignore blips shorter than this
FILLER_AFTER_S = 1.5        # play an acknowledgement if no reply audio by then
SAMPLE_RATE = 16000
BYTES_PER_MS = SAMPLE_RATE * 2 // 1000

_BOUNDARY = ".!?।॥\n"
_SOFT_BOUNDARY = ",;:—"


def pop_chunks(buf: str, first: bool) -> tuple[list[str], str]:
    """Cut complete speakable chunks off the front of a streaming text buffer.

    A chunk ends at a sentence mark followed by whitespace. The very first chunk
    of a reply may also end at a comma, so speech starts a little earlier.
    """
    chunks: list[str] = []
    start = 0
    for i, ch in enumerate(buf[:-1]):
        nxt = buf[i + 1]
        hard = ch in _BOUNDARY and (nxt.isspace() or ch == "\n")
        soft = first and not chunks and ch in _SOFT_BOUNDARY and nxt.isspace() and i - start >= 18
        if (hard and i - start >= 6) or soft:
            chunks.append(buf[start : i + 1].strip())
            start = i + 1
    return [c for c in chunks if c], buf[start:]


@dataclass
class CallState:
    call_id: str
    started_at: float = 0.0
    duration_s: float = 0.0
    is_active: bool = True
    turn_count: int = 0
    conversation: list = field(default_factory=list)
    captured_fields: dict = field(default_factory=dict)
    transcript: list = field(default_factory=list)
    credits_used: float = 0.0
    ai_actions: int = 0


class CallSession:
    def __init__(self, ws: WebSocket, call_id: str, agent_config: AgentConfig):
        self.ws = ws
        self.call_id = call_id
        self.agent = agent_config
        self.state = CallState(call_id=call_id, started_at=time.time())

        self.vad = EnergyVAD(VADConfig(silence_duration_ms=SILENCE_END_MS, min_speech_ms=MIN_SPEECH_MS))
        self.asr = get_asr()
        self.llm = get_llm()
        self.tts = get_tts()
        self.tts_config = TTSConfig(
            provider=agent_config.voice_provider,
            voice_id=agent_config.voice_id,
            language=agent_config.language,
        )

        self.speech_buffer = bytearray()
        self._preroll: deque = deque(maxlen=PREROLL_FRAMES)
        self.summary = ""

        self._speak_task: Optional[asyncio.Task] = None   # greeting / wrap-up
        self._turn_task: Optional[asyncio.Task] = None    # one caller turn: ASR -> LLM -> speech
        self._filler_task: Optional[asyncio.Task] = None
        self._fillers: list[bytes] = []
        self._fillers_task: Optional[asyncio.Task] = None
        self._last_filler_turn = -10

        self._turn_audio = b""
        self._turn_user_added = False
        self._turn_end_t = 0.0
        self._reply_started = False
        self._spoken: list[str] = []

        # Wall-clock time the caller's device finishes playing queued agent audio.
        # TTS is sent faster than realtime, so barge-in is judged against this.
        self._speaking_until = 0.0

        logger.info("session_created", call_id=call_id, agent=agent_config.name)

    # ───────────────────────── main loop ─────────────────────────

    async def run(self):
        # The greeting is the first thing the agent said: keep it in the history so the
        # model continues the call instead of greeting again.
        self.state.conversation.append(ConversationMessage(role="assistant", content=self.agent.greeting))
        self.state.transcript.append({"role": "assistant", "text": self.agent.greeting, "ts": 0.0})
        try:
            await self.ws.send_json({"type": "transcript", "role": "assistant", "text": self.agent.greeting})
        except Exception:
            pass
        self._start_speaking(self.agent.greeting)
        self._fillers_task = asyncio.create_task(self._prepare_fillers())

        try:
            while self.state.is_active:
                if time.time() - self.state.started_at > self.agent.max_call_duration_s:
                    await self._speak("I need to wrap up now. Thank you for your time!")
                    await asyncio.sleep(max(0.0, self._speaking_until - time.time()))
                    break

                try:
                    raw = await asyncio.wait_for(self.ws.receive_text(), timeout=30.0)
                    msg = json.loads(raw)
                except asyncio.TimeoutError:
                    break

                if msg.get("type") == "audio":
                    await self._handle_audio(msg["data"])
                elif msg.get("type") == "hangup":
                    break

        except Exception as e:
            logger.error("session_error", call_id=self.call_id, error=str(e))
        finally:
            for t in (self._speak_task, self._turn_task, self._filler_task, self._fillers_task):
                if t:
                    t.cancel()
            self.state.is_active = False
            self.state.duration_s = time.time() - self.state.started_at
            await self._send_call_ended()

    # ───────────────────────── listening ─────────────────────────

    async def _handle_audio(self, audio_b64: str):
        pcm16 = b64_to_pcm16(audio_b64)
        for frame in split_audio_chunks(pcm16, chunk_size_ms=30, sample_rate=SAMPLE_RATE):
            self._preroll.append(frame)
            event = self.vad.process_frame(frame)

            if event == VADEvent.SPEECH_START:
                if self._agent_speaking():
                    await self._barge_in()
                    self.speech_buffer = bytearray(b"".join(self._preroll))
                elif self._turn_in_flight():
                    # The caller is still talking and we have not answered yet:
                    # drop the pending turn and treat it all as one utterance.
                    self._drop_pending_turn()
                    self.speech_buffer = bytearray(self._turn_audio + b"".join(self._preroll))
                    logger.debug("turn_merged", call_id=self.call_id)
                else:
                    self.speech_buffer = bytearray(b"".join(self._preroll))
            elif event == VADEvent.SPEECH_CONTINUE:
                self.speech_buffer.extend(frame)
            elif event == VADEvent.TURN_COMPLETE:
                self.speech_buffer.extend(frame)
                self._begin_turn()

    def _turn_in_flight(self) -> bool:
        return bool(self._turn_task and not self._turn_task.done())

    def _drop_pending_turn(self):
        if self._turn_task:
            self._turn_task.cancel()
        if self._filler_task:
            self._filler_task.cancel()
        if self._turn_user_added:
            # take back the caller line we already logged for this unanswered turn
            if self.state.conversation and self.state.conversation[-1].role == "user":
                self.state.conversation.pop()
            if self.state.transcript and self.state.transcript[-1]["role"] == "user":
                self.state.transcript.pop()
            self.state.turn_count = max(0, self.state.turn_count - 1)
            self._turn_user_added = False
            asyncio.create_task(self.ws.send_json({"type": "transcript_undo", "role": "user"}))

    async def _barge_in(self):
        """Caller spoke over the agent: stop talking right now."""
        logger.debug("barge_in", call_id=self.call_id)
        for t in (self._speak_task, self._turn_task, self._filler_task):
            if t:
                t.cancel()
        self._speaking_until = 0.0
        await self.ws.send_json({"type": "clear"})
        self.speech_buffer.clear()

    def _begin_turn(self):
        audio = bytes(self.speech_buffer)
        self.speech_buffer.clear()
        # Keep only a short tail of the silence that ended the turn: less audio to transcribe
        trim = (SILENCE_END_MS - KEEP_TRAILING_SILENCE_MS) * BYTES_PER_MS
        if len(audio) > trim:
            audio = audio[:-trim]
        if len(audio) < MIN_UTTERANCE_MS * BYTES_PER_MS:
            return

        self._turn_audio = audio
        self._turn_user_added = False
        self._turn_end_t = time.time()
        self._reply_started = False
        self._turn_task = asyncio.create_task(self._run_turn(audio))
        self._filler_task = asyncio.create_task(self._filler_if_slow())

    # ───────────────────────── one turn ─────────────────────────

    async def _run_turn(self, audio: bytes):
        marks = {"end": self._turn_end_t}
        transcript = await self.asr.transcribe(audio, sample_rate=SAMPLE_RATE, language=self.agent.language)
        marks["asr"] = time.time()
        text = transcript.text.strip()
        if not text:
            if self._filler_task:
                self._filler_task.cancel()
            return

        self.state.turn_count += 1
        self.state.conversation.append(ConversationMessage(role="user", content=text))
        self.state.transcript.append({"role": "user", "text": text, "ts": time.time() - self.state.started_at})
        self._turn_user_added = True
        await self.ws.send_json({"type": "transcript", "role": "user", "text": text})

        self._spoken = []
        self._marks = marks
        try:
            messages = [self._build_system_message()] + self.state.conversation[-20:]
            tools = await self._stream_and_speak(messages, tools_enabled=True)
            if not self._spoken and tools:
                # The model only called a tool: ask it again, with no tools, for the spoken reply
                followup = messages + [ConversationMessage(role="user", content="[Tool result: ok]")]
                await self._stream_and_speak(followup, tools_enabled=False)
        finally:
            # Runs on normal end and on cancellation (barge-in): remember what was actually said
            if self._filler_task:
                self._filler_task.cancel()
            if self._spoken:
                said = " ".join(self._spoken)
                self.state.conversation.append(ConversationMessage(role="assistant", content=said))
                self.state.transcript.append(
                    {"role": "assistant", "text": said, "ts": time.time() - self.state.started_at}
                )
                self.state.ai_actions += 1
                try:
                    await self.ws.send_json({"type": "transcript", "role": "assistant", "text": said})
                except Exception:
                    pass
                m = self._marks
                if "first_audio" in m:
                    logger.info(
                        "turn_latency",
                        call_id=self.call_id,
                        asr_ms=round((m["asr"] - m["end"]) * 1000),
                        first_text_ms=round((m.get("first_text", m["asr"]) - m["end"]) * 1000),
                        first_audio_ms=round((m["first_audio"] - m["end"]) * 1000),
                    )

    async def _stream_and_speak(self, messages: list, tools_enabled: bool) -> list:
        """Stream the model's reply; speak each sentence as soon as it is complete.
        Returns the tool calls the model made (executed as they arrive)."""
        sentences: asyncio.Queue = asyncio.Queue()
        tool_calls: list = []

        async def produce():
            buf, first = "", True
            try:
                async for ev in self.llm.stream(messages, tools_enabled=tools_enabled):
                    if ev["type"] == "text":
                        self._marks.setdefault("first_text", time.time())
                        buf += ev["text"]
                        chunks, buf = pop_chunks(buf, first)
                        for c in chunks:
                            c = clean_for_speech(c)
                            if c:
                                first = False
                                await sentences.put(c)
                    elif ev["type"] == "tool":
                        tool_calls.append(ev)
                        await self._execute_tool(ev)
                    elif ev["type"] == "error":
                        logger.error("llm_stream_error", call_id=self.call_id, error=ev["error"])
                tail = clean_for_speech(buf)
                if tail:
                    await sentences.put(tail)
            finally:
                await sentences.put(None)

        async def consume():
            while True:
                sentence = await sentences.get()
                if sentence is None:
                    return
                async for chunk in self.tts.synthesize_streaming(sentence, self.tts_config):
                    await self._send_audio(chunk)
                self._spoken.append(sentence)

        producer = asyncio.create_task(produce())
        consumer = asyncio.create_task(consume())
        try:
            await asyncio.gather(producer, consumer)
        except BaseException:
            producer.cancel()
            consumer.cancel()
            raise
        return tool_calls

    async def _send_audio(self, chunk: bytes):
        self._reply_started = True
        self._marks.setdefault("first_audio", time.time())
        self._speaking_until = max(self._speaking_until, time.time()) + len(chunk) / 48000
        await self.ws.send_json({"type": "audio", "data": pcm16_to_b64(chunk)})

    # ───────────────────────── acknowledgements ─────────────────────────

    async def _prepare_fillers(self):
        """Synthesize the short acknowledgements once, while the greeting plays."""
        try:
            for phrase in FILLERS.get(self.agent.language, FILLERS["en-IN"]):
                audio = bytearray()
                async for chunk in self.tts.synthesize_streaming(phrase, self.tts_config):
                    audio.extend(chunk)
                if audio:
                    self._fillers.append(bytes(audio))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("filler_prepare_failed", call_id=self.call_id, error=str(e))

    async def _filler_if_slow(self):
        """If we still have no reply audio a moment after the caller stopped, say 'I see'."""
        try:
            await asyncio.sleep(max(0.0, FILLER_AFTER_S - (time.time() - self._turn_end_t)))
            if (
                self._reply_started
                or not self._fillers
                or self.state.turn_count - self._last_filler_turn < 2
            ):
                return
            self._last_filler_turn = self.state.turn_count
            logger.info("filler_played", call_id=self.call_id, after_ms=round((time.time() - self._turn_end_t) * 1000))
            audio = self._fillers[self.state.turn_count % len(self._fillers)]
            self._reply_started = True  # counts as the start of our reply
            self._speaking_until = max(self._speaking_until, time.time()) + len(audio) / 48000
            for i in range(0, len(audio), 9600):
                await self.ws.send_json({"type": "audio", "data": pcm16_to_b64(audio[i : i + 9600])})
        except asyncio.CancelledError:
            pass

    # ───────────────────────── greeting / wrap-up ─────────────────────────

    def _agent_speaking(self) -> bool:
        return time.time() < self._speaking_until

    def _start_speaking(self, text: str):
        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()
        self._speak_task = asyncio.create_task(self._speak(text))

    async def _speak(self, text: str):
        self._speaking_until = max(self._speaking_until, time.time())
        try:
            async for chunk in self.tts.synthesize_streaming(text, self.tts_config):
                self._speaking_until = max(self._speaking_until, time.time()) + len(chunk) / 48000
                await self.ws.send_json({"type": "audio", "data": pcm16_to_b64(chunk)})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("speak_error", call_id=self.call_id, error=str(e))

    # ───────────────────────── prompt & tools ─────────────────────────

    def _build_system_message(self) -> ConversationMessage:
        enhance = build_enhance_prompt(self.agent.language)
        lang_name = LANGUAGE_NAMES.get(self.agent.language, self.agent.language)
        prompt = f"""You are {self.agent.name}, a voice assistant on a live phone call on behalf of {self.agent.company}.

HOW TO TALK (this is a real-time phone conversation, not a chat):
1. Respond to what the caller JUST said. Open with a very short reaction of 1-3 words that ends with "!" or "." (for example a quick "Great!" or "Understood."), then give the real answer. If they asked a question, answer it. Never ignore their question or statement.
2. Keep every reply to 1-2 short sentences (about 20 words). Say ONE thing, then stop or ask one short question. Plain spoken words only: no emojis, no markdown, no lists.
3. The caller's words come from speech recognition and can contain mistakes. If their message does not make sense in context, say politely that you did not catch it and ask them to repeat. Do not guess.
4. Use the caller's details exactly as they said them (day, time, numbers, names). Never contradict or change them. Never ask the same question twice in a row. If they did not answer it, rephrase once, or move on to something else.
5. Vary how you start your replies. Do not begin every reply with "yes" or "okay": a short acknowledgement may already have been played.
6. Sound like a warm, natural person: simple everyday words, match the caller's tone and pace.
7. If the caller wants to end the call, or says they are not interested, thank them and say goodbye. Do not keep pushing.
8. LANGUAGE: Reply ONLY in {lang_name}, written in its native script so the voice pronounces it correctly. Do not switch to Hindi or English unless the caller does, or the language is English. Common English business words may stay in English.
9. Use respectful forms of address. Repeat back phone numbers, dates and amounts to confirm. If unsure of something, offer to have someone call back. Do not volunteer that you are an AI unless asked directly.

YOUR TASK (follow this scenario, stay in character, and steer the conversation toward its goal):
{self.agent.system_prompt}

KNOWLEDGE:
{self.agent.knowledge_base or 'None provided.'}

CAPTURE THESE FIELDS: {', '.join(self.agent.capture_fields)}
(Call capture_field only after the caller has actually stated the value. Never save placeholders or guesses.)
Captured so far: {json.dumps(self.state.captured_fields) or 'None'}

Turn {self.state.turn_count} | Call duration: {int(time.time() - self.state.started_at)}s
{enhance}"""
        return ConversationMessage(role="system", content=prompt)

    async def _execute_tool(self, tool_call: dict) -> dict:
        name = tool_call["name"]
        args = tool_call["arguments"]
        logger.info("tool_exec", call_id=self.call_id, tool=name)

        await self.ws.send_json({"type": "action", "name": name, "arguments": args})

        if name == "capture_field":
            self.state.captured_fields[args.get("field_name", "")] = args.get("field_value", "")
            return {"ok": True}
        elif name == "book_appointment":
            return {"ok": True, "msg": f"Booked {args.get('date')} at {args.get('time')}"}
        elif name == "send_whatsapp":
            return {"ok": True, "msg": "WhatsApp sent"}
        elif name == "transfer_to_human":
            return {"ok": True, "msg": "Transferring"}
        return {"ok": False, "msg": f"Unknown tool: {name}"}

    # ───────────────────────── end of call ─────────────────────────

    async def _send_call_ended(self):
        summary = ""
        if self.state.transcript:
            text = "\n".join(
                f"{'Caller' if t['role']=='user' else 'Agent'}: {t['text']}"
                for t in self.state.transcript
            )
            resp = await self.llm.generate(
                [
                    ConversationMessage(
                        role="system",
                        content="Summarize this call in 2-3 sentences. Include: topic, outcome, next steps.",
                    ),
                    ConversationMessage(role="user", content=text),
                ],
                tools_enabled=False,
            )
            summary = resp.text
            self.summary = summary

        try:
            await self.ws.send_json(
                {
                    "type": "call_ended",
                    "duration_s": round(self.state.duration_s),
                    "turns": self.state.turn_count,
                    "captured": self.state.captured_fields,
                    "summary": summary,
                }
            )
        except Exception:
            pass
