import logging
import asyncio
import os
import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
from dotenv import load_dotenv

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
)
from livekit.plugins import openai, deepgram, elevenlabs
from livekit.api import LiveKitAPI

from backend.monitoring import event_bus, EventType
from backend.tools import (
    check_availability,
    book_appointment,
    lookup_appointment,
    cancel_appointment,
    reschedule_appointment,
    transfer_to_human,
    end_call,
)
from backend.twilio_transfer import initiate_warm_transfer
from backend import db

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=True)
if os.getenv("ELEVENLABS_API_KEY") and not os.getenv("ELEVEN_API_KEY"):
    os.environ["ELEVEN_API_KEY"] = os.environ["ELEVENLABS_API_KEY"]

logger = logging.getLogger("voicedesk.agent")

async def get_system_prompt() -> str:
    from backend import cal_service as cal
    details = await cal.get_event_type_details()
    durations_str = ", ".join(f"{d}m" for d in details.get("durations", [30, 60]))
    title = details.get("title", "Consultation")
    return f"""You are Alex, VoiceDesk's AI receptionist for {title}. Match caller's language (multilingual). Keep voice replies natural & short (max 2 sentences).

## FLOW (Ask ONE detail at a time)
1. Greet & get appointment reason.
2. Duration -> Inform caller available durations for {title} are: {durations_str}. Ask which length they prefer.
3. Date/Time -> Verify via check_availability. Offer open alternatives if taken.
4. Full Name.
5. Phone -> Read back digit-by-digit to confirm.
6. Email -> Spell back letter-by-letter to confirm. Repeat until confirmed.
7. Confirm -> Read back full summary (reason, duration, date/time, name, phone, email). Ask "Shall I book this?"
8. Book -> Call book_appointment ONLY after explicit confirmation. Share ID & ask if anything else is needed.
9. End -> When caller is done, ask "Would you like me to end the call?" ONLY after "yes", say goodbye & call end_call.

## CRITICAL RULES
- NEVER call book_appointment without confirmed phone, email, and explicit user consent on the summary.
- Rescheduling/Changing time? ALWAYS use reschedule_appointment(booking_id). NEVER use book_appointment for changes.
- Existing appointments? Use lookup_appointment or cancel_appointment.
- Billing inquiries or complaints? Use transfer_to_human."""


def _get_llm(model: str = "gpt-4o"):
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key and os.getenv("OPENAI_API_KEY", "").startswith("gsk_"):
        groq_key = os.getenv("OPENAI_API_KEY")
    if groq_key:
        groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        return openai.LLM(
            model=groq_model,
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
        )
    return openai.LLM(model=model)


async def entrypoint(ctx: JobContext):
    await db.init_db()
    await ctx.connect()

    await event_bus.emit(EventType.CALL_STATUS, {"status": "connected"})

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=_get_llm(),
        tts=deepgram.TTS(model="aura-asteria-en"),
    )

    tools = [
        check_availability,
        book_appointment,
        lookup_appointment,
        cancel_appointment,
        reschedule_appointment,
        transfer_to_human,
        end_call,
    ]

    instructions = await get_system_prompt()
    agent = Agent(
        instructions=instructions,
        tools=tools,
    )

    import re
    _last_emitted = {}  # track last emitted text per role to deduplicate

    @session.on("conversation_item_added")
    def on_item_added(ev):
        item = ev.item
        if not hasattr(item, "role") or not hasattr(item, "text_content"):
            return
        text = item.text_content or ""
        # Strip function-call XML tags the LLM emits (e.g. <function=name>{...}</function>)
        text = re.sub(r"<function=[^>]*>.*?</function>", "", text, flags=re.DOTALL).strip()
        if not text:
            return
        role = "user" if item.role == "user" else "agent"
        # Deduplicate: skip if identical to last emitted text for this role
        if _last_emitted.get(role) == text:
            return
        _last_emitted[role] = text
        asyncio.create_task(
            event_bus.emit(EventType.TRANSCRIPT, {"role": role, "text": text})
        )

    @session.on("agent_state_changed")
    def on_state_changed(ev):
        asyncio.create_task(event_bus.emit(EventType.AGENT_STATE, {"state": ev.new_state}))

    @session.on("function_tools_executed")
    def on_tools_executed(ev):
        outputs = getattr(ev, "function_call_outputs", []) or []
        for out in outputs:
            output_str = str(getattr(out, "output", "") or getattr(out, "result", "") or "")
            logger.info(f"Tool output: {output_str}")
            if "__TRANSFER_REQUESTED__" in output_str:
                asyncio.create_task(handle_transfer(session, ctx))
            if "__END_CALL__" in output_str:
                asyncio.create_task(handle_end_call(session, ctx))

    @ctx.room.on("participant_connected")
    def on_participant_connected(participant):
        if participant.identity == "watcher":
            logger.info("Watcher joined, muting agent")
            session.interrupt()
            for pub in ctx.room.local_participant.track_publications.values():
                if pub.track:
                    pub.track.mute()

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant):
        if participant.identity == "watcher":
            logger.info("Watcher left, unmuting agent")
            for pub in ctx.room.local_participant.track_publications.values():
                if pub.track:
                    pub.track.unmute()
            return

        # Main caller left
        async def _generate_and_emit_summary():
            await event_bus.emit(EventType.CALL_STATUS, {"status": "ended"})
            summary = await generate_call_summary(session)
            await event_bus.emit(EventType.CALL_SUMMARY, {"summary": summary})
        
        asyncio.create_task(_generate_and_emit_summary())

    await session.start(agent=agent, room=ctx.room)

    await session.generate_reply(
        instructions="Greet the caller warmly by saying: 'Hello, thank you for calling VoiceDesk. My name is Alex, how can I assist you today?'"
    )


