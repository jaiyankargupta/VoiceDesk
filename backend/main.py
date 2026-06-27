import os
import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from livekit.api import LiveKitAPI, AccessToken, VideoGrants

from backend import db
from backend.monitoring import event_bus, EventType

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voicedesk.server")

LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

takeover_active = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(title="VoiceDesk API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/token")
async def create_token(room: str = "voicedesk-room", identity: str = "caller"):
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")

    token = (
        AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True,
        ))
    )

    return {"token": token.to_jwt(), "url": LIVEKIT_URL}


@app.get("/api/appointments")
async def list_appointments():
    bookings = await db.get_all_bookings()
    return {"appointments": bookings}


@app.post("/api/takeover")
async def takeover():
    global takeover_active
    takeover_active = True
    await event_bus.emit(EventType.ACTION, {"action": "human takeover active"})
    await event_bus.emit(EventType.AGENT_STATE, {"state": "paused"})
    return {"status": "takeover_active"}


@app.post("/api/release")
async def release():
    global takeover_active
    takeover_active = False
    await event_bus.emit(EventType.ACTION, {"action": "agent resumed"})
    await event_bus.emit(EventType.AGENT_STATE, {"state": "listening"})
    return {"status": "agent_resumed"}


@app.get("/api/takeover-status")
async def takeover_status():
    return {"active": takeover_active}


@app.post("/api/transfer-response")
async def transfer_response(request: Request):
    form = await request.form()
    digits = form.get("Digits", "")
    if digits == "1":
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response><Say voice="Polly.Joanna">Accepted. Connecting...</Say></Response>'
    else:
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response><Say voice="Polly.Joanna">Declined.</Say><Hangup/></Response>'
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/ws/monitor")
async def monitor_websocket(ws: WebSocket):
    await ws.accept()
    queue = event_bus.subscribe()
    try:
        while True:
            event = await queue.get()
            await ws.send_text(event.to_json())
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
