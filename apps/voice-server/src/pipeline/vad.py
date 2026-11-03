"""Voice Activity Detection -- detects when caller is speaking vs silent.

Two implementations:
- EnergyVAD: simple, fast, good for development
- SileroVAD: neural network, production-grade (requires torch)
"""

import numpy as np
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import structlog

logger = structlog.get_logger()


class VADEvent(Enum):
    SPEECH_START = "speech_start"
    SPEECH_CONTINUE = "speech_continue"
    SILENCE = "silence"
    TURN_COMPLETE = "turn_complete"


@dataclass
class VADConfig:
    sample_rate: int = 16000
    frame_ms: int = 30
    energy_threshold: float = 500.0
    silence_duration_ms: int = 700
    min_speech_ms: int = 250
    adaptive: bool = True
    noise_floor_alpha: float = 0.95
    threshold_multiplier: float = 3.0


class EnergyVAD:
    """Energy-based VAD. Computes RMS energy per 30ms frame.
    If energy > threshold → speech. If silence > 700ms after speech → turn complete.
    """

    def __init__(self, config: Optional[VADConfig] = None):
        self.config = config or VADConfig()
        self.frame_size = int(self.config.sample_rate * self.config.frame_ms / 1000)
        self.silence_frames_needed = int(
            self.config.silence_duration_ms / self.config.frame_ms
        )
        self.min_speech_frames = int(self.config.min_speech_ms / self.config.frame_ms)
        self.is_speaking = False
        self.silent_count = 0
        self.speech_count = 0
        self.noise_floor = self.config.energy_threshold * 0.3

    def get_threshold(self) -> float:
        if self.config.adaptive:
            return max(self.noise_floor * self.config.threshold_multiplier, 200.0)
        return self.config.energy_threshold

    def process_frame(self, pcm16_frame: bytes) -> VADEvent:
        samples = np.frombuffer(pcm16_frame, dtype=np.int16).astype(np.float64)
        energy = float(np.sqrt(np.mean(samples**2)))
        threshold = self.get_threshold()

        if energy > threshold:
            self.speech_count += 1
            self.silent_count = 0
            if not self.is_speaking and self.speech_count >= self.min_speech_frames:
                self.is_speaking = True
                return VADEvent.SPEECH_START
            elif self.is_speaking:
                return VADEvent.SPEECH_CONTINUE
            return VADEvent.SILENCE
        else:
            self.speech_count = 0
            if self.config.adaptive and not self.is_speaking:
                self.noise_floor = (
                    self.config.noise_floor_alpha * self.noise_floor
                    + (1 - self.config.noise_floor_alpha) * energy
                )
            if self.is_speaking:
                self.silent_count += 1
                if self.silent_count >= self.silence_frames_needed:
                    self.is_speaking = False
                    self.silent_count = 0
                    return VADEvent.TURN_COMPLETE
                return VADEvent.SILENCE
            return VADEvent.SILENCE

    def reset(self):
        self.is_speaking = False
        self.silent_count = 0
        self.speech_count = 0
