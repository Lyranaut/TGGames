from __future__ import annotations

import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import WHOAMI_MIN_PLAYERS
from core.registry import registry
from core.common import known_users
from core.utils import effective_thread_id, normalize
from core.content import random_whoami_identities

router = Router()

GAME_TYPE = "whoami"
games: dict = {}  # (chat_id, thread_id) -> WhoAmIGame


class WhoAmIGame:
    def __init__(self, chat_id, thread_id, host_id):
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.host_id = host_id
        self.players: dict = {}         # user_id -> full_name
        self.state = "REGISTRATION"      # REGISTRATION | PLAYING
        self.identities: dict = {}        # user_id -> идентичность
        self.solved_order: list = []       # порядок отгадавших
        self.reg_message_id = None


def registration_keyboard(game: WhoAmIGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Вступить ({len(game.players)})", callback_data="whoami_join")],
        [InlineKeyboardButton(text="▶️ Начать игру", callback_data="whoami_start")],
        [InlineKeyboardButton(text="🚫 Отменить", callback_data="whoami_cancel")],
    ])


def players_list_text(game: WhoAmIGame) -> str:
    if not game.players:
        return "пока никто не вступил"
    return "\n".join(f"{i + 1}. {name}" for i, name in enumerate(game.players.values()))


def registration_text(game: WhoAmIGame) -> str:
    return (
        "🎭 <b>Кто я?</b>\n\n"
        "Каждому достанется тайная личность — все остальные её узнают, кроме "
        "вас самих. Задавайте в чате вопросы (да/нет) и пробуйте отгадать "
        "себя командой <code>/answer ваш ответ</code>.\n\n"
        "Нажмите «Вступить», чтобы участвовать.\n"
        "⚠️ Перед этим обязательно напишите мне в личные сообщения /start.\n\n"
        f"Минимум игроков: {WHOAMI_MIN_PLAYERS}\n\n"
        f"Участники:\n{players_list_text(game)}"
    )


