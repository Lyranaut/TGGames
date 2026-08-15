from __future__ import annotations

import json
import os
from typing import Optional

from config import STARTING_BALANCE

BALANCES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "balances.json")


def _load() -> dict:
    if os.path.exists(BALANCES_FILE):
        try:
            with open(BALANCES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    with open(BALANCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


_balances: dict = _load()


def get_balance(user_id: int) -> int:
    """Возвращает баланс, выдавая стартовые фишки при первом обращении."""
    key = str(user_id)
    if key not in _balances:
        _balances[key] = STARTING_BALANCE
        _save(_balances)
    return _balances[key]


def set_balance(user_id: int, amount: int) -> None:
    _balances[str(user_id)] = max(0, amount)
    _save(_balances)


def add_balance(user_id: int, delta: int) -> int:
    """Прибавляет (или отнимает, если delta < 0) фишки. Возвращает новый баланс."""
    new_balance = get_balance(user_id) + delta
    set_balance(user_id, new_balance)
    return new_balance


def try_place_bet(user_id: int, amount: int) -> bool:
    """Списывает ставку, если хватает средств. True при успехе, False если нет."""
    balance = get_balance(user_id)
    if amount <= 0 or balance < amount:
        return False
    set_balance(user_id, balance - amount)
    return True


def parse_bet(raw: str, user_id: int, min_bet: int) -> tuple[Optional[int], Optional[str]]:
    """Общая проверка ставки для всех игр: (сумма, None) либо (None, текст ошибки)."""
    try:
        amount = int(raw)
    except ValueError:
        return None, "Ставка должна быть целым числом."
    if amount < min_bet:
        return None, f"Минимальная ставка — {min_bet} фишек."
    balance = get_balance(user_id)
    if amount > balance:
        return None, f"Недостаточно фишек. Ваш баланс: {balance}."
    return amount, None
