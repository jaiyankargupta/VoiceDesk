import os
import httpx
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

CAL_BASE_URL = "https://api.cal.com/v2"


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('CAL_API_KEY', '')}",
        "cal-api-version": "2024-06-14",
        "Content-Type": "application/json",
    }


def _get_event_type_id() -> str:
    return os.getenv("CAL_EVENT_TYPE_ID", "")


def is_configured() -> bool:
    return bool(os.getenv("CAL_API_KEY", "") and _get_event_type_id())


async def get_available_slots(date: str) -> list[str]:
    """Fetch open slots from Cal.com for a given date (YYYY-MM-DD)."""
    params = {
        "startTime": f"{date}T00:00:00Z",
        "endTime": f"{date}T23:59:59Z",
        "eventTypeId": _get_event_type_id(),
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
    for day_slots in slots.values():
        for slot in day_slots:
            available.append(slot["time"])
    return available


async def create_booking(
    name: str,
    email: str,
    start_time: str,
    reason: str = "",
    phone: str = "",
) -> dict:
    """Create a booking on Cal.com and return the booking details."""
    payload = {
        "eventTypeId": int(_get_event_type_id()),
        "start": start_time,
        "attendee": {
            "name": name,
            "email": email or f"{name.lower().replace(' ', '.')}@placeholder.com",
            "timeZone": "Asia/Kolkata",
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
