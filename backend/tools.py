import logging
from livekit.agents import function_tool, RunContext
from backend import db, calendar as cal
from backend.monitoring import event_bus, EventType

logger = logging.getLogger("voicedesk.tools")


@function_tool(
    name="check_availability",
    description="Check available appointment slots for a given date. Returns a list of open time slots.",
)
async def check_availability(
    context: RunContext,
    date: str,
):
    """date: The date to check in YYYY-MM-DD format."""
    await event_bus.emit(EventType.ACTION, {"action": "checking availability", "date": date})

    if cal.is_configured():
        slots = await cal.get_available_slots(date)
    else:
        slots = await db.get_available_slots(date)

    if not slots:
        return f"No available slots on {date}. Please try another date."

    formatted = ", ".join(slots)
    return f"Available slots on {date}: {formatted}"


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
    date_time: Appointment date and time in 'YYYY-MM-DD HH:MM' format.
    contact_number: Caller's phone number.
    """
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
            result = await cal.create_booking(
                name=caller_name,
                email="",
                start_time=date_time,
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
    booking_id: int,
):
    """booking_id: The numeric booking ID to cancel."""
    await event_bus.emit(EventType.ACTION, {"action": "cancelling appointment", "booking_id": booking_id})

    booking = await db.get_booking(booking_id)
    if not booking:
        return f"No appointment found with ID {booking_id}."

    if cal.is_configured() and booking.get("cal_booking_uid"):
        await cal.cancel_booking(booking["cal_booking_uid"])

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
    booking_id: int,
    new_date_time: str,
):
    """
    booking_id: The numeric booking ID to reschedule.
    new_date_time: New date and time in 'YYYY-MM-DD HH:MM' format.
    """
    await event_bus.emit(EventType.ACTION, {"action": "rescheduling", "booking_id": booking_id})

    booking = await db.get_booking(booking_id)
    if not booking:
        return f"No appointment found with ID {booking_id}."

    if cal.is_configured() and booking.get("cal_booking_uid"):
        result = await cal.reschedule_booking(booking["cal_booking_uid"], new_date_time)
        if not result:
            return f"The slot at {new_date_time} is not available. Please try another time."

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
