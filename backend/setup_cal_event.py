import asyncio
import httpx
import os
import re
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)

CAL_BASE_URL = "https://api.cal.com/v2"

async def create_new_event_type(title: str = "VoiceDesk AI Meeting", slug: str = "voicedesk-ai-meeting", duration: int = 15):
    api_key = os.getenv("CAL_API_KEY")
    if not api_key:
        print("CAL_API_KEY not found in .env")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "cal-api-version": "2024-06-14",
        "Content-Type": "application/json"
    }
    
    payload = {
        "title": title,
        "slug": slug,
        "lengthInMinutes": duration,
        "description": "Automatically created meeting template for VoiceDesk AI Receptionist"
    }

    print(f"Creating new Cal.com Event Type '{title}' ({duration} mins)...")
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{CAL_BASE_URL}/event-types", headers=headers, json=payload)
        
        if resp.status_code == 400 and "slug" in resp.text.lower():
            fallback_slug = f"{slug}-{duration}m-ai"
            payload["slug"] = fallback_slug
            resp = await client.post(f"{CAL_BASE_URL}/event-types", headers=headers, json=payload)

        if resp.status_code == 201:
            data = resp.json()
            event_id = data.get("data", {}).get("id")
            booking_url = data.get("data", {}).get("bookingUrl")
            print(f"Successfully created Event Type ID: {event_id}")
            print(f"Booking URL: {booking_url}")
            return event_id
        else:
            print(f"Failed to create Event Type. Status: {resp.status_code}")
            print("Response:", resp.text)
            return None

def update_env_var(key: str, val: str | int):
    os.environ[key] = str(val)
    if not os.path.exists(env_path):
        return
    with open(env_path, "r") as f:
        content = f.read()
    new_line = f"{key}={val}"
    if f"{key}=" in content:
        content = re.sub(rf"{key}=.*", new_line, content)
    else:
        content += f"\n{new_line}"
    with open(env_path, "w") as f:
        f.write(content.strip() + "\n")
    print(f"Updated {key}={val} in .env")


async def setup_all_event_types():
    print("Auto-generating 15m, 30m, and 60m Event Types on Cal.com...")
    id_15 = await create_new_event_type("Quick Discovery Call", "quick-discovery", 15)
    id_30 = await create_new_event_type("Standard Consultation", "standard-consultation", 30)
    id_60 = await create_new_event_type("Deep Dive Strategy Session", "deep-dive-session", 60)

    if id_30:
        update_env_var("CAL_EVENT_TYPE_ID", id_30)
    if id_15:
        update_env_var("CAL_EVENT_ID_15M", id_15)
    if id_30:
        update_env_var("CAL_EVENT_ID_30M", id_30)
    if id_60:
        update_env_var("CAL_EVENT_ID_60M", id_60)
    print("\n✨ All Event Types created and synced to .env successfully!")


if __name__ == "__main__":
    asyncio.run(setup_all_event_types())
