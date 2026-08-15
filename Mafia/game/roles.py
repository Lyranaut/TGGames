from __future__ import annotations

import random
import re

from game.models import Role

# Префиксы русских слов -> роль. Порядок важен только там, где префиксы
# могли бы пересечься — здесь пересечений нет, так что порядок свободный.
ROLE_ALIASES = [
    ("дон", Role.DON),
    ("маф", Role.MAFIA),
    ("доктор", Role.DOCTOR),
    ("комиссар", Role.DETECTIVE),
    ("детектив", Role.DETECTIVE),
    ("путан", Role.COURTESAN),
    ("маньяк", Role.MANIAC),
    ("двулик", Role.TWOFACED),
    ("мирн", Role.CIVILIAN),
    ("гражд", Role.CIVILIAN),
]


def parse_role_counts(text: str) -> tuple[dict, list[str]]:
    """Разбирает текст вида "мафия 2 доктор 1 комиссар 1" в {Role: count}.

    Возвращает (roles, unknown_words) — unknown_words содержит слова,
    которые не удалось сопоставить ни с одной ролью.
    """
    roles: dict = {}
    unknown: list[str] = []

    for word, num in re.findall(r"([а-яёА-ЯЁ]+)\s*[:\-]?\s*(\d+)", text):
        word_lower = word.lower()
        role = next((r for prefix, r in ROLE_ALIASES if word_lower.startswith(prefix)), None)
        if role is None:
            unknown.append(word)
            continue
        roles[role] = roles.get(role, 0) + int(num)

    return roles, unknown


def assign_roles(players: list, role_counts: dict) -> None:
    pool = []
    for role, count in role_counts.items():
        pool += [role] * count

    civilians = max(0, len(players) - len(pool))
    pool += [Role.CIVILIAN] * civilians

    random.shuffle(pool)
    for player, role in zip(players, pool):
        player.role = role
