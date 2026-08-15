from __future__ import annotations

from typing import Optional

from game.models import Game


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

    def get_for_message(self, chat_id: int, thread_id: Optional[int]) -> Optional[Game]:
        """Как get(), но с запасным вариантом: если точное совпадение по ветке
        не найдено (например, Telegram не проставил message_thread_id у
        ответа/реплая), а в чате идёт ровно одна активная игра — вернуть её."""
        game = self.get(chat_id, thread_id)
        if game is not None:
            return game

        candidates = [g for (c_id, _t_id), g in self.games.items() if c_id == chat_id]
        if len(candidates) == 1:
            return candidates[0]
        return None