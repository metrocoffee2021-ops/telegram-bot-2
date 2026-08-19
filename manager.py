"""Metropia Manager — owner-only operational controls."""
from datetime import datetime, timezone
import sqlite3
from urllib.parse import quote
import db, menu_store, branches, config
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()

def owner(uid):
    return bool(config.OWNER_TELEGRAM_ID) and uid == config.OWNER_TELEGRAM_ID

def btn(kb, text, data): kb.button(text=text, callback_data=data)

def back_kb():
    kb=InlineKeyboardBuilder(); btn(kb,"⬅️ Manager","m:home"); return kb.as_markup()

def manager_kb():
    kb=InlineKeyboardBuilder()
    for text,data in [("🏪 Locations","m:branches"),("🔥 Promotions","m:promos"),("📦 Products","m:products"),("🧾 Orders","m:orders"),("📊 Analytics","m:analytics"),("🎂 Birthday","m:birthday"),("📢 Broadcast","m:broadcast")]: btn(kb,text,data)
    kb.adjust(2); return kb.as_markup()

class MFlow(StatesGroup):
    branch_name=State(); branch_address=State(); branch_lat=State(); branch_lng=State(); branch_phone=State(); branch_hours=State(); branch_pickup=State(); branch_delivery=State(); branch_edit_id=State()
    promo_name=State(); promo_code=State(); promo_type=State(); promo_value=State(); promo_start=State(); promo_end=State(); promo_min=State(); promo_max=State(); promo_daily=State(); promo_edit_id=State()
    birthday_percent=State(); birthday_days=State()
    broadcast_text=State()

