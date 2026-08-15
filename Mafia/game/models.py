from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class Role(Enum):
    MAFIA = "mafia"
    DON = "don"
    DOCTOR = "doctor"
    DETECTIVE = "detective"
    COURTESAN = "courtesan"
    MANIAC = "maniac"
    TWOFACED = "twofaced"
    CIVILIAN = "civilian"


ROLE_NAMES = {
    Role.MAFIA: "🔪 Мафия",
    Role.DON: "🎩 Дон",
    Role.DOCTOR: "💉 Доктор",
    Role.DETECTIVE: "🕵️ Комиссар",
    Role.COURTESAN: "💋 Путана",
    Role.MANIAC: "🔦 Маньяк",
    Role.TWOFACED: "🎭 Двуликий",
    Role.CIVILIAN: "👤 Мирный житель",
}

ROLE_DESCRIPTIONS = {
    Role.MAFIA: (
        "Каждую ночь ты вместе с доном и остальной мафией выбираешь, кого убить. "
        "Днём притворяйся мирным жителем и вычисляй, кто может тебя раскрыть."
    ),
    Role.DON: (
        "Ты глава мафии. Как и рядовая мафия, ночью голосуешь, кого убить. "
        "Отличие: если комиссар проверит именно тебя — он получит ложный "
        "результат «не мафия»."
    ),
    Role.DOCTOR: (
        "Каждую ночь ты выбираешь одного игрока, которого лечишь. "
        "Если этой же ночью его выберет жертвой мафия или маньяк — он выживет."
    ),
    Role.DETECTIVE: (
        "Каждую ночь ты можешь проверить одного игрока и узнать, мафия он или нет. "
        "Учти: дон обманет проверку (покажется не мафией), а двуликий, наоборот, "
        "покажется мафией, хотя им не является."
    ),
    Role.COURTESAN: (
        "Каждую ночь ты «навещаешь» одного игрока — в эту ночь его действие "
        "(лечение, проверка, голос мафии на убийство, удар маньяка) не сработает. "
        "Кто ты сама — окружающим неизвестно. Осторожно: если этой же ночью тебя "
        "убьют мафия или маньяк, твой клиент погибнет вместе с тобой, если его не "
        "спасёт доктор."
    ),
    Role.MANIAC: (
        "Ты играешь один против всех. Каждую ночь независимо от мафии выбираешь "
        "жертву. Побеждаешь, если останешься единственным живым игроком в игре."
    ),
    Role.TWOFACED: (
        "Обычный мирный житель без ночных действий, но с подвохом: если тебя "
        "проверит комиссар — результат покажет, что ты мафия, хотя это не так."
    ),
    Role.CIVILIAN: (
        "У тебя нет ночных действий. Твоя задача — внимательно слушать обсуждения "
        "днём и голосованием вычислить мафию."
    ),
}


class GameState(Enum):
    REGISTRATION = auto()
    NIGHT = auto()
    DAY_SPEECH = auto()
    DAY_DISCUSSION = auto()
    DAY_VOTE = auto()
    FINISHED = auto()


@dataclass
class Player:
    user_id: int
    username: Optional[str]
    full_name: str
    role: Optional[Role] = None
    fake_role: Optional[Role] = None       # используется только в secret_mode для публичной "обманки"
    alive: bool = True

    @property
    def mention(self) -> str:
        return f'<a href="tg://user?id={self.user_id}">{self.full_name}</a>'


@dataclass
class Game:
    chat_id: int
    thread_id: Optional[int]
    host_id: int
    players: dict = field(default_factory=dict)          # user_id -> Player
    custom_roles: Optional[dict] = None                    # Role -> count, None = ещё не задано хостом
    secret_mode: bool = False
    reveal_deaths: bool = True             # показывать ли роль умершего/казнённого игрока
    state: GameState = GameState.REGISTRATION
    day_number: int = 0
    reg_message_id: Optional[int] = None
    night_actions: dict = field(default_factory=dict)    # kill_votes / heal / check
    last_heal_targets: dict = field(default_factory=dict)  # doctor_id -> кого лечил прошлой ночью
    votes: dict = field(default_factory=dict)             # voter_id -> target_id (0 = пропуск)
    speech_order: list = field(default_factory=list)
    speech_index: int = 0
    pending_last_word_id: Optional[int] = None    # user_id, кому сейчас можно сказать последнее слово
