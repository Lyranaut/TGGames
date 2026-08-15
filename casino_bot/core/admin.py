from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from core.economy import add_balance, get_balance
from core.users_registry import resolve_username, chat_members

router = Router()


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    balance = get_balance(message.from_user.id)
    await message.reply(f"💰 Ваш баланс: <b>{balance}</b> фишек.")


@router.message(Command("give"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_give(message: Message):
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ("administrator", "creator"):
        await message.reply("Эта команда доступна только администраторам чата.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply(
            "Использование:\n"
            "<code>/give @username 500</code> — начислить конкретному игроку\n"
            "<code>/give все 500</code> — начислить всем, кто уже писал в этом чате"
        )
        return

    target_raw, amount_raw = parts[1], parts[2]
    try:
        amount = int(amount_raw)
    except ValueError:
        await message.reply("Сумма должна быть целым числом.")
        return
    if amount == 0:
        await message.reply("Сумма не может быть нулевой.")
        return

    target_clean = target_raw.lstrip("@").lower()

    if target_clean in ("все", "всем", "all"):
        members = chat_members(message.chat.id)
        if not members:
            await message.reply(
                "Пока не знаю никого из этого чата — пусть сначала кто-нибудь "
                "напишет любое сообщение, чтобы я его запомнил."
            )
            return
        for uid_str in members:
            add_balance(int(uid_str), amount)
        await message.reply(
            f"💰 Начислено {amount} фишек всем известным участникам чата ({len(members)} чел.)."
        )
        return

    target_id = resolve_username(target_raw)
    if target_id is None:
        await message.reply(
            "Не знаю пользователя с таким username — он должен хотя бы раз "
            "написать что-нибудь в чате, где я есть, чтобы я его запомнил."
        )
        return

    new_balance = add_balance(target_id, amount)
    await message.reply(f"💰 Начислено {amount} фишек пользователю @{target_clean}. Баланс: {new_balance}.")
