import os
import httpx
from datetime import datetime

CAL_API_KEY = os.getenv("CAL_API_KEY", "")
CAL_EVENT_TYPE_ID = os.getenv("CAL_EVENT_TYPE_ID", "")
CAL_BASE_URL = "https://api.cal.com/v2"

HEADERS = {
    "Authorization": f"Bearer {CAL_API_KEY}",
    "cal-api-version": "2024-08-13",
    "Content-Type": "application/json",
}


def is_configured() -> bool:
    return bool(CAL_API_KEY and CAL_EVENT_TYPE_ID)


async def get_available_slots(date: str) -> list[str]:
    """Fetch open slots from Cal.com for a given date (YYYY-MM-DD)."""
    params = {
        "startTime": f"{date}T00:00:00Z",
        "endTime": f"{date}T23:59:59Z",
        "eventTypeId": CAL_EVENT_TYPE_ID,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{CAL_BASE_URL}/slots/available",
            headers=HEADERS,
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
        "eventTypeId": int(CAL_EVENT_TYPE_ID),
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
            headers=HEADERS,
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
            headers=HEADERS,
            timeout=10,
        )
        return resp.status_code in (200, 204)


async def reschedule_booking(booking_uid: str, new_start_time: str) -> dict | None:
    payload = {"start": new_start_time}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{CAL_BASE_URL}/bookings/{booking_uid}/reschedule",
            headers=HEADERS,
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
