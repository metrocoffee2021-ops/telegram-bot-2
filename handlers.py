# handlers.py
# Updated conversation logic: multi-item shopping cart integration, language selection,
# menu browsing, native checkout processing, and loyalty card logic.

import os
import time
import math

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, LabeledPrice, PreCheckoutQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart, Command

from texts import t
from menu_data import EXTRA_TOPPING_PRICE
import menu_store
import db

router = Router()
OWNER_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))
BARISTA_GROUP_ID = int(os.environ.get("BARISTA_GROUP_ID", "0"))

PROVIDER_TOKENS = {
    "click": os.environ.get("CLICK_PROVIDER_TOKEN", ""),
    "payme": os.environ.get("PAYME_PROVIDER_TOKEN", ""),
}

class OrderFlow(StatesGroup):
    choosing_payment_method = State()

# --- Helper Functions ---
def fmt_price(amount: int) -> str: return f"{amount:_}".replace("_", " ")
def temps_for(item: dict) -> list[str]: return list(set(v["temp"] for v in item["variants"]))
def sizes_for(item: dict, temp: str) -> list[str | None]: return [v["size"] for v in item["variants"] if v["temp"] == temp]
def price_for(item: dict, temp: str, size: str | None) -> int:
    return next((v["price"] for v in item["variants"] if v["temp"] == temp and v["size"] == size), 0)
def price_range_text(item: dict) -> str:
    prices = [v["price"] for v in item["variants"]]
    if not prices: return "—"
    lo, hi = min(prices), max(prices)
    return f"{fmt_price(lo)} so'm" if lo == hi else f"{fmt_price(lo)}-{fmt_price(hi)} so'm"
def lang_of(user_id: int) -> str: return db.get_user_language(user_id)

def main_menu_keyboard(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "menu_button"), callback_data="menu")
    kb.button(text="🛒 Savatcha / View Cart", callback_data="cart:view")
    kb.button(text="🎁 Stamp Card", callback_data="loyalty:view")
    kb.adjust(2)
    return kb.as_markup()

# --- (Other handlers: lang, contact, location, menu, items, temp, size) ---

@router.callback_query(F.data == "cart:view")
async def view_cart_handler(callback: CallbackQuery):
    # Handles viewing, calculating totals, and removing items (cart:remove)
    # Uses db.get_user_cart and provides checkout options (cart:checkout)
    pass # Implementation in provided context...

@router.callback_query(F.data.startswith("cart:checkout:"))
async def process_cart_checkout(callback: CallbackQuery):
    # Handles payments with Click/Payme using db.create_order
    pass # Implementation in provided context...

# --- Other handlers (pre_checkout, success, loyalty) ---


