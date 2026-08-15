from __future__ import annotations

import asyncio

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.dispatcher.event.bases import SkipHandler

from config import CROCODILE_MIN_PLAYERS, CROCODILE_ROUND_TIME
from core.registry import registry
from core.common import known_users
from core.utils import effective_thread_id, contains_word
from core.wordbank import draw_party_words

router = Router()

GAME_TYPE = "crocodile"
games: dict = {}  # (chat_id, thread_id) -> CrocodileGame

# (chat_id, thread_id) -> asyncio.Event, взводится при верной отгадке
_guess_events: dict = {}


class CrocodileGame:
    def __init__(self, chat_id, thread_id, host_id):
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.host_id = host_id
        self.players: dict = {}          # user_id -> full_name
        self.state = "REGISTRATION"       # REGISTRATION | ROUND
        self.order: list = []
        self.round_index = 0
        self.scores: dict = {}            # user_id -> очки
        self.word_pool: list = []
        self.current_word: str | None = None
        self.presenter_id: int | None = None
        self.reg_message_id = None


def registration_keyboard(game: CrocodileGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Вступить ({len(game.players)})", callback_data="croc_join")],
        [InlineKeyboardButton(text="▶️ Начать игру", callback_data="croc_start")],
        [InlineKeyboardButton(text="🚫 Отменить", callback_data="croc_cancel")],
    ])


def players_list_text(game: CrocodileGame) -> str:
    if not game.players:
        return "пока никто не вступил"
    return "\n".join(f"{i + 1}. {name}" for i, name in enumerate(game.players.values()))


def registration_text(game: CrocodileGame) -> str:
    return (
        "🐊 <b>Крокодил</b>\n\n"
        "Один игрок получает слово в личку и объясняет его словами (без "
        "самого слова и однокоренных), остальные пишут догадки прямо в чат — "
        "бот сам поймает правильный ответ.\n\n"
        "Нажмите «Вступить», чтобы участвовать.\n"
        "⚠️ Перед этим обязательно напишите мне в личные сообщения /start.\n\n"
        f"Минимум игроков: {CROCODILE_MIN_PLAYERS}\n\n"
        f"Участники:\n{players_list_text(game)}"
    )


@router.message(Command("crocodile"))
async def cmd_crocodile(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в групповом чате.")
        return

    thread_id = effective_thread_id(message)
    if registry.is_busy(message.chat.id, thread_id):
        await message.answer("В этом чате уже идёт другая игра. Дождитесь её окончания.")
        return

    game = CrocodileGame(message.chat.id, thread_id, message.from_user.id)
    games[(message.chat.id, thread_id)] = game
    registry.occupy(message.chat.id, thread_id, GAME_TYPE)

    sent = await message.answer(registration_text(game), reply_markup=registration_keyboard(game))
    game.reg_message_id = sent.message_id


async def refresh_registration_message(bot, game: CrocodileGame):
    try:
        await bot.edit_message_text(
            registration_text(game),
            chat_id=game.chat_id,
            message_id=game.reg_message_id,
            reply_markup=registration_keyboard(game),
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "croc_join")
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
    game.scores[user.id] = 0
    await callback.answer("Вы вступили в игру!")
    await refresh_registration_message(callback.bot, game)


@router.callback_query(F.data == "croc_cancel")
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


@router.callback_query(F.data == "croc_start")
async def cb_start(callback: CallbackQuery):
    key = (callback.message.chat.id, effective_thread_id(callback.message))
    game = games.get(key)
    if game is None or game.state != "REGISTRATION":
        await callback.answer("Игра уже идёт или отменена.", show_alert=True)
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("Начать игру может только тот, кто её создал.", show_alert=True)
        return
    if len(game.players) < CROCODILE_MIN_PLAYERS:
        await callback.answer(f"Нужно минимум {CROCODILE_MIN_PLAYERS} игроков.", show_alert=True)
        return

    unreachable = [uid for uid in game.players if uid not in known_users]
    if unreachable:
        names = ", ".join(game.players[uid] for uid in unreachable)
        await callback.answer("Не все игроки написали мне в личку.", show_alert=True)
        await callback.message.answer(f"Эти игроки должны написать мне /start в личку:\n{names}")
        return

    await callback.answer()
    await callback.message.edit_text("🎲 Игра начинается!")

    game.order = list(game.players.keys())
    game.round_index = 0
    game.word_pool = draw_party_words(len(game.order))
    game.state = "ROUND"

    await run_round(callback.bot, game)


async def run_round(bot, game: CrocodileGame):
    if game.round_index >= len(game.order):
        await finish_game(bot, game)
        return

    presenter_id = game.order[game.round_index]
    game.presenter_id = presenter_id
    game.current_word = game.word_pool[game.round_index]

    presenter_name = game.players[presenter_id]
    await bot.send_message(
        game.chat_id,
        f"🐊 Раунд {game.round_index + 1}/{len(game.order)}. Объясняет {presenter_name}!\n"
        f"У вас {CROCODILE_ROUND_TIME} секунд. Отгадки пишите прямо в чат.",
        message_thread_id=game.thread_id,
    )
    try:
        await bot.send_message(presenter_id, f"🐊 Ваше слово: <b>{game.current_word}</b>\nОбъясняйте в чате, не называя его напрямую!")
    except Exception:
        pass

    key = (game.chat_id, game.thread_id)
    event = asyncio.Event()
    _guess_events[key] = event
    game._winner_id = None

    try:
        await asyncio.wait_for(event.wait(), timeout=CROCODILE_ROUND_TIME)
    except asyncio.TimeoutError:
        await bot.send_message(
            game.chat_id,
            f"⏱ Время вышло! Загаданное слово было: <b>{game.current_word}</b>.",
            message_thread_id=game.thread_id,
        )
    finally:
        _guess_events.pop(key, None)

    game.round_index += 1
    await run_round(bot, game)


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message):
    if not message.text:
        raise SkipHandler
    key = (message.chat.id, effective_thread_id(message))
    game = games.get(key)
    if game is None or game.state != "ROUND":
        raise SkipHandler

    # Ведущий не должен произносить загаданное слово сам
    if message.from_user.id == game.presenter_id:
        if game.current_word and contains_word(message.text, game.current_word):
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.answer("⚠️ Нельзя называть само слово! Опишите его другими словами.")
            except Exception:
                pass
        return

    if game.current_word and contains_word(message.text, game.current_word):
        game.scores[message.from_user.id] = game.scores.get(message.from_user.id, 0) + 1
        game.scores[game.presenter_id] = game.scores.get(game.presenter_id, 0) + 1
        await message.reply(
            f"✅ Верно! Слово было: <b>{game.current_word}</b>. Очко {message.from_user.full_name} и ведущему!"
        )
        event = _guess_events.get(key)
        if event is not None:
            event.set()


async def finish_game(bot, game: CrocodileGame):
    ranking = sorted(game.scores.items(), key=lambda kv: kv[1], reverse=True)
    lines = ["🏁 <b>Игра окончена! Итоговый счёт:</b>", ""]
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, score) in enumerate(ranking):
        medal = medals[i] if i < 3 else "▪️"
        lines.append(f"{medal} {game.players.get(uid, '???')}: {score}")

    await bot.send_message(game.chat_id, "\n".join(lines), message_thread_id=game.thread_id)
    games.pop((game.chat_id, game.thread_id), None)
    registry.release(game.chat_id, game.thread_id)
