from __future__ import annotations
import os
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
import db, metropia_v2 as v2

router=Router()
OWNER_ID=int(os.environ.get("OWNER_TELEGRAM_ID","0"))
STAFF_GROUP_ID=int(os.environ.get("STAFF_GROUP_ID","0"))

def owner(uid): return OWNER_ID and uid==OWNER_ID
def staff(message): return message.chat.id==(STAFF_GROUP_ID or OWNER_ID)
def money(n): return f"{int(n):,}".replace(","," ")

@router.message(Command("manager"))
async def manager(message: Message):
    if not owner(message.from_user.id): return
    s=v2.dashboard_stats(7)
    text=("<b>METROPIA MANAGER</b>\n\n"
          f"📦 Open orders: <b>{s['open_orders']}</b>\n"
          f"📈 7-day orders: <b>{s['orders']}</b>\n"
          f"💰 Revenue: <b>{money(s['revenue'])} so'm</b>\n"
          f"🧾 Average order: <b>{money(s['avg_order'])} so'm</b>\n"
          f"👥 Customers: <b>{s['customers']}</b>\n"
          f"⭐ Rating: <b>{s['avg_rating'] or '—'}</b>")
    kb=InlineKeyboardBuilder()
    kb.button(text="📊 Analytics",callback_data="mgr:analytics")
    kb.button(text="🏪 Branches",callback_data="mgr:branches")
    kb.button(text="🔥 Promotions",callback_data="mgr:promos")
    kb.button(text="📦 Open orders",callback_data="mgr:orders")
    kb.adjust(2)
    await message.answer(text,reply_markup=kb.as_markup(),parse_mode="HTML")

@router.callback_query(F.data=="mgr:analytics")
async def analytics(c:CallbackQuery):
    if not owner(c.from_user.id): return
    s=v2.dashboard_stats(30); tops=v2.top_products(30)
    text=(f"<b>METROPIA / 30 DAYS</b>\n\nOrders: <b>{s['orders']}</b>\nRevenue: <b>{money(s['revenue'])} so'm</b>\nAverage: <b>{money(s['avg_order'])} so'm</b>\n\n<b>TOP PRODUCTS</b>\n"+
          "\n".join(f"{i+1}. {name} — {qty}" for i,(name,qty) in enumerate(tops)) or "—")
    await c.message.edit_text(text,parse_mode="HTML")
    await c.answer()

@router.callback_query(F.data=="mgr:branches")
async def branches(c:CallbackQuery):
    if not owner(c.from_user.id): return
    bs=v2.list_branches(); text="<b>🏪 BRANCHES</b>\n\n"+"\n\n".join(f"<b>{b['name']}</b>\n{b['address']}\n{b['open_time']}–{b['close_time']}" for b in bs)
    await c.message.edit_text(text,parse_mode="HTML"); await c.answer()

@router.callback_query(F.data=="mgr:promos")
async def promos(c:CallbackQuery):
    if not owner(c.from_user.id): return
    ps=v2.active_promotions()
    text="<b>🔥 ACTIVE PROMOTIONS</b>\n\n"+"\n\n".join(f"<b>{p['title']}</b>  ·  <code>{p['code']}</code>\n{p['description'] or ''}" for p in ps) if ps else "<b>🔥 ACTIVE PROMOTIONS</b>\n\nNo active promotions."
    await c.message.edit_text(text,parse_mode="HTML"); await c.answer()

@router.callback_query(F.data=="mgr:orders")
async def orders(c:CallbackQuery):
    if not owner(c.from_user.id): return
    os_=db.get_open_orders(); text="<b>📦 OPEN ORDERS</b>\n\n"
    text += "\n\n".join(f"<b>#{o['order_number']}</b> · {o['prep_status']}\n{o['items_summary'] or '—'}\n{o['branch_name'] or ''}" for o in os_) or "No open orders."
    await c.message.edit_text(text,parse_mode="HTML"); await c.answer()

@router.message(Command("dashboard"))
async def dashboard(message:Message):
    if not owner(message.from_user.id): return
    s=v2.dashboard_stats(1); tops=v2.top_products(1)
    await message.answer(f"<b>TODAY</b>\nOrders: {s['orders']}\nRevenue: {money(s['revenue'])} so'm\nOpen: {s['open_orders']}\n\n<b>TOP</b>\n"+"\n".join(f"• {n} — {q}" for n,q in tops),parse_mode="HTML")
