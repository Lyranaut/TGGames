from __future__ import annotations

import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import MIN_PLAYERS, BUNKER_CAPACITY_RATIO, MIN_CAPACITY
from game.manager import GameManager
from game.models import Game, GameState, Player
from game.cards import CATASTROPHES, BUNKERS, deal_cards, format_full_card
from handlers.common import known_users

router = Router()


def registration_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Вступить ({len(game.players)})", callback_data="bunker_join")],
        [InlineKeyboardButton(text="▶️ Начать игру", callback_data="bunker_start")],
        [InlineKeyboardButton(text="🚫 Отменить", callback_data="bunker_cancel")],
    ])


def players_list_text(game: Game) -> str:
    if not game.players:
        return "пока никто не вступил"
    return "\n".join(f"{i + 1}. {p.full_name}" for i, p in enumerate(game.players.values()))


def registration_text(game: Game) -> str:
    return (
        "🕳 <b>Бункер</b>\n\n"
        "Нажмите «Вступить», чтобы участвовать.\n"
        "⚠️ Перед этим обязательно напишите мне в личные сообщения /start — "
        "иначе я не смогу прислать вам карточки персонажа.\n\n"
        f"Минимум игроков: {MIN_PLAYERS}\n\n"
        f"Участники:\n{players_list_text(game)}"
    )


@router.message(Command("bunker"))
async def cmd_bunker(message: Message, game_manager: GameManager):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в групповом чате (в нужной ветке).")
        return

    thread_id = message.message_thread_id
    if game_manager.get(message.chat.id, thread_id) is not None:
        await message.answer("Игра уже создана в этой ветке. Дождитесь её окончания либо отмените (кнопка «Отменить»).")
        return

    game = game_manager.create(message.chat.id, thread_id, host_id=message.from_user.id)
    sent = await message.answer(registration_text(game), reply_markup=registration_keyboard(game))
    game.reg_message_id = sent.message_id


async def refresh_registration_message(bot, game: Game):
    try:
        await bot.edit_message_text(
            registration_text(game),
            chat_id=game.chat_id,
            message_id=game.reg_message_id,
            reply_markup=registration_keyboard(game),
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "bunker_join")
async def cb_join(callback: CallbackQuery, game_manager: GameManager):
    game = game_manager.get(callback.message.chat.id, callback.message.message_thread_id)
    if game is None or game.state != GameState.REGISTRATION:
        await callback.answer("Регистрация закрыта.", show_alert=True)
        return

    user = callback.from_user
    if user.id in game.players:
        await callback.answer("Вы уже в игре.")
        return

    game.players[user.id] = Player(user_id=user.id, username=user.username, full_name=user.full_name)
    await callback.answer("Вы вступили в игру!")
    await refresh_registration_message(callback.bot, game)


@router.callback_query(F.data == "bunker_cancel")
async def cb_cancel(callback: CallbackQuery, game_manager: GameManager):
    game = game_manager.get(callback.message.chat.id, callback.message.message_thread_id)
    if game is None:
        await callback.answer()
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("Отменить игру может только тот, кто её создал.", show_alert=True)
        return

    game_manager.remove(game.chat_id, game.thread_id)
    await callback.answer("Игра отменена.")
    await callback.message.edit_text("🚫 Игра отменена.")


@router.callback_query(F.data == "bunker_start")
async def cb_start(callback: CallbackQuery, game_manager: GameManager):
    game = game_manager.get(callback.message.chat.id, callback.message.message_thread_id)
    if game is None or game.state != GameState.REGISTRATION:
        await callback.answer("Игра уже идёт или отменена.", show_alert=True)
        return

    if callback.from_user.id != game.host_id:
        await callback.answer("Начать игру может только тот, кто её создал.", show_alert=True)
        return

    if len(game.players) < MIN_PLAYERS:
        await callback.answer(f"Нужно минимум {MIN_PLAYERS} игроков.", show_alert=True)
        return

    unreachable = [p for p in game.players.values() if p.user_id not in known_users]
    if unreachable:
        names = ", ".join(p.full_name for p in unreachable)
        await callback.answer("Не все игроки написали мне в личку.", show_alert=True)
        await callback.message.answer(
            "Эти игроки должны написать мне в личные сообщения /start, прежде чем можно "
            f"будет начать игру:\n{names}"
        )
        return

    await callback.answer()
    await callback.message.edit_text("🎲 Игра начинается! Катастрофа и карточки — далее в чате и в личных сообщениях.")

    players = list(game.players.values())
    deal_cards(players)

    game.catastrophe = random.choice(CATASTROPHES)
    game.bunker = random.choice(BUNKERS)

    capacity = round(len(players) * BUNKER_CAPACITY_RATIO)
    capacity = max(MIN_CAPACITY, capacity)
    if capacity >= len(players):
        capacity = max(MIN_CAPACITY, len(players) - 1)
    game.capacity = capacity

    bot = callback.bot

    intro = (
        f"☠️ <b>Катастрофа:</b> {game.catastrophe['title']}\n{game.catastrophe['description']}\n\n"
        f"🕳 <b>Бункер:</b> {game.bunker['title']}\n{game.bunker['description']}\n\n"
        f"В бункер поместится только <b>{game.capacity}</b> из {len(players)} человек. "
        "Остальным придётся остаться снаружи.\n\n"
        "Каждому в личные сообщения отправлены его карточки персонажа. Раунд за раундом "
        "вы будете раскрывать характеристики и убеждать остальных, что достойны места в бункере."
    )
    await bot.send_message(game.chat_id, intro, message_thread_id=game.thread_id)

    failed = []
    for player in players:
        card_text = "🗂 <b>Ваши карточки:</b>\n\n" + format_full_card(player.cards)
        try:
            await bot.send_message(player.user_id, card_text)
        except TelegramForbiddenError:
            failed.append(player)

    if failed:
        names = ", ".join(p.full_name for p in failed)
        await bot.send_message(
            game.chat_id,
            f"⚠️ Не удалось написать в личку: {names}. Попросите их написать мне /start.",
            message_thread_id=game.thread_id,
        )

    from handlers.round import start_round
    await start_round(bot, game, game_manager, round_index=0)