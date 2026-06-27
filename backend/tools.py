import logging
from datetime import datetime, timedelta
from livekit.agents import function_tool, RunContext
from backend import db, cal_service as cal
from backend.monitoring import event_bus, EventType

logger = logging.getLogger("voicedesk.tools")

_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _resolve_date(raw: str) -> str:
    """Convert natural-language date references to YYYY-MM-DD.

    Handles: 'today', 'tomorrow', day names like 'Thursday',
    and already-formatted YYYY-MM-DD strings.
    """
    s = raw.strip().lower()
    today = datetime.now()

    if s == "today":
        return today.strftime("%Y-%m-%d")
    if s == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # Check for day-of-week names (e.g. "thursday", "next monday")
    s_clean = s.replace("next ", "")
    for i, name in enumerate(_DAY_NAMES):
        if s_clean == name:
            days_ahead = i - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # If it already looks like YYYY-MM-DD, return as-is
    if len(raw) >= 10 and raw[4] == "-":
        return raw[:10]

    # Fallback: return today
    logger.warning(f"Could not parse date '{raw}', defaulting to today")
    return today.strftime("%Y-%m-%d")


@function_tool(
    name="check_availability",
    description="Check available appointment slots for a given date. The date can be natural language like 'today', 'tomorrow', 'Thursday', or a specific date in YYYY-MM-DD format.",
)
async def check_availability(
    context: RunContext,
    date: str,
):
    """date: The date to check, e.g. 'today', 'tomorrow', 'Thursday', or 'YYYY-MM-DD'."""
    date = _resolve_date(date)
    await event_bus.emit(EventType.ACTION, {"action": "checking availability", "date": date})

    if cal.is_configured():
        try:
            slots = await cal.get_available_slots(date)
        except Exception as e:
            logger.warning(f"Cal.com slot check failed: {e}")
            slots = await db.get_available_slots(date)
    else:
        slots = await db.get_available_slots(date)

    if not slots:
        return f"No available slots on {date}. Please try another date."

    # Format slots nicely for the AI to read aloud
    formatted_slots = []
    for slot in slots[:8]:  # Limit to 8 slots to avoid overwhelming the caller
        try:
            t = datetime.fromisoformat(slot.replace("Z", "+00:00"))
            formatted_slots.append(t.strftime("%-I:%M %p"))
        except Exception:
            formatted_slots.append(slot)

    return f"Available slots on {date}: {', '.join(formatted_slots)}"


@function_tool(
    name="book_appointment",
    description="Book an appointment after confirming details with the caller. All fields are required.",
)
async def book_appointment(
    context: RunContext,
    caller_name: str,
    reason: str,
    date_time: str,
    contact_number: str,
):
    """
    caller_name: Full name of the caller.
    reason: Reason for the appointment.
    date_time: Appointment date and time, e.g. 'today 3pm', 'Thursday 10:00', or 'YYYY-MM-DD HH:MM'.
    contact_number: Caller's phone number.
    """
    # Resolve date portion from natural language
    parts = date_time.strip().split(" ", 1)
    date_part = _resolve_date(parts[0])
    time_part = parts[1] if len(parts) > 1 else "09:00"
    # Normalize time_part (handle "3pm", "3:00 PM", "at 3 pm", etc.)
    time_part = time_part.strip().upper().replace(".", "")
    time_part = time_part.replace("AT ", "").strip()
    parsed_time = "09:00"  # fallback
    try:
        for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"):
            try:
                t = datetime.strptime(time_part, fmt)
                parsed_time = t.strftime("%H:%M")
                break
            except ValueError:
                continue
    except Exception:
        pass
    date_time = f"{date_part} {parsed_time}"

    await event_bus.emit(EventType.ACTION, {"action": "booking appointment"})
    await event_bus.emit(EventType.APPOINTMENT_DATA, {
        "name": caller_name,
        "reason": reason,
        "date_time": date_time,
        "contact": contact_number,
        "status": "booking...",
    })

    cal_uid = None
    if cal.is_configured():
        try:
            # Cal.com needs ISO 8601 format: YYYY-MM-DDTHH:MM:00Z
            cal_start = date_time.replace(" ", "T") + ":00Z" if "T" not in date_time else date_time
            result = await cal.create_booking(
                name=caller_name,
                email="",
                start_time=cal_start,
                reason=reason,
                phone=contact_number,
            )
            cal_uid = result.get("uid")
        except Exception as e:
            logger.warning(f"Cal.com booking failed, falling back to local DB: {e}")
    else:
        available = await db.check_slot_available(date_time)
        if not available:
            await event_bus.emit(EventType.APPOINTMENT_DATA, {"status": "slot taken"})
            return f"Sorry, the slot at {date_time} is no longer available. Please choose a different time."

    booking_id = await db.save_booking(
        caller_name=caller_name,
        reason=reason,
        date_time=date_time,
        contact_number=contact_number,
        cal_booking_uid=cal_uid,
    )

    await event_bus.emit(EventType.APPOINTMENT_DATA, {
        "name": caller_name,
        "reason": reason,
        "date_time": date_time,
        "contact": contact_number,
        "booking_id": booking_id,
        "status": "confirmed",
    })

    return (
        f"Appointment confirmed! Booking ID: {booking_id}. "
        f"{caller_name}, you are booked for {reason} on {date_time}. "
        f"We will reach you at {contact_number}."
    )


