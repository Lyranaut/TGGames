from __future__ import annotations

from collections import Counter

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import POKER_MIN_BET
from core.economy import add_balance, parse_bet, try_place_bet
from core.cards import new_shuffled_deck, format_card

router = Router()

games: dict = {}  # (chat_id, user_id) -> PokerGame

RANK_ORDER = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

PAYTABLE = [
    ("royal_flush", "Роял-флэш", 800),
    ("straight_flush", "Стрит-флэш", 50),
    ("four_kind", "Каре", 25),
    ("full_house", "Фулл-хаус", 9),
    ("flush", "Флэш", 6),
    ("straight", "Стрит", 4),
    ("three_kind", "Тройка", 3),
    ("two_pair", "Две пары", 2),
    ("jacks_or_better", "Валеты и старше в паре", 1),
]
PAYTABLE_DICT = {key: mult for key, _, mult in PAYTABLE}
HAND_NAMES = {key: name for key, name, _ in PAYTABLE}
HAND_NAMES["nothing"] = "Ничего"


def evaluate_hand(cards: list) -> str:
    ranks = sorted(RANK_ORDER.index(r) for r, _ in cards)
    rank_counts = Counter(r for r, _ in cards)
    counts = sorted(rank_counts.values(), reverse=True)
    suits = {s for _, s in cards}
    is_flush = len(suits) == 1

    unique_ranks = sorted(set(ranks))
    is_straight = False
    if len(unique_ranks) == 5:
        if unique_ranks[-1] - unique_ranks[0] == 4:
            is_straight = True
        elif unique_ranks == [0, 1, 2, 3, 12]:  # A-2-3-4-5
            is_straight = True

    if is_straight and is_flush and unique_ranks[0] == 8:
        return "royal_flush"
    if is_straight and is_flush:
        return "straight_flush"
    if counts == [4, 1]:
        return "four_kind"
    if counts == [3, 2]:
        return "full_house"
    if is_flush:
        return "flush"
    if is_straight:
        return "straight"
    if counts == [3, 1, 1]:
        return "three_kind"
    if counts == [2, 2, 1]:
        return "two_pair"
    if counts == [2, 1, 1, 1]:
        pair_rank = next(r for r, c in rank_counts.items() if c == 2)
        if RANK_ORDER.index(pair_rank) >= RANK_ORDER.index("J"):
            return "jacks_or_better"
        return "nothing"
    return "nothing"


class PokerGame:
    def __init__(self, chat_id, user_id, bet):
        self.chat_id = chat_id
        self.user_id = user_id
        self.bet = bet
        self.deck = new_shuffled_deck()
        self.hand = [self.deck.pop() for _ in range(5)]
        self.held = [False] * 5
        self.finished = False


def keyboard(game: PokerGame) -> InlineKeyboardMarkup:
    row = []
    for i, card in enumerate(game.hand):
        mark = "🔒 " if game.held[i] else ""
        row.append(InlineKeyboardButton(
            text=f"{mark}{format_card(card)}",
            callback_data=f"fp:hold:{game.chat_id}:{game.user_id}:{i}",
        ))
    draw_row = [InlineKeyboardButton(text="🔄 Раздать", callback_data=f"fp:draw:{game.chat_id}:{game.user_id}")]
    return InlineKeyboardMarkup(inline_keyboard=[row, draw_row])


def hand_text(game: PokerGame) -> str:
    return (
        f"🃏 <b>Быстрый покер</b> — ставка {game.bet}\n\n"
        "Выберите карты, которые хотите оставить (🔒), затем нажмите «Раздать».\n\n"
        + " ".join(f"[{format_card(c)}]" if game.held[i] else format_card(c) for i, c in enumerate(game.hand))
    )


@router.message(Command("poker"))
async def cmd_poker(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(f"Использование: <code>/poker СТАВКА</code> (минимум {POKER_MIN_BET})")
        return

    key = (message.chat.id, message.from_user.id)
    if key in games:
        await message.reply("У вас уже открыта партия в покер — доиграйте её сначала.")
        return

    amount, error = parse_bet(parts[1], message.from_user.id, POKER_MIN_BET)
    if error:
        await message.reply(error)
        return

    try_place_bet(message.from_user.id, amount)
    game = PokerGame(message.chat.id, message.from_user.id, amount)
    games[key] = game

    await message.answer(hand_text(game), reply_markup=keyboard(game))


@router.callback_query(F.data.startswith("fp:hold:"))
async def cb_hold(callback: CallbackQuery):
    _, _, chat_id, user_id, idx = callback.data.split(":")
    chat_id, user_id, idx = int(chat_id), int(user_id), int(idx)

    if callback.from_user.id != user_id:
        await callback.answer("Это не ваша партия!", show_alert=True)
        return

    game = games.get((chat_id, user_id))
    if game is None or game.finished:
        await callback.answer("Партия уже завершена.", show_alert=True)
        return

    game.held[idx] = not game.held[idx]
    await callback.answer()
    await callback.message.edit_text(hand_text(game), reply_markup=keyboard(game))


@router.callback_query(F.data.startswith("fp:draw:"))
async def cb_draw(callback: CallbackQuery):
    _, _, chat_id, user_id = callback.data.split(":")
    chat_id, user_id = int(chat_id), int(user_id)

    if callback.from_user.id != user_id:
        await callback.answer("Это не ваша партия!", show_alert=True)
        return

    game = games.get((chat_id, user_id))
    if game is None or game.finished:
        await callback.answer("Партия уже завершена.", show_alert=True)
        return

    await callback.answer()

    for i in range(5):
        if not game.held[i]:
            game.hand[i] = game.deck.pop()

    game.finished = True
    games.pop((chat_id, user_id), None)

    result = evaluate_hand(game.hand)
    multiplier = PAYTABLE_DICT.get(result, 0)
    payout = game.bet * multiplier

    if payout > 0:
        add_balance(user_id, payout)
        outcome = f"🎉 {HAND_NAMES[result]}! Выплата ×{multiplier} — вы получаете {payout} фишек."
    else:
        outcome = f"😔 {HAND_NAMES[result]}. Ставка {game.bet} сгорела."

    text = (
        f"🃏 <b>Быстрый покер</b> — итог\n\n"
        f"{' '.join(format_card(c) for c in game.hand)}\n\n{outcome}"
    )
    await callback.message.edit_text(text)
