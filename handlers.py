# handlers.py
# All the bot's conversation logic lives here: picking a language, browsing
# the menu, building an order, paying with Click or Payme through Telegram's
# own native checkout screen, and the loyalty card.
# The menu itself is NOT in this file — it's in the database, managed
# through /admin (see admin.py). This file only reads it.

import os
import time
import json

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, LabeledPrice, PreCheckoutQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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
import branches

router = Router()

OWNER_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))
STAFF_GROUP_ID = int(os.environ.get("STAFF_GROUP_ID", "0"))

# Telegram's native payment provider tokens, obtained via @BotFather > Payments.
# Format looks like "333605228:LIVE:xxxx" — nothing like a merchant API key.
PROVIDER_TOKENS = {
    "click": os.environ.get("CLICK_PROVIDER_TOKEN", ""),
    "payme": os.environ.get("PAYME_PROVIDER_TOKEN", ""),
}


class OrderFlow(StatesGroup):
    awaiting_contact = State()
    awaiting_location = State()
    awaiting_notes = State()
    choosing_pickup_time = State()  # button-only step; no message handler here on purpose
    choosing_payment_method = State()  # button-only step; no message handler here on purpose


class OnboardingFlow(StatesGroup):
    """A customer's name is asked exactly once, the first time they hit
    Checkout — not before, so nothing blocks them from browsing the menu.
    Phone number and nearest branch are already handled by the normal
    checkout steps below (and skipped automatically once saved)."""
    awaiting_name = State()


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


async def respond(target, text: str, reply_markup=None):
    """Use this instead of message.answer()/callback.message.answer() for every
    step in the ordering flow. When the step was reached by tapping a button,
    this EDITS that same message in place instead of sending a new one — so
    browsing the menu doesn't flood the chat with dozens of old messages.
    When reached via a typed command (no previous bot message to edit), it
    just sends normally. Returns the resulting message, so callers can track
    it with track_checkout_message() if it needs cleaning up later."""
    if isinstance(target, CallbackQuery):
        try:
            return await target.message.edit_text(text, reply_markup=reply_markup)
        except Exception:
            # message has no editable text (e.g. was a photo), or content is
            # byte-for-byte identical to what's already shown — either way,
            # falling back to a fresh message is always safe.
            return await target.message.answer(text, reply_markup=reply_markup)
    else:
        return await target.answer(text, reply_markup=reply_markup)


def add_nav_row(kb: InlineKeyboardBuilder, lang: str, back_callback: str):
    kb.button(text=t(lang, "back_button"), callback_data=back_callback)
    kb.button(text=t(lang, "menu_button"), callback_data="menu")


def main_menu_keyboard(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "menu_button"), callback_data="menu")
    kb.button(text=t(lang, "stamps_button"), callback_data="stamps")
    kb.adjust(2)
    return kb.as_markup()


