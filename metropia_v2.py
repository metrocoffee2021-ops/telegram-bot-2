"""Metropia Coffee V2 business layer.

Additive, migration-safe extension for the existing SQLite bot.
It adds branches, promotions, order events, customer analytics and dashboard helpers
without replacing the existing order/payment/loyalty logic.
"""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone, timedelta
import db

STATUSES = ("new", "preparing", "ready", "completed", "cancelled")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def init_v2():
    with db.get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS branches_v2(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, address TEXT, phone TEXT,
            lat REAL, lng REAL, open_time TEXT DEFAULT '08:00', close_time TEXT DEFAULT '23:00',
            active INTEGER DEFAULT 1
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS promotions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE, title TEXT NOT NULL, description TEXT,
            kind TEXT NOT NULL DEFAULT 'percent', value INTEGER DEFAULT 0,
            min_order INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
            starts_at TEXT, ends_at TEXT, max_uses INTEGER, used_count INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS order_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL, event TEXT NOT NULL, actor TEXT,
            note TEXT, created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS customer_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            event TEXT NOT NULL, metadata TEXT, created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS referrals_v2(
            user_id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL,
            referred_by INTEGER, reward_claimed INTEGER DEFAULT 0
        )""")


def event(order_id, event, actor="system", note=None):
    with db.get_db() as conn:
        conn.execute("INSERT INTO order_events(order_id,event,actor,note,created_at) VALUES(?,?,?,?,?)",
                     (order_id,event,actor,note,now_iso()))


def customer_event(user_id, event_name, metadata=None):
    with db.get_db() as conn:
        conn.execute("INSERT INTO customer_events(user_id,event,metadata,created_at) VALUES(?,?,?,?)",
                     (user_id,event_name,json.dumps(metadata or {}, ensure_ascii=False),now_iso()))


def set_status(order_id, status, actor="system", note=None):
    if status not in STATUSES:
        raise ValueError(status)
    prep = {"new":"new", "preparing":"preparing", "ready":"ready", "completed":"completed", "cancelled":"cancelled"}[status]
    with db.get_db() as conn:
        conn.execute("UPDATE orders SET prep_status=? WHERE order_id=?", (prep, order_id))
        if status in ("cancelled", "completed"):
            conn.execute("UPDATE orders SET status=? WHERE order_id=?", (status, order_id))
    event(order_id, status, actor, note)


def get_order_events(order_id, limit=30):
    with db.get_db() as conn:
        rows=conn.execute("SELECT event,actor,note,created_at FROM order_events WHERE order_id=? ORDER BY id DESC LIMIT ?",(order_id,limit)).fetchall()
    return [dict(event=r[0],actor=r[1],note=r[2],created_at=r[3]) for r in rows]


def seed_branches():
    from branches import BRANCHES
    with db.get_db() as conn:
        count=conn.execute("SELECT COUNT(*) FROM branches_v2").fetchone()[0]
        if count: return
        for b in BRANCHES:
            conn.execute("INSERT INTO branches_v2(name,address,lat,lng) VALUES(?,?,?,?)",(b["name"],b["address"],b["lat"],b["lng"]))


def list_branches(active_only=False):
    sql="SELECT id,name,address,phone,lat,lng,open_time,close_time,active FROM branches_v2"
    if active_only: sql += " WHERE active=1"
    sql += " ORDER BY id"
    with db.get_db() as conn: rows=conn.execute(sql).fetchall()
    return [dict(id=r[0],name=r[1],address=r[2],phone=r[3],lat=r[4],lng=r[5],open_time=r[6],close_time=r[7],active=bool(r[8])) for r in rows]


def create_promotion(code,title,description,kind,value,min_order=0,starts_at=None,ends_at=None,max_uses=None):
    with db.get_db() as conn:
        conn.execute("INSERT INTO promotions(code,title,description,kind,value,min_order,starts_at,ends_at,max_uses) VALUES(?,?,?,?,?,?,?,?,?)",
                     (code.upper(),title,description,kind,value,min_order,starts_at,ends_at,max_uses))


def active_promotions():
    now=now_iso()
    with db.get_db() as conn:
        rows=conn.execute("""SELECT id,code,title,description,kind,value,min_order,starts_at,ends_at,max_uses,used_count
                            FROM promotions WHERE active=1 AND (starts_at IS NULL OR starts_at<=?) AND (ends_at IS NULL OR ends_at>=?)
                            AND (max_uses IS NULL OR used_count<max_uses) ORDER BY id DESC""",(now,now)).fetchall()
    return [dict(id=r[0],code=r[1],title=r[2],description=r[3],kind=r[4],value=r[5],min_order=r[6],starts_at=r[7],ends_at=r[8],max_uses=r[9],used_count=r[10]) for r in rows]


def apply_promotion(code,total):
    if not code: return total,None
    promo=next((p for p in active_promotions() if p["code"]==code.upper() and total>=p["min_order"]),None)
    if not promo: return total,None
    discount = round(total*promo["value"]/100) if promo["kind"]=="percent" else promo["value"]
    new_total=max(0,total-discount)
    return new_total,promo


def redeem_promotion(promo_id):
    with db.get_db() as conn:
        conn.execute("UPDATE promotions SET used_count=used_count+1 WHERE id=?",(promo_id,))


def dashboard_stats(days=7):
    since=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    with db.get_db() as conn:
        orders=conn.execute("SELECT COUNT(*),COALESCE(SUM(total),0),COALESCE(AVG(total),0) FROM orders WHERE status IN ('paid','completed') AND created_at>=?",(since,)).fetchone()
        customers=conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        open_count=conn.execute("SELECT COUNT(*) FROM orders WHERE status='paid' AND prep_status IN ('new','preparing')").fetchone()[0]
        ratings=conn.execute("SELECT COALESCE(AVG(rating),0),COUNT(rating) FROM orders WHERE rating IS NOT NULL AND created_at>=?",(since,)).fetchone()
    return {"orders":orders[0],"revenue":orders[1],"avg_order":round(orders[2]),"customers":customers,"open_orders":open_count,"avg_rating":round(ratings[0],2),"rating_count":ratings[1]}


def top_products(days=7,limit=8):
    since=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    counts={}
    with db.get_db() as conn:
        rows=conn.execute("SELECT items_json FROM orders WHERE status IN ('paid','completed') AND created_at>=?",(since,)).fetchall()
    for (raw,) in rows:
        try: items=json.loads(raw or "[]")
        except Exception: continue
        for item in items:
            name=item.get("name","?"); counts[name]=counts.get(name,0)+int(item.get("qty",1))
    return sorted(counts.items(),key=lambda x:x[1],reverse=True)[:limit]
