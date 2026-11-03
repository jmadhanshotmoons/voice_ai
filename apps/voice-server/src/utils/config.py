"""Configuration loader for the voice server."""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # AWS Bedrock (LLM)
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    aws_bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"

    # Sarvam AI (ASR + budget TTS)
    sarvam_api_key: str = ""

    # Cartesia (premium TTS)
    cartesia_api_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Server
    host: str = "0.0.0.0"
    port: int = 8765

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
            aws_bedrock_model_id=os.getenv(
                "AWS_BEDROCK_MODEL_ID",
                "anthropic.claude-3-haiku-20240307-v1:0",
            ),
            sarvam_api_key=os.getenv("SARVAM_API_KEY", ""),
            cartesia_api_key=os.getenv("CARTESIA_API_KEY", ""),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            host=os.getenv("VOICE_HOST", "0.0.0.0"),
            port=int(os.getenv("VOICE_PORT", "8765")),
        )


config = Config.from_env()
