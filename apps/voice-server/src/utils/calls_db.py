"""Call records and credit billing, via the Supabase REST API (service key).

The voice server owns the facts of a call (real duration, transcript, captured
fields, summary), so it writes them and bills the credits. The API's provider
status callback then only fills in what the provider alone knows.
"""

import hashlib
import hmac
import time
import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

from src.models.schemas import AgentConfig

logger = structlog.get_logger()

# Mirrors the rates the API's status callback has always used (Rs per minute).
RATE_PER_MIN = {"premium": 5.5, "standard": 3.6}

DB_DEFAULT_GREETING = "Namaste! Main aapki kaise madad kar sakti hoon?"

DEFAULT_GREETINGS = {
    "hi-IN": "नमस्ते जी! मैं {name} बोल रही हूँ, {company} से। मैं आपकी कैसे मदद कर सकती हूँ?",
    "te-IN": "నమస్కారం! నేను {company} నుండి {name} మాట్లాడుతున్నాను. మీకు ఎలా సహాయం చేయగలను?",
    "ta-IN": "வணக்கம்! நான் {company} இலிருந்து {name} பேசுகிறேன். உங்களுக்கு எப்படி உதவலாம்?",
    "kn-IN": "ನಮಸ್ಕಾರ! ನಾನು {company} ಯಿಂದ {name} ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ. ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?",
    "ml-IN": "നമസ്കാരം! ഞാൻ {company}-ൽ നിന്ന് {name} സംസാരിക്കുന്നു. ഞാൻ എങ്ങനെ സഹായിക്കണം?",
    "mr-IN": "नमस्कार! मी {company} मधून {name} बोलत आहे. मी तुमची कशी मदत करू?",
    "en-IN": "Hello! This is {name} from {company}. How can I help you today?",
}


def _conf() -> tuple[str, str]:
    return os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_KEY", "")


def _headers(key: str, **extra: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}", **extra}


def sign_call(call_id: str) -> str:
    """Token that proves a request came from our own API for this call id."""
    secret = os.getenv("WEBHOOK_SECRET", "")
    return hmac.new(secret.encode(), call_id.encode(), hashlib.sha256).hexdigest()[:32]


def valid_call_token(call_id: str, token: Optional[str]) -> bool:
    if not os.getenv("WEBHOOK_SECRET") or not token:
        return False
    return hmac.compare_digest(sign_call(call_id), token)


def valid_ticket(subject: str, ticket: Optional[str]) -> bool:
    """Short-lived ticket minted by the API (apps/api/src/lib/ticket.ts) for a browser call."""
    secret = os.getenv("WEBHOOK_SECRET", "")
    if not secret or not ticket or "." not in ticket:
        return False
    exp_s, _, sig = ticket.partition(".")
    if not exp_s.isdigit() or int(exp_s) < time.time():
        return False
    want = hmac.new(secret.encode(), f"ticket:{subject}:{exp_s}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, sig)


def agent_from_employee(emp: dict) -> AgentConfig:
    company = (emp.get("accounts") or {}).get("company_name") or "our company"
    lang = emp.get("language") or "hi-IN"
    greeting = (emp.get("greeting") or "").strip()
    if not greeting or greeting == DB_DEFAULT_GREETING:
        greeting = DEFAULT_GREETINGS.get(lang, DEFAULT_GREETINGS["en-IN"]).format(
            name=emp["name"], company=company
        )
    return AgentConfig(
        id=emp["id"],
        name=emp["name"],
        company=company,
        language=lang,
        greeting=greeting,
        system_prompt=emp.get("system_prompt") or "",
        knowledge_base=emp.get("knowledge_base") or "",
        capture_fields=emp.get("capture_fields") or ["name", "interest"],
        voice_provider=emp.get("voice_provider") or "cartesia",
        voice_id=emp.get("voice_id") or "",
        voice_tier=emp.get("voice_tier") or "standard",
        tools_enabled=emp.get("tools_enabled") or [],
        max_call_duration_s=emp.get("max_call_duration_s") or 300,
    )


async def _get(path: str, params: dict) -> list:
    url, key = _conf()
    if not (url and key):
        return []
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{url}/rest/v1/{path}", params=params, headers=_headers(key))
        r.raise_for_status()
        return r.json()


async def load_employee(employee_id: str) -> Optional[dict]:
    rows = await _get(
        "employees", {"id": f"eq.{employee_id}", "select": "*,accounts(company_name)"}
    )
    return rows[0] if rows else None


async def load_call(call_id: str) -> Optional[dict]:
    """The call row with its employee (and company) embedded."""
    rows = await _get(
        "calls",
        {"id": f"eq.{call_id}", "select": "*,employees(*,accounts(company_name))"},
    )
    return rows[0] if rows else None


async def find_pending_call_by_number(number: str) -> Optional[dict]:
    """Fallback match for providers that cannot carry our call id (last 10 digits)."""
    digits = re.sub(r"\D", "", number)[-10:]
    if len(digits) < 10:
        return None
    rows = await _get(
        "calls",
        {
            "phone_number": f"like.*{digits}",
            "status": "in.(pending,ringing)",
            "direction": "eq.outbound",
            "order": "created_at.desc",
            "limit": "1",
            "select": "*,employees(*,accounts(company_name))",
        },
    )
    return rows[0] if rows else None


async def create_inbound_call(from_number: str, to_number: str, provider: str, sid: str) -> Optional[dict]:
    """An inbound call to one of our numbers: find its employee and record the call."""
    digits = re.sub(r"\D", "", to_number)[-10:]
    if len(digits) < 10:
        return None
    rows = await _get(
        "phone_numbers",
        {"number": f"like.*{digits}", "is_active": "eq.true", "select": "account_id,assigned_employee_id"},
    )
    if not rows or not rows[0].get("assigned_employee_id"):
        return None
    url, key = _conf()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{url}/rest/v1/calls",
            headers=_headers(key, **{"Content-Type": "application/json", "Prefer": "return=representation"}),
            json={
                "account_id": rows[0]["account_id"],
                "employee_id": rows[0]["assigned_employee_id"],
                "phone_number": from_number,
                "direction": "inbound",
                "status": "ringing",
                "provider": provider,
                "provider_call_sid": sid,
            },
        )
        r.raise_for_status()
        call_id = r.json()[0]["id"]
    return await load_call(call_id)


