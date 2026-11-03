"""Shared, pre-warmed provider clients.

A new connection to a provider costs a TLS handshake (and, for Bedrock, a cold
first request) of up to ~1.5 s. Doing that on the first turn of every call makes
the first reply feel dead. One shared client per provider keeps connections
open across turns and calls, and warm_up() opens them at server start.
"""

import asyncio
import io
import wave

import structlog

from src.providers.asr import SarvamASR
from src.providers.llm import BedrockLLM, ConversationMessage
from src.providers.tts import TTSRouter

logger = structlog.get_logger()

_asr = _llm = _tts = None


def get_asr() -> SarvamASR:
    global _asr
    if _asr is None:
        _asr = SarvamASR()
    return _asr


def get_llm() -> BedrockLLM:
    global _llm
    if _llm is None:
        _llm = BedrockLLM()
    return _llm


def get_tts() -> TTSRouter:
    global _tts
    if _tts is None:
        _tts = TTSRouter()
    return _tts


async def warm_up() -> None:
    """Open provider connections before the first call arrives. Failures are harmless."""

    async def llm():
        async for _ in get_llm().stream(
            [ConversationMessage(role="user", content="hi")], tools_enabled=False, max_tokens=5
        ):
            pass

    async def tts():
        from src.providers.tts import TTSConfig

        cfg = TTSConfig(provider="cartesia", voice_id="", language="hi-IN")
        async for _ in get_tts().synthesize_streaming("हाँ जी।", cfg):
            pass

    async def asr():
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 8000)
        await get_asr().transcribe(b"\x00\x00" * 8000, 16000, "hi-IN")

    results = await asyncio.gather(llm(), tts(), asr(), return_exceptions=True)
    names = ("llm", "tts", "asr")
    for name, r in zip(names, results):
        if isinstance(r, Exception):
            logger.warning("warmup_failed", provider=name, error=str(r))
    logger.info("providers_warmed")