def persistent_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """A bottom keyboard that stays visible at all times, so customers don't
    need to remember commands like /menu or /stamps. It coexists fine with the
    inline buttons used elsewhere — this doesn't replace those, just adds a
    always-there shortcut bar. is_persistent=True keeps it showing even while
    inline keyboards are also on screen (aiogram 3.x / Bot API 6.7+)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, "menu_button")), KeyboardButton(text=t(lang, "cart_button"))],
            [KeyboardButton(text=t(lang, "stamps_button")), KeyboardButton(text=t(lang, "my_orders_button"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


_ALL_LANGS = ("uz", "ru", "en")
MENU_BUTTON_TEXTS = {t(l, "menu_button") for l in _ALL_LANGS}
CART_BUTTON_TEXTS = {t(l, "cart_button") for l in _ALL_LANGS}
STAMPS_BUTTON_TEXTS = {t(l, "stamps_button") for l in _ALL_LANGS}
MY_ORDERS_BUTTON_TEXTS = {t(l, "my_orders_button") for l in _ALL_LANGS}


@router.message(F.text.in_(MENU_BUTTON_TEXTS))
async def menu_button_pressed(message: Message):
    await show_categories(message)


@router.message(F.text.in_(CART_BUTTON_TEXTS))
async def cart_button_pressed(message: Message):
    await show_cart_editable(message)


@router.message(F.text.in_(STAMPS_BUTTON_TEXTS))
async def stamps_button_pressed(message: Message):
    await show_stamps(message.from_user.id, message.answer)


@router.message(F.text.in_(MY_ORDERS_BUTTON_TEXTS))
async def my_orders_button_pressed(message: Message):
    await my_orders_command(message)


# ---------- language ----------

@router.message(CommandStart())
async def start(message: Message):
    db.save_username(message.from_user.id, message.from_user.username)

    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            referrer_id = int(parts[1].removeprefix("ref_"))
            db.record_referral(message.from_user.id, referrer_id)
        except ValueError:
            pass

    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇿 O'zbek", callback_data="lang:uz")
    kb.button(text="🇷🇺 Русский", callback_data="lang:ru")
    kb.button(text="🇺🇸 English", callback_data="lang:en")
    kb.adjust(3)
    await message.answer(t("en", "choose_language"), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("lang:"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    db.save_user_language(callback.from_user.id, lang)
    db.save_username(callback.from_user.id, callback.from_user.username)
    await callback.message.answer(t(lang, "welcome"), reply_markup=main_menu_keyboard(lang))
    # a second message just to attach the persistent bottom keyboard — Telegram
    # only allows one reply_markup per message, and this one is inline already
    await callback.message.answer(t(lang, "shortcuts_ready"), reply_markup=persistent_keyboard(lang))
    await callback.answer()


# ---------- one-time name ask, folded into first checkout instead of blocking browsing ----------

@router.message(OnboardingFlow.awaiting_name)
async def onboarding_name_received(message: Message, state: FSMContext):
    lang = lang_of(message.from_user.id)
    name = (message.text or "").strip()
    if not name:
        await message.answer(t(lang, "onboarding_name_invalid"))
        return

    db.save_full_name(message.from_user.id, name)
    track_checkout_message(message.from_user.id, message.message_id)  # their typed name — cleaned up after order
    # straight into the normal checkout flow — this was the only thing gating it
    await show_cart(message, offer_payment=True, state=state)


# ---------- menu browsing (reads from the database) ----------

@router.message(Command("menu"))
async def menu_command(message: Message):
    await show_categories(message)


@router.callback_query(F.data == "menu")
async def menu_callback(callback: CallbackQuery):
    await show_categories(callback)
    await callback.answer()


async def show_categories(target):
    user_id = target.from_user.id
    lang = lang_of(user_id)
    categories = menu_store.list_categories()
    if not categories:
        await respond(target, t(lang, "menu_currently_empty"))
        return
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(text=cat["name"].get(lang, cat["name"]["en"]), callback_data=f"cat:{cat['id']}")
    kb.adjust(2)
    header = t(lang, "choose_category")
    cart = CART.get(user_id, [])
    if cart:
        qty = sum(entry.get("qty", 1) for entry in cart)
        header += "\n" + t(lang, "cart_summary_line", qty=qty, total=fmt_price(cart_total(user_id)))
    await respond(target, header, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("cat:"))
async def show_items(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    category = menu_store.get_category(cat_id)
    items = menu_store.list_items(cat_id)
    kb = InlineKeyboardBuilder()
    for item in items:
        name = item["name"].get(lang, item["name"]["en"])
        if item["in_stock"]:
            kb.button(text=f"{name} — {price_range_text(item)}", callback_data=f"item:{item['id']}")
        else:
            kb.button(text=f"❌ {name} — {t(lang, 'out_of_stock')}", callback_data="outofstock")
    kb.button(text=t(lang, "back_button"), callback_data="menu")
    kb.adjust(*([1] * len(items)), 1)
    header = category["name"].get(lang, category["name"]["en"]) if category else ""
    await respond(callback, header, reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data == "outofstock")
async def out_of_stock_tap(callback: CallbackQuery):
    lang = lang_of(callback.from_user.id)
    await callback.answer(t(lang, "out_of_stock"), show_alert=True)


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
        add_nav_row(kb, lang, back_callback=f"cat:{item['category_id']}")
        kb.adjust(2, 2)
        await respond(callback, t(lang, "choose_temp"), reply_markup=kb.as_markup())
    else:
        await ask_size_or_add(callback, item_id, temps[0])

    if item.get("description"):
        await callback.answer(item["description"], show_alert=True)
    else:
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
        add_nav_row(kb, lang, back_callback=f"item:{item_id}")
        kb.adjust(2, 2)
        await respond(callback, t(lang, "choose_size"), reply_markup=kb.as_markup())
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
        add_nav_row(kb, lang, back_callback=f"temp:{item_id}:{temp}")
        kb.adjust(1, 1, 2)
        await respond(callback, t(lang, "add_topping", price=fmt_price(EXTRA_TOPPING_PRICE)), reply_markup=kb.as_markup())
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
    for entry in cart:
        if entry["name"] == name and entry["temp"] == temp and entry["size"] == size and entry["topping"] == topping:
            entry["qty"] += 1
            break
    else:
        cart.append({"name": name, "price": price, "temp": temp, "size": size, "topping": topping, "qty": 1})

    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "menu_button"), callback_data="menu")
    kb.button(text=t(lang, "cart_button"), callback_data="cart")
    kb.adjust(2)
    await respond(callback, t(lang, "added_to_cart", item=name), reply_markup=kb.as_markup())


# in-memory cart per user — cleared after a successful checkout. Lost if the bot restarts
# mid-order, which is an acceptable tradeoff for a small shop (customer just re-adds items).
CART: dict[int, list[dict]] = {}

# Tracks bot messages sent during checkout (contact/fulfillment/location/notes/pickup-time
# prompts) so they can all be deleted once the order completes — customers have a Back
# button for navigating while it's in progress, so nothing is lost by cleaning up after.
CHECKOUT_MESSAGES: dict[int, list[int]] = {}


def track_checkout_message(user_id: int, message_id: int):
    CHECKOUT_MESSAGES.setdefault(user_id, []).append(message_id)


async def cleanup_checkout_messages(bot, user_id: int):
    for message_id in CHECKOUT_MESSAGES.pop(user_id, []):
        try:
            await bot.delete_message(user_id, message_id)
        except Exception:
            pass  # message may already be gone, or too old to delete (Telegram's 48h limit) — harmless either way


async def finish_order_and_return_to_menu(bot, user_id: int, lang: str, thank_you_text: str):
    await cleanup_checkout_messages(bot, user_id)
    await bot.send_message(user_id, thank_you_text, reply_markup=main_menu_keyboard(lang))
    # the contact/location prompts during checkout replace Telegram's custom keyboard
    # with their own one-time ones, which then just vanish — this brings the
    # persistent Menu/Cart/Card/Orders bar back so there's always a way to start again
    await bot.send_message(user_id, t(lang, "shortcuts_ready"), reply_markup=persistent_keyboard(lang))

    categories = menu_store.list_categories()
    if categories:
        kb = InlineKeyboardBuilder()
        for cat in categories:
            kb.button(text=cat["name"].get(lang, cat["name"]["en"]), callback_data=f"cat:{cat['id']}")
        kb.adjust(2)
        await bot.send_message(user_id, t(lang, "choose_category"), reply_markup=kb.as_markup())




def cart_total(user_id: int) -> int:
    return sum(entry["price"] * entry["qty"] for entry in CART.get(user_id, []))


def cart_lines(cart: list[dict]) -> list[str]:
    lines = []
    for entry in cart:
        parts = [entry["name"]]
        if entry["size"]:
            parts.append(entry["size"])
        if entry["topping"]:
            parts.append("+ boba")
        qty_suffix = f" x{entry['qty']}" if entry["qty"] > 1 else ""
        lines.append("• " + " ".join(parts) + qty_suffix)
    return lines


# ---------- cart viewing & editing ----------

@router.message(Command("cart"))
async def cart_command(message: Message):
    await show_cart_editable(message)


@router.callback_query(F.data == "cart")
async def cart_callback(callback: CallbackQuery):
    await show_cart_editable(callback)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


async def show_cart_editable(target):
    user_id = target.from_user.id
    lang = lang_of(user_id)
    cart = CART.get(user_id, [])
    if not cart:
        kb = InlineKeyboardBuilder()
        kb.button(text=t(lang, "menu_button"), callback_data="menu")
        kb.adjust(1)
        await respond(target, t(lang, "cart_empty"), reply_markup=kb.as_markup())
        return

    text = t(lang, "your_order") + "\n" + "\n".join(cart_lines(cart)) + f"\n\n{t(lang, 'total')}: {fmt_price(cart_total(user_id))} so'm"

    kb = InlineKeyboardBuilder()
    for i, entry in enumerate(cart):
        label = entry["name"] + (f" {entry['size']}" if entry["size"] else "")
        kb.button(text="➖", callback_data=f"cartdec:{i}")
        kb.button(text=f"{label} x{entry['qty']}", callback_data="noop")
        kb.button(text="➕", callback_data=f"cartinc:{i}")
    kb.button(text=t(lang, "checkout_button"), callback_data="checkout")
    kb.button(text=t(lang, "clear_cart_button"), callback_data="clearcart")
    kb.button(text=t(lang, "menu_button"), callback_data="menu")
    kb.adjust(*([3] * len(cart)), 1, 1, 1)

    await respond(target, text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("cartinc:"))
async def cart_increment(callback: CallbackQuery):
    index = int(callback.data.split(":")[1])
    cart = CART.get(callback.from_user.id, [])
    if 0 <= index < len(cart):
        cart[index]["qty"] += 1
    await show_cart_editable(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("cartdec:"))
async def cart_decrement(callback: CallbackQuery):
    index = int(callback.data.split(":")[1])
    cart = CART.get(callback.from_user.id, [])
    if 0 <= index < len(cart):
        cart[index]["qty"] -= 1
        if cart[index]["qty"] <= 0:
            cart.pop(index)
    await show_cart_editable(callback)
    await callback.answer()


@router.callback_query(F.data == "clearcart")
async def cart_clear(callback: CallbackQuery):
    CART[callback.from_user.id] = []
    await show_cart_editable(callback)
    await callback.answer(t(lang_of(callback.from_user.id), "cart_cleared"))


# ---------- checkout & payment ----------

@router.callback_query(F.data == "checkout")
async def checkout_callback(callback: CallbackQuery, state: FSMContext):
    lang = lang_of(callback.from_user.id)
    if db.get_setting("ordering_paused") == "1":
        await callback.answer(t(lang, "ordering_paused_notice"), show_alert=True)
        return
    CHECKOUT_MESSAGES[callback.from_user.id] = [callback.message.message_id]

    if not db.is_onboarded(callback.from_user.id):
        # first-ever checkout for this customer — ask their name once, right here,
        # instead of making them answer it before they could even see the menu
        await state.set_state(OnboardingFlow.awaiting_name)
        sent = await callback.message.answer(t(lang, "onboarding_ask_name"))
        track_checkout_message(callback.from_user.id, sent.message_id)
        await callback.answer()
        return

    await show_cart(callback, offer_payment=True, state=state)
    await callback.answer()


async def show_cart(target, offer_payment: bool = False, state: FSMContext = None):
    """`target` can be the CallbackQuery from tapping Checkout, or a plain Message
    (used right after a first-time customer types their name) — respond() and the
    `send` lookup below handle either case."""
    user_id = target.from_user.id
    lang = lang_of(user_id)
    cart = CART.get(user_id, [])
    if not cart:
        await respond(target, t(lang, "cart_empty"))
        return

    total = cart_total(user_id)
    text = t(lang, "your_order") + "\n" + "\n".join(cart_lines(cart)) + f"\n\n{t(lang, 'total')}: {fmt_price(total)} so'm"
    send = target.message.answer if isinstance(target, CallbackQuery) else target.answer

    if offer_payment and state is not None:
        await state.set_data({"order_total": total})

        saved_phone = db.get_phone(user_id)
        if saved_phone:
            # already have their number from a past order — skip straight to
            # fulfillment instead of asking them to share it again every time
            await state.update_data(phone=saved_phone)
            sent = await respond(target, text)
            if not isinstance(target, CallbackQuery):
                track_checkout_message(user_id, sent.message_id)
            await ask_fulfillment(user_id, lang, send=send)
            return

        await state.set_state(OrderFlow.awaiting_contact)
        contact_kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=t(lang, "share_contact_button"), request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        sent = await respond(target, text)
        if not isinstance(target, CallbackQuery):
            track_checkout_message(user_id, sent.message_id)
        # A ReplyKeyboardMarkup can't be attached to an edited message in Telegram —
        # this one new message is unavoidable, everything else in the flow is edited in place.
        contact_msg = await send(t(lang, "share_contact_prompt"), reply_markup=contact_kb)
        track_checkout_message(user_id, contact_msg.message_id)
    else:
        await respond(target, text)


async def ask_fulfillment(user_id: int, lang: str, send):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "fulfillment_pickup_button"), callback_data="fulfillment:pickup")
    kb.button(text=t(lang, "fulfillment_delivery_button"), callback_data="fulfillment:delivery")
    kb.adjust(2)
    sent = await send(t(lang, "choose_fulfillment"), reply_markup=kb.as_markup())
    track_checkout_message(user_id, sent.message_id)


@router.message(OrderFlow.awaiting_contact, F.contact)
async def contact_received(message: Message, state: FSMContext):
    lang = lang_of(message.from_user.id)
    await state.update_data(phone=message.contact.phone_number)
    db.save_phone(message.from_user.id, message.contact.phone_number)  # remember it for next time
    track_checkout_message(message.from_user.id, message.message_id)  # their "shared contact" bubble
    await ask_fulfillment(message.from_user.id, lang, send=message.answer)


async def ask_notes(user_id: int, lang: str, state: FSMContext, send):
    skip_kb = InlineKeyboardBuilder()
    skip_kb.button(text=t(lang, "skip_notes_button"), callback_data="skipnotes")
    sent = await send(t(lang, "ask_notes"), reply_markup=skip_kb.as_markup())
    track_checkout_message(user_id, sent.message_id)
    await state.set_state(OrderFlow.awaiting_notes)


async def ask_for_location(user_id: int, lang: str, fulfillment: str, state: FSMContext, send):
    await state.set_state(OrderFlow.awaiting_location)
    prompt_key = "share_location_delivery_prompt" if fulfillment == "delivery" else "share_location_prompt"
    location_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "share_location_button"), request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    sent = await send(t(lang, prompt_key), reply_markup=location_kb)
    track_checkout_message(user_id, sent.message_id)


@router.callback_query(F.data.startswith("fulfillment:"))
async def fulfillment_chosen(callback: CallbackQuery, state: FSMContext):
    lang = lang_of(callback.from_user.id)
    fulfillment = callback.data.split(":", 1)[1]
    await state.update_data(fulfillment=fulfillment)

    if fulfillment == "pickup":
        home_branch = db.get_home_branch(callback.from_user.id)
        if home_branch:
            # already know their nearest branch from onboarding/a past order — skip
            # asking for location again, but let them switch if they're elsewhere today
            await state.update_data(branch_name=home_branch["name"])
            change_kb = InlineKeyboardBuilder()
            change_kb.button(text=t(lang, "change_branch_button"), callback_data="changebranch")
            sent = await callback.message.answer(
                t(lang, "nearest_branch", branch=home_branch["name"], address=home_branch["address"]),
                reply_markup=change_kb.as_markup(),
            )
            track_checkout_message(callback.from_user.id, sent.message_id)
            await ask_notes(callback.from_user.id, lang, state, send=callback.message.answer)
            await callback.answer()
            return

    await ask_for_location(callback.from_user.id, lang, fulfillment, state, send=callback.message.answer)
    await callback.answer()


@router.callback_query(F.data == "changebranch")
async def change_branch(callback: CallbackQuery, state: FSMContext):
    lang = lang_of(callback.from_user.id)
    await ask_for_location(callback.from_user.id, lang, "pickup", state, send=callback.message.answer)
    await callback.answer()


@router.message(OrderFlow.awaiting_contact)
async def contact_not_shared(message: Message):
    lang = lang_of(message.from_user.id)
    contact_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "share_contact_button"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    track_checkout_message(message.from_user.id, message.message_id)
    sent = await message.answer(t(lang, "share_contact_prompt"), reply_markup=contact_kb)
    track_checkout_message(message.from_user.id, sent.message_id)


@router.message(OrderFlow.awaiting_location, F.location)
async def location_received(message: Message, state: FSMContext):
    lang = lang_of(message.from_user.id)
    data = await state.get_data()
    lat, lng = message.location.latitude, message.location.longitude

    if data.get("fulfillment") == "delivery":
        maps_link = f"https://maps.google.com/?q={lat},{lng}"
        await state.update_data(delivery_address=maps_link)
        sent1 = await message.answer(t(lang, "delivery_address_saved"), reply_markup=ReplyKeyboardRemove())
    else:
        branch = branches.nearest_branch(lat, lng)
        await state.update_data(branch_name=branch["name"])
        db.save_home_branch(message.from_user.id, branch["name"], lat, lng)  # keep their saved branch fresh
        sent1 = await message.answer(
            t(lang, "nearest_branch", branch=branch["name"], address=branch["address"]),
            reply_markup=ReplyKeyboardRemove(),
        )
    track_checkout_message(message.from_user.id, message.message_id)  # their "shared location" bubble
    track_checkout_message(message.from_user.id, sent1.message_id)
    await ask_notes(message.from_user.id, lang, state, send=message.answer)


@router.message(OrderFlow.awaiting_notes)
async def notes_received(message: Message, state: FSMContext):
    lang = lang_of(message.from_user.id)
    text = (message.text or "").strip()
    if text and text.lower() not in {"skip", "o'tkazib yuborish", "пропустить", "-"}:
        await state.update_data(notes=text)
    track_checkout_message(message.from_user.id, message.message_id)  # their typed note (or "skip")
    await prompt_pickup_time(message.bot, message.from_user.id, lang, state, send=message.answer)


@router.callback_query(F.data == "skipnotes")
async def skip_notes(callback: CallbackQuery, state: FSMContext):
    lang = lang_of(callback.from_user.id)
    await prompt_pickup_time(callback.bot, callback.from_user.id, lang, state, send=callback.message.answer)
    await callback.answer()


async def prompt_pickup_time(bot, user_id: int, lang: str, state: FSMContext, send):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "pickup_asap_button"), callback_data="pickuptime:ASAP")
    kb.button(text=t(lang, "pickup_15_button"), callback_data="pickuptime:+15min")
    kb.button(text=t(lang, "pickup_30_button"), callback_data="pickuptime:+30min")
    kb.button(text=t(lang, "pickup_60_button"), callback_data="pickuptime:+1h")
    kb.adjust(1, 3)
    sent = await send(t(lang, "choose_pickup_time"), reply_markup=kb.as_markup())
    track_checkout_message(user_id, sent.message_id)
    await state.set_state(OrderFlow.choosing_pickup_time)


@router.callback_query(F.data.startswith("pickuptime:"))
async def pickup_time_chosen(callback: CallbackQuery, state: FSMContext):
    lang = lang_of(callback.from_user.id)
    pickup_time = callback.data.split(":", 1)[1]
    await state.update_data(pickup_time=pickup_time)

    kb = InlineKeyboardBuilder()
    kb.button(text="Click", callback_data="paymethod:click")
    kb.button(text="Payme", callback_data="paymethod:payme")
    kb.button(text=t(lang, "cash_payment_button"), callback_data="paymethod:cash")
    if db.get_bundle_credits(callback.from_user.id) > 0:
        kb.button(text=t(lang, "bundle_pay_button", credits=db.get_bundle_credits(callback.from_user.id)), callback_data="paymethod:bundle")
        add_nav_row(kb, lang, back_callback="cart")
        kb.adjust(2, 1, 1, 2)
    else:
        add_nav_row(kb, lang, back_callback="cart")
        kb.adjust(2, 1, 2)
    await respond(callback, t(lang, "choose_payment_method"), reply_markup=kb.as_markup())
    await state.set_state(OrderFlow.choosing_payment_method)
    await callback.answer()


@router.message(OrderFlow.awaiting_location)
async def location_not_shared(message: Message):
    lang = lang_of(message.from_user.id)
    location_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "share_location_button"), request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    track_checkout_message(message.from_user.id, message.message_id)
    sent = await message.answer(t(lang, "share_location_prompt"), reply_markup=location_kb)
    track_checkout_message(message.from_user.id, sent.message_id)


@router.callback_query(F.data.startswith("paymethod:"))
async def payment_method_chosen(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split(":")[1]
    lang = lang_of(callback.from_user.id)

    data = await state.get_data()
    total = data.get("order_total")
    if total is None:
        # FSM state was lost (e.g. stale/duplicate bot instance, or the
        # session expired) — recover gracefully instead of crashing.
        await callback.answer(t(lang, "payment_error"), show_alert=True)
        await show_cart(callback, offer_payment=True, state=state)
        return

    order_id = f"order_{callback.from_user.id}_{int(time.time())}"
    cart_snapshot = CART.get(callback.from_user.id, [])
    items_summary = "; ".join(cart_lines(cart_snapshot))
    db.create_order(
        order_id, callback.from_user.id, total, method,
        phone=data.get("phone"), branch_name=data.get("branch_name"), items_summary=items_summary,
        items_json=json.dumps(cart_snapshot), notes=data.get("notes"), pickup_time=data.get("pickup_time"),
        delivery_address=data.get("delivery_address"),
    )
    await state.clear()

    if method == "cash":
        await handle_cash_checkout(callback, order_id, lang)
        return

    if method == "bundle":
        await handle_bundle_checkout(callback, order_id, cart_snapshot, lang)
        return

    provider_token = PROVIDER_TOKENS.get(method, "")
    if not provider_token:
        await callback.answer(t(lang, "payment_error"), show_alert=True)
        return

    # Telegram invoice amounts are in the smallest currency unit — for UZS
    # that's tiyin (1 so'm = 100 tiyin), same as Payme's own API. Getting
    # this wrong would charge customers 100x too little or too much.
    amount_tiyin = total * 100

    try:
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=t(lang, "invoice_title"),
            description=t(lang, "invoice_description"),
            payload=order_id,
            provider_token=provider_token,
            currency="UZS",
            prices=[LabeledPrice(label=t(lang, "total"), amount=amount_tiyin)],
        )
    except Exception as e:
        # Without this, a bad/misconfigured provider token throws here and the
        # callback never gets answered — the button just spins forever on the
        # customer's screen with no error shown. Log the real reason so it's
        # visible in `get-logs` instead of silently failing.
        print(f"[payment] send_invoice failed for method={method} order={order_id}: {e}")
        await callback.answer(t(lang, "payment_error"), show_alert=True)
        return

    await callback.answer()


async def handle_cash_checkout(callback: CallbackQuery, order_id: str, lang: str):
    """Cash orders are NOT marked paid and get NO stamp yet — staff must confirm
    they actually received the money first. This is the one place a shortcut
    would let someone claim stamps for a payment that never happened."""
    order = db.get_order(order_id)
    notify_chat_id = STAFF_GROUP_ID or OWNER_ID
    customer_label = order_customer_label(order)

    if notify_chat_id:
        kb = InlineKeyboardBuilder()
        kb.button(text=t(lang, "cash_confirm_received_button"), callback_data=f"cashconfirm:{order_id}")
        ticket_text = build_staff_order_text(order, "—", customer_label, status_line=t(lang, "cash_awaiting_confirmation"))
        try:
            await callback.bot.send_message(notify_chat_id, ticket_text, reply_markup=kb.as_markup())
        except Exception as e:
            print(f"[cash-checkout] FAILED to notify chat_id={notify_chat_id}: {e}")

    await cleanup_checkout_messages(callback.bot, callback.from_user.id)
    await callback.message.answer(t(lang, "cash_order_placed_customer"))
    await callback.answer()


async def handle_bundle_checkout(callback: CallbackQuery, order_id: str, cart_snapshot: list, lang: str):
    """Bundle credits were already paid for up front when the bundle was
    bought, so — unlike cash — this confirms the order immediately, same as
    a successful Click/Payme payment."""
    qty_needed = sum(entry["qty"] for entry in cart_snapshot)
    if not db.use_bundle_credits(callback.from_user.id, qty_needed):
        await callback.answer(t(lang, "bundle_not_enough_credits"), show_alert=True)
        return

    db.mark_order_paid(order_id)
    ticket_number = db.assign_order_number(order_id, db.now_utc().strftime("%Y-%m-%d"))
    result = db.add_stamp(callback.from_user.id)
    await apply_referral_bonus_if_applicable(callback.bot, callback.from_user.id)
    CART[callback.from_user.id] = []

    reply = t(lang, "order_complete_thanks") + "\n" + t(lang, "payment_success", number=ticket_number)
    order = db.get_order(order_id)
    if order["branch_name"]:
        reply += "\n" + t(lang, "pickup_reminder", branch=order["branch_name"])
    if result["earned_free_item"]:
        reply += "\n" + t(lang, "free_coffee_ready")
    remaining = db.get_bundle_credits(callback.from_user.id)
    reply += "\n" + t(lang, "bundle_credits_remaining", credits=remaining)
    await finish_order_and_return_to_menu(callback.bot, callback.from_user.id, lang, reply)

    notify_chat_id = STAFF_GROUP_ID or OWNER_ID
    if notify_chat_id:
        customer_label = order_customer_label(order)
        staff_kb = InlineKeyboardBuilder()
        staff_kb.button(text="✅ Confirm order", callback_data=f"claim:{order_id}")
        try:
            await callback.bot.send_message(
                notify_chat_id, build_staff_order_text(order, ticket_number, customer_label),
                reply_markup=staff_kb.as_markup(),
            )
        except Exception as e:
            print(f"[bundle-checkout] FAILED to notify chat_id={notify_chat_id}: {e}")

    await callback.answer()


@router.callback_query(F.data.startswith("cashconfirm:"))
async def cash_checkout_confirm(callback: CallbackQuery):
    if not is_staff(callback):
        await callback.answer()
        return
    order_id = callback.data.split(":", 1)[1]
    order = db.get_order(order_id)
    if not order or order["status"] == "paid":
        await callback.answer()
        return

    db.mark_order_paid(order_id)
    today_str = db.now_utc().strftime("%Y-%m-%d")
    ticket_number = db.assign_order_number(order_id, today_str)
    result = db.add_stamp(order["user_id"])
    await apply_referral_bonus_if_applicable(callback.bot, order["user_id"])
    order = db.get_order(order_id)

    staff_name = callback.from_user.full_name
    customer_label = order_customer_label(order)
    confirm_kb = InlineKeyboardBuilder()
    confirm_kb.button(text="✅ Confirm order", callback_data=f"claim:{order_id}")
    await callback.message.edit_text(
        build_staff_order_text(order, ticket_number, customer_label, status_line=f"💵 Cash confirmed — {staff_name}"),
        reply_markup=confirm_kb.as_markup(),
    )

    customer_lang = lang_of(order["user_id"])
    try:
        notice = t(customer_lang, "order_complete_thanks") + "\n" + t(customer_lang, "cash_order_confirmed_customer", number=ticket_number)
        if order["branch_name"]:
            notice += "\n" + t(customer_lang, "pickup_reminder", branch=order["branch_name"])
        if result["earned_free_item"]:
            notice += "\n" + t(customer_lang, "free_coffee_ready")
        elif result["card_expired"]:
            notice += "\n" + t(customer_lang, "card_expired_notice")
        await finish_order_and_return_to_menu(callback.bot, order["user_id"], customer_lang, notice)
    except Exception:
        pass  # customer may have blocked the bot

    await callback.answer()




@router.message(Command("buybundle"))
async def buy_bundle(message: Message):
    lang = lang_of(message.from_user.id)
    price = db.get_setting("bundle_price")
    credits = db.get_setting("bundle_credits_amount")
    if not price or not credits:
        await message.answer(t(lang, "bundle_not_configured"))
        return
    price, credits = int(price), int(credits)

    provider_token = PROVIDER_TOKENS.get("click") or PROVIDER_TOKENS.get("payme")
    if not provider_token:
        await message.answer(t(lang, "payment_error"))
        return

    payload = f"bundle_{message.from_user.id}_{int(time.time())}"
    await message.bot.send_invoice(
        chat_id=message.from_user.id,
        title=t(lang, "bundle_invoice_title"),
        description=t(lang, "bundle_invoice_description", credits=credits),
        payload=payload,
        provider_token=provider_token,
        currency="UZS",
        prices=[LabeledPrice(label=t(lang, "total"), amount=price * 100)],
    )


async def handle_bundle_purchase_payment(message: Message):
    lang = lang_of(message.from_user.id)
    credits = int(db.get_setting("bundle_credits_amount", "0"))
    db.add_bundle_credits(message.from_user.id, credits)
    total_now = db.get_bundle_credits(message.from_user.id)
    await message.answer(
        t(lang, "bundle_purchased", credits=credits, total=total_now),
        reply_markup=main_menu_keyboard(lang),
    )


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    # Telegram requires an answer within 10 seconds or the payment fails on
    # the customer's side. The order (or bundle purchase) was already created
    # when the invoice was sent, so there's nothing further to validate here.
    payload = pre_checkout_query.invoice_payload
    if payload.startswith("bundle_"):
        await pre_checkout_query.answer(ok=True)
        return
    order = db.get_order(payload)
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

    if order_id.startswith("bundle_"):
        await handle_bundle_purchase_payment(message)
        return

    db.set_order_gateway_ref(order_id, payment.telegram_payment_charge_id)
    db.mark_order_paid(order_id)
    today_str = db.now_utc().strftime("%Y-%m-%d")
    ticket_number = db.assign_order_number(order_id, today_str)
    result = db.add_stamp(message.from_user.id)
    await apply_referral_bonus_if_applicable(message.bot, message.from_user.id)
    CART[message.from_user.id] = []

    order = db.get_order(order_id)
    reply = t(lang, "order_complete_thanks") + "\n" + t(lang, "payment_success", number=ticket_number)
    if order and order["branch_name"]:
        reply += "\n" + t(lang, "pickup_reminder", branch=order["branch_name"])
    if result["card_expired"]:
        reply += "\n" + t(lang, "card_expired_notice")
    if result["earned_free_item"]:
        reply += "\n" + t(lang, "free_coffee_ready")
    await finish_order_and_return_to_menu(message.bot, message.from_user.id, lang, reply)

    # Staff notification — without this, nobody at the shop knows an order came in.
    notify_chat_id = STAFF_GROUP_ID or OWNER_ID
    if notify_chat_id and order:
        customer_label = order_customer_label(order)
        staff_text = build_staff_order_text(order, ticket_number, customer_label)
        try:
            staff_kb = InlineKeyboardBuilder()
            staff_kb.button(text="✅ Confirm order", callback_data=f"claim:{order_id}")
            await message.bot.send_message(notify_chat_id, staff_text, reply_markup=staff_kb.as_markup())
        except Exception as e:
            print(f"[staff-notify] FAILED to send to chat_id={notify_chat_id}: {e}")


def order_customer_label(order: dict) -> str:
    username = db.get_username(order["user_id"])
    return f"@{username}" if username else f"ID {order['user_id']}"


async def apply_referral_bonus_if_applicable(bot, customer_id: int):
    """Call this once per customer right after their order is confirmed paid —
    on a NEW referred customer's first completed order, both people get a
    bonus stamp. Safe to call every time; it's a no-op once already rewarded."""
    referrer_id = db.get_unrewarded_referral(customer_id)
    if not referrer_id:
        return
    db.mark_referral_rewarded(customer_id)
    db.add_stamp(referrer_id)
    db.add_stamp(customer_id)
    try:
        referrer_lang = lang_of(referrer_id)
        await bot.send_message(referrer_id, t(referrer_lang, "referral_bonus_notice"))
    except Exception:
        pass
    try:
        customer_lang = lang_of(customer_id)
        await bot.send_message(customer_id, t(customer_lang, "referral_bonus_notice"))
    except Exception:
        pass


