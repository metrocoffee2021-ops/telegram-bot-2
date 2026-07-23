# menu_store.py
# The real, editable menu — stored in the database, not in a code file.
# categories -> items -> variants (each variant is one hot/cold + size + price combo).
# On first run, seed_if_empty() copies your starting menu from menu_data.py in.
# After that, every read and every change goes through the functions below —
# used both by customers browsing the menu and by /admin managing it.

from contextlib import contextmanager
import sqlite3

import db
from menu_data import SEED_CATEGORIES, SEED_ITEMS


@contextmanager
def get_db():
    conn = sqlite3.connect(db.DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_menu_tables():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name_uz TEXT NOT NULL,
            name_ru TEXT NOT NULL,
            name_en TEXT NOT NULL,
            position INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name_uz TEXT NOT NULL,
            name_ru TEXT NOT NULL,
            name_en TEXT NOT NULL,
            has_topping_option INTEGER DEFAULT 0,
            FOREIGN KEY (category_id) REFERENCES categories(id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            temp TEXT NOT NULL,
            size TEXT,
            price INTEGER NOT NULL,
            FOREIGN KEY (item_id) REFERENCES items(id)
        )""")


def seed_if_empty():
    """Only runs once — if categories already exist, does nothing, so it's
    always safe to call this every time the bot starts."""
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if count > 0:
            return

        category_ids = {}
        for position, (cat_key, name_uz, name_ru, name_en) in enumerate(SEED_CATEGORIES):
            cur = conn.execute(
                "INSERT INTO categories (name_uz, name_ru, name_en, position) VALUES (?, ?, ?, ?)",
                (name_uz, name_ru, name_en, position),
            )
            category_ids[cat_key] = cur.lastrowid

        for cat_key, item_key, name_uz, name_ru, name_en, has_topping, variants in SEED_ITEMS:
            cur = conn.execute(
                "INSERT INTO items (category_id, name_uz, name_ru, name_en, has_topping_option) VALUES (?, ?, ?, ?, ?)",
                (category_ids[cat_key], name_uz, name_ru, name_en, int(has_topping)),
            )
            item_id = cur.lastrowid
            for temp, size, price in variants:
                conn.execute(
                    "INSERT INTO variants (item_id, temp, size, price) VALUES (?, ?, ?, ?)",
                    (item_id, temp, size, price),
                )


# ---------- reading (used by customer-facing menu) ----------

def _row_to_names(row_prefix_vals):
    uz, ru, en = row_prefix_vals
    return {"uz": uz, "ru": ru, "en": en}


def list_categories() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name_uz, name_ru, name_en FROM categories ORDER BY position, id"
        ).fetchall()
    return [{"id": r[0], "name": _row_to_names(r[1:4])} for r in rows]


def get_category(category_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name_uz, name_ru, name_en FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
    return {"id": row[0], "name": _row_to_names(row[1:4])} if row else None


def list_items(category_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name_uz, name_ru, name_en, has_topping_option FROM items WHERE category_id = ? ORDER BY id",
            (category_id,),
        ).fetchall()
        items = []
        for r in rows:
            variants = conn.execute(
                "SELECT id, temp, size, price FROM variants WHERE item_id = ? ORDER BY id", (r[0],)
            ).fetchall()
            items.append({
                "id": r[0],
                "name": _row_to_names(r[1:4]),
                "has_topping_option": bool(r[4]),
                "variants": [{"id": v[0], "temp": v[1], "size": v[2], "price": v[3]} for v in variants],
            })
    return items


def get_item(item_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, category_id, name_uz, name_ru, name_en, has_topping_option FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        variants = conn.execute(
            "SELECT id, temp, size, price FROM variants WHERE item_id = ? ORDER BY id", (item_id,)
        ).fetchall()
    return {
        "id": row[0],
        "category_id": row[1],
        "name": _row_to_names(row[2:5]),
        "has_topping_option": bool(row[5]),
        "variants": [{"id": v[0], "temp": v[1], "size": v[2], "price": v[3]} for v in variants],
    }


# ---------- writing (used by /admin) ----------

def add_category(name_uz: str, name_ru: str, name_en: str) -> int:
    with get_db() as conn:
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM categories").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO categories (name_uz, name_ru, name_en, position) VALUES (?, ?, ?, ?)",
            (name_uz, name_ru, name_en, position),
        )
        return cur.lastrowid


def category_item_count(category_id: int) -> int:
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM items WHERE category_id = ?", (category_id,)).fetchone()[0]


def update_category_names(category_id: int, name_uz: str, name_ru: str, name_en: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE categories SET name_uz = ?, name_ru = ?, name_en = ? WHERE id = ?",
            (name_uz, name_ru, name_en, category_id),
        )


def update_item_names(item_id: int, name_uz: str, name_ru: str, name_en: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE items SET name_uz = ?, name_ru = ?, name_en = ? WHERE id = ?",
            (name_uz, name_ru, name_en, item_id),
        )


def delete_category(category_id: int):
    """Only call this after confirming the category has no items (see category_item_count)."""
    with get_db() as conn:
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def add_item(category_id: int, name_uz: str, name_ru: str, name_en: str, has_topping_option: bool) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO items (category_id, name_uz, name_ru, name_en, has_topping_option) VALUES (?, ?, ?, ?, ?)",
            (category_id, name_uz, name_ru, name_en, int(has_topping_option)),
        )
        return cur.lastrowid


def delete_item(item_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM variants WHERE item_id = ?", (item_id,))
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))


def toggle_item_topping(item_id: int):
    with get_db() as conn:
        conn.execute("UPDATE items SET has_topping_option = 1 - has_topping_option WHERE id = ?", (item_id,))


def add_variant(item_id: int, temp: str, size: str | None, price: int) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO variants (item_id, temp, size, price) VALUES (?, ?, ?, ?)",
            (item_id, temp, size, price),
        )
        return cur.lastrowid


def update_variant_price(variant_id: int, new_price: int):
    with get_db() as conn:
        conn.execute("UPDATE variants SET price = ? WHERE id = ?", (new_price, variant_id))


def delete_variant(variant_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM variants WHERE id = ?", (variant_id,))


def get_variant(variant_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, item_id, temp, size, price FROM variants WHERE id = ?", (variant_id,)
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "item_id": row[1], "temp": row[2], "size": row[3], "price": row[4]}
