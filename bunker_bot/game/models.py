from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class GameState(Enum):
    REGISTRATION = auto()
    ROUND_SPEECH = auto()
    ROUND_DISCUSSION = auto()
    ROUND_VOTE = auto()
    FINISHED = auto()


@dataclass
class Player:
    user_id: int
    username: Optional[str]
    full_name: str
    cards: dict = field(default_factory=dict)
    alive: bool = True

    @property
    def mention(self) -> str:
        return f'<a href="tg://user?id={self.user_id}">{self.full_name}</a>'


@dataclass
class Game:
    chat_id: int
    thread_id: Optional[int]
    host_id: int
    players: dict = field(default_factory=dict)           # user_id -> Player
    state: GameState = GameState.REGISTRATION
    reg_message_id: Optional[int] = None
    catastrophe: Optional[dict] = None
    bunker: Optional[dict] = None
    capacity: int = 3
    round_number: int = 0                                   # для отображения (1, 2, 3...)
    round_index: int = 0                                     # индекс в ROUND_CATEGORIES
    speech_order: list = field(default_factory=list)
    speech_index: int = 0
    votes: dict = field(default_factory=dict)                # voter_id -> target_id