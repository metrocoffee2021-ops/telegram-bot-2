# handlers.py
# Conversation logic including language pick, menu layout browsing,
# native checkout processing, and loyalty programs.

import os
import time

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart, Command

from texts import t
from menu_data import EXTRA_TOPPING_PRICE
import menu_store
import db

router = Router()

OWNER_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))

PROVIDER_TOKENS = {
    "click": os.environ.get("CLICK_PROVIDER_TOKEN", ""),
    "payme": os.environ.get("PAYME_PROVIDER_TOKEN", ""),
}


class OrderFlow(StatesGroup):
    choosing_payment_method = State()


# ---------- helpers ----------

def fmt_price(amount: int) -> str:
    return f"{amount:_}".replace("_", " ")


def temps_for(item: dict) -> list[str]:
    seen = []
    for v in item["variants"]:
        if v["temp"] not in seen:
            seen.append(v["temp"])
    return seen


def sizes_for(item: dict, temp: str) -> list[str | None]:
    seen = []
    for v in item["variants"]:
        if v["temp"] == temp and v["size"] not in seen:
            seen.append(v["size"])
    return seen


def price_for(item: dict, temp: str, size: str | None) -> int:
    for v in item["variants"]:
        if v["temp"] == temp and v["size"] == size:
            return v["price"]
    return 0


def price_range_text(item: dict) -> str:
    prices = [v["price"] for v in item["variants"]]
    if not prices:
        return "—"
    lo, hi = min(prices), max(prices)
    return f"{fmt_price(lo)} so'm" if lo == hi else f"{fmt_price(lo)}-{fmt_price(hi)} so'm"


def lang_of(user_id: int) -> str:
    return db.get_user_language(user_id)


def main_menu_keyboard(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "menu_button"), callback_data="menu")
    kb.button(text=t(lang, "stamps_button"), callback_data="stamps")
    kb.adjust(2)
    return kb.as_markup()


# ---------- language ----------

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
    await callback.message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


# ---------- menu browsing ----------

@router.message(Command("menu"))
async def menu_command(message: Message):
    await show_categories(message.from_user.id, message.answer)


@router.callback_query(F.data == "menu")
async def menu_callback(callback: CallbackQuery):
    await show_categories(callback.from_user.id, callback.message.answer)
    await callback.answer()


async def show_categories(user_id: int, send):
    lang = lang_of(user_id)
    categories = menu_store.list_categories()
    if not categories:
        await send(t(lang, "menu_currently_empty"))
        return
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(text=cat["name"].get(lang, cat["name"]["en"]), callback_data=f"cat:{cat['id']}")
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
    kb.adjust(1)
    header = category["name"].get(lang, category["name"]["en"]) if category else ""
    await callback.message.answer(header, reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("item:"))
async def choose_temp_or_size(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    item = menu_store.get_item(item_id)
    if not item:
        await callback.answer()
        return
    temps = temps_for(item)

    if len(temps) > 1:
        kb = InlineKeyboardBuilder()
        for temp in temps:
            kb.button(text=t(lang, f"temp_{temp}"), callback_data=f"temp:{item_id}:{temp}")
        kb.adjust(2)
        await callback.message.answer(t(lang, "choose_temp"), reply_markup=kb.as_markup())
    else:
        await ask_size_or_add(callback, item_id, temps[0])
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
    else:
        await maybe_ask_topping(callback, item_id, temp, sizes[0])


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
        kb.button(
            text=t(lang, "add_topping", price=fmt_price(EXTRA_TOPPING_PRICE)),
            callback_data=f"topping:{item_id}:{temp}:{size_token}:yes",
        )
        kb.button(text=t(lang, "skip_topping"), callback_data=f"topping:{item_id}:{temp}:{size_token}:no")
        kb.adjust(1)
        await callback.message.answer(t(lang, "add_topping", price=fmt_price(EXTRA_TOPPING_PRICE)), reply_markup=kb.as_markup())
    else:
        await add_to_cart(callback, item_id, temp, size, topping=False)


@router.callback_query(F.data.startswith("topping:"))
async def topping_callback(callback: CallbackQuery):
    _, item_id, temp, size, choice = callback.data.split(":")
    await add_to_cart(callback, int(item_id), temp, None if size == "-" else size, topping=(choice == "yes"))
    await callback.answer()


async def add_to_cart(callback: CallbackQuery, item_id: int, temp: str, size: str | None, topping: bool):
    """Saves selection directly to orders database as a pending session."""
    user_id = callback.from_user.id
    lang = lang_of(user_id)
    item = menu_store.get_item(item_id)
    if not item:
        return
        
    base_price = price_for(item, temp, size)
    final_price = base_price + (EXTRA_TOPPING_PRICE if topping else 0)
    generated_order_id = f"ORD_{user_id}_{int(time.time())}"
    
    db.create_order(
        order_id=generated_order_id,
        user_id=user_id,
        total=final_price,
        payment_method="pending"
    )
    
    kb = InlineKeyboardBuilder()
    if PROVIDER_TOKENS["click"]:
        kb.button(text="Pay via Click 🇺🇿", callback_data=f"pay:click:{generated_order_id}")
    if PROVIDER_TOKENS["payme"]:
        kb.button(text="Pay via Payme 🇺🇿", callback_data=f"pay:payme:{generated_order_id}")
    
    kb.button(text="❌ O'chirish / Cancel", callback_data=f"order:cancel:{generated_order_id}")
    kb.adjust(1)
    
    name = item["name"].get(lang, item["name"]["en"])
    checkout_text = f"🛒 {name}\n💵 Total: {fmt_price(final_price)} so'm\n\nChoose payment method:"
    await callback.message.answer(checkout_text, reply_markup=kb.as_markup())


# ---------- native telegram checkout logic ----------

@router.callback_query(F.data.startswith("pay:"))
async def send_invoice_checkout(callback: CallbackQuery):
    _, provider_name, target_order_id = callback.data.split(":")
    provider_token = PROVIDER_TOKENS.get(provider_name)
    user_id = callback.from_user.id
    lang = lang_of(user_id)
    
    order_data = db.get_order(target_order_id)
    if not order_data or order_data["status"] != "pending":
        await callback.message.answer("Order not found or processed.")
        await callback.answer()
        return

    if not provider_token:
        await callback.message.answer(f"System Error: {provider_name.upper()} payment token is empty on Railway.")
        await callback.answer()
        return

    prices = [LabeledPrice(label="Metropia Coffee Checkout", amount=int(order_data['total']) * 100)]

    await callback.message.answer_invoice(
        title="Payment Checkout",
        description="METROPIA COFFEE Secure Gateway",
        payload=target_order_id,
        provider_token=provider_token,
        currency="UZS",
        prices=prices,
        start_parameter="bot-order-checkout"
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)



