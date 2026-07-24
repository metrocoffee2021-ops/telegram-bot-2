# handlers.py
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

# ---------- language and onboarding ----------

@router.message(CommandStart())
async def start(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="O'zbek", callback_data="lang:uz")
    kb.button(text="Русский", callback_data="lang:ru")
    kb.button(text="English", callback_data="lang:en")
    kb.adjust(3)
    await message.answer(t("en", "choose_language"), reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("lang:"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    db.save_user_language(callback.from_user.id, lang)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish / Send Phone Number", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
    await callback.message.answer("Tasdiqlash uchun telefon raqamingizni yuboring:\nPlease share your phone number to verify registration:", reply_markup=kb)
    await callback.answer()

@router.message(F.contact)
async def handle_contact(message: Message):
    user_id = message.from_user.id
    with db.get_db() as conn:
        conn.execute("UPDATE users SET phone = ? WHERE user_id = ?", (message.contact.phone_number, user_id))
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Joylashuvni yuborish / Send Location", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Sizga eng yaqin qahvaxonamizni ko'rsatish uchun joylashuvingizni ulashing:\nPlease send your location to find the closest coffee shop:", reply_markup=kb)

@router.message(F.location)
async def handle_location(message: Message):
    user_id = message.from_user.id
    lang = lang_of(user_id)
    lat, lon = message.location.latitude, message.location.longitude
    db.save_user_location(user_id, lat, lon)
    
    # ─── UPDATED GEOGRAPHIC COORDINATES FOR METROPIA ───
    # Metropia Luxor (Abdulla Qaxxor 150A): 41.2721, 69.2553
    # Metropia Sayram (Sayram street 4A): 41.3283, 69.3248
    luxor_dist = math.sqrt((lat - 41.2721)**2 + (lon - 69.2553)**2)
    sayram_dist = math.sqrt((lat - 41.3283)**2 + (lon - 69.3248)**2)
    
    if luxor_dist < sayram_dist:
        closest_branch = "☕ METROPIA LUXOR (Abdulla Qaxxor 150A)"
    else:
        closest_branch = "☕ METROPIA SAYRAM (Sayram street, 5th passage 4A)"
    
    confirm_text = {
        "uz": f"Rahmat! Sizga eng yaqin filial: {closest_branch}\nEndi buyurtma berishingiz mumkin!",
        "ru": f"Спасибо! Ближайший филиал: {closest_branch}\nТеперь можно сделать заказ!",
        "en": f"Thank you! The closest branch to you is: {closest_branch}\nYou can now browse the menu!"
    }.get(lang, closest_branch)
    
    await message.answer(confirm_text, reply_markup=ReplyKeyboardRemove())
    await message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang))

# ---------- menu browsing ----------

@router.message(Command("menu"))
async def menu_command(message: Message): await show_categories(message.from_user.id, message.answer)
@router.callback_query(F.data == "menu")
async def menu_callback(callback: CallbackQuery): await show_categories(callback.from_user.id, callback.message.answer); await callback.answer()

async def show_categories(user_id: int, send):
    lang = lang_of(user_id)
    categories = menu_store.list_categories()
    if not categories: await send(t(lang, "menu_currently_empty")); return
    kb = InlineKeyboardBuilder()
    for cat in categories: kb.button(text=cat["name"].get(lang, cat["name"]["en"]), callback_data=f"cat:{cat['id']}")
    kb.button(text="🛒 View Cart", callback_data="cart:view")
    kb.adjust(2)
    await send(t(lang, "choose_category"), reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("cat:"))
