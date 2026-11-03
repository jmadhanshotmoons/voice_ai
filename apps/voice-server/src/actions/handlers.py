"""Mid-call actions -- calendar booking, WhatsApp, API calls.

These are triggered by LLM tool calls during a conversation.
"""

import os
import httpx
import structlog
from typing import Optional

logger = structlog.get_logger()


async def book_calendar(
    date: str,
    time: str,
    attendee_name: str = "",
    notes: str = "",
    google_credentials: Optional[dict] = None,
) -> dict:
    """Book a Google Calendar appointment.

    For MVP, this creates a placeholder. Full Google Calendar integration
    requires OAuth2 flow per account (implement in production).
    """
    logger.info(
        "calendar_booking",
        date=date,
        time=time,
        attendee=attendee_name,
    )

    # MVP: Return success with booking details
    # Production: Use google-api-python-client with stored OAuth tokens
    return {
        "success": True,
        "message": f"Appointment booked for {date} at {time}",
        "details": {
            "date": date,
            "time": time,
            "attendee": attendee_name,
            "notes": notes,
        },
    }


async def send_whatsapp(
    phone_number: str,
    message: str,
    template: str = "confirmation",
) -> dict:
    """Send a WhatsApp message via WhatsApp Business API.

    For MVP, logs the message. Production requires:
    - WhatsApp Business API account
    - Approved message templates
    - BSP (Business Solution Provider) like Twilio/Gupshup
    """
    logger.info(
        "whatsapp_message",
        phone=phone_number,
        template=template,
        message_preview=message[:50],
    )

    # MVP: Return success
    # Production: Call BSP API (e.g., Gupshup, Twilio WhatsApp)
    return {
        "success": True,
        "message": "WhatsApp message queued",
        "phone": phone_number,
    }


async def fire_webhook(
    url: str,
    payload: dict,
    secret: str,
    timeout: int = 10,
) -> dict:
    """Send a signed webhook to the customer's endpoint.

    SECURITY: HMAC-SHA256 signature in X-Signature header.
    """
    import hashlib
    import hmac
    import json

    body = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": signature,
                    "User-Agent": "Batkarai-Webhook/1.0",
                },
            )

            logger.info(
                "webhook_fired",
                url=url,
                status=response.status_code,
            )

            return {
                "success": response.status_code < 400,
                "status_code": response.status_code,
            }

    except Exception as e:
        logger.error("webhook_failed", url=url, error=str(e))
        return {"success": False, "error": str(e)}


async def call_custom_api(
    url: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    body: Optional[dict] = None,
    timeout: int = 10,
) -> dict:
    """Call a customer's custom API during a call.

    SECURITY: URL allowlisting should be enforced at the employee config level.
    Never allow arbitrary URLs from LLM output.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=headers or {},
                json=body,
            )

            return {
                "success": response.status_code < 400,
                "status_code": response.status_code,
                "data": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text[:500],
            }

    except Exception as e:
        logger.error("custom_api_failed", url=url, error=str(e))
        return {"success": False, "error": str(e)}
