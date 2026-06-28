import os
import httpx
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

CAL_BASE_URL = "https://api.cal.com/v2"


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('CAL_API_KEY', '')}",
        "cal-api-version": "2024-08-13",
        "Content-Type": "application/json",
    }


import re
import time

_DYNAMIC_EVENTS_CACHE = {}


def _parse_duration(duration: str | int) -> int:
    if isinstance(duration, int) and duration > 0:
        return duration
    dur_str = str(duration).strip().lower()
    match = re.search(r"(\d+)", dur_str)
    if match:
        val = int(match.group(1))
        if "h" in dur_str:
            return val * 60
        return val
    return 30


async def _get_or_create_event_type(title: str = "", duration: str | int = 30) -> int:
    fallback_id = os.getenv("CAL_EVENT_TYPE_ID") or "6143627"
    return int(fallback_id) if str(fallback_id).isdigit() else 6143627


def is_configured() -> bool:
    return bool(os.getenv("CAL_API_KEY"))


async def get_event_type_details() -> dict:
    """Fetch live event type configuration (title and allowed duration options) from Cal.com."""
    event_id = os.getenv("CAL_EVENT_TYPE_ID", "6143627")
    if not is_configured():
        return {"title": "Doctor Consultation", "durations": [30, 60, 90, 120]}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{CAL_BASE_URL}/event-types/{event_id}",
                headers=_get_headers(),
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                title = data.get("title") or "Consultation"
                return {"title": title, "durations": [30, 60, 90, 120]}
    except Exception as e:
        logger.warning(f"Failed to fetch Cal.com event details: {e}")
    return {"title": "Doctor Consultation", "durations": [30, 60, 90, 120]}


async def get_available_slots(date: str, duration: str = "30m") -> list[str]:
    dur_mins = _parse_duration(duration)
    event_type_id = await _get_or_create_event_type("", dur_mins)
    params = {
        "eventTypeId": event_type_id,
        "startTime": f"{date}T00:00:00Z",
        "endTime": f"{date}T23:59:59Z",
        "timeZone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{CAL_BASE_URL}/slots/available",
            headers=_get_headers(),
            params=params,
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    slots = data.get("data", {}).get("slots", {})
    available = []
    if isinstance(slots, dict):
        for slot_list in slots.values():
            for s in slot_list:
                if s.get("time"):
                    available.append(s["time"])
    elif isinstance(slots, list):
        for s in slots:
            if isinstance(s, dict) and s.get("time"):
                available.append(s["time"])

    return available


async def create_booking(
    name: str,
    email: str,
    start_time: str,
    reason: str = "",
    phone: str = "",
    duration: str = "",
) -> dict:
    dur_mins = _parse_duration(duration)
    event_type_id = await _get_or_create_event_type(reason or f"Meeting with {name}", dur_mins)
    user_email = email or f"{name.lower().replace(' ', '.')}@placeholder.com"
    payload = {
        "eventTypeId": event_type_id,
        "start": start_time,
        "lengthInMinutes": dur_mins,
        "attendee": {
            "name": name,
            "email": user_email,
            "timeZone": "Asia/Kolkata",
            "language": "en",
        },
        "bookingFieldsResponses": {
            "reason": reason or "Consultation",
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CAL_BASE_URL}/bookings?timeZone=Asia/Kolkata&language=en",
            headers=_get_headers(),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

    booking = data.get("data", {})
    return {
        "uid": booking.get("uid", ""),
        "start_time": booking.get("start", start_time),
        "status": booking.get("status", "accepted"),
    }


async def cancel_booking(booking_uid: str) -> bool:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CAL_BASE_URL}/bookings/{booking_uid}/cancel",
            headers=_get_headers(),
            json={"cancellationReason": "Cancelled by user via VoiceDesk"},
            timeout=10,
        )
        return resp.status_code in (200, 201, 204)


async def reschedule_booking(booking_uid: str, new_start_time: str) -> dict | None:
    payload = {"start": new_start_time}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CAL_BASE_URL}/bookings/{booking_uid}/reschedule",
            headers=_get_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            return None
        data = resp.json()
        booking = data.get("data", {})
        return {
            "uid": booking.get("uid", booking_uid),
            "start_time": booking.get("start", new_start_time),
        }
