# db.py
# All the bot's saved data (which language each customer picked, and their
# loyalty stamps) lives in one file: metropia.db — created automatically the
# first time the bot runs. Back this file up along with the rest of the bot.

import sqlite3
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

DB_PATH = "metropia.db"

STAMPS_FOR_FREE_ITEM = 10   # buy 9, the 10th is free
CARD_VALID_DAYS = 30        # matches the offline card: valid one month after the first stamp


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'en',
            phone TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS loyalty (
            user_id INTEGER PRIMARY KEY,
            stamps INTEGER DEFAULT 0,
            first_stamp_at TEXT,
            free_coffee_pending INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER,
            total INTEGER,
            status TEXT DEFAULT 'pending',
            payment_method TEXT,
            gateway_ref TEXT,
            created_at TEXT
        )""")


# ---- language ----

def save_user_language(user_id: int, lang: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (user_id, lang) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET lang = ?",
            (user_id, lang, lang),
        )


def get_user_language(user_id: int) -> str:
    with get_db() as conn:
        row = conn.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else "en"


def get_all_user_ids() -> list[int]:
    with get_db() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
    return [r[0] for r in rows]


# ---- loyalty (stamp card) ----

def add_stamp(user_id: int) -> dict:
    """Call this once per confirmed payment — never before. Returns whether this purchase
    earned a free item, and whether a previously-expired card was just restarted."""
    now = now_utc()
    expired = False
    earned_free_item = False

    with get_db() as conn:
        row = conn.execute(
            "SELECT stamps, first_stamp_at, free_coffee_pending FROM loyalty WHERE user_id = ?", (user_id,)
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO loyalty (user_id, stamps, first_stamp_at) VALUES (?, 1, ?)",
                (user_id, now.isoformat()),
            )
            stamps = 1
        else:
            stamps, first_stamp_at, pending = row
            if pending:
                # staff already handed over a free coffee at this visit — start fresh
                stamps = 1
                conn.execute(
                    "UPDATE loyalty SET stamps = 1, first_stamp_at = ?, free_coffee_pending = 0 WHERE user_id = ?",
                    (now.isoformat(), user_id),
                )
            elif first_stamp_at and now - datetime.fromisoformat(first_stamp_at) > timedelta(days=CARD_VALID_DAYS):
                stamps = 1
                expired = True
                conn.execute(
                    "UPDATE loyalty SET stamps = 1, first_stamp_at = ? WHERE user_id = ?",
                    (now.isoformat(), user_id),
                )
            else:
                stamps += 1
                conn.execute("UPDATE loyalty SET stamps = ? WHERE user_id = ?", (stamps, user_id))

        if stamps >= STAMPS_FOR_FREE_ITEM:
            conn.execute(
                "UPDATE loyalty SET stamps = ?, free_coffee_pending = 1, first_stamp_at = NULL WHERE user_id = ?",
                (STAMPS_FOR_FREE_ITEM, user_id),
            )
            earned_free_item = True

    return {
        "stamps": STAMPS_FOR_FREE_ITEM if earned_free_item else stamps,
        "earned_free_item": earned_free_item,
        "card_expired": expired,
    }


def get_loyalty_status(user_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT stamps, first_stamp_at, free_coffee_pending FROM loyalty WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return None
    stamps, first_stamp_at, pending = row
    return {"stamps": stamps, "first_stamp_at": first_stamp_at, "free_coffee_pending": bool(pending)}


# ---- orders (used to match a payment confirmation back to the right order) ----

def create_order(order_id: str, user_id: int, total: int, payment_method: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO orders (order_id, user_id, total, payment_method, created_at) VALUES (?, ?, ?, ?, ?)",
            (order_id, user_id, total, payment_method, now_utc().isoformat()),
        )


def set_order_gateway_ref(order_id: str, gateway_ref: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET gateway_ref = ? WHERE order_id = ?", (gateway_ref, order_id))


def mark_order_paid(order_id: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET status = 'paid' WHERE order_id = ?", (order_id,))


def get_order(order_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT order_id, user_id, total, status, payment_method, gateway_ref FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "order_id": row[0], "user_id": row[1], "total": row[2],
        "status": row[3], "payment_method": row[4], "gateway_ref": row[5],

        


    }