async def show_items(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    category = menu_store.get_category(cat_id)
    items = menu_store.list_items(cat_id)
    kb = InlineKeyboardBuilder()
    for item in items:
        name = item["name"].get(lang, item["name"]["en"])
        kb.button(text=f"{name} — {price_range_text(item)}", callback_data=f"item:{item['id']}")
    kb.button(text="⬅️ Back", callback_data="menu")
    kb.adjust(1)
    await callback.message.answer(category["name"].get(lang, category["name"]["en"]), reply_markup=kb.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("item:"))
async def choose_temp_or_size(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    item = menu_store.get_item(item_id)
    if not item: return await callback.answer()
    temps = temps_for(item)
    if len(temps) > 1:
        kb = InlineKeyboardBuilder()
        for temp in temps: kb.button(text=t(lang, f"temp_{temp}"), callback_data=f"temp:{item_id}:{temp}")
        kb.adjust(2)
        await callback.message.answer(t(lang, "choose_temp"), reply_markup=kb.as_markup())
    else: await ask_size_or_add(callback, item_id, temps[0])
    await callback.answer()

@router.callback_query(F.data.startswith("temp:"))
async def choose_size(callback: CallbackQuery):
    _, item_id, temp = callback.data.split(":")
    await ask_size_or_add(callback, int(item_id), temp)
    await callback.answer()

async def ask_size_or_add(callback: CallbackQuery, item_id: int, temp: str):
    lang = lang_of(callback.from_user.id)
    item = menu_store.get_item(item_id)
    sizes = sizes_for(item, temp)
    if len(sizes) > 1:
        kb = InlineKeyboardBuilder()
        for size in sizes:
            price = price_for(item, temp, size)
            kb.button(text=f"{size} — {fmt_price(price)} so'm", callback_data=f"size:{item_id}:{temp}:{size or '-'}")
        kb.adjust(2)
        await callback.message.answer(t(lang, "choose_size"), reply_markup=kb.as_markup())
    else: await maybe_ask_topping(callback, item_id, temp, sizes[0])

@router.callback_query(F.data.startswith("size:"))
async def choose_size_callback(callback: CallbackQuery):
    _, item_id, temp, size = callback.data.split(":")
    await maybe_ask_topping(callback, int(item_id), temp, None if size == "-" else size)
    await callback.answer()

async def maybe_ask_topping(callback: CallbackQuery, item_id: int, temp: str, size: str | None):
    lang = lang_of(callback.from_user.id)
    item = menu_store.get_item(item_id)
    size_token = size or "-"
    if item and item["has_topping_option"]:
        kb = InlineKeyboardBuilder()
        kb.button(text=t(lang, "add_topping", price=fmt_price(EXTRA_TOPPING_PRICE)), callback_data=f"topping:{item_id}:{temp}:{size_token}:yes")
        kb.button(text=t(lang, "skip_topping"), callback_data=f"topping:{item_id}:{temp}:{size_token}:no")
        kb.adjust(1)
        await callback.message.answer(t(lang, "add_topping", price=fmt_price(EXTRA_TOPPING_PRICE)), reply_markup=kb.as_markup())
    else: await add_to_cart(callback, item_id, temp, size, topping=False)

@router.callback_query(F.data.startswith("topping:"))
async def topping_callback(callback: CallbackQuery):
    _, item_id, temp, size, choice = callback.data.split(":")
    await add_to_cart(callback, int(item_id), temp, None if size == "-" else size, topping=(choice == "yes"))
    await callback.answer()

async def add_to_cart(callback: CallbackQuery, item_id: int, temp: str, size: str | None, topping: bool):
    user_id = callback.from_user.id
    lang = lang_of(user_id)
    item = menu_store.get_item(item_id)
    if not item: return
    price = price_for(item, temp, size) + (EXTRA_TOPPING_PRICE if topping else 0)
    db.add_item_to_cart(user_id, item_id, temp, size, topping, price)
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Add More", callback_data="menu")
    kb.button(text="🛒 View Cart & Pay", callback_data="cart:view")
    kb.adjust(1)
    await callback.message.answer(f"✅ Added {item['name'].get(lang, item['name']['en'])} to cart!", reply_markup=kb.as_markup())

# ---------- Cart Interface View ----------




