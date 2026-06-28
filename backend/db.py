import os
from datetime import datetime
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def get_db_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL environment variable is not set")
    return url


import re
from datetime import timedelta

def _parse_dur_mins(duration: int | str) -> int:
    if isinstance(duration, int):
        return duration
    match = re.search(r"(\d+)", str(duration))
    if match:
        val = int(match.group(1))
        return val * 60 if "h" in str(duration).lower() else val
    return 30


async def init_db():
    conn = await psycopg.AsyncConnection.connect(get_db_url())
    async with conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id SERIAL PRIMARY KEY,
                cal_booking_uid TEXT,
                caller_name TEXT NOT NULL,
                reason TEXT,
                date_time TEXT NOT NULL,
                contact_number TEXT,
                email TEXT,
                status TEXT DEFAULT 'confirmed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS email TEXT;")
        await conn.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS duration INT DEFAULT 30;")


async def save_booking(
    caller_name: str,
    reason: str,
    date_time: str,
    contact_number: str,
    cal_booking_uid: str | None = None,
    email: str = "",
    duration: int | str = 30,
) -> int:
    dur_mins = _parse_dur_mins(duration)
    conn = await psycopg.AsyncConnection.connect(get_db_url(), row_factory=dict_row)
    async with conn:
        cur = await conn.execute(
            """INSERT INTO appointments
               (cal_booking_uid, caller_name, reason, date_time, contact_number, email, duration)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (cal_booking_uid, caller_name, reason, date_time, contact_number, email, dur_mins),
        )
        row = await cur.fetchone()
        return row["id"]


async def check_slot_available(date_time: str, exclude_booking_id: int | None = None, duration: int | str = 30) -> bool:
    new_dur = _parse_dur_mins(duration)
    try:
        new_start = datetime.strptime(date_time, "%Y-%m-%d %H:%M")
    except Exception:
        return False
    new_end = new_start + timedelta(minutes=new_dur)
    date_prefix = date_time[:10]

    conn = await psycopg.AsyncConnection.connect(get_db_url())
    async with conn:
        if exclude_booking_id is not None:
            cur = await conn.execute(
                "SELECT date_time, COALESCE(duration, 30) FROM appointments WHERE date_time LIKE %s AND status = 'confirmed' AND id != %s",
                (f"{date_prefix}%", exclude_booking_id),
            )
        else:
            cur = await conn.execute(
                "SELECT date_time, COALESCE(duration, 30) FROM appointments WHERE date_time LIKE %s AND status = 'confirmed'",
                (f"{date_prefix}%",),
            )
        rows = await cur.fetchall()

    for dt_str, ex_dur in rows:
        try:
            ex_start = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            ex_end = ex_start + timedelta(minutes=int(ex_dur))
            # Check overlap
            if new_start < ex_end and ex_start < new_end:
                return False
        except Exception:
            continue
    return True


async def get_available_slots(date: str, duration: int | str = 30) -> list[str]:
    """Return available 30-minute intervals that have enough free room for the requested duration."""
    dur_mins = _parse_dur_mins(duration)
    all_slots = []
    # Generate slots every 30 mins from 9:00 to 17:00
    for h in range(9, 17):
        all_slots.append(f"{date} {h:02d}:00")
        all_slots.append(f"{date} {h:02d}:30")

    available = []
    for s in all_slots:
        if await check_slot_available(s, duration=dur_mins):
            available.append(s)
    return available


async def get_booking(booking_id: int) -> dict | None:
    conn = await psycopg.AsyncConnection.connect(get_db_url(), row_factory=dict_row)
    async with conn:
        cur = await conn.execute(
            "SELECT * FROM appointments WHERE id = %s", (booking_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def cancel_booking(booking_id: int) -> bool:
    conn = await psycopg.AsyncConnection.connect(get_db_url())
    async with conn:
        cur = await conn.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = %s AND status = 'confirmed'",
            (booking_id,),
        )
        return cur.rowcount > 0


async def reschedule_booking(booking_id: int, new_date_time: str) -> bool:
    if not await check_slot_available(new_date_time, exclude_booking_id=booking_id):
        return False

    conn = await psycopg.AsyncConnection.connect(get_db_url())
    async with conn:
        cur = await conn.execute(
            "UPDATE appointments SET date_time = %s WHERE id = %s AND status = 'confirmed'",
            (new_date_time, booking_id),
        )
        return cur.rowcount > 0


async def get_all_bookings() -> list[dict]:
    conn = await psycopg.AsyncConnection.connect(get_db_url(), row_factory=dict_row)
    async with conn:
        cur = await conn.execute(
            "SELECT * FROM appointments ORDER BY created_at DESC"
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def lookup_booking(query: str) -> list[dict]:
    clean_q = query.strip()
    q_like = f"%{clean_q.lower()}%"
    conn = await psycopg.AsyncConnection.connect(get_db_url(), row_factory=dict_row)
    async with conn:
        if clean_q.isdigit():
            cur = await conn.execute(
                "SELECT * FROM appointments WHERE id = %s OR contact_number LIKE %s ORDER BY id DESC LIMIT 5",
                (int(clean_q), q_like),
            )
        else:
            cur = await conn.execute(
                "SELECT * FROM appointments WHERE LOWER(caller_name) LIKE %s OR contact_number LIKE %s OR LOWER(email) LIKE %s ORDER BY id DESC LIMIT 5",
                (q_like, q_like, q_like),
            )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]