def build_staff_order_text(order: dict, ticket_number: int, customer_label: str, status_line: str = None) -> str:
    divider = "──────────────"
    items = order["items_summary"] or "—"
    lines = [
        f"🧾 ORDER #{ticket_number}",
        divider,
        items,
        divider,
        f"💰 {fmt_price(order['total'])} so'm  •  {order['payment_method'].title()}",
        f"👤 {customer_label}",
    ]
    if order["phone"]:
        lines.append(f"📞 {order['phone']}")
    if order.get("delivery_address"):
        lines.append(f"🚚 {order['delivery_address']}")
    elif order["branch_name"]:
        lines.append(f"📍 {order['branch_name']}")
    if order.get("pickup_time"):
        lines.append(f"🕐 {order['pickup_time']}")
    if order["notes"]:
        lines.append(f"📝 {order['notes']}")
    if status_line:
        lines.append(divider)
        lines.append(status_line)
    return "\n".join(lines)


def is_order_staff(chat_id: int) -> bool:
    """Authorization for order-floor actions (confirm/ready/cash stamps).
    Once a staff group is configured, THIS IS THE ONLY PLACE these work —
    not the owner's personal chat — so customer and staff activity never mix
    in the same conversation. Falls back to the owner's DM only if no staff
    group has been set up yet (e.g. still in initial setup)."""
    if STAFF_GROUP_ID:
        return chat_id == STAFF_GROUP_ID
    return chat_id == OWNER_ID