async def create_web_call(employee: dict) -> Optional[str]:
    """Record a dashboard test call so it shows on the Calls page."""
    url, key = _conf()
    if not (url and key):
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{url}/rest/v1/calls",
                headers=_headers(key, **{"Content-Type": "application/json", "Prefer": "return=representation"}),
                json={
                    "account_id": employee["account_id"],
                    "employee_id": employee["id"],
                    "phone_number": "web-test",
                    "direction": "web",
                    "status": "connected",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            r.raise_for_status()
            return r.json()[0]["id"]
    except Exception as e:
        logger.error("create_web_call_failed", error=str(e))
        return None


async def mark_connected(call_id: str, provider_call_sid: str = "") -> None:
    url, key = _conf()
    if not (url and key):
        return
    body = {"status": "connected", "started_at": datetime.now(timezone.utc).isoformat()}
    if provider_call_sid:
        body["provider_call_sid"] = provider_call_sid
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.patch(
                f"{url}/rest/v1/calls", params={"id": f"eq.{call_id}"},
                headers=_headers(key, **{"Content-Type": "application/json"}), json=body,
            )
    except Exception as e:
        logger.error("mark_connected_failed", call_id=call_id, error=str(e))


def credits_for(duration_s: float, voice_tier: str) -> float:
    """Billed in 30 s blocks, minimum one block."""
    rate = RATE_PER_MIN.get(voice_tier, RATE_PER_MIN["standard"])
    blocks = max(1, -(-int(duration_s) // 30))
    return round(blocks * 0.5 * rate, 2)


async def finalize_call(call_id: str, agent: AgentConfig, state, summary: str, account_id: str) -> None:
    """Save the outcome of a call and bill its credits (once)."""
    url, key = _conf()
    if not (url and key):
        return
    duration = int(state.duration_s)
    # A call that never got a caller turn is free; otherwise bill by duration.
    credits = credits_for(duration, str(getattr(agent.voice_tier, "value", agent.voice_tier))) if duration > 0 else 0.0
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            existing = (
                await client.get(
                    f"{url}/rest/v1/calls", params={"id": f"eq.{call_id}", "select": "credits_used"},
                    headers=_headers(key),
                )
            ).json()
            already_billed = bool(existing and float(existing[0].get("credits_used") or 0) > 0)

            await client.patch(
                f"{url}/rest/v1/calls", params={"id": f"eq.{call_id}"},
                headers=_headers(key, **{"Content-Type": "application/json"}),
                json={
                    "status": "completed",
                    "duration_seconds": duration,
                    "transcript": state.transcript,
                    "captured_fields": state.captured_fields,
                    "summary": summary,
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    **({} if already_billed else {"credits_used": credits}),
                },
            )

            if credits > 0 and not already_billed:
                r = await client.post(
                    f"{url}/rest/v1/rpc/deduct_credits",
                    headers=_headers(key, **{"Content-Type": "application/json"}),
                    json={
                        "p_account_id": account_id,
                        "p_amount": credits,
                        "p_type": "call_usage",
                        "p_reference_id": call_id,
                        "p_description": f"Call {duration}s",
                    },
                )
                logger.info("credits_deducted", call_id=call_id, credits=credits, result=r.json())
    except Exception as e:
        logger.error("finalize_call_failed", call_id=call_id, error=str(e))
