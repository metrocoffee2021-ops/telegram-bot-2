# handlers.py
# All the bot's conversation logic lives here: picking a language, browsing
# the menu, building an order, paying with Click or Payme through Telegram's
# own native checkout screen, and the loyalty card.
# The menu itself is NOT in this file — it's in the database, managed
# through /admin (see admin.py). This file only reads it.

import os
import time

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart, Command
from datetime import datetime, timedelta
import asyncio

from texts import t
from menu_data import EXTRA_TOPPING_PRICE
import menu_store
import db

router = Router()

OWNER_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))

# Telegram's native payment provider tokens, obtained via @BotFather > Payments.
# Format looks like "333605228:LIVE:xxxx" — nothing like a merchant API key.
PROVIDER_TOKENS = {
    "click": os.environ.get("CLICK_PROVIDER_TOKEN", ""),
    "payme": os.environ.get("PAYME_PROVIDER_TOKEN", ""),
}


class OrderFlow(StatesGroup):
    choosing_payment_method = State()  # button-only step; no message handler here on purpose


# ---------- helpers ----------

def fmt_price(amount: int) -> str:
    """Format a so'm amount the way the printed menu does: '20 000', not '20,000'."""
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


# ---------- menu browsing (reads from the database) ----------

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
    lang = lang_of(callback.from_user.id)
    item = menu_store.get_item(item_id)
    if not item:
        return
    price = price_for(item, temp, size) + (EXTRA_TOPPING_PRICE if topping else 0)
    name = item["name"].get(lang, item["name"]["en"])

    cart = CART.setdefault(callback.from_user.id, [])
    cart.append({"name": name, "price": price, "temp": temp, "size": size, "topping": topping})

    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "menu_button"), callback_data="menu")
    kb.button(text=t(lang, "checkout_button"), callback_data="checkout")
    kb.adjust(2)
    await callback.message.answer(t(lang, "added_to_cart", item=name), reply_markup=kb.as_markup())


# in-memory cart per user — cleared after a successful checkout. Lost if the bot restarts
# mid-order, which is an acceptable tradeoff for a small shop (customer just re-adds items).
CART: dict[int, list[dict]] = {}


# ---------- checkout & payment ----------

@router.message(Command("cart"))
async def cart_command(message: Message):
    await show_cart(message.from_user.id, message.answer)


@router.callback_query(F.data == "checkout")
async def checkout_callback(callback: CallbackQuery, state: FSMContext):
    await show_cart(callback.from_user.id, callback.message.answer, offer_payment=True, state=state)
    await callback.answer()


async def show_cart(user_id: int, send, offer_payment: bool = False, state: FSMContext = None):
    lang = lang_of(user_id)
    cart = CART.get(user_id, [])
    if not cart:
        await send(t(lang, "cart_empty"))
        return

    lines = []
    total = 0
    for entry in cart:
        parts = [entry["name"]]
        if entry["size"]:
            parts.append(entry["size"])
        if entry["topping"]:
            parts.append("+ boba")
        lines.append("• " + " ".join(parts))
        total += entry["price"]

    text = t(lang, "your_order") + "\n" + "\n".join(lines) + f"\n\n{t(lang, 'total')}: {fmt_price(total)} so'm"

    if offer_payment and state is not None:
        await state.set_data({"order_total": total})
        await state.set_state(OrderFlow.choosing_payment_method)
        kb = InlineKeyboardBuilder()
        kb.button(text="Click", callback_data="paymethod:click")
        kb.button(text="Payme", callback_data="paymethod:payme")
        kb.adjust(2)
        await send(text)
        await send(t(lang, "choose_payment_method"), reply_markup=kb.as_markup())
    else:
        await send(text)


