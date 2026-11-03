"""Voice Pipeline Server -- FastAPI + WebSocket entry point."""

import asyncio
import os
import re
import structlog
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.pipeline.session import CallSession
from src.pipeline.phone import PhoneTransport
from src.providers.pool import warm_up
from src.models.schemas import AgentConfig
from src.utils import calls_db

load_dotenv()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("voice_server_starting", port=8765)
    asyncio.create_task(warm_up())
    yield
    logger.info("voice_server_stopping")


app = FastAPI(title="VoiceAI Pipeline Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in [os.getenv("FRONTEND_URL", "http://localhost:3001")] if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"ok": True, "service": "voice-pipeline"}


# In-memory agent configs for MVP. Replace with DB lookup in production.
DEFAULT_AGENT = AgentConfig(
    id="default-agent",
    name="Priya",
    company="Demo Company",
    language="hi-IN",
    greeting="Namaste ji! Main Priya bol rahi hoon Demo Company se. Aapne enquiry ki thi, kya main aapki help kar sakti hoon?",
    system_prompt="You are calling leads who enquired about services. Qualify their interest, budget, and timeline. Book a follow-up if interested.",
    knowledge_base="Services: Standard plan Rs 5000/month, Premium plan Rs 12000/month. Free trial available. Support in Hindi, Telugu, Tamil, English.",
    capture_fields=["name", "interest", "budget", "timeline"],
    voice_provider="cartesia",
    voice_id="4459a9a5-69d6-4680-b970-e13dc51845b6",
    voice_tier="premium",
    tools_enabled=["capture_field", "book_appointment", "send_whatsapp"],
    max_call_duration_s=300,
)


TEST_CALL_ID = re.compile(r"^test-([0-9a-fA-F-]{36})$")


async def run_call(transport, call_id: str, agent: AgentConfig, account_id: str | None) -> None:
    """Run one call to completion, then save the record and bill the credits."""
    session = CallSession(transport, call_id, agent)
    await session.run()
    logger.info(
        "call_completed",
        call_id=call_id,
        duration=round(session.state.duration_s),
        turns=session.state.turn_count,
        captured=session.state.captured_fields,
    )
    if account_id:
        await calls_db.finalize_call(call_id, agent, session.state, session.summary, account_id)


@app.websocket("/call/{call_id}")
async def voice_call_ws(ws: WebSocket, call_id: str):
    """Browser calls. "test-<employee id>" is a dashboard Test Call."""
    await ws.accept()
    logger.info("call_connected", call_id=call_id)

    try:
        agent, record_id, account_id = DEFAULT_AGENT, call_id, None
        m = TEST_CALL_ID.match(call_id)
        if m:
            emp = await calls_db.load_employee(m.group(1))
            if emp:
                agent = calls_db.agent_from_employee(emp)
                account_id = emp["account_id"]
                record_id = await calls_db.create_web_call(emp) or call_id
                if record_id == call_id:
                    account_id = None  # no row to update or bill
        logger.info("agent_loaded", call_id=call_id, agent=agent.name, language=agent.language)
        await run_call(ws, record_id, agent, account_id)

    except WebSocketDisconnect:
        logger.info("call_disconnected", call_id=call_id)
    except Exception as e:
        logger.error("call_error", call_id=call_id, error=str(e))


async def _phone_call(ws: WebSocket, provider: str, call_id: str | None, query_token: str | None):
    await ws.accept()
    transport = PhoneTransport(ws, provider)
    try:
        start = await transport.wait_start()
        custom = start["custom"]
        call_id = call_id or custom.get("call_id")
        token = query_token or custom.get("token")

        call = None
        if call_id and calls_db.valid_call_token(call_id, token):
            call = await calls_db.load_call(call_id)
        elif not call_id and provider == "exotel":
            # Exotel's Voicebot URL is fixed per flow, so match the call we just placed
            call = await calls_db.find_pending_call_by_number(start["to"] or start["from"])
            if not call:  # no pending outbound call: an inbound call to one of our numbers
                call = await calls_db.create_inbound_call(start["from"], start["to"], provider, start["call_sid"])
            call_id = call["id"] if call else None

        if not call or not call.get("employees"):
            logger.warning("phone_call_rejected", provider=provider, call_id=call_id)
            await ws.close(code=1008)
            return

        agent = calls_db.agent_from_employee(call["employees"])
        logger.info("phone_call_connected", provider=provider, call_id=call_id, agent=agent.name, language=agent.language)
        await calls_db.mark_connected(call_id, start["call_sid"])
        await run_call(transport, call_id, agent, call["account_id"])

    except WebSocketDisconnect:
        logger.info("phone_call_disconnected", provider=provider, call_id=call_id)
    except Exception as e:
        logger.error("phone_call_error", provider=provider, call_id=call_id, error=str(e))


@app.websocket("/phone/{provider}/{call_id}")
async def phone_call_ws(ws: WebSocket, provider: str, call_id: str, token: str | None = None):
    """Phone calls placed by the API. The call id is in the path, the signed
    token arrives as a query parameter (Exotel) or a stream parameter (Twilio)."""
    await _phone_call(ws, provider, call_id, token)


@app.websocket("/phone/{provider}")
async def phone_call_ws_no_id(ws: WebSocket, provider: str, token: str | None = None):
    await _phone_call(ws, provider, None, token)


@app.websocket("/test-call")
async def test_call_ws(ws: WebSocket):
    """Simplified test endpoint -- no call_id needed."""
    await voice_call_ws(ws, "test-" + str(int(__import__("time").time())))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8765,
        reload=True,
        ws_ping_interval=30,
        ws_ping_timeout=30,
    )
