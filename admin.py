# admin.py
# The /admin command — lets the shop owner add, rename, price, and remove
# drinks and sections entirely from inside Telegram. No code editing, ever.
# Only the Telegram account matching OWNER_TELEGRAM_ID (set in .env) can use this.

import os
import json
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

from texts import t
import menu_store
import db

router = Router()

OWNER_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))


class AdminFlow(StatesGroup):
    name_uz = State()
    name_ru = State()
    name_en = State()
    choosing_options = State()  # temp/size selection is button-only; no message handler here on purpose
    awaiting_price = State()
    editing_price = State()


def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID


def lang_of(user_id: int) -> str:
    return db.get_user_language(user_id)


TEMP_LABELS = {"issiq": "🔥", "sovuq": "❄️"}


def fmt_price(amount: int) -> str:
    return f"{amount:_}".replace("_", " ")


def variant_label(temp: str, size: str | None) -> str:
    return f"{TEMP_LABELS.get(temp, temp)} {size}" if size else TEMP_LABELS.get(temp, temp)


# ---------- entry point ----------

@router.message(Command("admin"))
async def admin_entry(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer(t(lang_of(message.from_user.id), "not_authorized"))
        return
    await state.clear()
    await show_categories(message.from_user.id, message.answer)


async def show_categories(user_id: int, send):
    lang = lang_of(user_id)
    categories = menu_store.list_categories()
    kb = InlineKeyboardBuilder()
    for cat in categories:
        name = cat["name"].get(lang, cat["name"]["en"])
        item_count = menu_store.category_item_count(cat["id"])
        kb.button(text=f"{name} ({item_count})", callback_data=f"admcat:{cat['id']}")
    kb.button(text=t(lang, "admin_add_category_button"), callback_data="admaddcat")
    kb.adjust(1)
    header = t(lang, "admin_categories_header") if categories else t(lang, "admin_no_categories")
    await send(header, reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin_categories")
async def back_to_categories(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    await state.clear()
    await show_categories(callback.from_user.id, callback.message.answer)
    await callback.answer()


# ---------- add / rename category ----------

@router.callback_query(F.data == "admaddcat")
async def add_category_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    lang = lang_of(callback.from_user.id)
    await state.set_data({"mode": "new_category"})
    await state.set_state(AdminFlow.name_uz)
    await callback.message.answer(t(lang, "admin_send_name_uz"))
    await callback.answer()


@router.callback_query(F.data.startswith("admrenamecat:"))
async def rename_category_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    await state.set_data({"mode": "rename_category", "category_id": cat_id})
    await state.set_state(AdminFlow.name_uz)
    await callback.message.answer(t(lang, "admin_send_name_uz"))
    await callback.answer()


@router.message(AdminFlow.name_uz)
async def got_name_uz(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    if not message.text:
        return
    lang = lang_of(message.from_user.id)
    await state.update_data(name_uz=message.text.strip())
    await state.set_state(AdminFlow.name_ru)
    await message.answer(t(lang, "admin_send_name_ru"))


@router.message(AdminFlow.name_ru)
async def got_name_ru(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    if not message.text:
        return
    lang = lang_of(message.from_user.id)
    await state.update_data(name_ru=message.text.strip())
    await state.set_state(AdminFlow.name_en)
    await message.answer(t(lang, "admin_send_name_en"))


@router.message(AdminFlow.name_en)
async def got_name_en(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    if not message.text:
        return
    lang = lang_of(message.from_user.id)
    data = await state.get_data()
    name_uz, name_ru, name_en = data["name_uz"], data["name_ru"], message.text.strip()
    mode = data["mode"]

    if mode == "new_category":
        menu_store.add_category(name_uz, name_ru, name_en)
        await state.clear()
        await message.answer(t(lang, "admin_category_added"))
        await show_categories(message.from_user.id, message.answer)

    elif mode == "rename_category":
        menu_store.update_category_names(data["category_id"], name_uz, name_ru, name_en)
        await state.clear()
        await message.answer(t(lang, "admin_category_updated"))
        await show_category(message.from_user.id, data["category_id"], message.answer)

    elif mode == "new_item":
        item_id = menu_store.add_item(data["category_id"], name_uz, name_ru, name_en, has_topping_option=False)
        await state.update_data(item_id=item_id, name_uz=None, name_ru=None)
        await state.set_state(AdminFlow.choosing_options)
        await ask_temp_option(message.from_user.id, item_id, message.answer)

    elif mode == "rename_item":
        menu_store.update_item_names(data["item_id"], name_uz, name_ru, name_en)
        await state.clear()
        await message.answer(t(lang, "admin_item_updated"))
        await show_item(message.from_user.id, data["item_id"], message.answer)


# ---------- category detail ----------

@router.callback_query(F.data.startswith("admcat:"))
async def category_detail(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[1])
    await state.clear()
    await show_category(callback.from_user.id, cat_id, callback.message.answer)
    await callback.answer()


async def show_category(user_id: int, cat_id: int, send):
    lang = lang_of(user_id)
    category = menu_store.get_category(cat_id)
    items = menu_store.list_items(cat_id)

    kb = InlineKeyboardBuilder()
    for item in items:
        name = item["name"].get(lang, item["name"]["en"])
        kb.button(text=name, callback_data=f"admitem:{item['id']}")
    kb.button(text=t(lang, "admin_add_item_button"), callback_data=f"admadditem:{cat_id}")
    kb.button(text=t(lang, "admin_rename_button"), callback_data=f"admrenamecat:{cat_id}")
    kb.button(text=t(lang, "admin_delete_category_button"), callback_data=f"admdelcat:{cat_id}")
    kb.button(text=t(lang, "admin_back_button"), callback_data="admin_categories")
    kb.adjust(*([1] * len(items)), 1, 1, 1, 1)

    header = category["name"].get(lang, category["name"]["en"]) if category else ""
    body = header if items else header + "\n" + t(lang, "admin_no_items")
    await send(body, reply_markup=kb.as_markup())


# ---------- delete category ----------

@router.callback_query(F.data.startswith("admdelcat:"))
async def delete_category_confirm(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)

    if menu_store.category_item_count(cat_id) > 0:
        await callback.answer(t(lang, "admin_cant_delete_category_has_items"), show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "admin_yes_delete_button"), callback_data=f"admdelcat_go:{cat_id}")
    kb.button(text=t(lang, "admin_cancel_button"), callback_data=f"admcat:{cat_id}")
    kb.adjust(2)
    await callback.message.answer(t(lang, "admin_confirm_delete_category"), reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("admdelcat_go:"))
async def delete_category_go(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    menu_store.delete_category(cat_id)
    await callback.message.answer(t(lang, "admin_category_deleted"))
    await show_categories(callback.from_user.id, callback.message.answer)
    await callback.answer()


# ---------- add / rename item ----------

@router.callback_query(F.data.startswith("admadditem:"))
async def add_item_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    cat_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    await state.set_data({"mode": "new_item", "category_id": cat_id})
    await state.set_state(AdminFlow.name_uz)
    await callback.message.answer(t(lang, "admin_send_name_uz"))
    await callback.answer()


@router.callback_query(F.data.startswith("admrenameitem:"))
async def rename_item_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    item_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    await state.set_data({"mode": "rename_item", "item_id": item_id})
    await state.set_state(AdminFlow.name_uz)
    await callback.message.answer(t(lang, "admin_send_name_uz"))
    await callback.answer()


# ---------- temp / size / price flow (used for both new items and adding an option) ----------

async def ask_temp_option(user_id: int, item_id: int, send):
    lang = lang_of(user_id)
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "admin_temp_hot_only"), callback_data=f"admtemp:{item_id}:hot")
    kb.button(text=t(lang, "admin_temp_sovuq_only"), callback_data=f"admtemp:{item_id}:iced")
    kb.button(text=t(lang, "admin_temp_both"), callback_data=f"admtemp:{item_id}:both")
    kb.adjust(1)
    await send(t(lang, "admin_choose_temp_option"), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("admaddoption:"))
async def add_option_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    item_id = int(callback.data.split(":")[1])
    await state.set_data({"mode": "add_option", "item_id": item_id})
    await state.set_state(AdminFlow.choosing_options)
    await ask_temp_option(callback.from_user.id, item_id, callback.message.answer)
    await callback.answer()


@router.callback_query(F.data.startswith("admtemp:"))
async def temp_chosen(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    _, item_id, choice = callback.data.split(":")
    item_id = int(item_id)
    lang = lang_of(callback.from_user.id)

    temps = {"hot": ["issiq"], "iced": ["sovuq"], "both": ["issiq", "sovuq"]}[choice]
    data = await state.get_data()
    await state.update_data(item_id=item_id, temps_pending=temps, mode=data.get("mode", "new_item"))

    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "admin_size_single"), callback_data="admsize:single")
    kb.button(text=t(lang, "admin_size_two"), callback_data="admsize:two")
    kb.adjust(1)
    await callback.message.answer(t(lang, "admin_choose_size_option"), reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("admsize:"))
async def size_chosen(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    choice = callback.data.split(":")[1]
    data = await state.get_data()
    temps = data["temps_pending"]

    queue = []
    for temp in temps:
        if choice == "single":
            queue.append((temp, None))
        else:
            queue.append((temp, "M"))
            queue.append((temp, "L"))

    await state.update_data(price_queue=queue)
    await state.set_state(AdminFlow.awaiting_price)
    await ask_next_price(callback.from_user.id, state, callback.message.answer)
    await callback.answer()


async def ask_next_price(user_id: int, state: FSMContext, send):
    lang = lang_of(user_id)
    data = await state.get_data()
    queue = data["price_queue"]
    temp, size = queue[0]
    await send(t(lang, "admin_send_price_for", label=variant_label(temp, size)))


def parse_price(text: str | None) -> int | None:
    if not text:
        return None
    cleaned = text.strip().replace(" ", "").replace(",", "").replace("so'm", "").replace("сум", "")
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if value > 0 else None


@router.message(AdminFlow.awaiting_price)
async def got_price(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    lang = lang_of(message.from_user.id)
    price = parse_price(message.text)
    if price is None:
        await message.answer(t(lang, "admin_invalid_price"))
        return

    data = await state.get_data()
    queue = data["price_queue"]
    temp, size = queue.pop(0)
    menu_store.add_variant(data["item_id"], temp, size, price)

    if queue:
        await state.update_data(price_queue=queue)
        await ask_next_price(message.from_user.id, state, message.answer)
    else:
        item_id = data["item_id"]
        mode = data.get("mode", "new_item")
        await state.clear()
        if mode == "new_item":
            await message.answer(t(lang, "admin_item_added"))
        await show_item(message.from_user.id, item_id, message.answer)


# ---------- item detail ----------

@router.callback_query(F.data.startswith("admitem:"))
async def item_detail(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    item_id = int(callback.data.split(":")[1])
    await state.clear()
    await show_item(callback.from_user.id, item_id, callback.message.answer)
    await callback.answer()


async def show_item(user_id: int, item_id: int, send):
    lang = lang_of(user_id)
    item = menu_store.get_item(item_id)
    if not item:
        return

    name = item["name"].get(lang, item["name"]["en"])
    topping_state = t(lang, "admin_topping_on") if item["has_topping_option"] else t(lang, "admin_topping_off")
    stock_state = t(lang, "admin_stock_in") if item["in_stock"] else t(lang, "admin_stock_out")
    header = (
        f"{t(lang, 'admin_item_header')} {name}\n\n"
        f"{t(lang, 'admin_topping_label')} {topping_state}\n"
        f"{t(lang, 'admin_stock_label')} {stock_state}"
    )

    kb = InlineKeyboardBuilder()
    for v in item["variants"]:
        label = f"✏️ {variant_label(v['temp'], v['size'])} — {fmt_price(v['price'])} so'm"
        kb.button(text=label, callback_data=f"admeditprice:{v['id']}")
    kb.button(text=t(lang, "admin_rename_button"), callback_data=f"admrenameitem:{item_id}")
    kb.button(text=t(lang, "admin_add_option_button"), callback_data=f"admaddoption:{item_id}")
    trailing_rows = 6
    if item["variants"]:
        kb.button(text=t(lang, "admin_remove_option_button"), callback_data=f"admremoveopt:{item_id}")
        trailing_rows += 1
    kb.button(text=t(lang, "admin_toggle_topping_button"), callback_data=f"admtoggletop:{item_id}")
    kb.button(text=t(lang, "admin_toggle_stock_button"), callback_data=f"admtogglestock:{item_id}")
    kb.button(text=t(lang, "admin_delete_item_button"), callback_data=f"admdelitem:{item_id}")
    kb.button(text=t(lang, "admin_back_button"), callback_data=f"admcat:{item['category_id']}")
    kb.adjust(*([1] * len(item["variants"])), *([1] * trailing_rows))

    await send(header, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("admtogglestock:"))
async def toggle_stock(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    item_id = int(callback.data.split(":")[1])
    menu_store.toggle_item_stock(item_id)
    await show_item(callback.from_user.id, item_id, callback.message.answer)
    await callback.answer()


@router.callback_query(F.data.startswith("admeditprice:"))
async def edit_price_start(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        return
    variant_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    await state.set_data({"variant_id": variant_id})
    await state.set_state(AdminFlow.editing_price)
    await callback.message.answer(t(lang, "admin_send_new_price"))
    await callback.answer()


@router.message(AdminFlow.editing_price)
async def edit_price_got(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    lang = lang_of(message.from_user.id)
    price = parse_price(message.text)
    if price is None:
        await message.answer(t(lang, "admin_invalid_price"))
        return

    data = await state.get_data()
    variant = menu_store.get_variant(data["variant_id"])
    if not variant:
        await state.clear()
        return
    menu_store.update_variant_price(data["variant_id"], price)
    await state.clear()
    await message.answer(t(lang, "admin_price_updated"))
    await show_item(message.from_user.id, variant["item_id"], message.answer)


# ---------- edit / remove a specific price option ----------

@router.callback_query(F.data.startswith("admremoveopt:"))
async def remove_option_list(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    item_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    item = menu_store.get_item(item_id)

    kb = InlineKeyboardBuilder()
    for v in item["variants"]:
        label = f"🗑 {variant_label(v['temp'], v['size'])} — {fmt_price(v['price'])} so'm"
        kb.button(text=label, callback_data=f"admdelvar:{v['id']}:{item_id}")
    kb.button(text=t(lang, "admin_back_button"), callback_data=f"admitem:{item_id}")
    kb.adjust(1)
    await callback.message.answer(t(lang, "admin_choose_option_to_remove"), reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("admdelvar:"))
async def delete_variant_go(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    _, variant_id, item_id = callback.data.split(":")
    lang = lang_of(callback.from_user.id)
    menu_store.delete_variant(int(variant_id))
    await callback.message.answer(t(lang, "admin_option_deleted"))
    await show_item(callback.from_user.id, int(item_id), callback.message.answer)
    await callback.answer()


@router.callback_query(F.data.startswith("admtoggletop:"))
async def toggle_topping(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    item_id = int(callback.data.split(":")[1])
    menu_store.toggle_item_topping(item_id)
    await show_item(callback.from_user.id, item_id, callback.message.answer)
    await callback.answer()


# ---------- delete item ----------

@router.callback_query(F.data.startswith("admdelitem:"))
async def delete_item_confirm(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    item_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "admin_yes_delete_button"), callback_data=f"admdelitem_go:{item_id}")
    kb.button(text=t(lang, "admin_cancel_button"), callback_data=f"admitem:{item_id}")
    kb.adjust(2)
    await callback.message.answer(t(lang, "admin_confirm_delete_item"), reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("admdelitem_go:"))
async def delete_item_go(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    item_id = int(callback.data.split(":")[1])
    lang = lang_of(callback.from_user.id)
    item = menu_store.get_item(item_id)
    category_id = item["category_id"] if item else None
    menu_store.delete_item(item_id)
    await callback.message.answer(t(lang, "admin_item_deleted"))
    if category_id is not None:
        await show_category(callback.from_user.id, category_id, callback.message.answer)
    else:
        await show_categories(callback.from_user.id, callback.message.answer)
    await callback.answer()


# ---------- pause ordering ----------

@router.message(Command("pause"))
async def toggle_pause(message: Message):
    if not is_owner(message.from_user.id):
        return
    lang = lang_of(message.from_user.id)
    currently_paused = db.get_setting("ordering_paused") == "1"
    db.set_setting("ordering_paused", "0" if currently_paused else "1")
    key = "admin_ordering_resumed" if currently_paused else "admin_ordering_paused"
    await message.answer(t(lang, key))


# ---------- sales report ----------

def _aggregate(orders: list[dict]) -> tuple[int, int, dict]:
    total_revenue = sum(o["total"] for o in orders)
    item_counts: dict[str, int] = {}
    for o in orders:
        if not o["items_json"]:
            continue
        try:
            items = json.loads(o["items_json"])
        except (ValueError, TypeError):
            continue
        for entry in items:
            name = entry.get("name", "?")
            item_counts[name] = item_counts.get(name, 0) + 1
    return len(orders), total_revenue, item_counts


def _format_report(lang: str, label: str, count: int, revenue: int, item_counts: dict) -> str:
    from handlers import fmt_price  # reuse the same so'm formatting used everywhere else
    lines = [t(lang, "admin_report_header", label=label), f"{t(lang, 'admin_report_orders')}: {count}",
             f"{t(lang, 'admin_report_revenue')}: {fmt_price(revenue)} so'm"]
    if item_counts:
        top = sorted(item_counts.items(), key=lambda x: -x[1])[:5]
        lines.append(t(lang, "admin_report_top_items"))
        for name, qty in top:
            lines.append(f"  {name} — {qty}")
    return "\n".join(lines)


@router.message(Command("report"))
async def sales_report(message: Message):
    if not is_owner(message.from_user.id):
        return
    lang = lang_of(message.from_user.id)
    arg = message.text.removeprefix("/report").strip().lower()

    if arg == "week":
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        orders = db.get_orders_since(since)
        label = t(lang, "admin_report_week")
    else:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        orders = db.get_orders_on_date(today)
        label = t(lang, "admin_report_today")

    count, revenue, item_counts = _aggregate(orders)
    await message.answer(_format_report(lang, label, count, revenue, item_counts))
