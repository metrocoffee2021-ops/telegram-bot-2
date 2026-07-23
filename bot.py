# bot.py
# This is the file you run to start the bot. It doesn't need editing —
# all the actual behavior lives in handlers.py (customers), admin.py (menu
# management), menu_store.py (the database-backed menu), and texts.py.

import asyncio
import os
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

import db
import menu_store
from handlers import router as customer_router
from admin import router as admin_router

load_dotenv()  # reads the .env file next to this one

logging.basicConfig(level=logging.INFO)


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

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
