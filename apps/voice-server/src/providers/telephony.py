"""Exotel telephony bridge -- connects voice pipeline to real phone calls.

Handles:
- Outbound call initiation via Exotel API
- Inbound call routing to voice pipeline
- Call status callbacks
- Audio streaming between Exotel and WebSocket pipeline
"""

import os
import httpx
import structlog
from dataclasses import dataclass
from typing import Optional

logger = structlog.get_logger()


@dataclass
class ExotelConfig:
    account_sid: str = ""
    api_key: str = ""
    api_token: str = ""
    caller_id: str = ""
    subdomain: str = ""

    @classmethod
    def from_env(cls) -> "ExotelConfig":
        return cls(
            account_sid=os.getenv("EXOTEL_ACCOUNT_SID", ""),
            api_key=os.getenv("EXOTEL_API_KEY", ""),
            api_token=os.getenv("EXOTEL_API_TOKEN", ""),
            caller_id=os.getenv("EXOTEL_CALLER_ID", ""),
            subdomain=os.getenv("EXOTEL_SUBDOMAIN", ""),
        )


class ExotelBridge:
    """Bridge between Exotel telephony and the voice pipeline."""

    def __init__(self, config: Optional[ExotelConfig] = None):
        self.config = config or ExotelConfig.from_env()
        self.base_url = f"https://{self.config.account_sid}.exotel.com/v1/Accounts/{self.config.account_sid}"

    async def initiate_call(
        self,
        to_number: str,
        call_id: str,
        callback_base_url: str,
    ) -> dict:
        """Initiate an outbound call via Exotel.

        Args:
            to_number: Phone number to call (+91...)
            call_id: Our internal call ID for tracking
            callback_base_url: Base URL for webhooks (e.g., https://api.yourdomain.com)
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/Calls/connect",
                auth=(self.config.api_key, self.config.api_token),
                data={
                    "From": to_number,
                    "CallerId": self.config.caller_id,
                    "Url": f"{callback_base_url}/telephony/call-handler/{call_id}",
                    "StatusCallback": f"{callback_base_url}/telephony/status/{call_id}",
                    "StatusCallbackEvents[0]": "terminal",
                    "Record": "true",
                },
            )
            response.raise_for_status()
            data = response.json()

            logger.info(
                "call_initiated",
                call_id=call_id,
                to=to_number,
                exotel_sid=data.get("Call", {}).get("Sid"),
            )
            return data

    async def get_call_status(self, exotel_call_sid: str) -> dict:
        """Get call status from Exotel."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/Calls/{exotel_call_sid}",
                auth=(self.config.api_key, self.config.api_token),
            )
            response.raise_for_status()
            return response.json()

    def generate_call_handler_xml(self, call_id: str, ws_base_url: str) -> str:
        """Generate ExoML response to stream audio to our WebSocket server.

        This XML tells Exotel to stream the call audio to our voice pipeline.
        """
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_base_url}/call/{call_id}" />
    </Connect>
</Response>"""


class TelephonyService:
    """High-level telephony operations."""

    def __init__(self):
        self.bridge = ExotelBridge()

    async def make_call(
        self,
        phone_number: str,
        employee_id: str,
        call_id: str,
        account_id: str,
    ) -> dict:
        """Make an outbound call to a phone number using an AI employee."""
        callback_base = os.getenv("API_URL", "http://localhost:3001")

        result = await self.bridge.initiate_call(
            to_number=phone_number,
            call_id=call_id,
            callback_base_url=callback_base,
        )

        logger.info(
            "outbound_call_started",
            call_id=call_id,
            employee_id=employee_id,
            account_id=account_id,
            phone=phone_number,
        )

        return result