def is_staff(callback: CallbackQuery) -> bool:
    return is_order_staff(callback.message.chat.id)


def is_staff_message(message: Message) -> bool:
    return is_order_staff(message.chat.id)


@router.message(Command("queue"))
async def queue_command(message: Message):
    """Lists every unclaimed/in-progress order in one place, so staff don't have
    to scroll back through the group chat to see what's still open."""
    if not is_staff_message(message):
        return
    lang = lang_of(message.from_user.id)
    open_orders = db.get_open_orders()
    if not open_orders:
        await message.answer(t(lang, "queue_empty"))
        return

    lines = [t(lang, "queue_header")]
    for o in open_orders:
        icon = "🔵" if o["prep_status"] == "preparing" else "🟡"
        claimed = f" ({o['claimed_by_name']})" if o["claimed_by_name"] else ""
        branch = f" · {o['branch_name']}" if o["branch_name"] else ""
        pickup = f" · {o['pickup_time']}" if o["pickup_time"] else ""
        lines.append(
            f"{icon} #{o['order_number']}{claimed}{branch}{pickup}\n{o['items_summary'] or '—'}"
        )
    await message.answer("\n\n".join(lines))


# ---------- staff stock toggle — lets anyone in the staff group mark an item
# in/out of stock without going through owner-only /admin ----------

