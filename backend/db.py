import aiosqlite
import os
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_PATH = os.getenv("DB_PATH", "voicedesk.db")


def is_postgres() -> bool:
    return bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))


async def init_db():
    if is_postgres():
        import psycopg
        conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
        async with conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id SERIAL PRIMARY KEY,
                    cal_booking_uid TEXT,
                    caller_name TEXT NOT NULL,
                    reason TEXT,
                    date_time TEXT NOT NULL,
                    contact_number TEXT,
                    status TEXT DEFAULT 'confirmed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        return

    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cal_booking_uid TEXT,
                caller_name TEXT NOT NULL,
                reason TEXT,
                date_time TEXT NOT NULL,
                contact_number TEXT,
                status TEXT DEFAULT 'confirmed',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.commit()


async def save_booking(
    caller_name: str,
    reason: str,
    date_time: str,
    contact_number: str,
    cal_booking_uid: str | None = None,
) -> int:
    if is_postgres():
        import psycopg
        from psycopg.rows import dict_row
        conn = await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row)
        async with conn:
            cur = await conn.execute(
                """INSERT INTO appointments
                   (cal_booking_uid, caller_name, reason, date_time, contact_number)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (cal_booking_uid, caller_name, reason, date_time, contact_number),
            )
            row = await cur.fetchone()
            return row["id"]

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            """INSERT INTO appointments
               (cal_booking_uid, caller_name, reason, date_time, contact_number)
               VALUES (?, ?, ?, ?, ?)""",
            (cal_booking_uid, caller_name, reason, date_time, contact_number),
        )
        await conn.commit()
        return cursor.lastrowid


async def check_slot_available(date_time: str) -> bool:
    if is_postgres():
        import psycopg
        conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
        async with conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE date_time = %s AND status = 'confirmed'",
                (date_time,),
            )
            row = await cur.fetchone()
            return row[0] == 0

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            """SELECT COUNT(*) FROM appointments
               WHERE date_time = ? AND status = 'confirmed'""",
            (date_time,),
        )
        row = await cursor.fetchone()
        return row[0] == 0


async def get_available_slots(date: str) -> list[str]:
    """Return available hourly slots for a given date (YYYY-MM-DD)."""
    all_slots = [f"{date} {h:02d}:00" for h in range(9, 18)]

    if is_postgres():
        import psycopg
        conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
        async with conn:
            cur = await conn.execute(
                "SELECT date_time FROM appointments WHERE date_time LIKE %s AND status = 'confirmed'",
                (f"{date}%",),
            )
            booked = {row[0] for row in await cur.fetchall()}
        return [s for s in all_slots if s not in booked]

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            """SELECT date_time FROM appointments
               WHERE date_time LIKE ? AND status = 'confirmed'""",
            (f"{date}%",),
        )
        booked = {row[0] for row in await cursor.fetchall()}

    return [s for s in all_slots if s not in booked]


async def get_booking(booking_id: int) -> dict | None:
    if is_postgres():
        import psycopg
        from psycopg.rows import dict_row
        conn = await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row)
        async with conn:
            cur = await conn.execute(
                "SELECT * FROM appointments WHERE id = %s", (booking_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM appointments WHERE id = ?", (booking_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def cancel_booking(booking_id: int) -> bool:
    if is_postgres():
        import psycopg
        conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
        async with conn:
            cur = await conn.execute(
                "UPDATE appointments SET status = 'cancelled' WHERE id = %s AND status = 'confirmed'",
                (booking_id,),
            )
            return cur.rowcount > 0

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = ? AND status = 'confirmed'",
            (booking_id,),
        )
        await conn.commit()
        return cursor.rowcount > 0


async def reschedule_booking(booking_id: int, new_date_time: str) -> bool:
    if not await check_slot_available(new_date_time):
        return False

    if is_postgres():
        import psycopg
        conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
        async with conn:
            cur = await conn.execute(
                "UPDATE appointments SET date_time = %s WHERE id = %s AND status = 'confirmed'",
                (new_date_time, booking_id),
            )
            return cur.rowcount > 0

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "UPDATE appointments SET date_time = ? WHERE id = ? AND status = 'confirmed'",
            (new_date_time, booking_id),
        )
        await conn.commit()
        return cursor.rowcount > 0


async def get_all_bookings() -> list[dict]:
    if is_postgres():
        import psycopg
        from psycopg.rows import dict_row
        conn = await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=dict_row)
        async with conn:
            cur = await conn.execute(
                "SELECT * FROM appointments ORDER BY created_at DESC"
            )
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM appointments ORDER BY created_at DESC"
        )
        return [dict(row) for row in await cursor.fetchall()]
