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
BIRTHDAY_DISCOUNT_PERCENT = 50
BIRTHDAY_REWARD_VALID_DAYS = 7


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
        _add_column_if_missing(conn, "orders", "order_number", "INTEGER")
        _add_column_if_missing(conn, "orders", "prep_status", "TEXT DEFAULT 'new'")
        _add_column_if_missing(conn, "orders", "claimed_by_name", "TEXT")
        _add_column_if_missing(conn, "users", "username", "TEXT")
        _add_column_if_missing(conn, "users", "birthday", "TEXT")  # stored as MM-DD
        _add_column_if_missing(conn, "users", "bundle_credits", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "orders", "rating", "INTEGER")
        _add_column_if_missing(conn, "orders", "pickup_time", "TEXT")
        _add_column_if_missing(conn, "orders", "delivery_address", "TEXT")
        _add_column_if_missing(conn, "orders", "used_bundle_credit", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "users", "full_name", "TEXT")
        _add_column_if_missing(conn, "users", "home_branch", "TEXT")
        _add_column_if_missing(conn, "users", "home_lat", "REAL")
        _add_column_if_missing(conn, "users", "home_lng", "REAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS referrals (
            referred_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            rewarded INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS birthday_rewards (
            reward_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            birthday_year INTEGER NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            order_id TEXT,
            status TEXT DEFAULT 'active',
            UNIQUE(user_id, birthday_year)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS carts (
            user_id INTEGER PRIMARY KEY,
            items_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        _add_column_if_missing(conn, "orders", "subtotal", "INTEGER")
        _add_column_if_missing(conn, "orders", "discount_amount", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "orders", "birthday_reward_id", "INTEGER")
        _add_column_if_missing(conn, "orders", "promo_code", "TEXT")
    ensure_management_tables()


# ---- language ----

def save_user_language(user_id: int, lang: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (user_id, lang) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET lang = ?",
            (user_id, lang, lang),
        )


def save_username(user_id: int, username: str):
    """username without the @ — call this whenever we see the user, so staff
    can later look them up by @handle instead of needing their numeric ID."""
    if not username:
        return
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET username = ?",
            (user_id, username, username),
        )


def get_user_id_by_username(username: str) -> int | None:
    username = username.lstrip("@")
    with get_db() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    return row[0] if row else None


def get_username(user_id: int) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else None


def get_user_language(user_id: int) -> str:
    with get_db() as conn:
        row = conn.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else "en"


def get_all_user_ids() -> list[int]:
    with get_db() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
    return [r[0] for r in rows]


# ---- onboarding profile (name, saved phone, home branch) ----

def save_full_name(user_id: int, full_name: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (user_id, full_name) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET full_name = ?",
            (user_id, full_name, full_name),
        )


def get_full_name(user_id: int) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else None


def save_phone(user_id: int, phone: str):
    """Remembers the customer's phone number so checkout doesn't need to ask again."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (user_id, phone) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET phone = ?",
            (user_id, phone, phone),
        )


def get_phone(user_id: int) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT phone FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else None


def save_home_branch(user_id: int, branch_name: str, lat: float, lng: float):
    """Remembers the customer's nearest branch so pickup checkout doesn't need to ask
    for location again. Call this again any time a customer shares a fresher location
    (e.g. via the 'change branch' option), so it stays accurate as they move around."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (user_id, home_branch, home_lat, home_lng) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET home_branch = ?, home_lat = ?, home_lng = ?",
            (user_id, branch_name, lat, lng, branch_name, lat, lng),
        )


def get_home_branch(user_id: int) -> dict | None:
    """Return the customer's saved branch only if it still exists and is active.
    This prevents a deleted/deactivated branch from being silently used at checkout."""
    with get_db() as conn:
        row = conn.execute("SELECT home_branch FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not row or not row[0]:
        return None
    ensure_management_tables()
    with get_db() as conn:
        b = conn.execute("SELECT id,name,address,lat,lng,active FROM branches WHERE name=? AND active=1 LIMIT 1", (row[0],)).fetchone()
    if b:
        return {"id":b[0],"name":b[1],"address":b[2],"lat":b[3],"lng":b[4],"active":bool(b[5])}
    return None


def is_onboarded(user_id: int) -> bool:
    """True once the welcome flow (name/location/phone) has been completed."""
    return bool(get_full_name(user_id))


# ---- loyalty (stamp card) ----

def grant_free_coffee(user_id: int):
    """Directly grants a free item without needing 10 stamps — used for
    birthday rewards. Doesn't touch their existing stamp progress."""
    with get_db() as conn:
        existing = conn.execute("SELECT user_id FROM loyalty WHERE user_id = ?", (user_id,)).fetchone()
        if existing:
            conn.execute("UPDATE loyalty SET free_coffee_pending = 1 WHERE user_id = ?", (user_id,))
        else:
            conn.execute(
                "INSERT INTO loyalty (user_id, stamps, free_coffee_pending) VALUES (?, 0, 1)", (user_id,)
            )


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
                  branch_name: str = None, items_summary: str = None, items_json: str = None, notes: str = None,
                  pickup_time: str = None, delivery_address: str = None, subtotal: int = None,
                  discount_amount: int = 0, birthday_reward_id: int = None, promo_code: str = None):
    if subtotal is None:
        subtotal = total + (discount_amount or 0)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO orders (order_id, user_id, total, payment_method, phone, branch_name, items_summary, "
            "items_json, notes, pickup_time, delivery_address, created_at, subtotal, discount_amount, birthday_reward_id, promo_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, user_id, total, payment_method, phone, branch_name, items_summary, items_json, notes,
             pickup_time, delivery_address, now_utc().isoformat(), subtotal, discount_amount, birthday_reward_id, promo_code),
        )


