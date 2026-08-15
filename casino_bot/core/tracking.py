from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

from core.users_registry import remember_user


class UserTrackingMiddleware(BaseMiddleware):
    """Запоминает username и chat_id/user_id каждого, кто написал в чат —
    выполняется как middleware, поэтому не участвует в роутинге хендлеров
    и не может случайно «перехватить» апдейт у игровых обработчиков."""

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if event.from_user and not event.from_user.is_bot:
            remember_user(
                event.chat.id,
                event.from_user.id,
                event.from_user.username,
                event.from_user.full_name,
            )
        return await handler(event, data)