async def render_stock_list(callback: CallbackQuery, category_id: int):
    lang = lang_of(callback.from_user.id)
    items = menu_store.list_items(category_id)
    kb = InlineKeyboardBuilder()
    for item in items:
        name = item["name"].get(lang, item["name"]["en"])
        icon = "✅" if item["in_stock"] else "🚫"
        kb.button(text=f"{icon} {name}", callback_data=f"stocktoggle:{item['id']}:{category_id}")
    kb.adjust(1)
    kb.button(text=t(lang, "back_button"), callback_data="stockback")
    kb.adjust(*([1] * len(items)), 1)
    await callback.message.edit_text(t(lang, "stock_tap_to_toggle"), reply_markup=kb.as_markup())


@router.message(Command("stock"))
async def stock_command(message: Message):
    if not is_staff_message(message):
        return
    lang = lang_of(message.from_user.id)
    categories = menu_store.list_categories()
    if not categories:
        await message.answer(t(lang, "menu_currently_empty"))
        return
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(text=cat["name"].get(lang, cat["name"]["en"]), callback_data=f"stockcat:{cat['id']}")
    kb.adjust(2)
    await message.answer(t(lang, "stock_choose_category"), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("stockcat:"))
async def stock_category_chosen(callback: CallbackQuery):
    if not is_staff(callback):
        await callback.answer()
        return
    category_id = int(callback.data.split(":")[1])
    await render_stock_list(callback, category_id)
    await callback.answer()


