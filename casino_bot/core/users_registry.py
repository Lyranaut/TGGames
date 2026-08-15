from __future__ import annotations

import json
import os
from typing import Optional

REGISTRY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "users_registry.json")


def _load() -> dict:
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"usernames": {}, "chat_members": {}}


def _save(data: dict) -> None:
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


_data: dict = _load()


def remember_user(chat_id: int, user_id: int, username: Optional[str], full_name: str) -> None:
    """Запоминает username->id и то, что этот пользователь встречался в этом чате.
    Нужно, чтобы @username и «все» в /give вообще можно было разрешить в id —
    у Telegram Bot API нет способа просто получить полный список участников чата."""
    changed = False

    if username:
        key = username.lower()
        if _data["usernames"].get(key) != user_id:
            _data["usernames"][key] = user_id
            changed = True

    chat_key = str(chat_id)
    members = _data["chat_members"].setdefault(chat_key, {})
    entry = {"name": full_name, "username": username}
    if members.get(str(user_id)) != entry:
        members[str(user_id)] = entry
        changed = True

    if changed:
        _save(_data)


def resolve_username(username: str) -> Optional[int]:
    return _data["usernames"].get(username.lstrip("@").lower())


def chat_members(chat_id: int) -> dict:
    return _data["chat_members"].get(str(chat_id), {})
