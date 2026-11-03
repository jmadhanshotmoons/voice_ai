"""Text-to-Speech providers.

Premium tier: Cartesia Sonic 3.6 (#1 ranked, streaming, ~100ms latency)
Budget tier: Sarvam Bulbul v4 Flash (best Indian language voices, cheapest)

Both support streaming -- start speaking before full text is generated.
"""

import os
import base64
import httpx
import structlog
from dataclasses import dataclass
from typing import Optional, AsyncIterator

logger = structlog.get_logger()


@dataclass
class TTSConfig:
    provider: str = "cartesia"
    voice_id: str = ""
    sample_rate: int = 24000
    language: str = "hi-IN"
    speed: float = 1.0


# Cartesia language codes and a default voice per language, used when an
# employee has no voice_id (the dashboard form doesn't set one).
CARTESIA_LANG = {
    "hi-IN": "hi", "te-IN": "te", "ta-IN": "ta", "kn-IN": "kn",
    "ml-IN": "ml", "mr-IN": "mr", "en-IN": "en",
}
CARTESIA_DEFAULT_VOICE = {
    "hi-IN": "4459a9a5-69d6-4680-b970-e13dc51845b6",  # Siya
    "te-IN": "3a8e6fea-81e5-4d4d-8755-86093146cdb8",  # Vidya
    "ta-IN": "fb7d8d97-9730-4165-bd79-36b5ce61b5f2",  # Janani
    "kn-IN": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",  # Jacqueline
    "ml-IN": "e8e5fffb-252c-436d-b842-8879b84445b6",  # Cathy
    "mr-IN": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",  # Jacqueline
    "en-IN": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",  # Skylar
}


class CartesiaTTS:
    """Cartesia Sonic -- premium tier. State Space Model architecture."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("CARTESIA_API_KEY", "")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from cartesia import AsyncCartesia
            self._client = AsyncCartesia(
                api_key=self.api_key,
                http_client=httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(keepalive_expiry=300)),
            )
        return self._client

    async def synthesize_streaming(
        self,
        text: str,
        voice_id: str,
        sample_rate: int = 24000,
        language: str = "hi-IN",
    ) -> AsyncIterator[bytes]:
        try:
            voice_id = voice_id or CARTESIA_DEFAULT_VOICE.get(language, "")
            client = self._get_client()
            output_format = {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": sample_rate,
            }

            response = await client.tts.generate(
                model_id="sonic-3.6",
                transcript=text,
                voice={"mode": "id", "id": voice_id},
                output_format=output_format,
                language=CARTESIA_LANG.get(language, "hi"),
            )
            async for chunk in response.iter_bytes():
                if chunk:
                    yield chunk

        except Exception as e:
            logger.error("cartesia_tts_error", error=str(e))
            yield b"\x00" * (sample_rate * 2)

    async def synthesize_full(
        self,
        text: str,
        voice_id: str,
        sample_rate: int = 24000,
        language: str = "hi-IN",
    ) -> bytes:
        chunks = []
        async for chunk in self.synthesize_streaming(
            text, voice_id, sample_rate, language
        ):
            chunks.append(chunk)
        return b"".join(chunks)


class SarvamTTS:
    """Sarvam Bulbul v4 Flash -- budget tier. Best native Indian voices."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SARVAM_API_KEY", "")
        self._http = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(keepalive_expiry=300))

    async def synthesize_streaming(
        self,
        text: str,
        voice_id: str,
        sample_rate: int = 24000,
        language: str = "hi-IN",
    ) -> AsyncIterator[bytes]:
        try:
            client = self._http
            response = await client.post(
                "https://api.sarvam.ai/text-to-speech",
                headers={"api-subscription-key": self.api_key},
                json={
                    "inputs": [text],
                    "target_language_code": language,
                    "speaker": voice_id or "meera",
                    "model": "bulbul:v4-flash",
                    "enable_preprocessing": True,
                    "pitch": 0,
                    "pace": 1.0,
                },
            )
            response.raise_for_status()
            data = response.json()

            if "audios" in data and data["audios"]:
                audio_bytes = base64.b64decode(data["audios"][0])
                pcm_data = audio_bytes[44:]  # Skip WAV header
                chunk_size = sample_rate * 2 * 100 // 1000  # 100ms chunks
                for i in range(0, len(pcm_data), chunk_size):
                    yield pcm_data[i : i + chunk_size]

        except Exception as e:
            logger.error("sarvam_tts_error", error=str(e))
            yield b"\x00" * (sample_rate * 2)


class TTSRouter:
    """Routes TTS to the correct provider based on agent config."""

    def __init__(self):
        self.cartesia = CartesiaTTS()
        self.sarvam = SarvamTTS()

    async def synthesize_streaming(
        self, text: str, config: TTSConfig
    ) -> AsyncIterator[bytes]:
        if config.provider == "cartesia":
            async for chunk in self.cartesia.synthesize_streaming(
                text, config.voice_id, config.sample_rate, config.language
            ):
                yield chunk
        elif config.provider == "sarvam":
            async for chunk in self.sarvam.synthesize_streaming(
                text, config.voice_id, config.sample_rate, config.language
            ):
                yield chunk
        else:
            raise ValueError(f"Unknown TTS provider: {config.provider}")
