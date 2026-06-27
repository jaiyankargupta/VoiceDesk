import logging
import asyncio
import os
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

load_dotenv()
logger = logging.getLogger("voicedesk.agent")

SYSTEM_PROMPT = """You are a friendly, professional receptionist named Alex at a medical clinic called VoiceDesk Health.

Your responsibilities:
- Greet callers warmly and ask how you can help
- Book, reschedule, or cancel appointments using the available tools
- When booking, collect: full name, reason for visit, preferred date and time, and contact phone number
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

    @session.on("user_speech_committed")
    def on_user_speech(msg):
        asyncio.create_task(
            event_bus.emit(EventType.TRANSCRIPT, {"role": "user", "text": msg.content})
        )

    @session.on("agent_speech_committed")
    def on_agent_speech(msg):
        asyncio.create_task(
            event_bus.emit(EventType.TRANSCRIPT, {"role": "agent", "text": msg.content})
        )

    @session.on("agent_started_speaking")
    def on_speaking():
        asyncio.create_task(event_bus.emit(EventType.AGENT_STATE, {"state": "speaking"}))

    @session.on("agent_stopped_speaking")
    def on_stopped():
        asyncio.create_task(event_bus.emit(EventType.AGENT_STATE, {"state": "listening"}))

    @session.on("function_calls_collected")
    def on_thinking():
        asyncio.create_task(event_bus.emit(EventType.AGENT_STATE, {"state": "thinking"}))

    @session.on("function_calls_finished")
    async def on_tool_done(called_functions):
        for fn in called_functions:
            if fn.result and "__TRANSFER_REQUESTED__" in str(fn.result):
                await handle_transfer(session, ctx)

    await session.start(agent=agent, room=ctx.room)

    await session.generate_reply(
        instructions="Greet the caller warmly. Ask how you can help them today."
    )


async def handle_transfer(session: AgentSession, ctx: JobContext):
    transcript_parts = []
    for msg in session.chat_ctx.items:
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
    for msg in session.chat_ctx.items:
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

    response = await llm.chat(
        messages=[{"role": "user", "content": summary_prompt}]
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
