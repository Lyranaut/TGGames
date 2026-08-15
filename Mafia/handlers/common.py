from __future__ import annotations

import json
import os

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()

KNOWN_USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "known_users.json")


def load_known_users() -> set:
    if os.path.exists(KNOWN_USERS_FILE):
        try:
            with open(KNOWN_USERS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_known_users(users: set) -> None:
    with open(KNOWN_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(users), f)


# Множество user_id, которые хотя бы раз написали боту в личку —
# только им бот сможет отправить роль и кнопки ночных действий.
known_users: set = load_known_users()


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start_private(message: Message):
    known_users.add(message.from_user.id)
    save_known_users(known_users)
    await message.answer(
        "Привет! Я бот для игры в Мафию 🎭\n\n"
        "Теперь я смогу писать тебе в личные сообщения — можешь спокойно "
        "нажимать «Вступить» в игре в чате.\n"
        "Когда игра начнётся, я пришлю сюда твою роль и все инструкции по "
        "ночным действиям."
    )
