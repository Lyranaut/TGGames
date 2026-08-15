from __future__ import annotations

import asyncio
import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.dispatcher.event.bases import SkipHandler

from config import ELIAS_ROUND_TIME, ELIAS_ROUNDS_PER_TEAM
from core.registry import registry
from core.common import known_users
from core.utils import effective_thread_id, contains_word
from core.wordbank import draw_party_words, PARTY_WORDS

router = Router()

GAME_TYPE = "elias"
games: dict = {}  # (chat_id, thread_id) -> EliasGame

_guess_events: dict = {}


class EliasGame:
    def __init__(self, chat_id, thread_id, host_id):
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.host_id = host_id
        self.players: dict = {}          # user_id -> full_name, ровно 4 нужно
        self.state = "REGISTRATION"       # REGISTRATION | ROUND
        self.team_a: list = []             # [user_id, user_id]
        self.team_b: list = []
        self.scores = {"A": 0, "B": 0}
        self.turn_index = 0                # индекс захода (0..2*ELIAS_ROUNDS_PER_TEAM-1)
        self.word_pool: list = []
        self.word_index = 0
        self.current_word: str | None = None
        self.explainer_id: int | None = None
        self.guesser_id: int | None = None
        self.reg_message_id = None


def registration_keyboard(game: EliasGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Вступить ({len(game.players)}/4)", callback_data="elias_join")],
        [InlineKeyboardButton(text="▶️ Начать игру", callback_data="elias_start")],
        [InlineKeyboardButton(text="🚫 Отменить", callback_data="elias_cancel")],
    ])


def players_list_text(game: EliasGame) -> str:
    if not game.players:
        return "пока никто не вступил"
    return "\n".join(f"{i + 1}. {name}" for i, name in enumerate(game.players.values()))


def registration_text(game: EliasGame) -> str:
    return (
        "🗣 <b>Элиас 2 на 2</b> (командный Крокодил словами)\n\n"
        "Нужно ровно 4 игрока — команды по 2 составятся случайно. Один "
        "объясняет слово словами (без однокоренных), партнёр отгадывает в "
        "чат, бот сам ловит верный ответ и сразу выдаёт следующее слово.\n\n"
        "Нажмите «Вступить», чтобы участвовать.\n"
        "⚠️ Перед этим обязательно напишите мне в личные сообщения /start.\n\n"
        f"Участники:\n{players_list_text(game)}"
    )


