import os
import logging
import asyncio
from twilio.rest import Client

logger = logging.getLogger("voicedesk.transfer")

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM_NUMBER", "")
HUMAN_PHONE = os.getenv("HUMAN_AGENT_PHONE", "")

TRANSFER_TIMEOUT = 30


def _get_client() -> Client | None:
    if not all([TWILIO_SID, TWILIO_TOKEN]):
        logger.warning("Twilio credentials not configured")
        return None
    return Client(TWILIO_SID, TWILIO_TOKEN)


async def initiate_warm_transfer(call_summary: str) -> dict:
    """
    Dial the human agent, speak the call summary, and gather their response.
    Returns {"accepted": bool, "message": str}.
    """
    client = _get_client()
    if not client:
        return {"accepted": False, "message": "Twilio is not configured"}

    if not HUMAN_PHONE:
        return {"accepted": False, "message": "Human agent phone number not set"}

    try:
        twiml = _build_transfer_twiml(call_summary)
        call = await asyncio.to_thread(
            client.calls.create,
            to=HUMAN_PHONE,
            from_=TWILIO_FROM,
            twiml=twiml,
            timeout=TRANSFER_TIMEOUT,
            status_callback_event=["completed"],
        )
        logger.info(f"Initiated transfer call: {call.sid}")

        accepted = await _poll_call_status(client, call.sid)

        if accepted:
            return {
                "accepted": True,
                "message": "Human agent accepted the transfer",
                "call_sid": call.sid,
            }
        return {"accepted": False, "message": "Human agent declined or did not answer"}

    except Exception as e:
        logger.error(f"Transfer failed: {e}")
        return {"accepted": False, "message": f"Transfer failed: {str(e)}"}


def _build_transfer_twiml(summary: str) -> str:
    escaped = summary.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">
        You have an incoming transfer from VoiceDesk.
        Here is the call summary: {escaped}
    </Say>
    <Pause length="1"/>
    <Gather numDigits="1" timeout="10" action="/api/transfer-response">
        <Say voice="Polly.Joanna">
            Press 1 to accept the call, or press 2 to decline.
        </Say>
    </Gather>
    <Say voice="Polly.Joanna">No response received. The call will be declined.</Say>
</Response>"""


async def _poll_call_status(client: Client, call_sid: str, max_wait: int = 45) -> bool:
    """Poll Twilio for call completion. In production, use a webhook instead."""
    for _ in range(max_wait // 3):
        await asyncio.sleep(3)
        try:
            call = await asyncio.to_thread(client.calls(call_sid).fetch)
            if call.status in ("completed", "failed", "busy", "no-answer", "canceled"):
                return call.status == "completed"
        except Exception:
            break
    return False


async def end_transfer_call(call_sid: str):
    client = _get_client()
    if client and call_sid:
        try:
            await asyncio.to_thread(
                client.calls(call_sid).update, status="completed"
            )
        except Exception as e:
            logger.error(f"Failed to end transfer call: {e}")