@router.callback_query(F.data.startswith("stocktoggle:"))
async def stock_item_toggled(callback: CallbackQuery):
    if not is_staff(callback):
        await callback.answer()
        return
    _, item_id_str, category_id_str = callback.data.split(":")
    menu_store.toggle_item_stock(int(item_id_str))
    await render_stock_list(callback, int(category_id_str))
    await callback.answer(t(lang_of(callback.from_user.id), "stock_updated"))


@router.callback_query(F.data == "stockback")
async def stock_back(callback: CallbackQuery):
    if not is_staff(callback):
        await callback.answer()
        return
    lang = lang_of(callback.from_user.id)
    categories = menu_store.list_categories()
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(text=cat["name"].get(lang, cat["name"]["en"]), callback_data=f"stockcat:{cat['id']}")
    kb.adjust(2)
    await callback.message.edit_text(t(lang, "stock_choose_category"), reply_markup=kb.as_markup())
    await callback.answer()


@router.message(Command("testgroup"))
async def test_group_notification(message: Message):
    """Owner-only diagnostic — sends a test message to wherever order notifications
    are configured to go, and reports exactly what happened. Use this instead of
    placing a real order when checking if the staff group connection works."""
    if message.from_user.id != OWNER_ID:
        return
    notify_chat_id = STAFF_GROUP_ID or OWNER_ID
    target = f"STAFF_GROUP_ID ({STAFF_GROUP_ID})" if STAFF_GROUP_ID else f"your DM (no STAFF_GROUP_ID set, OWNER_TELEGRAM_ID={OWNER_ID})"
    try:
        await message.bot.send_message(notify_chat_id, "🧪 Test message — if you see this in the right place, the connection works.")
        await message.answer(f"✅ Sent successfully to: {target}")
    except Exception as e:
        await message.answer(f"❌ Failed to send to: {target}\n\nError: {e}")