async def handle_end_call(session: AgentSession, ctx: JobContext):
    """Gracefully end the call: generate summary, then disconnect all participants."""
    logger.info("End call requested by agent")

    # Generate call summary before disconnecting
    try:
        summary = await generate_call_summary(session)
        await event_bus.emit(EventType.CALL_SUMMARY, {"summary": summary})
    except Exception as e:
        logger.warning(f"Failed to generate call summary: {e}")

    # Wait for TTS to finish the goodbye message
    await asyncio.sleep(4)

    # Remove all remote participants (callers) from the room via LiveKit server API
    try:
        from livekit.protocol.room import RoomParticipantIdentity, DeleteRoomRequest

        lk_api = LiveKitAPI(
            url=os.getenv("LIVEKIT_URL", ""),
            api_key=os.getenv("LIVEKIT_API_KEY", ""),
            api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
        )

        for participant in list(ctx.room.remote_participants.values()):
            logger.info(f"Removing participant: {participant.identity}")
            try:
                await lk_api.room.remove_participant(
                    RoomParticipantIdentity(
                        room=ctx.room.name,
                        identity=participant.identity,
                    )
                )
            except Exception as ex:
                logger.warning(f"Could not remove {participant.identity}: {ex}")

        # Delete the room entirely
        await lk_api.room.delete_room(
            DeleteRoomRequest(room=ctx.room.name)
        )
        await lk_api.aclose()
        logger.info("Room deleted, call ended")
    except Exception as e:
        logger.error(f"Failed to end call via API: {e}", exc_info=True)


async def handle_transfer(session: AgentSession, ctx: JobContext):
    transcript_parts = []
    # In livekit-agents >= 1.6, AgentSession uses session.history which is a ChatContext with .items
    for msg in session.history.items:
        if hasattr(msg, "role") and hasattr(msg, "content") and msg.content:
            transcript_parts.append(f"{msg.role}: {msg.content}")
    summary = ". ".join(transcript_parts[-6:]) if transcript_parts else "No context available"

    await event_bus.emit(EventType.CALL_STATUS, {"status": "transferring"})

    result = await initiate_warm_transfer(summary)

    if result["accepted"]:
        await event_bus.emit(EventType.CALL_STATUS, {"status": "transferred"})
        await session.generate_reply(
            instructions="Tell the caller you've connected them with a team member who can help. Say goodbye warmly."
        )
    else:
        await event_bus.emit(EventType.CALL_STATUS, {"status": "connected"})
        await session.generate_reply(
            instructions="Apologize to the caller — our team isn't available right now. Offer to help with anything else or take a message."
        )


async def generate_call_summary(session: AgentSession) -> str:
    messages = []
    for msg in session.history.items:
        if hasattr(msg, "role") and hasattr(msg, "content") and msg.content:
            messages.append(f"{msg.role}: {msg.content}")

    if not messages:
        return "No conversation recorded."

    transcript = "\n".join(messages)
    llm = _get_llm()

    summary_prompt = f"""Summarize this call transcript in 3-4 sentences. Include:
- What the caller wanted
- What actions were taken (bookings, transfers, etc.)
- How the call ended

Transcript:
{transcript}"""

    from livekit.agents.llm import ChatContext, ChatMessage
    ctx = ChatContext()
    ctx.items.append(ChatMessage(role="user", content=[summary_prompt]))
    stream = llm.chat(chat_ctx=ctx)
    summary_text = ""
    async for text in stream.to_str_iterable():
        summary_text += text
    return summary_text


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )
