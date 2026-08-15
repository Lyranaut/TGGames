from __future__ import annotations

import asyncio
import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from config import ROULETTE_MIN_BET, ROULETTE_BET_TIME
from core.economy import try_place_bet, add_balance, parse_bet

router = Router()

rounds: dict = {}  # (chat_id, thread_id) -> RouletteRound

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

BET_KEYWORDS = {
    "красное": "red", "red": "red", "кр": "red",
    "черное": "black", "чёрное": "black", "black": "black", "чер": "black",
    "чет": "even", "чёт": "even", "even": "even",
    "нечет": "odd", "нечёт": "odd", "odd": "odd",
    "меньше": "low", "low": "low",
    "больше": "high", "high": "high",
}

PAYOUT_MULTIPLIER = {
    "number": 35,
    "red": 1, "black": 1,
    "even": 1, "odd": 1,
    "low": 1, "high": 1,
}


class Bet:
    def __init__(self, user_id, bet_type, value, amount):
        self.user_id = user_id
        self.bet_type = bet_type   # "number" | "red" | "black" | "even" | "odd" | "low" | "high"
        self.value = value          # число для "number", иначе None
        self.amount = amount


class RouletteRound:
    def __init__(self, chat_id, thread_id):
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.bets: list = []
        self.open = True


def number_color(n: int) -> str:
    if n == 0:
        return "green"
    return "red" if n in RED_NUMBERS else "black"


def bet_wins(bet: Bet, winning_number: int) -> bool:
    color = number_color(winning_number)
    if bet.bet_type == "number":
        return bet.value == winning_number
    if winning_number == 0:
        return False  # зеро — все внешние ставки (цвет/чёт-нечет/половина) проигрывают
    if bet.bet_type == "red":
        return color == "red"
    if bet.bet_type == "black":
        return color == "black"
    if bet.bet_type == "even":
        return winning_number % 2 == 0
    if bet.bet_type == "odd":
        return winning_number % 2 == 1
    if bet.bet_type == "low":
        return 1 <= winning_number <= 18
    if bet.bet_type == "high":
        return 19 <= winning_number <= 36
    return False


@router.message(Command("roulette"))
async def cmd_roulette(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в групповом чате.")
        return

    thread_id = message.message_thread_id if message.is_topic_message else None
    key = (message.chat.id, thread_id)
    if key in rounds:
        await message.answer("Приём ставок уже идёт — присоединяйтесь командой /bet.")
        return

    round_ = RouletteRound(message.chat.id, thread_id)
    rounds[key] = round_

    await message.answer(
        "🎡 <b>Рулетка!</b>\n\n"
        f"Приём ставок открыт на {ROULETTE_BET_TIME} секунд.\n"
        "Ставьте командой <code>/bet ТИП СУММА</code>, например:\n"
        "<code>/bet 17 100</code> — на число (выплата 35:1)\n"
        "<code>/bet красное 100</code> / <code>/bet черное 100</code> — на цвет (1:1)\n"
        "<code>/bet чет 100</code> / <code>/bet нечет 100</code> — чёт/нечет (1:1)\n"
        "<code>/bet меньше 100</code> (1-18) / <code>/bet больше 100</code> (19-36) — 1:1",
        message_thread_id=thread_id,
    )

    await asyncio.sleep(ROULETTE_BET_TIME)
    await spin(message.bot, round_)


@router.message(Command("bet"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_bet(message: Message):
    thread_id = message.message_thread_id if message.is_topic_message else None
    key = (message.chat.id, thread_id)
    round_ = rounds.get(key)
    if round_ is None or not round_.open:
        await message.reply("Сейчас приём ставок закрыт. Откройте раунд командой /roulette.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply("Использование: <code>/bet ТИП СУММА</code>, например <code>/bet красное 100</code>")
        return

    bet_type_raw, amount_raw = parts[1].lower(), parts[2]
    amount, error = parse_bet(amount_raw, message.from_user.id, ROULETTE_MIN_BET)
    if error:
        await message.reply(error)
        return

    if bet_type_raw.isdigit() and 0 <= int(bet_type_raw) <= 36:
        bet_type, value = "number", int(bet_type_raw)
    elif bet_type_raw in BET_KEYWORDS:
        bet_type, value = BET_KEYWORDS[bet_type_raw], None
    else:
        await message.reply("Не распознал тип ставки. Число 0-36, или: красное/черное/чет/нечет/меньше/больше.")
        return

    if not try_place_bet(message.from_user.id, amount):
        await message.reply("Не удалось списать ставку — недостаточно фишек.")
        return

    round_.bets.append(Bet(message.from_user.id, bet_type, value, amount))
    await message.reply(f"✅ Ставка принята: {amount} фишек.")


async def spin(bot, round_: RouletteRound):
    round_.open = False
    rounds.pop((round_.chat_id, round_.thread_id), None)

    winning_number = random.randint(0, 36)
    color = number_color(winning_number)
    color_emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[color]

    if not round_.bets:
        await bot.send_message(
            round_.chat_id,
            f"🎡 Выпало: {color_emoji} <b>{winning_number}</b>\nНикто не сделал ставок.",
            message_thread_id=round_.thread_id,
        )
        return

    lines = [f"🎡 Выпало: {color_emoji} <b>{winning_number}</b>", ""]
    for bet in round_.bets:
        if bet_wins(bet, winning_number):
            multiplier = PAYOUT_MULTIPLIER[bet.bet_type]
            payout = bet.amount * (multiplier + 1)
            add_balance(bet.user_id, payout)
            lines.append(f"✅ <a href=\"tg://user?id={bet.user_id}\">игрок</a>: +{payout} фишек")
        else:
            lines.append(f"❌ <a href=\"tg://user?id={bet.user_id}\">игрок</a>: -{bet.amount} фишек")

    await bot.send_message(round_.chat_id, "\n".join(lines), message_thread_id=round_.thread_id)
