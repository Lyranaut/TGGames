from __future__ import annotations

import re
from typing import Optional

from aiogram.types import Message


def effective_thread_id(message: Message) -> Optional[int]:
    """thread_id сообщения для поиска игры.

    Telegram проставляет message_thread_id не только темам форума, но и
    обычным reply-цепочкам в супергруппе без форума. Если это не настоящая
    тема (is_topic_message не True) — thread_id игнорируем, иначе игра,
    созданная с thread_id=None, перестаёт находиться при следующем сообщении.
    """
    return message.message_thread_id if message.is_topic_message else None


def normalize(text: str) -> str:
    """Убирает всё, кроме букв и цифр, приводит к нижнему регистру —
    для сравнения ответов без оглядки на пунктуацию, пробелы и регистр."""
    return re.sub(r"[^а-яёa-z0-9]", "", text.lower())


def contains_word(message_text: str, target_word: str) -> bool:
    """Проверяет, встречается ли target_word (как отдельное слово, без учёта
    регистра/пунктуации) внутри message_text."""
    target_norm = normalize(target_word)
    if not target_norm:
        return False
    words_norm = [normalize(w) for w in re.split(r"\s+", message_text)]
    return target_norm in words_norm
