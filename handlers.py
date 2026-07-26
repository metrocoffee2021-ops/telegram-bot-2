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


def add_nav_row(kb: InlineKeyboardBuilder, lang: str, back_callback: str):
    kb.button(text=t(lang, "back_button"), callback_data=back_callback)
    kb.button(text=t(lang, "menu_button"), callback_data="menu")


def main_menu_keyboard(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "menu_button"), callback_data="menu")
    kb.button(text=t(lang, "stamps_button"), callback_data="stamps")
    kb.adjust(2)
    return kb.as_markup()


# ---------- language ----------

@router.message(CommandStart())
async def start(message: Message):
    db.save_username(message.from_user.id, message.from_user.username)
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
    db.save_username(callback.from_user.id, callback.from_user.username)
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
        if item["in_stock"]:
            kb.button(text=f"{name} — {price_range_text(item)}", callback_data=f"item:{item['id']}")
        else:
            kb.button(text=f"❌ {name} — {t(lang, 'out_of_stock')}", callback_data="outofstock")
    kb.button(text=t(lang, "back_button"), callback_data="menu")
    kb.adjust(*([1] * len(items)), 1)
    header = category["name"].get(lang, category["name"]["en"]) if category else ""
    await callback.message.answer(header, reply_markup=kb.as_markup())
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
        add_nav_row(kb, lang, back_callback=f"item:{item_id}")
        kb.adjust(2, 2)
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
        add_nav_row(kb, lang, back_callback=f"temp:{item_id}:{temp}")
        kb.adjust(1, 1, 2)
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
    kb.button(text=t(lang, "cart_button"), callback_data="cart")
    kb.adjust(2)
    await callback.message.answer(t(lang, "added_to_cart", item=name), reply_markup=kb.as_markup())


# in-memory cart per user — cleared after a successful checkout. Lost if the bot restarts
# mid-order, which is an acceptable tradeoff for a small shop (customer just re-adds items).
CART: dict[int, list[dict]] = {}


def cart_total(user_id: int) -> int:
    return sum(entry["price"] for entry in CART.get(user_id, []))


def cart_lines(cart: list[dict]) -> list[str]:
    lines = []
    for entry in cart:
        parts = [entry["name"]]
        if entry["size"]:
            parts.append(entry["size"])
        if entry["topping"]:
            parts.append("+ boba")
        lines.append("• " + " ".join(parts))
    return lines


# ---------- cart viewing & editing ----------

@router.message(Command("cart"))
async def cart_command(message: Message):
    await show_cart_editable(message.from_user.id, message.answer)


@router.callback_query(F.data == "cart")
async def cart_callback(callback: CallbackQuery):
    await show_cart_editable(callback.from_user.id, callback.message.answer)
    await callback.answer()


async def show_cart_editable(user_id: int, send):
    lang = lang_of(user_id)
    cart = CART.get(user_id, [])
    if not cart:
        await send(t(lang, "cart_empty"))
        return

    text = t(lang, "your_order") + "\n" + "\n".join(cart_lines(cart)) + f"\n\n{t(lang, 'total')}: {fmt_price(cart_total(user_id))} so'm"

    kb = InlineKeyboardBuilder()
    for i, entry in enumerate(cart):
        label = entry["name"] + (f" {entry['size']}" if entry["size"] else "")
        kb.button(text=f"🗑 {label}", callback_data=f"cartdel:{i}")
    kb.button(text=t(lang, "checkout_button"), callback_data="checkout")
    kb.button(text=t(lang, "clear_cart_button"), callback_data="clearcart")
    kb.button(text=t(lang, "menu_button"), callback_data="menu")
    kb.adjust(*([1] * len(cart)), 1, 1, 1)

    await send(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("cartdel:"))
async def cart_delete_item(callback: CallbackQuery):
    index = int(callback.data.split(":")[1])
    cart = CART.get(callback.from_user.id, [])
    if 0 <= index < len(cart):
        cart.pop(index)
    await show_cart_editable(callback.from_user.id, callback.message.answer)
    await callback.answer()


@router.callback_query(F.data == "clearcart")
async def cart_clear(callback: CallbackQuery):
    lang = lang_of(callback.from_user.id)
    CART[callback.from_user.id] = []
    await callback.message.answer(t(lang, "cart_cleared"))
    await callback.answer()


# ---------- checkout & payment ----------

@router.callback_query(F.data == "checkout")
async def checkout_callback(callback: CallbackQuery, state: FSMContext):
    lang = lang_of(callback.from_user.id)
    if db.get_setting("ordering_paused") == "1":
        await callback.answer(t(lang, "ordering_paused_notice"), show_alert=True)
        return
    await show_cart(callback.from_user.id, callback.message.answer, offer_payment=True, state=state)
    await callback.answer()


async def show_cart(user_id: int, send, offer_payment: bool = False, state: FSMContext = None):
    lang = lang_of(user_id)
    cart = CART.get(user_id, [])
    if not cart:
        await send(t(lang, "cart_empty"))
        return

    total = cart_total(user_id)
    text = t(lang, "your_order") + "\n" + "\n".join(cart_lines(cart)) + f"\n\n{t(lang, 'total')}: {fmt_price(total)} so'm"

    if offer_payment and state is not None:
        await state.set_data({"order_total": total})
        await state.set_state(OrderFlow.awaiting_contact)
        contact_kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=t(lang, "share_contact_button"), request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await send(text)
        await send(t(lang, "share_contact_prompt"), reply_markup=contact_kb)
    else:
        await send(text)


