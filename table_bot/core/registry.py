from __future__ import annotations

from typing import Optional


class ActiveGameRegistry:
    """Гарантирует, что в одном чате/ветке одновременно идёт только одна игра
    — неважно, какого типа (Крокодил, Виселица и т.д. используют общий реестр)."""

    def __init__(self):
        self._active: dict = {}  # (chat_id, thread_id) -> game_type (str)

    @staticmethod
    def _key(chat_id: int, thread_id: Optional[int]):
        return (chat_id, thread_id)

    def current(self, chat_id: int, thread_id: Optional[int]) -> Optional[str]:
        return self._active.get(self._key(chat_id, thread_id))

    def is_busy(self, chat_id: int, thread_id: Optional[int]) -> bool:
        return self._key(chat_id, thread_id) in self._active

    def occupy(self, chat_id: int, thread_id: Optional[int], game_type: str) -> None:
        self._active[self._key(chat_id, thread_id)] = game_type

    def release(self, chat_id: int, thread_id: Optional[int]) -> None:
        self._active.pop(self._key(chat_id, thread_id), None)


registry = ActiveGameRegistry()
