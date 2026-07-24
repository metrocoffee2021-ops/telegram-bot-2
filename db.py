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


def _add_column_if_missing(conn, table: str, column: str, coltype: str):
    """Safely add a column to an existing table — needed because CREATE TABLE
    IF NOT EXISTS does nothing to a table that already exists (e.g. on a
    database that's already live on Railway from before this update)."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise


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
            phone TEXT,
            branch_name TEXT,
            items_summary TEXT,
            created_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        # Columns added after the first release — safe to run every startup.
        _add_column_if_missing(conn, "orders", "notes", "TEXT")
        _add_column_if_missing(conn, "orders", "items_json", "TEXT")
        _add_column_if_missing(conn, "orders", "status_notified_ready", "INTEGER DEFAULT 0")


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

def create_order(order_id: str, user_id: int, total: int, payment_method: str, phone: str = None,
                  branch_name: str = None, items_summary: str = None, items_json: str = None, notes: str = None):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO orders (order_id, user_id, total, payment_method, phone, branch_name, items_summary, items_json, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, user_id, total, payment_method, phone, branch_name, items_summary, items_json, notes, now_utc().isoformat()),
        )


def set_order_gateway_ref(order_id: str, gateway_ref: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET gateway_ref = ? WHERE order_id = ?", (gateway_ref, order_id))


def mark_order_paid(order_id: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET status = 'paid' WHERE order_id = ?", (order_id,))


def mark_order_ready_notified(order_id: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET status_notified_ready = 1 WHERE order_id = ?", (order_id,))


def get_order(order_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT order_id, user_id, total, status, payment_method, gateway_ref, phone, branch_name, "
            "items_summary, items_json, notes, status_notified_ready FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "order_id": row[0], "user_id": row[1], "total": row[2],
        "status": row[3], "payment_method": row[4], "gateway_ref": row[5],
        "phone": row[6], "branch_name": row[7], "items_summary": row[8],
        "items_json": row[9], "notes": row[10], "status_notified_ready": bool(row[11]),
    }


def get_recent_orders(user_id: int, limit: int = 5) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT order_id, total, status, branch_name, items_summary, items_json, created_at FROM orders "
            "WHERE user_id = ? AND status = 'paid' ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [
        {"order_id": r[0], "total": r[1], "status": r[2], "branch_name": r[3],
         "items_summary": r[4], "items_json": r[5], "created_at": r[6]}
        for r in rows
    ]


def get_orders_on_date(date_str: str) -> list[dict]:
    """date_str like '2026-07-24' (UTC)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT total, items_json FROM orders WHERE status = 'paid' AND created_at LIKE ?",
            (f"{date_str}%",),
        ).fetchall()
    return [{"total": r[0], "items_json": r[1]} for r in rows]


def get_orders_since(iso_datetime: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT total, items_json FROM orders WHERE status = 'paid' AND created_at >= ?",
            (iso_datetime,),
        ).fetchall()
    return [{"total": r[0], "items_json": r[1]} for r in rows]


# ---- settings (simple key/value store — e.g. whether ordering is paused) ----

def get_setting(key: str, default: str = None) -> str:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value),
        )