async def record_cash_payment(bot, customer_id: int, amount: int, description: str, staff_reply_send, staff_lang: str):
    """Shared by /cash and the button-based flow — records the sale, adds the
    stamp, replies to staff, and quietly notifies the customer."""
    order_id = f"cash_{customer_id}_{int(time.time())}"
    db.create_order(order_id, customer_id, amount, "cash", items_summary=description)
    db.mark_order_paid(order_id)
    today_str = db.now_utc().strftime("%Y-%m-%d")
    ticket_number = db.assign_order_number(order_id, today_str)
    result = db.add_stamp(customer_id)

    reply = t(staff_lang, "cash_recorded", number=ticket_number, amount=fmt_price(amount))
    if result["earned_free_item"]:
        reply += "\n" + t(staff_lang, "cash_customer_earned_free")
    elif result["card_expired"]:
        reply += "\n" + t(staff_lang, "cash_customer_card_restarted")
    else:
        reply += "\n" + t(staff_lang, "cash_customer_stamps", stamps=result["stamps"], total=db.STAMPS_FOR_FREE_ITEM)
    await staff_reply_send(reply)

    try:
        customer_lang = lang_of(customer_id)
        notice = t(customer_lang, "cash_stamp_notice_customer")
        if result["earned_free_item"]:
            notice += "\n" + t(customer_lang, "free_coffee_ready")
        await bot.send_message(customer_id, notice)
    except Exception:
        pass  # customer may never have started the bot themselves — the stamp is still recorded


