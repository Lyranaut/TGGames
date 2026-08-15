from __future__ import annotations

from typing import Optional

from aiogram.types import Message

from game.models import Game


def effective_thread_id(message: Message) -> Optional[int]:
    """thread_id сообщения для поиска игры.

    Telegram проставляет message_thread_id не только темам форума, но и
    обычным reply-цепочкам в супергруппе без форума (id ветки = id корневого
    сообщения). Если это не настоящая тема форума (is_topic_message не True),
    такой thread_id игнорируем — иначе ответ на чьё-то сообщение получает
    "чужой" thread_id и игра, созданная с thread_id=None, перестаёт находиться.
    """
    return message.message_thread_id if message.is_topic_message else None


class GameManager:
    """Хранит активные игры, по одной на пару (chat_id, thread_id)."""

    def __init__(self):
        self.games: dict = {}

    @staticmethod
    def _key(chat_id: int, thread_id: Optional[int]):
        return (chat_id, thread_id)

    def get(self, chat_id: int, thread_id: Optional[int]) -> Optional[Game]:
        return self.games.get(self._key(chat_id, thread_id))

    def create(self, chat_id: int, thread_id: Optional[int], host_id: int) -> Game:
        game = Game(chat_id=chat_id, thread_id=thread_id, host_id=host_id)
        self.games[self._key(chat_id, thread_id)] = game
        return game

    def remove(self, chat_id: int, thread_id: Optional[int]) -> None:
        self.games.pop(self._key(chat_id, thread_id), None)

    def find_by_player(self, user_id: int) -> Optional[Game]:
        for game in self.games.values():
            if user_id in game.players:
                return game
        return None
