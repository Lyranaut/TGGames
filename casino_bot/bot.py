import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from core import help as help_module, admin
from core.tracking import UserTrackingMiddleware
from games import blackjack, roulette, fastpoker, slots


async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Запоминает username/id каждого написавшего — работает как middleware,
    # поэтому не мешает роутингу обычных хендлеров.
    dp.message.middleware(UserTrackingMiddleware())

    dp.include_router(help_module.router)
    dp.include_router(admin.router)
    dp.include_router(blackjack.router)
    dp.include_router(roulette.router)
    dp.include_router(fastpoker.router)
    dp.include_router(slots.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
