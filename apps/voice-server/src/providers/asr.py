"""Sarvam AI Speech-to-Text provider.

Sarvam Saaras v4: best ASR for Indian languages + code-switching.
Supports: Hindi, Telugu, Tamil, Kannada, Malayalam, Marathi, English.
Price: ~Rs 0.49/min (pay-as-you-go).
"""

import os
import io
import wave
import httpx
import structlog
from dataclasses import dataclass
from typing import Optional

logger = structlog.get_logger()

SARVAM_API_URL = "https://api.sarvam.ai"


@dataclass
class TranscriptResult:
    text: str
    language: str
    confidence: float
    duration_ms: int


class SarvamASR:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SARVAM_API_KEY", "")
        self.client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(keepalive_expiry=300))

    async def transcribe(
        self,
        pcm16_audio: bytes,
        sample_rate: int = 16000,
        language: str = "auto",
    ) -> TranscriptResult:
        wav_bytes = self._pcm16_to_wav(pcm16_audio, sample_rate)
        lang_code = language if language != "auto" else "unknown"

        try:
            response = await self.client.post(
                f"{SARVAM_API_URL}/speech-to-text",
                headers={"api-subscription-key": self.api_key},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"language_code": lang_code, "model": "saaras:v4"},
            )
            response.raise_for_status()
            data = response.json()
            duration_ms = int(len(pcm16_audio) / (sample_rate * 2) * 1000)
            return TranscriptResult(
                text=data.get("transcript", ""),
                language=data.get("language_code", lang_code),
                confidence=data.get("confidence", 0.0),
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.error("sarvam_asr_error", error=str(e))
            return TranscriptResult(text="", language=lang_code, confidence=0.0, duration_ms=0)

    def _pcm16_to_wav(self, pcm16_bytes: bytes, sample_rate: int) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16_bytes)
        buf.seek(0)
        return buf.read()

    async def close(self):
        await self.client.aclose()
