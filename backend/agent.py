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
from livekit.plugins import openai, deepgram, elevenlabs, silero

from backend.monitoring import event_bus, EventType
from backend.tools import (
    check_availability,
    book_appointment,
    cancel_appointment,
    reschedule_appointment,
    transfer_to_human,
)
from backend.twilio_transfer import initiate_warm_transfer
from backend import db

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)
if os.getenv("ELEVENLABS_API_KEY") and not os.getenv("ELEVEN_API_KEY"):
    os.environ["ELEVEN_API_KEY"] = os.environ["ELEVENLABS_API_KEY"]

logger = logging.getLogger("voicedesk.agent")

SYSTEM_PROMPT = """You are a friendly, professional receptionist named Alex at a medical clinic called VoiceDesk Health.

Your responsibilities:
- Greet callers warmly and ask how you can help
- Book, reschedule, or cancel appointments using the available tools
- When booking, you must collect: full name, reason for visit, preferred date and time, and contact phone number.
- CRITICAL: Ask for these details ONE AT A TIME naturally (e.g. ask for the date/time first to check availability, then ask for their name, then their phone number). Do NOT ask for all details in a single sentence.
- Always check availability before confirming a booking
- Read back the full booking confirmation to the caller

Intent detection:
- If the caller mentions billing, payments, or account charges → use transfer_to_human with reason "billing inquiry"
- If the caller wants to file a complaint → use transfer_to_human with reason "complaint"
- If the caller says anything like "talk to a person", "speak to someone", "real agent", "human" → use transfer_to_human with the appropriate reason
- For general questions about clinic hours or services, answer directly

Style:
- Keep responses concise and conversational — this is a phone call, not a chat
- Use natural spoken language, avoid bullet points or markdown
- Confirm details by repeating them back before booking
- Be patient if the caller is unclear; ask clarifying questions
"""


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


def _get_llm(model: str = "gpt-4o"):
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key and os.getenv("OPENAI_API_KEY", "").startswith("gsk_"):
        groq_key = os.getenv("OPENAI_API_KEY")
    if groq_key:
        groq_model = "llama-3.3-70b-versatile" if "gpt" in model else model
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
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(model="nova-3"),
        llm=_get_llm(),
        tts=elevenlabs.TTS(),
    )

    tools = [
        check_availability,
        book_appointment,
        cancel_appointment,
        reschedule_appointment,
        transfer_to_human,
    ]

    agent = Agent(
        instructions=SYSTEM_PROMPT,
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
        for out in ev.function_call_outputs:
            if out and out.output and "__TRANSFER_REQUESTED__" in str(out.output):
                asyncio.create_task(handle_transfer(session, ctx))

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
        instructions="Greet the caller warmly. Ask how you can help them today."
    )


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
            prewarm_fnc=prewarm,
        )
    )
