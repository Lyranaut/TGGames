import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from game.manager import GameManager
from handlers import common, registration, night, day


async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # GameManager доступен во всех хендлерах как параметр game_manager
    dp["game_manager"] = GameManager()

    dp.include_router(common.router)
    dp.include_router(registration.router)
    dp.include_router(night.router)
    dp.include_router(day.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())