"""Pydantic models for data validation."""

from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class VoiceProvider(str, Enum):
    CARTESIA = "cartesia"
    SARVAM = "sarvam"


class VoiceTier(str, Enum):
    STANDARD = "standard"
    PREMIUM = "premium"


class CallDirection(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class CallStatus(str, Enum):
    PENDING = "pending"
    RINGING = "ringing"
    CONNECTED = "connected"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"


class AgentConfig(BaseModel):
    id: str
    name: str
    company: str
    language: str = "hi-IN"
    greeting: str = "Namaste! Main aapki kaise madad kar sakti hoon?"
    system_prompt: str = ""
    knowledge_base: str = ""
    capture_fields: List[str] = Field(default_factory=lambda: ["name", "interest"])
    voice_provider: VoiceProvider = VoiceProvider.CARTESIA
    voice_id: str = ""
    voice_tier: VoiceTier = VoiceTier.STANDARD
    tools_enabled: List[str] = Field(default_factory=list)
    max_call_duration_s: int = 300


class TranscriptEntry(BaseModel):
    role: str  # "user" | "assistant"
    text: str
    timestamp: float


class CallResult(BaseModel):
    call_id: str
    duration_s: float
    turns: int
    transcript: List[TranscriptEntry]
    captured_fields: dict
    summary: str
    credits_used: float


class WebSocketMessage(BaseModel):
    type: str
    data: Optional[str] = None
    text: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    message: Optional[str] = None