@router.message(Command("elias"))
async def cmd_elias(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в групповом чате.")
        return

    thread_id = effective_thread_id(message)
    if registry.is_busy(message.chat.id, thread_id):
        await message.answer("В этом чате уже идёт другая игра. Дождитесь её окончания.")
        return

    game = EliasGame(message.chat.id, thread_id, message.from_user.id)
    games[(message.chat.id, thread_id)] = game
    registry.occupy(message.chat.id, thread_id, GAME_TYPE)

    sent = await message.answer(registration_text(game), reply_markup=registration_keyboard(game))
    game.reg_message_id = sent.message_id


async def refresh_registration_message(bot, game: EliasGame):
    try:
        await bot.edit_message_text(
            registration_text(game),
            chat_id=game.chat_id,
            message_id=game.reg_message_id,
            reply_markup=registration_keyboard(game),
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "elias_join")
async def cb_join(callback: CallbackQuery):
    game = games.get((callback.message.chat.id, effective_thread_id(callback.message)))
    if game is None or game.state != "REGISTRATION":
        await callback.answer("Регистрация закрыта.", show_alert=True)
        return
    if len(game.players) >= 4:
        await callback.answer("Уже набрано 4 игрока.", show_alert=True)
        return
    user = callback.from_user
    if user.id in game.players:
        await callback.answer("Вы уже в игре.")
        return
    game.players[user.id] = user.full_name
    await callback.answer("Вы вступили в игру!")
    await refresh_registration_message(callback.bot, game)


@router.callback_query(F.data == "elias_cancel")
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


@router.callback_query(F.data == "elias_start")
async def cb_start(callback: CallbackQuery):
    key = (callback.message.chat.id, effective_thread_id(callback.message))
    game = games.get(key)
    if game is None or game.state != "REGISTRATION":
        await callback.answer("Игра уже идёт или отменена.", show_alert=True)
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("Начать игру может только тот, кто её создал.", show_alert=True)
        return
    if len(game.players) != 4:
        await callback.answer("Нужно ровно 4 игрока.", show_alert=True)
        return

    unreachable = [uid for uid in game.players if uid not in known_users]
    if unreachable:
        names = ", ".join(game.players[uid] for uid in unreachable)
        await callback.answer("Не все игроки написали мне в личку.", show_alert=True)
        await callback.message.answer(f"Эти игроки должны написать мне /start в личку:\n{names}")
        return

    await callback.answer()

    ids = list(game.players.keys())
    random.shuffle(ids)
    game.team_a = ids[:2]
    game.team_b = ids[2:]
    game.state = "ROUND"
    # с запасом слов на все заходы + пара лишних на случай неудачных попыток
    game.word_pool = draw_party_words(min(len(PARTY_WORDS), 60))
    game.word_index = 0

    team_text = (
        f"🎲 Игра начинается!\n\n"
        f"🔴 Команда А: {game.players[game.team_a[0]]} + {game.players[game.team_a[1]]}\n"
        f"🔵 Команда Б: {game.players[game.team_b[0]]} + {game.players[game.team_b[1]]}"
    )
    await callback.message.edit_text(team_text)

    await run_turn(callback.bot, game)


def _team_for_turn(game: EliasGame):
    total_turns = ELIAS_ROUNDS_PER_TEAM * 2
    is_team_a = game.turn_index % 2 == 0
    team = game.team_a if is_team_a else game.team_b
    team_letter = "A" if is_team_a else "B"
    # чередуем, кто в паре объясняет в разные заходы этой команды
    turn_number_for_team = game.turn_index // 2
    if turn_number_for_team % 2 == 0:
        explainer, guesser = team[0], team[1]
    else:
        explainer, guesser = team[1], team[0]
    return team_letter, explainer, guesser


async def run_turn(bot, game: EliasGame):
    total_turns = ELIAS_ROUNDS_PER_TEAM * 2
    if game.turn_index >= total_turns:
        await finish_game(bot, game)
        return

    team_letter, explainer_id, guesser_id = _team_for_turn(game)
    game.explainer_id = explainer_id
    game.guesser_id = guesser_id

    team_name = "🔴 Команда А" if team_letter == "A" else "🔵 Команда Б"
    await bot.send_message(
        game.chat_id,
        f"{team_name}: объясняет {game.players[explainer_id]}, отгадывает "
        f"{game.players[guesser_id]}. У вас {ELIAS_ROUND_TIME} секунд на весь заход!",
        message_thread_id=game.thread_id,
    )

    await next_word(bot, game)
    asyncio.create_task(_turn_timer(bot, game, game.turn_index))


async def next_word(bot, game: EliasGame):
    if game.word_index >= len(game.word_pool):
        game.word_pool += draw_party_words(20)

    game.current_word = game.word_pool[game.word_index]
    game.word_index += 1

    try:
        await bot.send_message(game.explainer_id, f"🗣 Слово: <b>{game.current_word}</b>")
    except Exception:
        pass


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message):
    if not message.text:
        raise SkipHandler
    key = (message.chat.id, effective_thread_id(message))
    game = games.get(key)
    if game is None or game.state != "ROUND":
        raise SkipHandler

    if message.from_user.id == game.explainer_id:
        if game.current_word and contains_word(message.text, game.current_word):
            try:
                await message.delete()
            except Exception:
                pass
        return

    if message.from_user.id != game.guesser_id:
        return

    if game.current_word and contains_word(message.text, game.current_word):
        team_letter, _, _ = _team_for_turn(game)
        game.scores[team_letter] += 1
        await message.reply(f"✅ Верно! +1 команде {'А' if team_letter == 'A' else 'Б'} (счёт {game.scores['A']}:{game.scores['B']})")
        await next_word(message.bot, game)


async def _turn_timer(bot, game: EliasGame, turn_index: int):
    await asyncio.sleep(ELIAS_ROUND_TIME)
    if game.turn_index == turn_index and game.state == "ROUND":
        await bot.send_message(
            game.chat_id,
            f"⏱ Время вышло! Счёт: 🔴 {game.scores['A']} — 🔵 {game.scores['B']}",
            message_thread_id=game.thread_id,
        )
        game.turn_index += 1
        await run_turn(bot, game)


async def finish_game(bot, game: EliasGame):
    if game.scores["A"] > game.scores["B"]:
        winner = "🔴 Команда А побеждает!"
    elif game.scores["B"] > game.scores["A"]:
        winner = "🔵 Команда Б побеждает!"
    else:
        winner = "🤝 Ничья!"

    await bot.send_message(
        game.chat_id,
        f"🏁 <b>Игра окончена!</b>\n\n"
        f"🔴 Команда А: {game.scores['A']}\n🔵 Команда Б: {game.scores['B']}\n\n{winner}",
        message_thread_id=game.thread_id,
    )
    games.pop((game.chat_id, game.thread_id), None)
    registry.release(game.chat_id, game.thread_id)
