# bot.py
# This is the file you run to start the bot. It doesn't need editing —
# all the actual behavior lives in handlers.py (customers), admin.py (menu
# management), menu_store.py (the database-backed menu), and texts.py.

import asyncio
import os
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

import db
import menu_store
from handlers import router as customer_router, fmt_price
from admin import router as admin_router, _aggregate, _format_report
from texts import t

load_dotenv()  # reads the .env file next to this one

logging.basicConfig(level=logging.INFO)

DAILY_SUMMARY_HOUR_UTC = 17  # ~22:00 Tashkent time (UTC+5) — edit this if the shop's hours change
BIRTHDAY_CHECK_HOUR_UTC = 4  # ~09:00 Tashkent time — sends birthday rewards early in the day


async def daily_summary_loop(bot: Bot, owner_id: int):
    """Sends the owner a sales summary once a day, automatically. Checks every
    few minutes rather than sleeping until the exact time, so it still fires
    correctly even after the bot restarts partway through the day."""
    if not owner_id:
        return
    while True:
        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        already_sent = db.get_setting("daily_summary_sent_date")
        if now.hour == DAILY_SUMMARY_HOUR_UTC and already_sent != today_str:
            try:
                lang = db.get_user_language(owner_id)
                orders = db.get_orders_on_date(today_str)
                count, revenue, item_counts = _aggregate(orders)
                label = t(lang, "admin_report_today")
                await bot.send_message(owner_id, _format_report(lang, label, count, revenue, item_counts))
            except Exception:
                pass  # don't let a failed summary crash the whole bot
            db.set_setting("daily_summary_sent_date", today_str)
        await asyncio.sleep(300)  # check every 5 minutes


async def birthday_loop(bot: Bot):
    """Checks once a day for customers whose birthday is today and grants
    them a free coffee automatically."""
    while True:
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y-%m-%d")
        month_day = now.strftime("%m-%d")
        already_sent = db.get_setting("birthday_check_date")
        if now.hour == BIRTHDAY_CHECK_HOUR_UTC and already_sent != today_key:
            try:
                for user_id in db.get_birthdays_today(month_day):
                    db.grant_free_coffee(user_id)
                    try:
                        lang = db.get_user_language(user_id)
                        await bot.send_message(user_id, t(lang, "birthday_gift_notice"))
                    except Exception:
                        pass  # customer may have blocked the bot
            except Exception:
                pass  # don't let a failed birthday check crash the whole bot
            db.set_setting("birthday_check_date", today_key)
        await asyncio.sleep(300)


async def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing — open the .env file and paste your bot token there.")

    db.init_db()
    menu_store.init_menu_tables()
    menu_store.seed_if_empty()

    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_router)
    dp.include_router(customer_router)

    owner_id = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))
    asyncio.create_task(daily_summary_loop(bot, owner_id))
    asyncio.create_task(birthday_loop(bot))

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
