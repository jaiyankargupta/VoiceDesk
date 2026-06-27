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
        print("❌ CAL_API_KEY not found in .env")
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

    print(f"🔄 Creating new Cal.com Event Type '{title}' ({duration} mins)...")
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{CAL_BASE_URL}/event-types", headers=headers, json=payload)
        
        if resp.status_code == 201:
            data = resp.json()
            event_id = data.get("data", {}).get("id")
            booking_url = data.get("data", {}).get("bookingUrl")
            print(f"✅ Successfully created Event Type ID: {event_id}")
            print(f"🔗 Booking URL: {booking_url}")
            update_env_file(event_id)
            return event_id
        else:
            print(f"❌ Failed to create Event Type. Status: {resp.status_code}")
            print("Response:", resp.text)
            return None

def update_env_file(new_id: int):
    if not os.path.exists(env_path):
        print(f"❌ .env file not found at {env_path}")
        return

    with open(env_path, "r") as f:
        content = f.read()

    new_line = f"CAL_EVENT_TYPE_ID={new_id}"
    if "CAL_EVENT_TYPE_ID=" in content:
        content = re.sub(r"CAL_EVENT_TYPE_ID=.*", new_line, content)
    else:
        content += f"\n{new_line}\n"

    with open(env_path, "w") as f:
        f.write(content)
    print(f"💾 Automatically updated backend/.env with CAL_EVENT_TYPE_ID={new_id}")

if __name__ == "__main__":
    asyncio.run(create_new_event_type())
