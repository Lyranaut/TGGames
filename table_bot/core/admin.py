# ФАЙЛ ДЛЯ ПАПКИ: table_bot
# КУДА ВСТАВЛЯТЬ: table_bot\core\admin.py  (новый файл)

from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from core.registry import registry
from core.utils import effective_thread_id
from games import crocodile, hangman, whoami, elias, funprompt, quiz

router = Router()

_GAME_MODULES = (crocodile, hangman, whoami, elias, funprompt, quiz)


@router.message(Command("force_stop"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_force_stop(message: Message):
    """Сбрасывает зависшую игру в этой ветке — на случай, если какая-то из
    игр упала с ошибкой посреди старта и не успела освободить чат."""
    thread_id = effective_thread_id(message)
    key = (message.chat.id, thread_id)

    was_busy = registry.is_busy(message.chat.id, thread_id)
    removed_any = False
    for module in _GAME_MODULES:
        if key in module.games:
            module.games.pop(key, None)
            removed_any = True

    registry.release(message.chat.id, thread_id)

    if was_busy or removed_any:
        await message.answer("🛠 Сброшено. Можно начинать новую игру.")
    else:
        await message.answer("Здесь и так нет активной игры.")