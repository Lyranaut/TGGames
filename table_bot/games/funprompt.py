from __future__ import annotations

import asyncio

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import (
    FUNPROMPT_MIN_PLAYERS, FUNPROMPT_ROUNDS,
    FUNPROMPT_SUBMIT_TIME, FUNPROMPT_VOTE_TIME,
)
from core.registry import registry
from core.common import known_users
from core.utils import effective_thread_id
from core.content import random_funprompt

router = Router()

GAME_TYPE = "funprompt"
games: dict = {}  # (chat_id, thread_id) -> FunPromptGame


class FunPromptGame:
    def __init__(self, chat_id, thread_id, host_id):
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.host_id = host_id
        self.players: dict = {}          # user_id -> full_name
        self.state = "REGISTRATION"       # REGISTRATION | SUBMIT | VOTE
        self.scores: dict = {}
        self.round_number = 0
        self.used_prompts: set = set()
        self.current_prompt: str | None = None
        self.answers: dict = {}           # user_id -> текст ответа
        self.votes: dict = {}              # voter_id -> author_id
        self.reg_message_id = None


def registration_keyboard(game: FunPromptGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Вступить ({len(game.players)})", callback_data="fp_join")],
        [InlineKeyboardButton(text="▶️ Начать игру", callback_data="fp_start")],
        [InlineKeyboardButton(text="🚫 Отменить", callback_data="fp_cancel")],
    ])


def players_list_text(game: FunPromptGame) -> str:
    if not game.players:
        return "пока никто не вступил"
    return "\n".join(f"{i + 1}. {name}" for i, name in enumerate(game.players.values()))


def registration_text(game: FunPromptGame) -> str:
    return (
        "😂 <b>Придумай смешнее</b> (в духе Quiplash / Fibbage из Jackbox Party Pack)\n\n"
        "Каждый раунд всем даётся одна и та же фраза с пропуском — придумайте "
        "смешное продолжение в личке боту. Потом все ответы показываются "
        "анонимно, и вы голосуете за самый смешной чужой вариант.\n\n"
        "Нажмите «Вступить», чтобы участвовать.\n"
        "⚠️ Перед этим обязательно напишите мне в личные сообщения /start.\n\n"
        f"Минимум игроков: {FUNPROMPT_MIN_PLAYERS}\n\n"
        f"Участники:\n{players_list_text(game)}"
    )


