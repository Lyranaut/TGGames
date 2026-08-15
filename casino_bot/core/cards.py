from __future__ import annotations

import random

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["♠", "♥", "♦", "♣"]


def new_shuffled_deck() -> list:
    """Полная колода 52 карты, перемешанная — раздача без повторов внутри одной руки."""
    deck = [(r, s) for r in RANKS for s in SUITS]
    random.shuffle(deck)
    return deck


def format_card(card: tuple) -> str:
    rank, suit = card
    return f"{rank}{suit}"


def format_hand(cards: list) -> str:
    return " ".join(format_card(c) for c in cards)