@router.message(Command("manager"))
@router.message(Command("manage"))
async def manager_entry(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return await m.answer("⛔ Owner access only.")
    await state.clear(); await m.answer("🖤 METROPIA MANAGER\n\nChoose what you want to manage:",reply_markup=manager_kb())

@router.message(Command("admin_status"))
async def status(m:Message):
    if owner(m.from_user.id): await m.answer("✅ You are the configured Metropia owner.\n/admin = menu editor\n/manager = business manager")
    else: await m.answer(f"Your Telegram ID: {m.from_user.id}\nOwner configured: {'yes' if config.OWNER_TELEGRAM_ID else 'no'}")

@router.callback_query(F.data=="m:home")
async def home(c:CallbackQuery):
    if not owner(c.from_user.id): return
    await c.message.edit_text("🖤 METROPIA MANAGER\n\nChoose what you want to manage:",reply_markup=manager_kb()); await c.answer()

# ---------- locations ----------
async def render_branches(target):
    rows=db.list_branches(); kb=InlineKeyboardBuilder()
    for b in rows: btn(kb,("🟢 " if b['active'] else "⚪ ")+b['name'],f"m:branch:{b['id']}")
    btn(kb,"➕ Add location","m:branch_add"); btn(kb,"⬅️ Manager","m:home"); kb.adjust(1)
    if isinstance(target,CallbackQuery): await target.message.edit_text("🏪 LOCATIONS\n\nAdd, edit, activate/deactivate or delete branches.",reply_markup=kb.as_markup())
    else: await target.answer("🏪 LOCATIONS",reply_markup=kb.as_markup())

@router.callback_query(F.data=="m:branches")
async def branches_menu(c:CallbackQuery):
    if not owner(c.from_user.id): return
    await render_branches(c); await c.answer()

@router.callback_query(F.data=="m:branch_add")
async def branch_add(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    await state.set_state(MFlow.branch_name); await c.message.answer("Send branch name:"); await c.answer()

@router.message(MFlow.branch_name)
async def bname(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); raw=(m.text or '').strip()
    if 'edit_id' in d:
        b=db.get_branch(d['edit_id']); name=b['name'] if raw.upper()=='SAME' else raw
        await state.update_data(name=name); await state.set_state(MFlow.branch_address); await m.answer(f"Current address: {b['address']}\nSend new address (or SAME):")
        return
    await state.update_data(name=raw); await state.set_state(MFlow.branch_address); await m.answer("Send address:")

@router.message(MFlow.branch_address)
async def baddr(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); raw=(m.text or '').strip()
    if 'edit_id' in d:
        b=db.get_branch(d['edit_id']); addr=b['address'] if raw.upper()=='SAME' else raw
        await state.update_data(address=addr); await state.set_state(MFlow.branch_lat); await m.answer(f"Current latitude: {b['lat']}\nSend new latitude (or SAME):")
        return
    await state.update_data(address=raw); await state.set_state(MFlow.branch_lat); await m.answer("Send latitude:")

@router.message(MFlow.branch_lat)
async def blat(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); raw=(m.text or '').strip()
    try:
        v=db.get_branch(d['edit_id'])['lat'] if 'edit_id' in d and raw.upper()=='SAME' else float(raw)
    except (ValueError,TypeError): return await m.answer("Invalid latitude. Send a number.")
    await state.update_data(lat=v); await state.set_state(MFlow.branch_lng); await m.answer("Send longitude:")

@router.message(MFlow.branch_lng)
async def blng(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); raw=(m.text or '').strip()
    try:
        v=db.get_branch(d['edit_id'])['lng'] if 'edit_id' in d and raw.upper()=='SAME' else float(raw)
    except (ValueError,TypeError): return await m.answer("Invalid longitude. Send a number.")
    await state.update_data(lng=v)
    await state.set_state(MFlow.branch_phone)
    current=db.get_branch(d['edit_id']) if 'edit_id' in d else None
    await m.answer(f"Phone number (or SAME): {current['phone'] if current else 'optional'}")

@router.message(MFlow.branch_phone)
async def bphone(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); raw=(m.text or '').strip(); b=db.get_branch(d['edit_id']) if 'edit_id' in d else None
    await state.update_data(phone=(b['phone'] if b and raw.upper()=='SAME' else raw))
    await state.set_state(MFlow.branch_hours); await m.answer(f"Opening hours (e.g. 08:00-23:00, or SAME): {b['hours'] if b else '08:00-23:00'}")

@router.message(MFlow.branch_hours)
async def bhours(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); raw=(m.text or '').strip(); b=db.get_branch(d['edit_id']) if 'edit_id' in d else None
    hours=b['hours'] if b and raw.upper()=='SAME' else raw
    if '-' not in hours or len(hours.split('-'))!=2: return await m.answer('Use format HH:MM-HH:MM.')
    await state.update_data(hours=hours); await state.set_state(MFlow.branch_pickup); await m.answer('Pickup enabled? YES or NO' + (f" (current: {'YES' if b['pickup_enabled'] else 'NO'})" if b else ''))

@router.message(MFlow.branch_pickup)
async def bpickup(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    raw=(m.text or '').strip().upper(); d=await state.get_data(); b=db.get_branch(d['edit_id']) if 'edit_id' in d else None
    if raw=='SAME' and b: v=b['pickup_enabled']
    elif raw in ('YES','Y','HA','ДА'): v=1
    elif raw in ('NO','N','YOQ','НЕТ'): v=0
    else: return await m.answer('Send YES or NO.')
    await state.update_data(pickup=v); await state.set_state(MFlow.branch_delivery); await m.answer('Delivery enabled? YES or NO' + (f" (current: {'YES' if b['delivery_enabled'] else 'NO'})" if b else ''))

@router.message(MFlow.branch_delivery)
async def bdelivery(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    raw=(m.text or '').strip().upper(); d=await state.get_data(); b=db.get_branch(d['edit_id']) if 'edit_id' in d else None
    if raw=='SAME' and b: v=b['delivery_enabled']
    elif raw in ('YES','Y','HA','ДА'): v=1
    elif raw in ('NO','N','YOQ','НЕТ'): v=0
    else: return await m.answer('Send YES or NO.')
    if 'edit_id' in d:
        db.update_branch(d['edit_id'],d['name'],d['address'],d['lat'],d['lng'],d.get('phone',''),d.get('hours','08:00-23:00'),d.get('pickup',1),v); msg='✅ Location updated.'
    else:
        db.add_branch(d['name'],d['address'],d['lat'],d['lng'],d.get('phone',''),d.get('hours','08:00-23:00'),d.get('pickup',1),v); msg='✅ Location added.'
    await state.clear(); await m.answer(msg); await render_branches(m)

@router.callback_query(F.data.startswith("m:branch:"))
async def branch_detail(c:CallbackQuery):
    if not owner(c.from_user.id): return
    bid=int(c.data.split(':')[-1]); b=db.get_branch(bid)
    if not b: return await c.answer("Not found",show_alert=True)
    kb=InlineKeyboardBuilder(); btn(kb,"✏️ Edit location",f"m:branchedit:{bid}"); btn(kb,"📱 QR code",f"m:branchqr:{bid}"); btn(kb,"🔁 Activate/Deactivate",f"m:branchtoggle:{bid}"); btn(kb,"🗑 Delete",f"m:branchdel:{bid}"); btn(kb,"⬅️ Locations","m:branches"); kb.adjust(1)
    await c.message.edit_text(f"🏪 {b['name']}\n📍 {b['address']}\n🧭 {b['lat']}, {b['lng']}\n☎️ {b['phone'] or '-'}\n🕒 {b['hours']}\nPickup: {'YES' if b['pickup_enabled'] else 'NO'}\nDelivery: {'YES' if b['delivery_enabled'] else 'NO'}\nStatus: {'ACTIVE' if b['active'] else 'INACTIVE'}",reply_markup=kb.as_markup()); await c.answer()

@router.callback_query(F.data.startswith("m:branchqr:"))
async def branch_qr(c:CallbackQuery):
    if not owner(c.from_user.id): return
    bid=int(c.data.split(':')[-1]); b=db.get_branch(bid)
    if not b: return await c.answer("Not found",show_alert=True)
    me=await c.bot.get_me()
    deep_link=f"https://t.me/{me.username}?start=branch_{bid}"
    qr_image_url=f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={quote(deep_link)}"
    kb=InlineKeyboardBuilder(); btn(kb,"⬅️ Back",f"m:branch:{bid}"); kb.adjust(1)
    caption=f"📱 QR code for {b['name']}\n\nPrint this on a table tent or at the counter. Scanning it opens the bot with this branch pre-selected — customers skip the location-share step at checkout.\n\nLink: {deep_link}"
    await c.message.answer_photo(qr_image_url, caption=caption, reply_markup=kb.as_markup())
    await c.answer()

@router.callback_query(F.data.startswith("m:branchedit:"))
async def branch_edit_start(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    bid=int(c.data.split(':')[-1]); b=db.get_branch(bid)
    if not b: return await c.answer("Not found",show_alert=True)
    await state.set_data({'edit_id':bid}); await state.set_state(MFlow.branch_name); await c.message.answer(f"Current name: {b['name']}\nSend new branch name (or type SAME):"); await c.answer()

@router.callback_query(F.data.startswith("m:branchtoggle:"))
async def btog(c:CallbackQuery):
    if owner(c.from_user.id): db.toggle_branch(int(c.data.split(':')[-1])); await branch_detail(c); await c.answer("Updated")

@router.callback_query(F.data.startswith("m:branchdel:"))
async def bdel(c:CallbackQuery):
    if owner(c.from_user.id): db.delete_branch(int(c.data.split(':')[-1])); await render_branches(c); await c.answer("Deleted")

# Reuse branch states for edit with a small branch-edit dispatcher.
# ---------- promotions ----------
async def render_promos(target):
    rows=db.list_promotions(); kb=InlineKeyboardBuilder()
    for p in rows: btn(kb,("🟢 " if p['active'] else "⚪ ")+f"{p['name']} ({p['code']})",f"m:promo:{p['id']}")
    btn(kb,"➕ Create promotion","m:promo_add"); btn(kb,"⬅️ Manager","m:home"); kb.adjust(1)
    if isinstance(target,CallbackQuery): await target.message.edit_text("🔥 PROMOTIONS\n\nCreate, edit, activate/deactivate or delete promotions.",reply_markup=kb.as_markup())
    else: await target.answer("🔥 PROMOTIONS",reply_markup=kb.as_markup())

@router.callback_query(F.data=="m:promos")
async def promos(c:CallbackQuery):
    if not owner(c.from_user.id): return
    await render_promos(c); await c.answer()

@router.callback_query(F.data=="m:promo_add")
async def pstart(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    await state.clear(); await state.set_state(MFlow.promo_name); await c.message.answer("Promotion name:"); await c.answer()

@router.message(MFlow.promo_name)
async def pname(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); raw=(m.text or '').strip();
    if 'edit_id' in d and raw.upper()=='SAME': raw=db.get_promotion(d['edit_id'])['name']
    await state.update_data(name=raw)
    if 'edit_id' in d:
        await state.set_state(MFlow.promo_code); await m.answer("Promo code (or SAME):")
    else:
        await state.set_state(MFlow.promo_code); await m.answer("Promo code (example LATTE20):")

@router.message(MFlow.promo_code)
async def pcode(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); raw=(m.text or '').strip().upper()
    if 'edit_id' in d and raw=='SAME': raw=db.get_promotion(d['edit_id'])['code']
    await state.update_data(code=raw); await state.set_state(MFlow.promo_type)
    kb=InlineKeyboardBuilder(); btn(kb,"Percent %","m:ptype:percent"); btn(kb,"Fixed so'm","m:ptype:fixed"); kb.adjust(2); await m.answer("Choose discount type:",reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith('m:ptype:'))
async def ptype(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    kind=c.data.split(':')[-1]; d=await state.get_data(); await state.update_data(kind=kind); await state.set_state(MFlow.promo_value)
    current=''
    if 'edit_id' in d:
        p=db.get_promotion(d['edit_id']); current=f" Current value: {p['value']}. Send SAME to keep it."
    await c.message.answer('Discount value (20 = 20%, or 10000 so\'m).'+current); await c.answer()

@router.message(MFlow.promo_value)
async def pvalue(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); raw=(m.text or '').strip()
    if 'edit_id' in d and raw.upper()=='SAME': v=db.get_promotion(d['edit_id'])['value']
    else:
        try: v=int(raw)
        except ValueError: return await m.answer('Send a whole number.')
    if v<=0 or (d['kind']=='percent' and v>100): return await m.answer('Invalid discount value.')
    await state.update_data(value=v); await state.set_state(MFlow.promo_start)
    p=db.get_promotion(d['edit_id']) if 'edit_id' in d else None
    await m.answer(f"Start date/time UTC YYYY-MM-DD HH:MM, blank for now (or SAME): {p['starts_at'] if p and p['starts_at'] else '-'}")

def _promo_dt(raw, current=None):
    raw=(raw or '').strip()
    if raw.upper()=='SAME': return current
    if not raw: return None
    try: return datetime.strptime(raw,'%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc).isoformat()
    except ValueError: return '__INVALID__'

@router.message(MFlow.promo_start)
async def pstart_set(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); p=db.get_promotion(d['edit_id']) if 'edit_id' in d else None; v=_promo_dt(m.text,p['starts_at'] if p else None)
    if v=='__INVALID__': return await m.answer('Use YYYY-MM-DD HH:MM or leave blank.')
    await state.update_data(starts_at=v); await state.set_state(MFlow.promo_end); await m.answer('End date/time UTC YYYY-MM-DD HH:MM, blank for no expiry (or SAME):')

@router.message(MFlow.promo_end)
async def pend_set(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); p=db.get_promotion(d['edit_id']) if 'edit_id' in d else None; v=_promo_dt(m.text,p['ends_at'] if p else None)
    if v=='__INVALID__': return await m.answer('Use YYYY-MM-DD HH:MM or leave blank.')
    await state.update_data(ends_at=v); await state.set_state(MFlow.promo_min); await m.answer("Minimum order value in so'm (0 for none, or SAME):")

@router.message(MFlow.promo_min)
async def pmin_set(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); p=db.get_promotion(d['edit_id']) if 'edit_id' in d else None; raw=(m.text or '').strip(); v=p['min_subtotal'] if p and raw.upper()=='SAME' else int(raw or 0) if raw.isdigit() else -1
    if v<0: return await m.answer('Send a whole number.')
    await state.update_data(min_subtotal=v); await state.set_state(MFlow.promo_max); await m.answer('Maximum uses (0 = unlimited, or SAME):')

@router.message(MFlow.promo_max)
async def pmax_set(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); p=db.get_promotion(d['edit_id']) if 'edit_id' in d else None; raw=(m.text or '').strip(); v=p['max_uses'] if p and raw.upper()=='SAME' else int(raw or 0) if raw.isdigit() else -1
    if v<0: return await m.answer('Send a whole number.')
    await state.update_data(max_uses=v); await state.set_state(MFlow.promo_daily)
    p=db.get_promotion(d['edit_id']) if 'edit_id' in d else None
    current=f" Current: {p['daily_start']}-{p['daily_end']}." if p and p.get('daily_start') else ''
    await m.answer("Recurring daily window? e.g. 15:00-17:00 for every-day happy hour, or blank for a normal one-time promo (or SAME)."+current)

def _promo_daily(raw, current_start=None, current_end=None):
    raw=(raw or '').strip()
    if raw.upper()=='SAME': return (current_start, current_end)
    if not raw: return (None, None)
    try:
        start_s, end_s = [part.strip() for part in raw.split('-', 1)]
        datetime.strptime(start_s, '%H:%M'); datetime.strptime(end_s, '%H:%M')
        return (start_s, end_s)
    except (ValueError, IndexError):
        return ('__INVALID__', None)

@router.message(MFlow.promo_daily)
async def pdaily_set(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    d=await state.get_data(); p=db.get_promotion(d['edit_id']) if 'edit_id' in d else None
    daily_start, daily_end = _promo_daily(m.text, p['daily_start'] if p else None, p['daily_end'] if p else None)
    if daily_start=='__INVALID__': return await m.answer("Use HH:MM-HH:MM (e.g. 15:00-17:00) or leave blank.")
    try:
        if 'edit_id' in d:
            db.update_promotion(d['edit_id'],d['name'],d['code'],d['kind'],d['value'],d.get('starts_at'),d.get('ends_at'),d.get('min_subtotal',0),d.get('max_uses',0),daily_start,daily_end); msg='✅ Promotion updated.'
        else:
            db.add_promotion(d['name'],d['code'],d['kind'],d['value'],d.get('starts_at'),d.get('ends_at'),d.get('min_subtotal',0),d.get('max_uses',0),daily_start,daily_end); msg='✅ Promotion created. It is inactive until you activate it.'
    except sqlite3.IntegrityError:
        return await m.answer('That promo code already exists. Choose a different code.')
    await state.clear(); await m.answer(msg); await render_promos(m)

@router.callback_query(F.data.startswith('m:promo:'))
async def pdetail(c:CallbackQuery):
    if not owner(c.from_user.id): return
    p=db.get_promotion(int(c.data.split(':')[-1]));
    if not p: return await c.answer('Not found',show_alert=True)
    value=f"{p['value']}%" if p['kind']=='percent' else f"{p['value']} so'm"
    daily=f"\nDaily window: {p['daily_start']}-{p['daily_end']} (every day)" if p.get('daily_start') else ''
    kb=InlineKeyboardBuilder(); btn(kb,'✏️ Edit promotion',f'm:promoedit:{p["id"]}'); btn(kb,'🔁 Activate/Deactivate',f'm:promotoggle:{p["id"]}'); btn(kb,'🗑 Delete',f'm:promodel:{p["id"]}'); btn(kb,'⬅️ Promotions','m:promos'); kb.adjust(1)
    await c.message.edit_text(f"🔥 {p['name']}\nCode: {p['code']}\nDiscount: {value}\nStarts: {p['starts_at'] or 'now'}\nEnds: {p['ends_at'] or 'never'}{daily}\nMinimum: {p['min_subtotal']:,} so\'m\nUses: {p['used_count']}/{p['max_uses'] if p['max_uses'] else '∞'}\nStatus: {'ACTIVE' if p['active'] else 'INACTIVE'}",reply_markup=kb.as_markup()); await c.answer()

@router.callback_query(F.data.startswith('m:promoedit:'))
async def pedit(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    pid=int(c.data.split(':')[-1]); p=db.get_promotion(pid)
    if not p: return await c.answer('Not found',show_alert=True)
    await state.set_data({'edit_id':pid}); await state.set_state(MFlow.promo_name); await c.message.answer(f"Current name: {p['name']}\nSend new name (or SAME):"); await c.answer()

@router.callback_query(F.data.startswith('m:promotoggle:'))
async def ptog(c:CallbackQuery):
    if owner(c.from_user.id): db.toggle_promotion(int(c.data.split(':')[-1])); await pdetail(c); await c.answer('Updated')
@router.callback_query(F.data.startswith('m:promodel:'))
async def pdel(c:CallbackQuery):
    if owner(c.from_user.id): db.delete_promotion(int(c.data.split(':')[-1])); await render_promos(c); await c.answer('Deleted')

# ---------- products ----------
@router.callback_query(F.data=='m:products')
async def products(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    from admin import show_categories
    await state.clear(); await show_categories(c.from_user.id,c.message.answer); await c.answer()

# ---------- orders ----------
@router.callback_query(F.data=='m:orders')
async def orders(c:CallbackQuery):
    if not owner(c.from_user.id): return
    rows=db.get_open_orders(); kb=InlineKeyboardBuilder(); lines=['🧾 OPEN ORDERS','']
    for o in rows:
        lines.append(f"#{o['order_number']} — {o['total']} so'm — {o['prep_status']} — {o['branch_name'] or '-'}")
        btn(kb,'🔎 '+f"#{o['order_number']}",f"m:order:{o['order_id']}")
    if not rows: lines.append('No open orders.')
    btn(kb,'⬅️ Manager','m:home'); kb.adjust(1)
    await c.message.edit_text('\n'.join(lines),reply_markup=kb.as_markup()); await c.answer()

@router.callback_query(F.data.startswith('m:order:'))
async def order_detail(c:CallbackQuery):
    if not owner(c.from_user.id): return
    oid=c.data.split(':',2)[2]; o=db.get_order(oid)
    if not o: return await c.answer('Not found',show_alert=True)
    kb=InlineKeyboardBuilder();
    if o['prep_status']=='new': btn(kb,'👋 Start preparing',f'm:orderclaim:{oid}')
    if o['prep_status']=='preparing': btn(kb,'✅ Mark ready',f'm:orderready:{oid}')
    if o['prep_status']=='ready': btn(kb,'🏁 Complete order',f'm:ordercomplete:{oid}')
    btn(kb,'❌ Cancel order',f'm:ordercancel:{oid}'); btn(kb,'⬅️ Orders','m:orders'); kb.adjust(1)
    await c.message.edit_text(f"🧾 ORDER #{o['order_number']}\n\n{o['items_summary'] or '—'}\n\n💰 {o['total']} so'm\n📍 {o['branch_name'] or '-'}\nStatus: {o['prep_status']}",reply_markup=kb.as_markup()); await c.answer()

@router.callback_query(F.data.startswith('m:orderclaim:'))
async def order_claim(c:CallbackQuery):
    if not owner(c.from_user.id): return
    oid=c.data.split(':',2)[2]; db.claim_order(oid,c.from_user.full_name); await order_detail(c); await c.answer('Preparing')
@router.callback_query(F.data.startswith('m:orderready:'))
async def order_ready(c:CallbackQuery):
    if not owner(c.from_user.id): return
    oid=c.data.split(':',2)[2]; db.mark_order_prep_ready(oid); o=db.get_order(oid)
    if o:
        try:
            lang=db.get_user_language(o['user_id']); await c.bot.send_message(o['user_id'], '☕ ' + {'uz':'Buyurtmangiz tayyor! Filialdan olib ketishingiz mumkin.','ru':'Ваш заказ готов! Вы можете забрать его в филиале.','en':'Your order is ready! You can pick it up at the branch.'}[lang])
        except Exception: pass
    await order_detail(c); await c.answer('Ready')

@router.callback_query(F.data.startswith('m:ordercomplete:'))
async def order_complete(c:CallbackQuery):
    if not owner(c.from_user.id): return
    oid=c.data.split(':',2)[2]; db.mark_order_completed(oid); await orders(c); await c.answer('Completed')
@router.callback_query(F.data.startswith('m:ordercancel:'))
async def order_cancel(c:CallbackQuery):
    if not owner(c.from_user.id): return
    oid=c.data.split(':',2)[2]; db.cancel_order(oid); await orders(c); await c.answer('Cancelled')

# ---------- analytics ----------
def _analytics_blocks(rows_by_window):
    blocks=[]
    for label,rows in rows_by_window:
        rev=sum(o['total'] for o in rows); avg=round(rev/len(rows)) if rows else 0
        blocks.append(f"📊 {label}\nOrders: {len(rows)}\nRevenue: {rev:,} so'm\nAverage: {avg:,} so'm")
    return blocks

def _analytics_windows(all_rows_fn):
    now=datetime.now(timezone.utc); starts=[now.replace(hour=0,minute=0,second=0,microsecond=0)-__import__('datetime').timedelta(days=d) for d in (0,6,29)]
    return [(label, all_rows_fn(start_dt.isoformat())) for label,start_dt in zip(('TODAY','7 DAYS','30 DAYS'),starts)]

@router.callback_query(F.data=='m:analytics')
async def analytics(c:CallbackQuery):
    if not owner(c.from_user.id): return
    blocks=_analytics_blocks(_analytics_windows(db.get_orders_since))
    kb=InlineKeyboardBuilder(); btn(kb,'🏪 Per-branch breakdown','m:analytics_branches'); btn(kb,'⬅️ Manager','m:home'); kb.adjust(1)
    await c.message.edit_text("\n\n".join(blocks),reply_markup=kb.as_markup()); await c.answer()

@router.callback_query(F.data=='m:analytics_branches')
async def analytics_branches(c:CallbackQuery):
    if not owner(c.from_user.id): return
    rows=db.list_branches(); kb=InlineKeyboardBuilder()
    for b in rows: btn(kb,("🟢 " if b['active'] else "⚪ ")+b['name'],f"m:analytics_branch:{b['id']}")
    btn(kb,'⬅️ Analytics','m:analytics'); kb.adjust(1)
    await c.message.edit_text("🏪 Choose a branch for its own Today / 7-day / 30-day numbers:",reply_markup=kb.as_markup()); await c.answer()

@router.callback_query(F.data.startswith('m:analytics_branch:'))
async def analytics_branch(c:CallbackQuery):
    if not owner(c.from_user.id): return
    b=db.get_branch(int(c.data.split(':')[-1]))
    if not b: return await c.answer('Not found',show_alert=True)
    def rows_for_branch(iso_dt): return [o for o in db.get_orders_since(iso_dt) if o.get('branch_name')==b['name']]
    blocks=_analytics_blocks(_analytics_windows(rows_for_branch))
    kb=InlineKeyboardBuilder(); btn(kb,'⬅️ Branches','m:analytics_branches'); kb.adjust(1)
    await c.message.edit_text(f"🏪 {b['name']}\n\n"+"\n\n".join(blocks),reply_markup=kb.as_markup()); await c.answer()

# ---------- birthday settings ----------
@router.callback_query(F.data=='m:birthday')
async def birthday(c:CallbackQuery):
    if not owner(c.from_user.id): return
    pct=db.get_birthday_discount_percent(); days=db.get_birthday_reward_valid_days(); kb=InlineKeyboardBuilder(); btn(kb,'✏️ Change discount','m:bdpct'); btn(kb,'⏱ Change validity','m:bddays'); btn(kb,'⬅️ Manager','m:home'); kb.adjust(1)
    await c.message.edit_text(f"🎂 BIRTHDAY REWARD\n\nDiscount: {pct}%\nOne drink\nValid: {days} days\nOnce per calendar year\nCannot stack with another promotion.",reply_markup=kb.as_markup()); await c.answer()
@router.callback_query(F.data=='m:bdpct')
async def bdpct(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    await state.set_state(MFlow.birthday_percent); await c.message.answer('Send birthday discount percent (1–100):'); await c.answer()
@router.message(MFlow.birthday_percent)
async def bdpct_set(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    try: v=int((m.text or '').strip())
    except ValueError: return await m.answer('Send a whole number.')
    if not 1<=v<=100: return await m.answer('Use 1–100.')
    db.set_setting('birthday_discount_percent',str(v)); await state.clear(); await m.answer('✅ Birthday discount updated.'); await m.answer('Use /manager → Birthday to review it.',reply_markup=manager_kb())
@router.callback_query(F.data=='m:bddays')
async def bddays(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    await state.set_state(MFlow.birthday_days); await c.message.answer('Send validity in days (1–30):'); await c.answer()
@router.message(MFlow.birthday_days)
async def bddays_set(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    try: v=int((m.text or '').strip())
    except ValueError: return await m.answer('Send a whole number.')
    if not 1<=v<=30: return await m.answer('Use 1–30.')
    db.set_setting('birthday_reward_valid_days',str(v)); await state.clear(); await m.answer('✅ Birthday validity updated.'); await m.answer('Use /manager → Birthday to review it.',reply_markup=manager_kb())

# ---------- broadcast ----------
@router.callback_query(F.data=='m:broadcast')
async def broadcast_start(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    kb=InlineKeyboardBuilder()
    btn(kb, f"👥 All customers ({len(db.get_all_user_ids())})", 'm:broadcast_audience:all')
    btn(kb, f"🔁 Win-back — inactive 30+ days ({len(db.get_inactive_user_ids(30))})", 'm:broadcast_audience:winback')
    btn(kb, '⬅️ Manager', 'm:home')
    kb.adjust(1)
    await c.message.edit_text("📢 Who should this broadcast go to?", reply_markup=kb.as_markup())
    await c.answer()

@router.callback_query(F.data.startswith('m:broadcast_audience:'))
async def broadcast_audience(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    audience=c.data.split(':')[-1]
    await state.update_data(audience=audience)
    await state.set_state(MFlow.broadcast_text)
    label='all customers' if audience=='all' else 'customers inactive 30+ days (win-back)'
    await c.message.answer(f"📢 Send what you want to broadcast to {label}.\n\nEither send a photo with a caption (for a picture ad), or just plain text.\n\nThis goes out immediately to that group once you confirm — there's a review step next.")
    await c.answer()

def _broadcast_recipients(audience:str) -> list[int]:
    return db.get_inactive_user_ids(30) if audience=='winback' else db.get_all_user_ids()

@router.message(MFlow.broadcast_text, F.photo)
async def broadcast_compose_photo(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    caption=(m.caption or '').strip()
    d=await state.get_data(); audience=d.get('audience','all')
    await state.update_data(kind='photo', photo_id=m.photo[-1].file_id, text=caption)
    count=len(_broadcast_recipients(audience))
    kb=InlineKeyboardBuilder(); btn(kb,f'✅ Send to {count} customers','m:broadcast_confirm'); btn(kb,'❌ Cancel','m:broadcast_cancel'); kb.adjust(1)
    await m.answer_photo(m.photo[-1].file_id, caption=f"Preview — this exact photo/caption goes to {count} customers:\n\n{caption or '(no caption)'}", reply_markup=kb.as_markup())

@router.message(MFlow.broadcast_text)
async def broadcast_compose(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    text=(m.text or '').strip()
    if not text: return await m.answer('Send some text, or a photo with a caption.')
    d=await state.get_data(); audience=d.get('audience','all')
    await state.update_data(kind='text', text=text)
    count=len(_broadcast_recipients(audience))
    kb=InlineKeyboardBuilder(); btn(kb,f'✅ Send to {count} customers','m:broadcast_confirm'); btn(kb,'❌ Cancel','m:broadcast_cancel'); kb.adjust(1)
    await m.answer(f"Preview:\n\n{text}\n\nSend this to {count} customers?",reply_markup=kb.as_markup())

@router.callback_query(F.data=='m:broadcast_confirm')
async def broadcast_confirm(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    d=await state.get_data(); kind=d.get('kind','text'); text=d.get('text',''); photo_id=d.get('photo_id'); audience=d.get('audience','all')
    await state.clear()
    if kind=='photo' and not photo_id:
        await c.answer(); return
    if kind=='text' and not text:
        await c.answer(); return

    if kind=='photo':
        await c.message.edit_caption(caption='📢 Sending…')
    else:
        await c.message.edit_text('📢 Sending…')

    user_ids=_broadcast_recipients(audience); sent=0
    import asyncio as _asyncio
    for user_id in user_ids:
        try:
            if kind=='photo':
                await c.bot.send_photo(user_id, photo_id, caption=text or None)
            else:
                await c.bot.send_message(user_id, text)
            sent+=1
        except Exception:
            pass
        await _asyncio.sleep(0.05)

    result_text=f'✅ Broadcast sent to {sent}/{len(user_ids)} customers.'
    if kind=='photo':
        await c.bot.send_message(c.from_user.id, result_text, reply_markup=back_kb())
    else:
        await c.message.edit_text(result_text,reply_markup=back_kb())
    await c.answer()

@router.callback_query(F.data=='m:broadcast_cancel')
async def broadcast_cancel(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    await state.clear()
    if c.message.photo:
        await c.bot.send_message(c.from_user.id, 'Cancelled — nothing was sent.', reply_markup=back_kb())
    else:
        await c.message.edit_text('Cancelled — nothing was sent.',reply_markup=back_kb())
    await c.answer()
