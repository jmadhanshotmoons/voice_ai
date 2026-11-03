"""Telephony transport: lets CallSession talk over a phone-provider WebSocket.

CallSession speaks the browser protocol ({"type": "audio", "data": <b64 pcm16>},
{"type": "clear"}, {"type": "hangup"}). Phone providers speak their own media
protocol at 8 kHz. PhoneTransport sits in between and presents the same two
methods CallSession uses (`receive_text` / `send_json`), so the pipeline itself
does not change.

Providers:
- twilio: Media Streams. mulaw 8 kHz, camelCase keys (streamSid).
- exotel: Voicebot streaming. 16-bit PCM 8 kHz little-endian, snake_case keys
  (stream_sid). NOTE: written from Exotel's public docs; verify the exact
  message fields against a real Exotel account before going live.
"""

import base64
import json
from typing import Optional

import numpy as np
import structlog
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = structlog.get_logger()

PHONE_RATE = 8000
ASR_RATE = 16000
TTS_RATE = 24000
FRAME_MS = 20
FRAME_SAMPLES = PHONE_RATE * FRAME_MS // 1000  # 160 samples per 20 ms
VAD_FRAME_BYTES = ASR_RATE * 30 // 1000 * 2  # CallSession reads 30 ms frames


# ───────────── G.711 mu-law ─────────────

_BIAS = 0x84
_CLIP = 32635


_SEG_END = np.array([0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF])


def pcm16_to_mulaw(pcm: np.ndarray) -> bytes:
    """G.711 mu-law encode (same algorithm as the C reference / audioop)."""
    val = pcm.astype(np.int32) >> 2
    mask = np.where(val < 0, 0x7F, 0xFF)
    val = np.minimum(np.abs(val), 8159) + 0x21
    seg = np.searchsorted(_SEG_END, val, side="left")
    uval = np.where(seg >= 8, 0x7F, (seg << 4) | ((val >> (np.minimum(seg, 7) + 1)) & 0x0F))
    return (uval ^ mask).astype(np.uint8).tobytes()


def mulaw_to_pcm16(data: bytes) -> np.ndarray:
    u = (~np.frombuffer(data, dtype=np.uint8)).astype(np.int32) & 0xFF
    sign = u & 0x80
    exponent = (u >> 4) & 0x07
    mantissa = u & 0x0F
    mag = (((mantissa << 3) + _BIAS) << exponent) - _BIAS
    return np.where(sign != 0, -mag, mag).astype(np.int16)


# ───────────── Resampling ─────────────

def tts24k_to_phone8k(pcm24: bytes) -> np.ndarray:
    """24 kHz -> 8 kHz: average each group of 3 samples (cheap anti-alias)."""
    x = np.frombuffer(pcm24, dtype=np.int16).astype(np.float32)
    n = (len(x) // 3) * 3
    return x[:n].reshape(-1, 3).mean(axis=1).astype(np.int16)


def phone8k_to_asr16k(pcm8: np.ndarray) -> bytes:
    """8 kHz -> 16 kHz by linear interpolation."""
    if len(pcm8) == 0:
        return b""
    x = pcm8.astype(np.float32)
    idx = np.linspace(0, len(x) - 1, len(x) * 2)
    return np.interp(idx, np.arange(len(x)), x).astype(np.int16).tobytes()


# ───────────── Transport ─────────────

class PhoneTransport:
    def __init__(self, ws: WebSocket, provider: str):
        if provider not in ("twilio", "exotel"):
            raise ValueError(f"unknown telephony provider: {provider}")
        self.ws = ws
        self.provider = provider
        self.stream_id: str = ""
        self.start_info: dict = {}
        self._in = bytearray()   # 16 kHz audio waiting to fill 30 ms frames
        self._out = bytearray()  # encoded phone audio waiting to fill 20 ms frames
        self._frame_bytes = FRAME_SAMPLES if provider == "twilio" else FRAME_SAMPLES * 2

    # --- inbound: provider -> CallSession ---

    async def wait_start(self) -> dict:
        """Consume 'connected' / 'start' and return the call's start details."""
        while True:
            msg = json.loads(await self.ws.receive_text())
            event = msg.get("event")
            if event == "start":
                start = msg.get("start") or {}
                self.stream_id = (
                    msg.get("streamSid") or msg.get("stream_sid")
                    or start.get("streamSid") or start.get("stream_sid") or ""
                )
                custom = (
                    start.get("customParameters")
                    or start.get("custom_parameters")
                    or {}
                )
                self.start_info = {
                    "call_sid": start.get("callSid") or start.get("call_sid") or "",
                    "from": start.get("from") or "",
                    "to": start.get("to") or "",
                    "custom": custom if isinstance(custom, dict) else {},
                }
                logger.info("phone_stream_started", provider=self.provider, stream=self.stream_id)
                return self.start_info
            if event == "stop":
                raise WebSocketDisconnect()

    async def receive_text(self) -> str:
        """Next message in the browser protocol, as CallSession expects."""
        while True:
            try:
                msg = json.loads(await self.ws.receive_text())
            except WebSocketDisconnect:
                return json.dumps({"type": "hangup"})

            event = msg.get("event")
            if event == "stop":
                return json.dumps({"type": "hangup"})
            if event != "media":
                continue  # connected / mark / dtmf are not needed

            payload = (msg.get("media") or {}).get("payload")
            if not payload:
                continue
            raw = base64.b64decode(payload)
            pcm8 = mulaw_to_pcm16(raw) if self.provider == "twilio" else np.frombuffer(raw, dtype="<i2")
            self._in.extend(phone8k_to_asr16k(pcm8))

            # CallSession drops partial 30 ms frames, so hand it whole frames only
            usable = len(self._in) // VAD_FRAME_BYTES * VAD_FRAME_BYTES
            if usable:
                chunk = bytes(self._in[:usable])
                del self._in[:usable]
                return json.dumps({"type": "audio", "data": base64.b64encode(chunk).decode()})

    # --- outbound: CallSession -> provider ---

    async def send_json(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "audio":
            await self._send_audio(base64.b64decode(msg["data"]))
        elif kind == "clear":
            self._out.clear()
            key = "streamSid" if self.provider == "twilio" else "stream_sid"
            await self.ws.send_text(json.dumps({"event": "clear", key: self.stream_id}))
        # transcript / action / call_ended are browser-only; nothing to send

    async def _send_audio(self, pcm24: bytes) -> None:
        pcm8 = tts24k_to_phone8k(pcm24)
        encoded = pcm16_to_mulaw(pcm8) if self.provider == "twilio" else pcm8.astype("<i2").tobytes()
        self._out.extend(encoded)

        key = "streamSid" if self.provider == "twilio" else "stream_sid"
        while len(self._out) >= self._frame_bytes:
            frame = bytes(self._out[: self._frame_bytes])
            del self._out[: self._frame_bytes]
            await self.ws.send_text(json.dumps({
                "event": "media",
                key: self.stream_id,
                "media": {"payload": base64.b64encode(frame).decode()},
            }))
