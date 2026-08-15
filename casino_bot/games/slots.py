from __future__ import annotations

import random

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import SLOTS_MIN_BET
from core.economy import add_balance, parse_bet, try_place_bet

router = Router()

SYMBOLS = ["🍒", "🍋", "🍊", "🔔", "⭐", "💎", "7️⃣"]

TRIPLE_MULTIPLIER = {
    "🍒": 8, "🍋": 8, "🍊": 10, "🔔": 15, "⭐": 20, "💎": 40, "7️⃣": 77,
}
PAIR_MULTIPLIER = 2


@router.message(Command("slots"))
async def cmd_slots(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(f"Использование: <code>/slots СТАВКА</code> (минимум {SLOTS_MIN_BET})")
        return

    amount, error = parse_bet(parts[1], message.from_user.id, SLOTS_MIN_BET)
    if error:
        await message.reply(error)
        return

    try_place_bet(message.from_user.id, amount)

    reels = [random.choice(SYMBOLS) for _ in range(3)]
    reel_text = " | ".join(reels)

    if reels[0] == reels[1] == reels[2]:
        multiplier = TRIPLE_MULTIPLIER[reels[0]]
        payout = amount * multiplier
        add_balance(message.from_user.id, payout)
        outcome = f"🎉 Три в ряд! Выплата ×{multiplier} — вы получаете {payout} фишек."
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        payout = amount * PAIR_MULTIPLIER
        add_balance(message.from_user.id, payout)
        outcome = f"🙂 Пара совпала! Выплата ×{PAIR_MULTIPLIER} — вы получаете {payout} фишек."
    else:
        outcome = f"😔 Не повезло. Ставка {amount} сгорела."

    await message.answer(f"🎰 [ {reel_text} ]\n\n{outcome}")