@router.message(Command("whoami"))
async def cmd_whoami(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в групповом чате.")
        return

    thread_id = effective_thread_id(message)
    if registry.is_busy(message.chat.id, thread_id):
        await message.answer("В этом чате уже идёт другая игра. Дождитесь её окончания.")
        return

    game = WhoAmIGame(message.chat.id, thread_id, message.from_user.id)
    games[(message.chat.id, thread_id)] = game
    registry.occupy(message.chat.id, thread_id, GAME_TYPE)

    sent = await message.answer(registration_text(game), reply_markup=registration_keyboard(game))
    game.reg_message_id = sent.message_id


async def refresh_registration_message(bot, game: WhoAmIGame):
    try:
        await bot.edit_message_text(
            registration_text(game),
            chat_id=game.chat_id,
            message_id=game.reg_message_id,
            reply_markup=registration_keyboard(game),
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "whoami_join")
async def cb_join(callback: CallbackQuery):
    game = games.get((callback.message.chat.id, effective_thread_id(callback.message)))
    if game is None or game.state != "REGISTRATION":
        await callback.answer("Регистрация закрыта.", show_alert=True)
        return
    user = callback.from_user
    if user.id in game.players:
        await callback.answer("Вы уже в игре.")
        return
    game.players[user.id] = user.full_name
    await callback.answer("Вы вступили в игру!")
    await refresh_registration_message(callback.bot, game)


@router.callback_query(F.data == "whoami_cancel")
async def cb_cancel(callback: CallbackQuery):
    key = (callback.message.chat.id, effective_thread_id(callback.message))
    game = games.get(key)
    if game is None:
        await callback.answer()
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("Отменить игру может только тот, кто её создал.", show_alert=True)
        return
    games.pop(key, None)
    registry.release(game.chat_id, game.thread_id)
    await callback.answer("Игра отменена.")
    await callback.message.edit_text("🚫 Игра отменена.")


@router.callback_query(F.data == "whoami_start")
async def cb_start(callback: CallbackQuery):
    key = (callback.message.chat.id, effective_thread_id(callback.message))
    game = games.get(key)
    if game is None or game.state != "REGISTRATION":
        await callback.answer("Игра уже идёт или отменена.", show_alert=True)
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("Начать игру может только тот, кто её создал.", show_alert=True)
        return
    if len(game.players) < WHOAMI_MIN_PLAYERS:
        await callback.answer(f"Нужно минимум {WHOAMI_MIN_PLAYERS} игроков.", show_alert=True)
        return

    unreachable = [uid for uid in game.players if uid not in known_users]
    if unreachable:
        names = ", ".join(game.players[uid] for uid in unreachable)
        await callback.answer("Не все игроки написали мне в личку.", show_alert=True)
        await callback.message.answer(f"Эти игроки должны написать мне /start в личку:\n{names}")
        return

    await callback.answer()

    player_ids = list(game.players.keys())
    identities = random_whoami_identities(len(player_ids))
    game.identities = dict(zip(player_ids, identities))
    game.state = "PLAYING"

    await callback.message.edit_text(
        "🎲 Игра начинается! Каждому в личку разослали личности остальных.\n\n"
        "Задавайте вопросы да/нет в чат, а когда думаете, что знаете ответ — "
        "пишите <code>/answer ваш ответ</code>."
    )

    bot = callback.bot
    for viewer_id in player_ids:
        lines = ["🎭 <b>Личности игроков:</b>", ""]
        for owner_id in player_ids:
            if owner_id == viewer_id:
                continue
            lines.append(f"{game.players[owner_id]}: <b>{game.identities[owner_id]}</b>")
        try:
            await bot.send_message(viewer_id, "\n".join(lines))
        except TelegramForbiddenError:
            pass

    await bot.send_message(
        game.chat_id,
        f"🎭 Игра началась! Игроков: {len(player_ids)}. Удачи в отгадывании!",
        message_thread_id=game.thread_id,
    )


@router.message(Command("answer"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_answer(message: Message):
    key = (message.chat.id, effective_thread_id(message))
    game = games.get(key)
    if game is None or game.state != "PLAYING":
        return

    user_id = message.from_user.id
    if user_id not in game.identities:
        return
    if user_id in game.solved_order:
        await message.reply("Вы уже отгадали свою личность!")
        return

    guess_text = message.text.partition(" ")[2].strip()
    if not guess_text:
        await message.reply("Использование: <code>/answer ваш ответ</code>")
        return

    real_identity = game.identities[user_id]
    if normalize(guess_text) == normalize(real_identity):
        game.solved_order.append(user_id)
        place = len(game.solved_order)
        await message.answer(
            f"🎉 Верно! {message.from_user.full_name} — это <b>{real_identity}</b>! "
            f"(отгадал(а) {place}-м(ой))"
        )
        remaining = [uid for uid in game.identities if uid not in game.solved_order]
        if not remaining:
            await finish_game(message.bot, game)
    else:
        await message.reply("❌ Не угадали, попробуйте ещё!")


@router.message(Command("whoami_stop"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_whoami_stop(message: Message):
    key = (message.chat.id, effective_thread_id(message))
    game = games.get(key)
    if game is None:
        await message.answer("Сейчас в этой ветке нет активной игры «Кто я?».")
        return
    if message.from_user.id != game.host_id:
        await message.answer("Закончить игру может только тот, кто её создал.")
        return
    await finish_game(message.bot, game)


async def finish_game(bot, game: WhoAmIGame):
    lines = ["🏁 <b>Игра окончена! Все личности:</b>", ""]
    for uid, identity in game.identities.items():
        place = ""
        if uid in game.solved_order:
            place = f" (место {game.solved_order.index(uid) + 1})"
        lines.append(f"{game.players[uid]}: <b>{identity}</b>{place}")

    await bot.send_message(game.chat_id, "\n".join(lines), message_thread_id=game.thread_id)
    games.pop((game.chat_id, game.thread_id), None)
    registry.release(game.chat_id, game.thread_id)