@router.message(Command("cash"))
async def cash_order(message: Message):
    lang = lang_of(message.from_user.id)
    if not is_staff_message(message):
        await message.answer(t(lang, "not_authorized"))
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(t(lang, "cash_usage"))
        return

    identifier = parts[1]
    if identifier.startswith("@"):
        customer_id = db.get_user_id_by_username(identifier)
        if customer_id is None:
            await message.answer(t(lang, "cash_username_not_found", username=identifier))
            return
    else:
        try:
            customer_id = int(identifier)
        except ValueError:
            await message.answer(t(lang, "cash_usage"))
            return

    try:
        amount = int(parts[2].replace(" ", "").replace(",", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer(t(lang, "cash_usage"))
        return

    description = parts[3] if len(parts) > 3 else t(lang, "cash_order_default_desc")
    await record_cash_payment(message.bot, customer_id, amount, description, message.answer, lang)


@router.callback_query(F.data.startswith("claim:"))
async def claim_order(callback: CallbackQuery):
    if not is_staff(callback):
        await callback.answer()
        return
    order_id = callback.data.split(":", 1)[1]
    staff_name = callback.from_user.full_name

    if not db.claim_order(order_id, staff_name):
        await callback.answer(t(lang_of(callback.from_user.id), "order_already_claimed"), show_alert=True)
        return

    order = db.get_order(order_id)
    customer_label = order_customer_label(order)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Mark ready", callback_data=f"markready:{order_id}")
    await callback.message.edit_text(
        build_staff_order_text(order, order["order_number"], customer_label, status_line=f"☑️ Confirmed — {staff_name}"),
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("markready:"))
async def mark_order_ready(callback: CallbackQuery):
    if not is_staff(callback):
        await callback.answer()
        return
    order_id = callback.data.split(":", 1)[1]
    order = db.get_order(order_id)
    if not order or order["status_notified_ready"]:
        await callback.answer()
        return

    db.mark_order_ready_notified(order_id)
    db.mark_order_prep_ready(order_id)
    customer_lang = lang_of(order["user_id"])
    try:
        rating_kb = InlineKeyboardBuilder()
        for stars in range(1, 6):
            rating_kb.button(text="⭐" * stars, callback_data=f"rate:{order_id}:{stars}")
        rating_kb.adjust(5)
        await callback.bot.send_message(order["user_id"], t(customer_lang, "order_ready_notice"))
        await callback.bot.send_message(order["user_id"], t(customer_lang, "rate_order_prompt"), reply_markup=rating_kb.as_markup())
    except Exception:
        pass  # customer may have blocked the bot

    staff_name = order["claimed_by_name"] or callback.from_user.full_name
    customer_label = order_customer_label(order)
    await callback.message.edit_text(
        build_staff_order_text(order, order["order_number"], customer_label, status_line=f"✅ Ready — {staff_name}")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rate:"))
async def rate_order(callback: CallbackQuery):
    lang = lang_of(callback.from_user.id)
    _, order_id, stars = callback.data.split(":")
    order = db.get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer()
        return
    db.save_order_rating(order_id, int(stars))
    await callback.message.edit_text(t(lang, "rating_thanks", stars="⭐" * int(stars)))
    # this was the dead end customers were getting stuck at — nothing told them
    # how to start another order, so close the loop explicitly right here
    await callback.message.answer(t(lang, "ready_for_next_order"), reply_markup=persistent_keyboard(lang))
    await callback.answer()




# ---------- loyalty ----------

@router.message(Command("birthday"))
async def set_birthday(message: Message):
    lang = lang_of(message.from_user.id)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(t(lang, "birthday_usage"))
        return
    raw = parts[1].strip().replace(".", "-").replace("/", "-")
    segments = raw.split("-")
    if len(segments) != 2:
        await message.answer(t(lang, "birthday_invalid"))
        return
    try:
        # accept either DD-MM or MM-DD by checking which segment can be a valid month
        a, b = int(segments[0]), int(segments[1])
        if 1 <= a <= 12 and not (1 <= b <= 12 and b <= 12 < a):
            month, day = a, b
        else:
            month, day = b, a
        if not (1 <= month <= 12 and 1 <= day <= 31):
            raise ValueError
        month_day = f"{month:02d}-{day:02d}"
    except ValueError:
        await message.answer(t(lang, "birthday_invalid"))
        return
    db.save_birthday(message.from_user.id, month_day)
    await message.answer(t(lang, "birthday_saved"))


@router.message(Command("myorders"))
async def my_orders_command(message: Message):
    lang = lang_of(message.from_user.id)
    orders = db.get_recent_orders(message.from_user.id, limit=5)
    if not orders:
        await message.answer(t(lang, "no_past_orders"))
        return

    await message.answer(t(lang, "past_orders_header"))
    for o in orders:
        date = o["created_at"][:10]
        block = f"{date} — {fmt_price(o['total'])} so'm\n{o['items_summary'] or '—'}"
        if o["branch_name"]:
            block += f"\n📍 {o['branch_name']}"
        kb = None
        if o["items_json"]:
            kb = InlineKeyboardBuilder()
            kb.button(text=t(lang, "order_again_button"), callback_data=f"reorder:{o['order_id']}")
            kb = kb.as_markup()
        await message.answer(block, reply_markup=kb)


@router.callback_query(F.data.startswith("reorder:"))
async def reorder(callback: CallbackQuery):
    lang = lang_of(callback.from_user.id)
    order_id = callback.data.split(":", 1)[1]
    order = db.get_order(order_id)
    if not order or not order["items_json"]:
        await callback.answer(t(lang, "payment_error"), show_alert=True)
        return

    items = json.loads(order["items_json"])
    for entry in items:
        entry.setdefault("qty", 1)
    cart = CART.setdefault(callback.from_user.id, [])
    cart.extend(items)
    await callback.answer(t(lang, "items_added_to_cart"), show_alert=False)
    await show_cart_editable(callback)


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
    username = db.get_username(user_id)
    code_line = t(lang, "loyalty_code_line", code=f"@{username}" if username else user_id)

    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "pay_cash_button"), callback_data="cashrequest")
    markup = kb.as_markup()

    if not status:
        await send(t(lang, "stamps_header") + "\n" + t(lang, "stamps_none_yet") + "\n\n" + code_line, reply_markup=markup)
        return

    if status["free_coffee_pending"]:
        await send(t(lang, "stamps_header") + "\n" + t(lang, "free_coffee_ready") + "\n\n" + code_line, reply_markup=markup)
        return

    stamps = status["stamps"]
    card = "☕" * stamps + "⬜" * (db.STAMPS_FOR_FREE_ITEM - stamps)
    text = t(lang, "stamps_header") + "\n" + t(lang, "stamps_progress", card=card, stamps=stamps, total=db.STAMPS_FOR_FREE_ITEM)
    if status["first_stamp_at"]:
        expires = datetime.fromisoformat(status["first_stamp_at"]) + timedelta(days=db.CARD_VALID_DAYS)
        text += t(lang, "stamps_valid_until", date=expires.strftime("%d.%m.%Y"))
    text += "\n\n" + code_line
    await send(text, reply_markup=markup)


@router.callback_query(F.data == "cashrequest")
async def cash_request(callback: CallbackQuery):
    lang = lang_of(callback.from_user.id)
    notify_chat_id = STAFF_GROUP_ID or OWNER_ID
    if not notify_chat_id:
        await callback.answer()
        return

    customer_label = order_customer_label({"user_id": callback.from_user.id})
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "cash_enter_amount_button"), callback_data=f"cashamount:{callback.from_user.id}")
    try:
        await callback.bot.send_message(
            notify_chat_id,
            t(lang, "cash_request_staff_text", customer=customer_label),
            reply_markup=kb.as_markup(),
        )
        await callback.answer(t(lang, "cash_request_sent_customer"))
    except Exception as e:
        print(f"[cash-request] FAILED to notify chat_id={notify_chat_id}: {e}")
        await callback.answer(t(lang, "payment_error"), show_alert=True)


class CashFlow(StatesGroup):
    awaiting_amount = State()


@router.callback_query(F.data.startswith("cashamount:"))
async def cash_amount_start(callback: CallbackQuery, state: FSMContext):
    if not is_staff(callback):
        await callback.answer()
        return
    lang = lang_of(callback.from_user.id)
    customer_id = int(callback.data.split(":", 1)[1])
    await state.set_data({"customer_id": customer_id})
    await state.set_state(CashFlow.awaiting_amount)
    await callback.message.answer(t(lang, "cash_send_amount_prompt"))
    await callback.answer()


@router.message(CashFlow.awaiting_amount)
async def cash_amount_received(message: Message, state: FSMContext):
    lang = lang_of(message.from_user.id)
    if not is_staff_message(message):
        return  # neutral state — don't let a random group message misfire this

    parts = (message.text or "").split(maxsplit=1)
    try:
        amount = int(parts[0].replace(" ", "").replace(",", ""))
        if amount <= 0:
            raise ValueError
    except (ValueError, IndexError):
        await message.answer(t(lang, "cash_invalid_amount"))
        return  # stay in the same state so they can just retype it

    description = parts[1] if len(parts) > 1 else t(lang, "cash_order_default_desc")
    data = await state.get_data()
    await state.clear()
    await record_cash_payment(message.bot, data["customer_id"], amount, description, message.answer, lang)


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