@router.message(Command("funprompt"))
async def cmd_funprompt(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в групповом чате.")
        return

    thread_id = effective_thread_id(message)
    if registry.is_busy(message.chat.id, thread_id):
        await message.answer("В этом чате уже идёт другая игра. Дождитесь её окончания.")
        return

    game = FunPromptGame(message.chat.id, thread_id, message.from_user.id)
    games[(message.chat.id, thread_id)] = game
    registry.occupy(message.chat.id, thread_id, GAME_TYPE)

    sent = await message.answer(registration_text(game), reply_markup=registration_keyboard(game))
    game.reg_message_id = sent.message_id


async def refresh_registration_message(bot, game: FunPromptGame):
    try:
        await bot.edit_message_text(
            registration_text(game),
            chat_id=game.chat_id,
            message_id=game.reg_message_id,
            reply_markup=registration_keyboard(game),
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "fp_join")
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


@router.callback_query(F.data == "fp_cancel")
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


@router.callback_query(F.data == "fp_start")
async def cb_start(callback: CallbackQuery):
    key = (callback.message.chat.id, effective_thread_id(callback.message))
    game = games.get(key)
    if game is None or game.state != "REGISTRATION":
        await callback.answer("Игра уже идёт или отменена.", show_alert=True)
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("Начать игру может только тот, кто её создал.", show_alert=True)
        return
    if len(game.players) < FUNPROMPT_MIN_PLAYERS:
        await callback.answer(f"Нужно минимум {FUNPROMPT_MIN_PLAYERS} игроков.", show_alert=True)
        return

    unreachable = [uid for uid in game.players if uid not in known_users]
    if unreachable:
        names = ", ".join(game.players[uid] for uid in unreachable)
        await callback.answer("Не все игроки написали мне в личку.", show_alert=True)
        await callback.message.answer(f"Эти игроки должны написать мне /start в личку:\n{names}")
        return

    await callback.answer()
    await callback.message.edit_text("🎲 Игра начинается!")

    await run_round(callback.bot, game)


async def run_round(bot, game: FunPromptGame):
    if game.round_number >= FUNPROMPT_ROUNDS:
        await finish_game(bot, game)
        return

    game.round_number += 1
    game.state = "SUBMIT"
    game.answers = {}
    game.votes = {}
    game.current_prompt = random_funprompt(exclude=game.used_prompts)
    game.used_prompts.add(game.current_prompt)

    await bot.send_message(
        game.chat_id,
        f"📝 <b>Раунд {game.round_number}/{FUNPROMPT_ROUNDS}</b>\n\n"
        f"«{game.current_prompt}»\n\n"
        f"Пришлите мне в личку свой вариант! У вас {FUNPROMPT_SUBMIT_TIME} секунд.",
        message_thread_id=game.thread_id,
    )

    for uid in game.players:
        try:
            await bot.send_message(uid, f"📝 «{game.current_prompt}»\n\nОтветьте на это сообщение своим вариантом!")
        except Exception:
            pass

    await asyncio.sleep(FUNPROMPT_SUBMIT_TIME)
    await start_vote(bot, game)


@router.message(F.chat.type == "private")
async def on_private_answer(message: Message):
    if not message.text:
        return
    game = None
    for g in games.values():
        if g.state == "SUBMIT" and message.from_user.id in g.players:
            game = g
            break
    if game is None:
        return
    if message.from_user.id in game.answers:
        await message.answer("Вы уже отправили вариант в этом раунде.")
        return

    game.answers[message.from_user.id] = message.text.strip()
    await message.answer("✅ Принято! Ждём остальных.")


def vote_keyboard(game: FunPromptGame, entries: list) -> InlineKeyboardMarkup:
    buttons = []
    for i, (author_id, text) in enumerate(entries):
        label = text if len(text) <= 60 else text[:57] + "..."
        buttons.append([InlineKeyboardButton(
            text=f"{i + 1}. {label}",
            callback_data=f"fpvote:{game.chat_id}:{game.thread_id or 0}:{author_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def start_vote(bot, game: FunPromptGame):
    game.state = "VOTE"

    if not game.answers:
        await bot.send_message(
            game.chat_id, "Никто не прислал вариант — раунд пропущен.",
            message_thread_id=game.thread_id,
        )
        await run_round(bot, game)
        return

    import random as _random
    entries = list(game.answers.items())
    _random.shuffle(entries)
    game._vote_entries = entries

    text_lines = ["🗳 <b>Голосуем за самый смешной ответ!</b>", ""]
    for i, (author_id, text) in enumerate(entries):
        text_lines.append(f"{i + 1}. {text}")

    await bot.send_message(
        game.chat_id, "\n".join(text_lines),
        message_thread_id=game.thread_id,
        reply_markup=vote_keyboard(game, entries),
    )
    await asyncio.sleep(FUNPROMPT_VOTE_TIME)
    await resolve_vote(bot, game)


@router.callback_query(F.data.startswith("fpvote:"))
async def cb_vote(callback: CallbackQuery):
    _, chat_id, thread_id, author_id = callback.data.split(":")
    chat_id = int(chat_id)
    thread_id = int(thread_id) or None
    author_id = int(author_id)

    game = games.get((chat_id, thread_id))
    if game is None or game.state != "VOTE":
        await callback.answer("Голосование уже завершено.", show_alert=True)
        return
    voter_id = callback.from_user.id
    if voter_id not in game.players:
        await callback.answer("Голосовать могут только участники игры.", show_alert=True)
        return
    if author_id == voter_id:
        await callback.answer("Нельзя голосовать за свой вариант!", show_alert=True)
        return

    game.votes[voter_id] = author_id
    await callback.answer("Голос учтён!")


async def resolve_vote(bot, game: FunPromptGame):
    tally: dict = {}
    for author_id in game.votes.values():
        tally[author_id] = tally.get(author_id, 0) + 1

    lines = ["📢 <b>Результаты раунда:</b>", ""]
    for author_id, text in game._vote_entries:
        votes = tally.get(author_id, 0)
        lines.append(f"{game.players[author_id]}: «{text}» — {votes} 👍")
        game.scores[author_id] = game.scores.get(author_id, 0) + votes

    await bot.send_message(game.chat_id, "\n".join(lines), message_thread_id=game.thread_id)
    await run_round(bot, game)


async def finish_game(bot, game: FunPromptGame):
    ranking = sorted(game.scores.items(), key=lambda kv: kv[1], reverse=True)
    lines = ["🏁 <b>Игра окончена! Итоговый счёт:</b>", ""]
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, score) in enumerate(ranking):
        medal = medals[i] if i < 3 else "▪️"
        lines.append(f"{medal} {game.players.get(uid, '???')}: {score}")

    await bot.send_message(game.chat_id, "\n".join(lines), message_thread_id=game.thread_id)
    games.pop((game.chat_id, game.thread_id), None)
    registry.release(game.chat_id, game.thread_id)