def set_order_gateway_ref(order_id: str, gateway_ref: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET gateway_ref = ? WHERE order_id = ?", (gateway_ref, order_id))


def mark_order_paid(order_id: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET status = 'paid' WHERE order_id = ?", (order_id,))
        reward = conn.execute(
            "SELECT birthday_reward_id FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if reward and reward[0]:
            cur = conn.execute(
                "UPDATE birthday_rewards SET status='used', used_at=?, order_id=? "
                "WHERE reward_id=? AND status='active' AND expires_at >= ?",
                (now_utc().isoformat(), order_id, reward[0], now_utc().isoformat()),
            )
            if cur.rowcount != 1:
                raise ValueError("Birthday reward is no longer valid")
        promo = conn.execute("SELECT promo_code FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if promo and promo[0]:
            conn.execute("UPDATE promotions SET used_count=used_count+1 WHERE code=? AND max_uses>0", (promo[0],))

def cancel_order(order_id: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET status='cancelled', prep_status='cancelled' WHERE order_id=?", (order_id,))

def mark_order_ready_notified(order_id: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET status_notified_ready = 1 WHERE order_id = ?", (order_id,))


def get_order(order_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT order_id, user_id, total, status, payment_method, gateway_ref, phone, branch_name, "
            "items_summary, items_json, notes, status_notified_ready, order_number, prep_status, claimed_by_name, "
            "pickup_time, delivery_address, rating, subtotal, discount_amount, birthday_reward_id, promo_code "
            "FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "order_id": row[0], "user_id": row[1], "total": row[2],
        "status": row[3], "payment_method": row[4], "gateway_ref": row[5],
        "phone": row[6], "branch_name": row[7], "items_summary": row[8],
        "items_json": row[9], "notes": row[10], "status_notified_ready": bool(row[11]),
        "order_number": row[12], "prep_status": row[13], "claimed_by_name": row[14],
        "pickup_time": row[15], "delivery_address": row[16], "rating": row[17],
        "subtotal": row[18], "discount_amount": row[19] or 0, "birthday_reward_id": row[20], "promo_code": row[21],
    }


def get_open_orders() -> list[dict]:
    """Paid orders that aren't marked ready yet — new (unclaimed) and preparing
    (claimed) — oldest first, for the staff /queue view."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT order_id, order_number, prep_status, claimed_by_name, branch_name, "
            "items_summary, pickup_time, created_at "
            "FROM orders WHERE status = 'paid' AND prep_status IN ('new', 'preparing', 'ready') "
            "ORDER BY created_at ASC"
        ).fetchall()
    return [
        {
            "order_id": r[0], "order_number": r[1], "prep_status": r[2],
            "claimed_by_name": r[3], "branch_name": r[4],
            "items_summary": r[5], "pickup_time": r[6], "created_at": r[7],
        }
        for r in rows
    ]


def assign_order_number(order_id: str, today_str: str) -> int:
    """Called once, right after payment succeeds — gives the order a short daily
    ticket number (#1, #2, ...) instead of showing staff the long internal order_id."""
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status = 'paid' AND created_at LIKE ? AND order_number IS NOT NULL",
            (f"{today_str}%",),
        ).fetchone()[0]
        number = count + 1
        conn.execute("UPDATE orders SET order_number = ? WHERE order_id = ?", (number, order_id))
    return number


def claim_order(order_id: str, staff_name: str) -> bool:
    """Returns False if someone already claimed it — prevents two baristas
    both starting the same drink in a busy group chat."""
    with get_db() as conn:
        current = conn.execute("SELECT prep_status FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if not current or current[0] != "new":
            return False
        conn.execute(
            "UPDATE orders SET prep_status = 'preparing', claimed_by_name = ? WHERE order_id = ?",
            (staff_name, order_id),
        )
    return True


def mark_order_prep_ready(order_id: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET prep_status = 'ready' WHERE order_id = ?", (order_id,))

def mark_order_completed(order_id: str):
    with get_db() as conn:
        conn.execute("UPDATE orders SET prep_status='completed' WHERE order_id=?", (order_id,))


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

# ---- birthday club ----

def save_birthday(user_id: int, month_day: str):
    """month_day format: 'MM-DD' — never store the year, that's a date of birth."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (user_id, birthday) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET birthday = ?",
            (user_id, month_day, month_day),
        )


def get_birthdays_today(month_day: str) -> list[int]:
    with get_db() as conn:
        rows = conn.execute("SELECT user_id FROM users WHERE birthday = ?", (month_day,)).fetchall()
    return [r[0] for r in rows]


def get_birthday_discount_percent() -> int:
    try:
        return max(1, min(100, int(get_setting("birthday_discount_percent") or BIRTHDAY_DISCOUNT_PERCENT)))
    except Exception:
        return BIRTHDAY_DISCOUNT_PERCENT

def get_birthday_reward_valid_days() -> int:
    try:
        return max(1, min(30, int(get_setting("birthday_reward_valid_days") or BIRTHDAY_REWARD_VALID_DAYS)))
    except Exception:
        return BIRTHDAY_REWARD_VALID_DAYS

def issue_birthday_reward(user_id: int, year: int | None = None) -> dict:
    """Issue one birthday reward for a calendar year. The reward is valid for the configured number of days."""
    now = now_utc()
    year = year or now.year
    issued_at = now.isoformat()
    expires_at = (now + timedelta(days=get_birthday_reward_valid_days())).isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT reward_id, status, expires_at FROM birthday_rewards WHERE user_id=? AND birthday_year=?",
            (user_id, year),
        ).fetchone()
        if row:
            return {"reward_id": row[0], "status": row[1], "expires_at": row[2], "new": False}
        cur = conn.execute(
            "INSERT INTO birthday_rewards (user_id, birthday_year, issued_at, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, year, issued_at, expires_at),
        )
        return {"reward_id": cur.lastrowid, "status": "active", "expires_at": expires_at, "new": True}


def get_active_birthday_reward(user_id: int) -> dict | None:
    now = now_utc().isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT reward_id, birthday_year, issued_at, expires_at, status FROM birthday_rewards "
            "WHERE user_id=? AND status='active' AND expires_at >= ? ORDER BY reward_id DESC LIMIT 1",
            (user_id, now),
        ).fetchone()
    if not row:
        return None
    return {"reward_id": row[0], "birthday_year": row[1], "issued_at": row[2], "expires_at": row[3], "status": row[4]}


# ---- ratings ----

def save_order_rating(order_id: str, rating: int):
    with get_db() as conn:
        conn.execute("UPDATE orders SET rating = ? WHERE order_id = ?", (rating, order_id))


# ---- referrals ----

def record_referral(referred_id: int, referrer_id: int):
    """Only takes effect the first time — a user can't be re-referred later."""
    if referred_id == referrer_id:
        return
    with get_db() as conn:
        existing = conn.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (referred_id,)).fetchone()
        if existing:
            return
        conn.execute("INSERT INTO referrals (referred_id, referrer_id, rewarded) VALUES (?, ?, 0)", (referred_id, referrer_id))


def get_unrewarded_referral(referred_id: int) -> int | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT referrer_id FROM referrals WHERE referred_id = ? AND rewarded = 0", (referred_id,)
        ).fetchone()
    return row[0] if row else None


def mark_referral_rewarded(referred_id: int):
    with get_db() as conn:
        conn.execute("UPDATE referrals SET rewarded = 1 WHERE referred_id = ?", (referred_id,))


# ---- prepaid bundle credits ----

def get_bundle_credits(user_id: int) -> int:
    with get_db() as conn:
        row = conn.execute("SELECT bundle_credits FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row and row[0] else 0


def add_bundle_credits(user_id: int, amount: int):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (user_id, bundle_credits) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET bundle_credits = COALESCE(bundle_credits, 0) + ?",
            (user_id, amount, amount),
        )


def use_bundle_credits(user_id: int, amount: int) -> bool:
    """Returns False (and changes nothing) if the customer doesn't have enough credits."""
    with get_db() as conn:
        row = conn.execute("SELECT bundle_credits FROM users WHERE user_id = ?", (user_id,)).fetchone()
        current = row[0] if row and row[0] else 0
        if current < amount:
            return False
        conn.execute("UPDATE users SET bundle_credits = bundle_credits - ? WHERE user_id = ?", (amount, user_id))
    return True


# ---- win-back (inactive customers) ----

def get_inactive_customers(days: int) -> list[int]:
    """Customers whose most recent PAID order is older than `days` ago (or who
    have never ordered but did message the bot — excluded, since a win-back
    message to someone who never ordered isn't a 'win back')."""
    cutoff = (now_utc() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT user_id FROM orders WHERE status = 'paid'
               GROUP BY user_id HAVING MAX(created_at) < ?""",
            (cutoff,),
        ).fetchall()
    return [r[0] for r in rows]


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

# ---- managed branches / promotions ----
def ensure_management_tables():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, address TEXT NOT NULL,
            lat REAL NOT NULL, lng REAL NOT NULL, active INTEGER DEFAULT 1,
            phone TEXT, hours TEXT DEFAULT '08:00-23:00', pickup_enabled INTEGER DEFAULT 1,
            delivery_enabled INTEGER DEFAULT 0)""")
        for col, typ in (("phone","TEXT"),("hours","TEXT DEFAULT '08:00-23:00'"),("pickup_enabled","INTEGER DEFAULT 1"),("delivery_enabled","INTEGER DEFAULT 0")):
            _add_column_if_missing(conn, "branches", col, typ)
        conn.execute("""CREATE TABLE IF NOT EXISTS promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, code TEXT UNIQUE NOT NULL,
            kind TEXT NOT NULL, value INTEGER NOT NULL, active INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, starts_at TEXT, ends_at TEXT, min_subtotal INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT 0, used_count INTEGER DEFAULT 0)""")
        for col, typ in (("starts_at","TEXT"),("ends_at","TEXT"),("min_subtotal","INTEGER DEFAULT 0"),("max_uses","INTEGER DEFAULT 0"),("used_count","INTEGER DEFAULT 0")):
            _add_column_if_missing(conn, "promotions", col, typ)
        if conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0] == 0:
            try:
                import branches as legacy
                for b in legacy.BRANCHES:
                    conn.execute("INSERT INTO branches(name,address,lat,lng,active) VALUES(?,?,?,?,1)",(b['name'],b['address'],b['lat'],b['lng']))
            except Exception: pass

def list_branches():
    ensure_management_tables()
    with get_db() as conn:
        rows=conn.execute("SELECT id,name,address,lat,lng,active,phone,hours,pickup_enabled,delivery_enabled FROM branches ORDER BY id").fetchall()
    return [dict(id=r[0],name=r[1],address=r[2],lat=r[3],lng=r[4],active=bool(r[5]),phone=r[6] or '',hours=r[7] or '08:00-23:00',pickup_enabled=bool(r[8]),delivery_enabled=bool(r[9])) for r in rows]
def get_branch(i): return next((b for b in list_branches() if b['id']==i),None)
def add_branch(name,address,lat,lng,phone='',hours='08:00-23:00',pickup_enabled=1,delivery_enabled=0):
    ensure_management_tables()
    with get_db() as c:
        cur=c.execute("INSERT INTO branches(name,address,lat,lng,active,phone,hours,pickup_enabled,delivery_enabled) VALUES(?,?,?,?,1,?,?,?,?)",(name,address,lat,lng,phone,hours,int(pickup_enabled),int(delivery_enabled)))
        return cur.lastrowid
def toggle_branch(i):
    ensure_management_tables()
    with get_db() as c: c.execute("UPDATE branches SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(i,))
def delete_branch(i):
    ensure_management_tables()
    with get_db() as c:
        old=c.execute("SELECT name FROM branches WHERE id=?",(i,)).fetchone(); c.execute("DELETE FROM branches WHERE id=?",(i,))
        if old: c.execute("UPDATE users SET home_branch=NULL, home_lat=NULL, home_lng=NULL WHERE home_branch=?",(old[0],))
def update_branch(i,name,address,lat,lng,phone='',hours='08:00-23:00',pickup_enabled=1,delivery_enabled=0):
    ensure_management_tables()
    with get_db() as c:
        old=c.execute("SELECT name FROM branches WHERE id=?",(i,)).fetchone()
        c.execute("UPDATE branches SET name=?,address=?,lat=?,lng=?,phone=?,hours=?,pickup_enabled=?,delivery_enabled=? WHERE id=?",(name,address,lat,lng,phone,hours,int(pickup_enabled),int(delivery_enabled),i))
        if old and old[0] != name: c.execute("UPDATE users SET home_branch=? WHERE home_branch=?",(name,old[0]))
def list_promotions():
    ensure_management_tables()
    with get_db() as c: rows=c.execute("SELECT id,name,code,kind,value,active,created_at,starts_at,ends_at,min_subtotal,max_uses,used_count FROM promotions ORDER BY id DESC").fetchall()
    return [dict(id=r[0],name=r[1],code=r[2],kind=r[3],value=r[4],active=bool(r[5]),created_at=r[6],starts_at=r[7],ends_at=r[8],min_subtotal=r[9] or 0,max_uses=r[10] or 0,used_count=r[11] or 0) for r in rows]
def get_promotion(i): return next((p for p in list_promotions() if p['id']==i),None)
def add_promotion(name,code,kind,value,starts_at=None,ends_at=None,min_subtotal=0,max_uses=0):
    ensure_management_tables()
    with get_db() as c: cur=c.execute("INSERT INTO promotions(name,code,kind,value,active,created_at,starts_at,ends_at,min_subtotal,max_uses,used_count) VALUES(?,?,?,?,0,?,?,?,?,?,0)",(name,code,kind,value,now_utc().isoformat(),starts_at,ends_at,int(min_subtotal),int(max_uses))); return cur.lastrowid
def toggle_promotion(i):
    ensure_management_tables()
    with get_db() as c: c.execute("UPDATE promotions SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(i,))
def delete_promotion(i):
    ensure_management_tables()
    with get_db() as c: c.execute("DELETE FROM promotions WHERE id=?",(i,))
def update_promotion(i,name,code,kind,value,starts_at=None,ends_at=None,min_subtotal=0,max_uses=0):
    ensure_management_tables()
    with get_db() as c: c.execute("UPDATE promotions SET name=?,code=?,kind=?,value=?,starts_at=?,ends_at=?,min_subtotal=?,max_uses=? WHERE id=?",(name,code,kind,value,starts_at,ends_at,int(min_subtotal),int(max_uses),i))

def save_cart(user_id:int, items:list[dict]):
    import json
    with get_db() as c:
        if items: c.execute("INSERT INTO carts(user_id,items_json,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET items_json=?,updated_at=?",(user_id,json.dumps(items,ensure_ascii=False),now_utc().isoformat(),json.dumps(items,ensure_ascii=False),now_utc().isoformat()))
        else: c.execute("DELETE FROM carts WHERE user_id=?",(user_id,))
def load_cart(user_id:int)->list[dict]:
    import json
    with get_db() as c: row=c.execute("SELECT items_json FROM carts WHERE user_id=?",(user_id,)).fetchone()
    if not row: return []
    try: return json.loads(row[0])
    except Exception: return []
def clear_cart(user_id:int):
    with get_db() as c: c.execute("DELETE FROM carts WHERE user_id=?",(user_id,))

