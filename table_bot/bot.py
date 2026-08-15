# ФАЙЛ ДЛЯ ПАПКИ: table_bot
# КУДА ВСТАВЛЯТЬ: table_bot\bot.py  (заменить весь файл целиком)

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from core import common, help as help_module, admin
from games import crocodile, hangman, whoami, elias, funprompt, quiz


async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.include_router(common.router)
    dp.include_router(help_module.router)
    dp.include_router(admin.router)
    dp.include_router(crocodile.router)
    dp.include_router(hangman.router)
    dp.include_router(whoami.router)
    dp.include_router(elias.router)
    dp.include_router(funprompt.router)
    dp.include_router(quiz.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())