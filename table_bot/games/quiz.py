from __future__ import annotations

import asyncio

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.dispatcher.event.bases import SkipHandler

from config import QUIZ_MIN_PLAYERS, QUIZ_ROUNDS, QUIZ_QUESTION_TIME
from core.registry import registry
from core.utils import effective_thread_id, normalize
from core.content import draw_quiz_questions

router = Router()

GAME_TYPE = "quiz"
games: dict = {}  # (chat_id, thread_id) -> QuizGame

_answer_events: dict = {}


class QuizGame:
    def __init__(self, chat_id, thread_id, host_id):
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.host_id = host_id
        self.players: dict = {}          # user_id -> full_name, пополняется по ходу игры
        self.state = "REGISTRATION"       # REGISTRATION | ROUND
        self.scores: dict = {}
        self.questions: list = []
        self.round_index = 0
        self.current_answer: str | None = None
        self.reg_message_id = None


def registration_keyboard(game: QuizGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Вступить ({len(game.players)})", callback_data="quiz_join")],
        [InlineKeyboardButton(text="▶️ Начать игру", callback_data="quiz_start")],
        [InlineKeyboardButton(text="🚫 Отменить", callback_data="quiz_cancel")],
    ])


def players_list_text(game: QuizGame) -> str:
    if not game.players:
        return "пока никто не вступил"
    return "\n".join(f"{i + 1}. {name}" for i, name in enumerate(game.players.values()))


def registration_text(game: QuizGame) -> str:
    return (
        "🧠 <b>Викторина</b>\n\n"
        "Вопрос — прямо в чат, кто первым напишет верный ответ, тот получает "
        "очко. Личные сообщения не нужны, отвечать можно всем в чате, даже "
        "не вступившим заранее.\n\n"
        "Нажмите «Вступить» (или просто отвечайте по ходу игры — вступите "
        "автоматически) и «Начать», когда будете готовы.\n\n"
        f"Минимум игроков: {QUIZ_MIN_PLAYERS}\n\n"
        f"Участники:\n{players_list_text(game)}"
    )


@router.message(Command("quiz"))
async def cmd_quiz(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в групповом чате.")
        return

    thread_id = effective_thread_id(message)
    if registry.is_busy(message.chat.id, thread_id):
        await message.answer("В этом чате уже идёт другая игра. Дождитесь её окончания.")
        return

    game = QuizGame(message.chat.id, thread_id, message.from_user.id)
    games[(message.chat.id, thread_id)] = game
    registry.occupy(message.chat.id, thread_id, GAME_TYPE)

    sent = await message.answer(registration_text(game), reply_markup=registration_keyboard(game))
    game.reg_message_id = sent.message_id


async def refresh_registration_message(bot, game: QuizGame):
    try:
        await bot.edit_message_text(
            registration_text(game),
            chat_id=game.chat_id,
            message_id=game.reg_message_id,
            reply_markup=registration_keyboard(game),
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "quiz_join")
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


@router.callback_query(F.data == "quiz_cancel")
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


@router.callback_query(F.data == "quiz_start")
async def cb_start(callback: CallbackQuery):
    key = (callback.message.chat.id, effective_thread_id(callback.message))
    game = games.get(key)
    if game is None or game.state != "REGISTRATION":
        await callback.answer("Игра уже идёт или отменена.", show_alert=True)
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("Начать игру может только тот, кто её создал.", show_alert=True)
        return
    if len(game.players) < QUIZ_MIN_PLAYERS:
        await callback.answer(f"Нужно минимум {QUIZ_MIN_PLAYERS} игроков.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text("🎲 Игра начинается!")

    game.questions = draw_quiz_questions(QUIZ_ROUNDS)
    game.round_index = 0
    game.state = "ROUND"

    await run_round(callback.bot, game)


async def run_round(bot, game: QuizGame):
    if game.round_index >= len(game.questions):
        await finish_game(bot, game)
        return

    question, answer = game.questions[game.round_index]
    game.current_answer = answer

    await bot.send_message(
        game.chat_id,
        f"❓ <b>Вопрос {game.round_index + 1}/{len(game.questions)}:</b>\n{question}\n\n"
        f"У вас {QUIZ_QUESTION_TIME} секунд.",
        message_thread_id=game.thread_id,
    )

    key = (game.chat_id, game.thread_id)
    event = asyncio.Event()
    _answer_events[key] = event

    try:
        await asyncio.wait_for(event.wait(), timeout=QUIZ_QUESTION_TIME)
    except asyncio.TimeoutError:
        await bot.send_message(
            game.chat_id, f"⏱ Время вышло! Правильный ответ: <b>{answer}</b>.",
            message_thread_id=game.thread_id,
        )
    finally:
        _answer_events.pop(key, None)

    game.round_index += 1
    await run_round(bot, game)


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message):
    if not message.text:
        raise SkipHandler
    key = (message.chat.id, effective_thread_id(message))
    game = games.get(key)
    if game is None or game.state != "ROUND" or game.current_answer is None:
        raise SkipHandler

    if normalize(message.text) == normalize(game.current_answer):
        uid = message.from_user.id
        if uid not in game.players:
            game.players[uid] = message.from_user.full_name
            game.scores[uid] = 0
        game.scores[uid] = game.scores.get(uid, 0) + 1
        await message.reply(f"✅ Верно! Очко {message.from_user.full_name}!")
        game.current_answer = None
        event = _answer_events.get(key)
        if event is not None:
            event.set()


async def finish_game(bot, game: QuizGame):
    ranking = sorted(game.scores.items(), key=lambda kv: kv[1], reverse=True)
    lines = ["🏁 <b>Викторина окончена! Итоговый счёт:</b>", ""]
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, score) in enumerate(ranking):
        medal = medals[i] if i < 3 else "▪️"
        lines.append(f"{medal} {game.players.get(uid, '???')}: {score}")

    await bot.send_message(game.chat_id, "\n".join(lines), message_thread_id=game.thread_id)
    games.pop((game.chat_id, game.thread_id), None)
    registry.release(game.chat_id, game.thread_id)
