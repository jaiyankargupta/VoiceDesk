import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from livekit.agents import function_tool, RunContext
from backend import db, cal_service as cal
from backend.monitoring import event_bus, EventType

logger = logging.getLogger("voicedesk.tools")

_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _to_utc_iso(dt_str: str) -> str:
    try:
        clean = dt_str.replace("T", " ")[:16]
        local_dt = datetime.strptime(clean, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        return local_dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return dt_str.replace(" ", "T") + ":00Z" if "T" not in dt_str else dt_str


def _sanitize_email(email: str) -> str:
    import re
    e = email.strip()
    # If already looks like a valid email, just lowercase and return
    if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', e):
        return e.lower()
    # Normalise spoken email: replace 'dot' → '.', 'at' → '@', 'underscore' → '_', 'dash'/'hyphen' → '-'
    e = e.lower()
    e = re.sub(r'\s+dot\s+', '.', e)
    e = re.sub(r'\s+at\s+', '@', e)
    e = re.sub(r'\s+(underscore|under score|under_score)\s+', '_', e)
    e = re.sub(r'\s+(dash|hyphen|minus)\s+', '-', e)
    # Remove any remaining spaces
    e = e.replace(' ', '')
    return e


def _resolve_date(raw: str) -> str:
    import re
    s = raw.strip().lower()
    today = datetime.now()

    # If it contains YYYY-MM-DD anywhere, extract it
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    if match:
        return match.group(0)

    if "tomorrow" in s:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if "today" in s:
        return today.strftime("%Y-%m-%d")

    for i, name in enumerate(_DAY_NAMES):
        if name in s:
            days_ahead = i - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    
    logger.warning(f"Could not parse date '{raw}', defaulting to today")
    return today.strftime("%Y-%m-%d")


@function_tool(
    name="check_availability",
    description="Check available appointment slots for a given date. The date can be natural language like 'today', 'tomorrow', 'Thursday', or a specific date in YYYY-MM-DD format. Specify duration like '30m' or '60m'.",
)
async def check_availability(
    context: RunContext,
    date: str,
    duration: str = "30m",
):
   
    date = _resolve_date(date)
    await event_bus.emit(EventType.ACTION, {"action": f"checking availability ({duration})", "date": date})

    if cal.is_configured():
        try:
            slots = await cal.get_available_slots(date, duration)
        except Exception as e:
            logger.warning(f"Cal.com slot check failed: {e}")
            slots = await db.get_available_slots(date, duration)
    else:
        slots = await db.get_available_slots(date, duration)

    if not slots:
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            day_name = dt.strftime("%A")
            
            # Find next business day
            days_ahead = 1
            while (dt + timedelta(days=days_ahead)).weekday() in [5, 6]:
                days_ahead += 1
            next_dt = dt + timedelta(days=days_ahead)
            next_date = next_dt.strftime("%Y-%m-%d")
            next_day_name = next_dt.strftime("%A")
            
            if cal.is_configured():
                try:
                    next_slots = await cal.get_available_slots(next_date, duration)
                except Exception:
                    next_slots = await db.get_available_slots(next_date, duration)
            else:
                next_slots = await db.get_available_slots(next_date, duration)
                
            formatted_next = []
            for slot in next_slots:
                try:
                    t = datetime.fromisoformat(slot.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Kolkata"))
                    formatted_next.append(t.strftime("%-I:%M %p"))
                except Exception:
                    formatted_next.append(slot)
            
            slots_str = ", ".join(formatted_next) if formatted_next else "No slots available"
            if day_name in ["Saturday", "Sunday"]:
                return f"No available slots on {date} because our office is closed on {day_name}s. However, we checked the calendar for Monday ({next_date}) and these times are open for a {duration} appointment: {slots_str}. Please suggest these exact available times to the caller."
            else:
                return f"No available slots on {date} as it is fully booked. However, on {next_day_name} ({next_date}), these times are open for a {duration} appointment: {slots_str}. Please suggest these exact available times to the caller."
        except Exception as e:
            logger.warning(f"Next day check failed: {e}")
        return f"No available slots on {date}. All appointment times are fully booked."

    # Format all slots dynamically without hardcoded limits
    formatted_slots = []
    for slot in slots:
        try:
            t = datetime.fromisoformat(slot.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Kolkata"))
            formatted_slots.append(t.strftime("%-I:%M %p"))
        except Exception:
            formatted_slots.append(slot)

    return f"Available slots on {date}: {', '.join(formatted_slots)}"


@function_tool(
    name="book_appointment",
    description="Book an appointment after confirming details with the caller. All fields are required. Specify the exact duration (e.g. '30m' or '60m') and the specific topic/reason so the system dynamically generates their custom meeting.",
)
async def book_appointment(
    context: RunContext,
    caller_name: str,
    reason: str,
    date_time: str,
    contact_number: str,
    email: str = "",
    duration: str = "30m",
):
    # Sanitize email — convert verbally-spelled format to proper email
    if email:
        email = _sanitize_email(email)

    if not caller_name.strip() or not contact_number.strip() or not email.strip():
        return "Error: Cannot book appointment. Missing required details (name, contact number, or email). Please collect all details from the caller or use reschedule_appointment if modifying an existing booking."

    if "T" in date_time:
        parts = date_time.strip().split("T", 1)
        time_clean = parts[1].replace(".000Z", "").replace("Z", "")
        if len(time_clean.split(":")) == 3:
            time_clean = ":".join(time_clean.split(":")[:2])
        date_part = _resolve_date(parts[0])
        parsed_time = time_clean
        date_time = f"{date_part} {parsed_time}"
    else:
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

    await event_bus.emit(EventType.ACTION, {"action": f"booking appointment ({duration})"})
    await event_bus.emit(EventType.APPOINTMENT_DATA, {
        "name": caller_name,
        "reason": reason,
        "date_time": date_time,
        "contact": contact_number,
        "status": "booking...",
    })

    available = await db.check_slot_available(date_time, duration=duration)
    if not available:
        await event_bus.emit(EventType.APPOINTMENT_DATA, {"status": "slot taken"})
        return f"Sorry, the slot at {date_time} is no longer available. Please choose a different time."

    cal_uid = None
    if cal.is_configured():
        try:
            cal_start = _to_utc_iso(date_time)
            result = await cal.create_booking(
                name=caller_name,
                email=email,
                start_time=cal_start,
                reason=reason,
                phone=contact_number,
                duration=duration,
            )
            cal_uid = result.get("uid")
        except Exception as e:
            logger.warning(f"Cal.com booking failed: {e}")
            await event_bus.emit(EventType.APPOINTMENT_DATA, {"status": "slot unavailable"})
            return f"Sorry, could not confirm the slot at {date_time} on the calendar ({e}). Please ask the caller to choose a different available time."

    booking_id = await db.save_booking(
        caller_name=caller_name,
        reason=reason,
        date_time=date_time,
        contact_number=contact_number,
        cal_booking_uid=cal_uid,
        email=email,
        duration=duration,
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
    name="lookup_appointment",
    description="Look up existing appointments by caller name, phone number, or email.",
)
async def lookup_appointment(context: RunContext, query: str):
    results = await db.lookup_booking(query)
    if not results:
        return f"No appointments found matching '{query}'."
    formatted = [f"ID {r['id']}: {r['caller_name']} for {r['reason']} on {r['date_time']} ({r['status']})" for r in results]
    return f"Found appointments: {'; '.join(formatted)}"


@function_tool(
    name="cancel_appointment",
    description="Cancel an existing appointment by its booking ID.",
)
async def cancel_appointment(
    context: RunContext,
    booking_id: str,
):
   
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
    
    import re
    booking_id = int(booking_id)
    await event_bus.emit(EventType.ACTION, {"action": "rescheduling", "booking_id": booking_id})

    booking = await db.get_booking(booking_id)
    if not booking:
        return f"No appointment found with ID {booking_id}."

    # 1. Clean number words if STT/LLM spelled them out
    s_clean = new_date_time.lower()
    for w, num in [('forty five', ':45'), ('thirty', ':30'), ('fifteen', ':15'),
                   ('twelve', '12'), ('eleven', '11'), ('ten', '10'), ('nine', '9'),
                   ('eight', '8'), ('seven', '7'), ('six', '6'), ('five', '5'),
                   ('four', '4'), ('three', '3'), ('two', '2'), ('one', '1')]:
        s_clean = re.sub(r'\b' + w + r'\b', num, s_clean)
    s_clean = s_clean.replace(' :', ':').upper()

    # 2. Determine date (if no date mentioned, preserve existing appointment date)
    has_date = 'TODAY' in s_clean or 'TOMORROW' in s_clean or any(d in s_clean for d in ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY']) or re.search(r'\d{4}-\d{2}-\d{2}', s_clean)
    if has_date:
        date_part = _resolve_date(new_date_time)
    else:
        date_part = str(booking.get("date_time", ""))[:10]

    # 3. Extract time
    parsed_time = "09:00"
    match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?', s_clean)
    if match:
        hr = int(match.group(1))
        mn = int(match.group(2) or 0)
        ampm = match.group(3)
        if ampm == 'PM' and hr < 12:
            hr += 12
        elif ampm == 'AM' and hr == 12:
            hr = 0
        elif not ampm and hr < 8:
            hr += 12
        parsed_time = f"{hr:02d}:{mn:02d}"

    new_date_time = f"{date_part} {parsed_time}"

    if cal.is_configured() and booking.get("cal_booking_uid"):
        cal_start = _to_utc_iso(new_date_time)
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
    
    await event_bus.emit(EventType.INTENT, {"intent": "transfer_request", "reason": reason})
    await event_bus.emit(EventType.ACTION, {"action": "initiating warm transfer"})
    await event_bus.emit(EventType.CALL_STATUS, {"status": "transferring"})

    return "__TRANSFER_REQUESTED__"


@function_tool(
    name="end_call",
    description="End the current call. Use this AFTER saying goodbye to the caller, when the conversation is complete and the caller has confirmed they don't need anything else.",
)
async def end_call(context: RunContext):
    await event_bus.emit(EventType.CALL_STATUS, {"status": "ended"})
    return "__END_CALL__"

