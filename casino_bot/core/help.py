# ФАЙЛ ДЛЯ ПАПКИ: casino_bot
# КУДА ВСТАВЛЯТЬ: casino_bot\core\help.py  (заменить весь файл целиком)

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

HELP_TEXT = (
    "🎰 <b>Казино-бот — список игр и команд</b>\n\n"
    "У каждого своя копилка фишек, выдаётся автоматически при первой игре "
    "или проверке баланса — регистрироваться не нужно.\n\n"
    "🃏 <b>/blackjack СТАВКА</b> — Блэкджек. Играете против дилера, "
    "кнопки «Ещё карту» / «Хватит». Блэкджек с двух карт — выплата 3:2.\n\n"
    "🎡 <b>/roulette</b> — Рулетка. Открывает приём ставок на 30 секунд для "
    "всех в чате, дальше — команда <code>/bet ТИП СУММА</code>.\n\n"
    "🃏 <b>/poker СТАВКА</b> — Быстрый покер (видеопокер, Jacks or Better). "
    "5 карт, выбираете, что оставить, добираете остальное, выплата по "
    "таблице комбинаций.\n\n"
    "🎰 <b>/slots СТАВКА</b> — Слоты. Три барабана, мгновенный результат.\n\n"
    "💰 <b>/balance</b> — проверить свой баланс фишек.\n\n"
    "👑 <b>/give @username СУММА</b> или <b>/give все СУММА</b> — команда "
    "для админов чата, начисляет фишки."
)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(HELP_TEXT)
