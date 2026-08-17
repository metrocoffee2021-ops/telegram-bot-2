"""Metropia Manager: real CRUD, not a read-only dashboard."""
from datetime import datetime, timezone
import db, menu_store, branches, config
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

router=Router()

def owner(uid): return config.OWNER_TELEGRAM_ID and uid==config.OWNER_TELEGRAM_ID

def kbbtn(kb,text,data): kb.button(text=text,callback_data=data)

class MFlow(StatesGroup):
    branch_name=State(); branch_address=State(); branch_lat=State(); branch_lng=State()
    promo_name=State(); promo_code=State(); promo_type=State(); promo_value=State(); promo_start=State(); promo_end=State()


def manager_kb():
    kb=InlineKeyboardBuilder()
    for text,data in [('🏪 Locations','m:branches'),('🔥 Promotions','m:promos'),('📦 Products','m:products'),('🧾 Orders','m:orders'),('📊 Analytics','m:analytics'),('🎂 Birthday','m:birthday')]: kbbtn(kb,text,data)
    kb.adjust(2); return kb.as_markup()

@router.message(Command('manager'))
@router.message(Command('manage'))
async def manager_entry(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return await m.answer('⛔ Owner access only.')
    await state.clear(); await m.answer('🖤 METROPIA MANAGER\n\nChoose what you want to manage:',reply_markup=manager_kb())

@router.message(Command('admin_status'))
async def status(m:Message):
    if owner(m.from_user.id): await m.answer('✅ You are the configured Metropia owner.\n/admin = menu editor\n/manager = business manager')
    else: await m.answer(f'Your Telegram ID: {m.from_user.id}\nOwner configured: {"yes" if config.OWNER_TELEGRAM_ID else "no"}')

@router.callback_query(F.data=='m:branches')
async def branches_menu(c:CallbackQuery):
    if not owner(c.from_user.id): return
    rows=db.list_branches(); kb=InlineKeyboardBuilder()
    for b in rows: kbbtn(kb,('🟢 ' if b['active'] else '⚪ ')+b['name'],f'm:branch:{b["id"]}')
    kbbtn(kb,'➕ Add location','m:branch_add'); kbbtn(kb,'⬅️ Manager','m:home'); kb.adjust(1)
    await c.message.edit_text('🏪 LOCATIONS\n\nAdd, edit, activate/deactivate or delete your branches.',reply_markup=kb.as_markup()); await c.answer()

@router.callback_query(F.data=='m:branch_add')
async def branch_add(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    await state.set_state(MFlow.branch_name); await c.message.answer('Send branch name:'); await c.answer()

@router.message(MFlow.branch_name)
async def bname(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    await state.update_data(name=m.text.strip()); await state.set_state(MFlow.branch_address); await m.answer('Send address:')
@router.message(MFlow.branch_address)
async def baddr(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    await state.update_data(address=m.text.strip()); await state.set_state(MFlow.branch_lat); await m.answer('Send latitude (example: 41.3292):')
@router.message(MFlow.branch_lat)
async def blat(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    try: float(m.text.strip())
    except: return await m.answer('Invalid latitude. Send a number.')
    await state.update_data(lat=float(m.text.strip())); await state.set_state(MFlow.branch_lng); await m.answer('Send longitude (example: 69.3227):')
@router.message(MFlow.branch_lng)
async def blng(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    try: lng=float(m.text.strip())
    except: return await m.answer('Invalid longitude. Send a number.')
    d=await state.get_data(); db.add_branch(d['name'],d['address'],d['lat'],lng); await state.clear(); await m.answer('✅ Location added.'); await branches_menu_proxy(m)

async def branches_menu_proxy(m):
    rows=db.list_branches(); kb=InlineKeyboardBuilder()
    for b in rows: kbbtn(kb,('🟢 ' if b['active'] else '⚪ ')+b['name'],f'm:branch:{b["id"]}')
    kbbtn(kb,'➕ Add location','m:branch_add'); kbbtn(kb,'⬅️ Manager','m:home'); kb.adjust(1)
    await m.answer('🏪 LOCATIONS',reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith('m:branch:'))
async def branch_detail(c:CallbackQuery):
    if not owner(c.from_user.id): return
    bid=int(c.data.split(':')[-1]); b=db.get_branch(bid)
    if not b: return await c.answer('Not found',show_alert=True)
    kb=InlineKeyboardBuilder(); kbbtn(kb,'🔁 Activate/Deactivate',f'm:branchtoggle:{bid}'); kbbtn(kb,'🗑 Delete',f'm:branchdel:{bid}'); kbbtn(kb,'⬅️ Locations','m:branches'); kb.adjust(1)
    await c.message.edit_text(f"🏪 {b['name']}\n📍 {b['address']}\n🧭 {b['lat']}, {b['lng']}\nStatus: {'ACTIVE' if b['active'] else 'INACTIVE'}",reply_markup=kb.as_markup()); await c.answer()
@router.callback_query(F.data.startswith('m:branchtoggle:'))
async def btog(c:CallbackQuery):
    if owner(c.from_user.id): db.toggle_branch(int(c.data.split(':')[-1])); await c.answer('Updated'); await branch_detail(c)
@router.callback_query(F.data.startswith('m:branchdel:'))
async def bdel(c:CallbackQuery):
    if owner(c.from_user.id): db.delete_branch(int(c.data.split(':')[-1])); await c.answer('Deleted'); await branches_menu(c)

@router.callback_query(F.data=='m:promos')
async def promos(c:CallbackQuery):
    if not owner(c.from_user.id): return
    rows=db.list_promotions(); kb=InlineKeyboardBuilder()
    for p in rows: kbbtn(kb,('🟢 ' if p['active'] else '⚪ ')+f"{p['name']} ({p['code']})",f"m:promo:{p['id']}")
    kbbtn(kb,'➕ Create promotion','m:promo_add'); kbbtn(kb,'⬅️ Manager','m:home'); kb.adjust(1)
    await c.message.edit_text('🔥 PROMOTIONS\n\nThese are saved promotions you can activate/deactivate.',reply_markup=kb.as_markup()); await c.answer()
@router.callback_query(F.data=='m:promo_add')
async def pstart(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    await state.set_state(MFlow.promo_name); await c.message.answer('Promotion name:'); await c.answer()
@router.message(MFlow.promo_name)
async def pname(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    await state.update_data(name=m.text.strip()); await state.set_state(MFlow.promo_code); await m.answer('Promo code (example BIRTHDAY50):')
@router.message(MFlow.promo_code)
async def pcode(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    await state.update_data(code=m.text.strip().upper()); await state.set_state(MFlow.promo_type); kb=InlineKeyboardBuilder(); kbbtn(kb,'Percent %','m:ptype:percent'); kbbtn(kb,'Fixed soʻm','m:ptype:fixed'); kb.adjust(2); await m.answer('Choose discount type:',reply_markup=kb.as_markup())
@router.callback_query(F.data.startswith('m:ptype:'))
async def ptype(c:CallbackQuery,state:FSMContext):
    if not owner(c.from_user.id): return
    await state.update_data(kind=c.data.split(':')[-1]); await state.set_state(MFlow.promo_value); await c.message.answer('Discount value (example 20 for 20%, or 10000 soʻm):'); await c.answer()
@router.message(MFlow.promo_value)
async def pvalue(m:Message,state:FSMContext):
    if not owner(m.from_user.id): return
    try: v=int(m.text.strip())
    except: return await m.answer('Send a whole number.')
    if v<=0: return await m.answer('Value must be greater than 0.')
    d=await state.get_data(); db.add_promotion(d['name'],d['code'],d['kind'],v); await state.clear(); await m.answer('✅ Promotion created and saved.'); await m.answer('Open /manager → Promotions to activate it.')
@router.callback_query(F.data.startswith('m:promo:'))
async def pdetail(c:CallbackQuery):
    if not owner(c.from_user.id): return
    p=db.get_promotion(int(c.data.split(':')[-1])); kb=InlineKeyboardBuilder(); kbbtn(kb,'🔁 Activate/Deactivate',f'm:promotoggle:{p["id"]}'); kbbtn(kb,'🗑 Delete',f'm:promodel:{p["id"]}'); kbbtn(kb,'⬅️ Promotions','m:promos'); kb.adjust(1)
    value=f"{p['value']}%" if p['kind']=='percent' else f"{p['value']} soʻm"
    await c.message.edit_text(f"🔥 {p['name']}\nCode: {p['code']}\nDiscount: {value}\nStatus: {'ACTIVE' if p['active'] else 'INACTIVE'}",reply_markup=kb.as_markup()); await c.answer()
@router.callback_query(F.data.startswith('m:promotoggle:'))
async def ptog(c:CallbackQuery):
    if owner(c.from_user.id): db.toggle_promotion(int(c.data.split(':')[-1])); await c.answer('Updated'); await pdetail(c)
@router.callback_query(F.data.startswith('m:promodel:'))
async def pdel(c:CallbackQuery):
    if owner(c.from_user.id): db.delete_promotion(int(c.data.split(':')[-1])); await c.answer('Deleted'); await promos(c)

@router.callback_query(F.data=='m:products')
async def products(c:CallbackQuery):
    if owner(c.from_user.id): await c.message.answer('📦 Product editing uses the full /admin menu editor.'); await c.answer()
@router.callback_query(F.data=='m:orders')
async def orders(c:CallbackQuery):
    if not owner(c.from_user.id): return
    rows=db.get_open_orders(); text='🧾 OPEN ORDERS\n\n'
    text += '\n'.join(f"#{o['order_number']} — {o['total']} soʻm — {o['prep_status']} — {o['branch_name'] or '-'}" for o in rows) if rows else 'No open orders.'
    await c.message.edit_text(text,reply_markup=manager_back()); await c.answer()
@router.callback_query(F.data=='m:analytics')
async def analytics(c:CallbackQuery):
    if not owner(c.from_user.id): return
    orders=db.get_orders_since((datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)).isoformat()); rev=sum(o['total'] for o in orders); avg=round(rev/len(orders)) if orders else 0
    await c.message.edit_text(f"📊 TODAY\n\nOrders: {len(orders)}\nRevenue: {rev:,} soʻm\nAverage order: {avg:,} soʻm",reply_markup=manager_back()); await c.answer()
@router.callback_query(F.data=='m:birthday')
async def birthday(c:CallbackQuery):
    if owner(c.from_user.id): await c.message.edit_text('🎂 BIRTHDAY REWARD\n\n50% OFF one drink\nValid 7 days\nOne reward per calendar year\nCannot be combined with another promotion.',reply_markup=manager_back()); await c.answer()

def manager_back():
    kb=InlineKeyboardBuilder(); kbbtn(kb,'⬅️ Manager','m:home'); return kb.as_markup()
@router.callback_query(F.data=='m:home')
async def home(c:CallbackQuery):
    if owner(c.from_user.id): await c.message.edit_text('🖤 METROPIA MANAGER\n\nChoose what you want to manage:',reply_markup=manager_kb()); await c.answer()
