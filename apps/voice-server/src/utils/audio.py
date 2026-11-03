"""Audio processing utilities for the voice pipeline.

Handles conversion between formats:
- Phone network: 8kHz mulaw
- ASR (Sarvam): 16kHz PCM16
- TTS (Cartesia): 24kHz PCM16
- Browser playback: 24kHz PCM16
"""

import base64
import io
import wave
import numpy as np
from typing import List


PHONE_SAMPLE_RATE = 8000
ASR_SAMPLE_RATE = 16000
TTS_SAMPLE_RATE = 24000
BROWSER_SAMPLE_RATE = 24000


def pcm16_to_float32(pcm_bytes: bytes) -> np.ndarray:
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


def float32_to_pcm16(audio: np.ndarray) -> bytes:
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype(np.int16).tobytes()


def resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    if from_rate == to_rate:
        return audio
    ratio = to_rate / from_rate
    new_length = int(len(audio) * ratio)
    indices = np.linspace(0, len(audio) - 1, new_length)
    return np.interp(indices, np.arange(len(audio)), audio)


def b64_to_pcm16(b64_string: str) -> bytes:
    return base64.b64decode(b64_string)


def pcm16_to_b64(pcm_bytes: bytes) -> str:
    return base64.b64encode(pcm_bytes).decode("ascii")


def compute_rms_energy(pcm_bytes: bytes) -> float:
    if not pcm_bytes:
        return 0.0
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float64)
    return float(np.sqrt(np.mean(samples ** 2)))


def pcm16_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    buf.seek(0)
    return buf.read()


def wav_to_pcm16(wav_bytes: bytes) -> tuple[bytes, int]:
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        sample_rate = wf.getframerate()
        pcm_data = wf.readframes(wf.getnframes())
    return pcm_data, sample_rate


def split_audio_chunks(
    audio_bytes: bytes, chunk_size_ms: int = 30, sample_rate: int = 16000
) -> List[bytes]:
    bytes_per_chunk = int(sample_rate * chunk_size_ms / 1000) * 2
    chunks = []
    for i in range(0, len(audio_bytes), bytes_per_chunk):
        chunk = audio_bytes[i : i + bytes_per_chunk]
        if len(chunk) == bytes_per_chunk:
            chunks.append(chunk)
    return chunks


def create_silence(duration_ms: int, sample_rate: int = 24000) -> bytes:
    num_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00" * (num_samples * 2)


def generate_ambient_noise(duration_s: float, sample_rate: int = 24000,
                           volume: float = 0.02) -> bytes:
    """Generate subtle pink noise as office background ambience."""
    samples = int(duration_s * sample_rate)
    white = np.random.randn(samples)
    # Simple 1/f filter for pink noise
    pink = np.cumsum(white) / np.sqrt(samples)
    pink = pink - np.mean(pink)
    pink = (pink / (np.max(np.abs(pink)) + 1e-8)) * volume
    return float32_to_pcm16(pink.astype(np.float32))