@router.callback_query(F.data.startswith("paymethod:"))
async def payment_method_chosen(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split(":")[1]
    lang = lang_of(callback.from_user.id)
    provider_token = PROVIDER_TOKENS.get(method, "")

    if not provider_token:
        await callback.answer(t(lang, "payment_error"), show_alert=True)
        return

    data = await state.get_data()
    total = data["order_total"]
    order_id = f"order_{callback.from_user.id}_{int(time.time())}"
    db.create_order(order_id, callback.from_user.id, total, method)
    await state.clear()

    # Telegram invoice amounts are in the smallest currency unit — for UZS
    # that's tiyin (1 so'm = 100 tiyin), same as Payme's own API. Getting
    # this wrong would charge customers 100x too little or too much.
    amount_tiyin = total * 100

    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=t(lang, "invoice_title"),
        description=t(lang, "invoice_description"),
        payload=order_id,
        provider_token=provider_token,
        currency="UZS",
        prices=[LabeledPrice(label=t(lang, "total"), amount=amount_tiyin)],
    )
    await callback.answer()


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    # Telegram requires an answer within 10 seconds or the payment fails on
    # the customer's side. The order was already created when the invoice
    # was sent, so there's nothing further to validate here.
    order = db.get_order(pre_checkout_query.invoice_payload)
    if order and order["status"] == "pending":
        await pre_checkout_query.answer(ok=True)
    else:
        lang = lang_of(pre_checkout_query.from_user.id)
        await pre_checkout_query.answer(ok=False, error_message=t(lang, "payment_error"))


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    lang = lang_of(message.from_user.id)
    payment = message.successful_payment
    order_id = payment.invoice_payload

    db.set_order_gateway_ref(order_id, payment.telegram_payment_charge_id)
    db.mark_order_paid(order_id)
    result = db.add_stamp(message.from_user.id)
    CART[message.from_user.id] = []

    reply = t(lang, "payment_success")
    if result["card_expired"]:
        reply += "\n" + t(lang, "card_expired_notice")
    if result["earned_free_item"]:
        reply += "\n" + t(lang, "free_coffee_ready")
    await message.answer(reply, reply_markup=main_menu_keyboard(lang))


# ---------- loyalty ----------

@router.message(Command("stamps"))
async def stamps_command(message: Message):
    await show_stamps(message.from_user.id, message.answer)


@router.callback_query(F.data == "stamps")
async def stamps_callback(callback: CallbackQuery):
    await show_stamps(callback.from_user.id, callback.message.answer)
    await callback.answer()


async def show_stamps(user_id: int, send):
    lang = lang_of(user_id)
    status = db.get_loyalty_status(user_id)

    if not status:
        await send(t(lang, "stamps_header") + "\n" + t(lang, "stamps_none_yet"))
        return

    if status["free_coffee_pending"]:
        await send(t(lang, "stamps_header") + "\n" + t(lang, "free_coffee_ready"))
        return

    stamps = status["stamps"]
    card = "☕" * stamps + "⬜" * (db.STAMPS_FOR_FREE_ITEM - stamps)
    text = t(lang, "stamps_header") + "\n" + t(lang, "stamps_progress", card=card, stamps=stamps, total=db.STAMPS_FOR_FREE_ITEM)
    if status["first_stamp_at"]:
        expires = datetime.fromisoformat(status["first_stamp_at"]) + timedelta(days=db.CARD_VALID_DAYS)
        text += t(lang, "stamps_valid_until", date=expires.strftime("%d.%m.%Y"))
    await send(text)


# ---------- broadcast (owner only) ----------

@router.message(Command("broadcast"))
async def broadcast(message: Message):
    lang = lang_of(message.from_user.id)
    if message.from_user.id != OWNER_ID:
        await message.answer(t(lang, "not_authorized"))
        return

    text = message.text.removeprefix("/broadcast").strip()
    if not text:
        return

    user_ids = db.get_all_user_ids()
    sent = 0
    for user_id in user_ids:
        try:
            await message.bot.send_message(user_id, text)
            sent += 1
        except Exception:
            pass  # user may have blocked the bot — skip and continue
        await asyncio.sleep(0.05)

    await message.answer(t(lang, "broadcast_sent", count=sent))