@function_tool(
    name="cancel_appointment",
    description="Cancel an existing appointment by its booking ID.",
)
async def cancel_appointment(
    context: RunContext,
    booking_id: str,
):
    """booking_id: The numeric booking ID to cancel."""
    booking_id = int(booking_id)
    await event_bus.emit(EventType.ACTION, {"action": "cancelling appointment", "booking_id": booking_id})

    booking = await db.get_booking(booking_id)
    if not booking:
        return f"No appointment found with ID {booking_id}."

    if cal.is_configured() and booking.get("cal_booking_uid"):
        try:
            await cal.cancel_booking(booking["cal_booking_uid"])
        except Exception as e:
            logger.warning(f"Cal.com cancellation failed: {e}")

    success = await db.cancel_booking(booking_id)
    if success:
        await event_bus.emit(EventType.APPOINTMENT_DATA, {"booking_id": booking_id, "status": "cancelled"})
        return f"Appointment {booking_id} has been cancelled."
    return f"Could not cancel appointment {booking_id}. It may already be cancelled."


@function_tool(
    name="reschedule_appointment",
    description="Reschedule an existing appointment to a new date and time.",
)
async def reschedule_appointment(
    context: RunContext,
    booking_id: str,
    new_date_time: str,
):
    """
    booking_id: The numeric booking ID to reschedule.
    new_date_time: New date and time in 'YYYY-MM-DD HH:MM' format.
    """
    booking_id = int(booking_id)
    
    # Resolve date portion from natural language
    parts = new_date_time.strip().split(" ", 1)
    date_part = _resolve_date(parts[0])
    time_part = parts[1] if len(parts) > 1 else "09:00"
    time_part = time_part.strip().upper().replace(".", "")
    time_part = time_part.replace("AT ", "").strip()
    parsed_time = "09:00"  # fallback
    try:
        for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"):
            try:
                t = datetime.strptime(time_part, fmt)
                parsed_time = t.strftime("%H:%M")
                break
            except ValueError:
                continue
    except Exception:
        pass
    new_date_time = f"{date_part} {parsed_time}"

    await event_bus.emit(EventType.ACTION, {"action": "rescheduling", "booking_id": booking_id})

    booking = await db.get_booking(booking_id)
    if not booking:
        return f"No appointment found with ID {booking_id}."

    if cal.is_configured() and booking.get("cal_booking_uid"):
        cal_start = new_date_time.replace(" ", "T") + ":00Z" if "T" not in new_date_time else new_date_time
        try:
            result = await cal.reschedule_booking(booking["cal_booking_uid"], cal_start)
            if not result:
                return f"The slot at {new_date_time} is not available. Please try another time."
        except Exception as e:
            logger.warning(f"Cal.com rescheduling failed: {e}")

    success = await db.reschedule_booking(booking_id, new_date_time)
    if success:
        await event_bus.emit(EventType.APPOINTMENT_DATA, {
            "booking_id": booking_id,
            "date_time": new_date_time,
            "status": "rescheduled",
        })
        return f"Appointment {booking_id} has been rescheduled to {new_date_time}."
    return f"Could not reschedule — the slot at {new_date_time} may not be available."


@function_tool(
    name="transfer_to_human",
    description="Transfer the caller to a human agent. Use when the caller requests to speak to a person, has a billing issue, or wants to make a complaint.",
)
async def transfer_to_human(
    context: RunContext,
    reason: str,
):
    """reason: Brief summary of why the caller needs a human agent."""
    await event_bus.emit(EventType.INTENT, {"intent": "transfer_request", "reason": reason})
    await event_bus.emit(EventType.ACTION, {"action": "initiating warm transfer"})
    await event_bus.emit(EventType.CALL_STATUS, {"status": "transferring"})

    return "__TRANSFER_REQUESTED__"