@router.message(OrderFlow.awaiting_contact, F.contact)
async def contact_received(message: Message, state: FSMContext):
    lang = lang_of(message.from_user.id)
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(OrderFlow.awaiting_location)

    location_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "share_location_button"), request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(t(lang, "share_location_prompt"), reply_markup=location_kb)


@router.message(OrderFlow.awaiting_contact)
async def contact_not_shared(message: Message):
    lang = lang_of(message.from_user.id)
    contact_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "share_contact_button"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(t(lang, "share_contact_prompt"), reply_markup=contact_kb)


@router.message(OrderFlow.awaiting_location, F.location)
async def location_received(message: Message, state: FSMContext):
    lang = lang_of(message.from_user.id)
    branch = branches.nearest_branch(message.location.latitude, message.location.longitude)
    await state.update_data(branch_name=branch["name"])

    await message.answer(
        t(lang, "nearest_branch", branch=branch["name"], address=branch["address"]),
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(t(lang, "ask_notes"))
    await state.set_state(OrderFlow.awaiting_notes)


@router.message(OrderFlow.awaiting_notes)
async def notes_received(message: Message, state: FSMContext):
    lang = lang_of(message.from_user.id)
    text = (message.text or "").strip()
    if text and text.lower() not in {"skip", "o'tkazib yuborish", "пропустить", "-"}:
        await state.update_data(notes=text)

    kb = InlineKeyboardBuilder()
    kb.button(text="Click", callback_data="paymethod:click")
    kb.button(text="Payme", callback_data="paymethod:payme")
    kb.button(text=t(lang, "cash_payment_button"), callback_data="paymethod:cash")
    add_nav_row(kb, lang, back_callback="cart")
    kb.adjust(2, 1, 2)
    await message.answer(t(lang, "choose_payment_method"), reply_markup=kb.as_markup())
    await state.set_state(OrderFlow.choosing_payment_method)


@router.message(OrderFlow.awaiting_location)
async def location_not_shared(message: Message):
    lang = lang_of(message.from_user.id)
    location_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "share_location_button"), request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(t(lang, "share_location_prompt"), reply_markup=location_kb)


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
        await show_cart(callback.from_user.id, callback.message.answer, offer_payment=True, state=state)
        return

    order_id = f"order_{callback.from_user.id}_{int(time.time())}"
    cart_snapshot = CART.get(callback.from_user.id, [])
    items_summary = "; ".join(cart_lines(cart_snapshot))
    db.create_order(
        order_id, callback.from_user.id, total, method,
        phone=data.get("phone"), branch_name=data.get("branch_name"), items_summary=items_summary,
        items_json=json.dumps(cart_snapshot), notes=data.get("notes"),
    )
    await state.clear()

    if method == "cash":
        await handle_cash_checkout(callback, order_id, lang)
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

    await callback.message.answer(t(lang, "cash_order_placed_customer"))
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
        notice = t(customer_lang, "cash_order_confirmed_customer", number=ticket_number)
        if order["branch_name"]:
            notice += "\n" + t(customer_lang, "pickup_reminder", branch=order["branch_name"])
        if result["earned_free_item"]:
            notice += "\n" + t(customer_lang, "free_coffee_ready")
        elif result["card_expired"]:
            notice += "\n" + t(customer_lang, "card_expired_notice")
        await callback.bot.send_message(order["user_id"], notice)
    except Exception:
        pass  # customer may have blocked the bot

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
    today_str = db.now_utc().strftime("%Y-%m-%d")
    ticket_number = db.assign_order_number(order_id, today_str)
    result = db.add_stamp(message.from_user.id)
    CART[message.from_user.id] = []

    order = db.get_order(order_id)
    reply = t(lang, "payment_success", number=ticket_number)
    if order and order["branch_name"]:
        reply += "\n" + t(lang, "pickup_reminder", branch=order["branch_name"])
    if result["card_expired"]:
        reply += "\n" + t(lang, "card_expired_notice")
    if result["earned_free_item"]:
        reply += "\n" + t(lang, "free_coffee_ready")
    await message.answer(reply, reply_markup=main_menu_keyboard(lang))

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
    if order["branch_name"]:
        lines.append(f"📍 {order['branch_name']}")
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
        await callback.bot.send_message(order["user_id"], t(customer_lang, "order_ready_notice"))
    except Exception:
        pass  # customer may have blocked the bot

    staff_name = order["claimed_by_name"] or callback.from_user.full_name
    customer_label = order_customer_label(order)
    await callback.message.edit_text(
        build_staff_order_text(order, order["order_number"], customer_label, status_line=f"✅ Ready — {staff_name}")
    )
    await callback.answer()




# ---------- loyalty ----------

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
    cart = CART.setdefault(callback.from_user.id, [])
    cart.extend(items)
    await callback.answer(t(lang, "items_added_to_cart"), show_alert=False)
    await show_cart_editable(callback.from_user.id, callback.message.answer)


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
