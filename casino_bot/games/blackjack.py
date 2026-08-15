from __future__ import annotations

import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import BLACKJACK_MIN_BET
from core.economy import try_place_bet, add_balance, parse_bet
from core.cards import format_hand

router = Router()

games: dict = {}  # (chat_id, user_id) -> BlackjackGame


def draw_card() -> tuple:
    rank = random.choice(["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"])
    suit = random.choice(["♠", "♥", "♦", "♣"])
    return (rank, suit)


def card_value(rank: str) -> int:
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def hand_value(cards: list) -> int:
    total = sum(card_value(r) for r, _ in cards)
    aces = sum(1 for r, _ in cards if r == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards: list) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


class BlackjackGame:
    def __init__(self, chat_id, user_id, bet):
        self.chat_id = chat_id
        self.user_id = user_id
        self.bet = bet
        self.player = [draw_card(), draw_card()]
        self.dealer = [draw_card(), draw_card()]
        self.finished = False


def keyboard(chat_id, user_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🃏 Ещё карту", callback_data=f"bj:hit:{chat_id}:{user_id}"),
        InlineKeyboardButton(text="✋ Хватит", callback_data=f"bj:stand:{chat_id}:{user_id}"),
    ]])


def status_text(game: BlackjackGame, reveal_dealer: bool = False) -> str:
    if reveal_dealer:
        dealer_text = f"{format_hand(game.dealer)} ({hand_value(game.dealer)})"
    else:
        dealer_text = f"{format_hand(game.dealer[:1])} + 🂠"
    return (
        f"🎰 <b>Блэкджек</b> — ставка {game.bet}\n\n"
        f"Дилер: {dealer_text}\n"
        f"Вы: {format_hand(game.player)} ({hand_value(game.player)})"
    )


@router.message(Command("blackjack"))
async def cmd_blackjack(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(f"Использование: <code>/blackjack СТАВКА</code> (минимум {BLACKJACK_MIN_BET})")
        return

    key = (message.chat.id, message.from_user.id)
    if key in games:
        await message.reply("У вас уже открыта партия в блэкджек — доиграйте её сначала.")
        return

    amount, error = parse_bet(parts[1], message.from_user.id, BLACKJACK_MIN_BET)
    if error:
        await message.reply(error)
        return

    try_place_bet(message.from_user.id, amount)
    game = BlackjackGame(message.chat.id, message.from_user.id, amount)
    games[key] = game

    if is_blackjack(game.player):
        await finish_game(message, game, natural=True)
        return

    await message.answer(status_text(game), reply_markup=keyboard(message.chat.id, message.from_user.id))


@router.callback_query(F.data.startswith("bj:"))
async def cb_action(callback: CallbackQuery):
    _, action, chat_id, user_id = callback.data.split(":")
    chat_id, user_id = int(chat_id), int(user_id)

    if callback.from_user.id != user_id:
        await callback.answer("Это не ваша партия!", show_alert=True)
        return

    key = (chat_id, user_id)
    game = games.get(key)
    if game is None or game.finished:
        await callback.answer("Партия уже завершена.", show_alert=True)
        return

    await callback.answer()

    if action == "hit":
        game.player.append(draw_card())
        if hand_value(game.player) > 21:
            await finish_game(callback.message, game, busted=True)
            return
        await callback.message.edit_text(status_text(game), reply_markup=keyboard(chat_id, user_id))

    elif action == "stand":
        while hand_value(game.dealer) < 17:
            game.dealer.append(draw_card())
        await finish_game(callback.message, game)


async def finish_game(message: Message, game: BlackjackGame, natural: bool = False, busted: bool = False):
    game.finished = True
    games.pop((game.chat_id, game.user_id), None)

    player_total = hand_value(game.player)
    dealer_total = hand_value(game.dealer)

    if busted:
        outcome = f"💥 Перебор! У вас {player_total}. Вы проиграли {game.bet} фишек."
        payout = 0
    elif natural:
        payout = int(game.bet * 2.5)  # ставка + выигрыш 3:2
        add_balance(game.user_id, payout)
        outcome = f"🂡 Блэкджек! Выплата 3:2 — вы получаете {payout} фишек."
    elif dealer_total > 21:
        payout = game.bet * 2
        add_balance(game.user_id, payout)
        outcome = f"🎉 У дилера перебор ({dealer_total})! Вы выигрываете {payout} фишек."
    elif player_total > dealer_total:
        payout = game.bet * 2
        add_balance(game.user_id, payout)
        outcome = f"🎉 Вы выиграли! {player_total} против {dealer_total}. Выплата: {payout} фишек."
    elif player_total < dealer_total:
        payout = 0
        outcome = f"😔 Дилер выиграл. {dealer_total} против {player_total}. Вы теряете {game.bet} фишек."
    else:
        payout = game.bet
        add_balance(game.user_id, payout)
        outcome = f"🤝 Ничья ({player_total})! Ставка {game.bet} возвращена."

    text = (
        f"{status_text(game, reveal_dealer=True)}\n\n{outcome}"
    )
    try:
        await message.edit_text(text)
    except Exception:
        await message.answer(text)
