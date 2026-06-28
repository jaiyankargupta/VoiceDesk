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
    dur_mins = _parse_duration(duration)
    clean_title = title.strip() or f"VoiceDesk Consultation ({dur_mins}m)"
    cache_key = (clean_title.lower(), dur_mins)

    if cache_key in _DYNAMIC_EVENTS_CACHE:
        return _DYNAMIC_EVENTS_CACHE[cache_key]

    slug_base = re.sub(r"[^a-z0-9]+", "-", clean_title.lower()).strip("-") or "meeting"
    slug = f"{slug_base}-{dur_mins}m"

    headers = {
        "Authorization": f"Bearer {os.getenv('CAL_API_KEY', '')}",
        "cal-api-version": "2024-06-14",
        "Content-Type": "application/json",
    }
    payload = {
        "title": clean_title,
        "slug": slug,
        "lengthInMinutes": dur_mins,
        "description": f"On-demand scheduled event for {clean_title}",
    }

    fallback_id = os.getenv("CAL_EVENT_TYPE_ID") or "6140294"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{CAL_BASE_URL}/event-types", headers=headers, json=payload, timeout=10)
            if resp.status_code == 400 and "slug" in resp.text.lower():
                payload["slug"] = f"{slug}-{int(time.time())}"
                resp = await client.post(f"{CAL_BASE_URL}/event-types", headers=headers, json=payload, timeout=10)

            if resp.status_code == 201:
                event_id = int(resp.json().get("data", {}).get("id"))
                _DYNAMIC_EVENTS_CACHE[cache_key] = event_id
                os.environ["CAL_EVENT_TYPE_ID"] = str(event_id)
                return event_id
    except Exception as e:
        print(f"Dynamic event creation error: {e}")

    return int(fallback_id) if str(fallback_id).isdigit() else 6140294


def is_configured() -> bool:
    return bool(os.getenv("CAL_API_KEY"))


async def get_available_slots(date: str, duration: str = "") -> list[str]:
    """Fetch open slots from Cal.com for a given date (YYYY-MM-DD)."""
    event_type_id = await _get_or_create_event_type("VoiceDesk Meeting", duration or 30)
    params = {
        "startTime": f"{date}T00:00:00Z",
        "endTime": f"{date}T23:59:59Z",
        "eventTypeId": str(event_type_id),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{CAL_BASE_URL}/slots/available",
            headers=_get_headers(),
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
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

    return available[:10]


async def create_booking(
    name: str,
    email: str,
    start_time: str,
    reason: str = "",
    phone: str = "",
    duration: str = "",
) -> dict:
    """Create a booking on Cal.com and return the booking details."""
    event_type_id = await _get_or_create_event_type(reason or f"Meeting with {name}", duration or 30)
    payload = {
        "eventTypeId": event_type_id,
        "start": start_time,
        "attendee": {
            "name": name,
            "email": email or f"{name.lower().replace(' ', '.')}@placeholder.com",
            "timeZone": "Asia/Kolkata",
            "language": "en",
        },
        "metadata": {"reason": reason, "phone": phone},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CAL_BASE_URL}/bookings",
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
        resp = await client.delete(
            f"{CAL_BASE_URL}/bookings/{booking_uid}/cancel",
            headers=_get_headers(),
            timeout=10,
        )
        return resp.status_code in (200, 204)


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
