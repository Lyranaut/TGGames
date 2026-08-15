# -*- coding: utf-8 -*-
"""
UNO-бот для одного группового чата, на aiogram 3 (тот же стек, что и mafia bot.py).

Это ОТДЕЛЬНЫЙ бот (свой токен, свой процесс) — можно запускать
одновременно с bot.py (Мафией), они друг другу не мешают.

Идея показа карт:
- В чате всегда висит ОДНО общее статусное сообщение: верхняя карта стола,
  чей ход, у кого сколько карт на руках.
- Свои карты каждый игрок смотрит через кнопку «🎴 Мои карты» под этим
  сообщением — ответ на нажатие уходит всплывающим окном (callback.answer(
  show_alert=True)), которое видно ТОЛЬКО нажавшему, хотя кнопка общая для
  всех и находится прямо в чате (никаких личных сообщений не требуется).
- Ход делается командой /play <номер> или /draw прямо в чате.
- Цвет для Wild/+4 выбирается публичными кнопками, но нажать может только
  тот, чей сейчас ход.

Запуск:
    pip install -r requirements.txt   # aiogram>=3.4,<4 — уже в проекте
    python uno_bot.py

Токен и chat_id берутся из config.py (UNO_BOT_TOKEN, UNO_CHAT_ID).
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import UNO_BOT_TOKEN, UNO_CHAT_ID

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("uno_bot")

router = Router()

COLORS = ["red", "yellow", "green", "blue"]
COLOR_NAMES = {"red": "🔴 Красный", "yellow": "🟡 Жёлтый", "green": "🟢 Зелёный", "blue": "🔵 Синий"}
COLOR_EMOJI = {"red": "🔴", "yellow": "🟡", "green": "🟢", "blue": "🔵", "wild": "⚫"}
VALUE_NAMES = {"skip": "Пропуск", "reverse": "Реверс", "draw2": "+2", "wild": "Wild", "wild4": "Wild +4"}


def card_label(card):
    color, value = card
    return f"{COLOR_EMOJI[color]}{VALUE_NAMES.get(value, value)}"


def new_deck():
    deck = []
    for color in COLORS:
        deck.append((color, "0"))
        for v in list("123456789"):
            deck += [(color, v), (color, v)]
        for v in ("skip", "reverse", "draw2"):
            deck += [(color, v), (color, v)]
    for _ in range(4):
        deck += [("wild", "wild"), ("wild", "wild4")]
    random.shuffle(deck)
    return deck


@dataclass
class Game:
    chat_id: int
    host_id: int
    players: list = field(default_factory=list)
    names: dict = field(default_factory=dict)
    hands: dict = field(default_factory=dict)
    draw_pile: list = field(default_factory=list)
    discard_pile: list = field(default_factory=list)
    current_color: str = None
    current_idx: int = 0
    direction: int = 1
    started: bool = False
    status_msg_id: int = None
    awaiting_color_from: int = None
    winner: int = None

    def current_player(self):
        return self.players[self.current_idx]

    def top(self):
        return self.discard_pile[-1]

    def advance(self, steps=1):
        n = len(self.players)
        self.current_idx = (self.current_idx + self.direction * steps) % n

    def draw_card(self, user_id, n=1):
        for _ in range(n):
            if not self.draw_pile:
                self._reshuffle()
                if not self.draw_pile:
                    break
            self.hands[user_id].append(self.draw_pile.pop())

    def _reshuffle(self):
        if len(self.discard_pile) <= 1:
            return
        top_card = self.discard_pile.pop()
        random.shuffle(self.discard_pile)
        self.draw_pile, self.discard_pile = self.discard_pile, [top_card]


GAMES: dict[int, Game] = {}


def is_valid_move(card, top, current_color):
    color, value = card
    return color == "wild" or color == current_color or value == top[1]


def status_text(game: Game) -> str:
    lines = ["🎴 <b>UNO</b>"]
    top = game.top()
    lines.append(
        f"Верхняя карта: <b>{card_label(top)}</b>  |  Цвет хода: {COLOR_NAMES.get(game.current_color, '-')}"
    )
    lines.append("")
    for uid in game.players:
        n = len(game.hands[uid])
        marker = "👉 " if (not game.winner and uid == game.current_player()) else ""
        uno_tag = " (UNO!)" if n == 1 else ""
        lines.append(f"{marker}{game.names[uid]}: {n} карт{uno_tag}")
    lines.append("")
    if game.winner:
        lines.append(f"🏆 Победил {game.names[game.winner]}!")
    elif game.awaiting_color_from:
        lines.append(f"⏳ {game.names[game.awaiting_color_from]} выбирает цвет...")
    else:
        lines.append(f"Ходит: <b>{game.names[game.current_player()]}</b>")
        lines.append("Команды: /play &lt;номер&gt;  или  /draw")
    return "\n".join(lines)


def status_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🎴 Мои карты", callback_data="myhand")]]
    )


async def push_status(bot: Bot, game: Game):
    text = status_text(game)
    if game.status_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=game.chat_id,
                message_id=game.status_msg_id,
                text=text,
                reply_markup=status_keyboard(),
            )
            return
        except Exception:
            pass
    msg = await bot.send_message(game.chat_id, text, reply_markup=status_keyboard())
    game.status_msg_id = msg.message_id


def guard_chat(message_or_query) -> bool:
    chat = message_or_query.message.chat if isinstance(message_or_query, CallbackQuery) else message_or_query.chat
    return chat.id == UNO_CHAT_ID


# ---------- commands ----------

@router.message(Command("uno"))
async def cmd_uno(message: Message):
    if not guard_chat(message):
        return
    existing = GAMES.get(message.chat.id)
    if existing and not existing.winner:
        await message.answer("Игра уже идёт. Дождитесь конца или /uno_stop.")
        return
    game = Game(chat_id=message.chat.id, host_id=message.from_user.id)
    GAMES[message.chat.id] = game
    game.players.append(message.from_user.id)
    game.names[message.from_user.id] = message.from_user.first_name
    game.hands[message.from_user.id] = []
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Присоединиться", callback_data="join")],
            [InlineKeyboardButton(text="▶️ Начать игру", callback_data="begin")],
        ]
    )
    await message.answer(
        f"Новая игра UNO! {message.from_user.first_name} создал(а) игру и уже в ней.\n"
        f"Нажмите «Присоединиться», когда все соберутся — «Начать игру».",
        reply_markup=kb,
    )


@router.message(Command("uno_stop"))
async def cmd_stop(message: Message):
    if not guard_chat(message):
        return
    if message.chat.id in GAMES:
        del GAMES[message.chat.id]
        await message.answer("Игра остановлена.")


@router.message(Command("play"))
async def cmd_play(message: Message, command: CommandObject):
    if not guard_chat(message):
        return
    game = GAMES.get(message.chat.id)
    if not game or not game.started or game.winner:
        return
    uid = message.from_user.id
    if uid != game.current_player():
        await message.answer("Сейчас не ваш ход.")
        return
    if game.awaiting_color_from:
        await message.answer("Сначала выберите цвет кнопкой выше.")
        return
    if not command.args:
        await message.answer("Использование: /play <номер карты> (см. «Мои карты»)")
        return
    try:
        n = int(command.args.split()[0])
    except ValueError:
        await message.answer("Номер должен быть числом.")
        return

    hand = game.hands[uid]
    if n < 1 or n > len(hand):
        await message.answer("Нет такой карты.")
        return
    card = hand[n - 1]
    if not is_valid_move(card, game.top(), game.current_color):
        await message.answer("Эту карту сейчас нельзя положить.")
        return

    hand.pop(n - 1)
    game.discard_pile.append(card)
    color, value = card
    await message.answer(f"{game.names[uid]} кладёт: {card_label(card)}")

    if not hand:
        game.winner = uid
        await push_status(message.bot, game)
        return

    if color == "wild":
        game.awaiting_color_from = uid
        game.advance()
        if value == "wild4":
            victim = game.current_player()
            game.draw_card(victim, 4)
            game.advance()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=COLOR_NAMES[c], callback_data=f"color:{c}") for c in COLORS[:2]],
                [InlineKeyboardButton(text=COLOR_NAMES[c], callback_data=f"color:{c}") for c in COLORS[2:]],
            ]
        )
        await message.answer(f"{game.names[uid]}, выберите цвет:", reply_markup=kb)
        await push_status(message.bot, game)
        return

    game.current_color = color
    if value == "skip":
        game.advance(2)
    elif value == "reverse":
        game.direction *= -1
        game.advance(2 if len(game.players) == 2 else 1)
    elif value == "draw2":
        game.advance()
        victim = game.current_player()
        game.draw_card(victim, 2)
        game.advance()
    else:
        game.advance()

    await push_status(message.bot, game)


@router.message(Command("draw"))
async def cmd_draw(message: Message):
    if not guard_chat(message):
        return
    game = GAMES.get(message.chat.id)
    if not game or not game.started or game.winner:
        return
    uid = message.from_user.id
    if uid != game.current_player():
        await message.answer("Сейчас не ваш ход.")
        return
    if game.awaiting_color_from:
        await message.answer("Сначала выберите цвет кнопкой выше.")
        return
    game.draw_card(uid, 1)
    await message.answer(f"{game.names[uid]} берёт карту из колоды.")
    game.advance()
    await push_status(message.bot, game)


# ---------- callback buttons ----------

@router.callback_query(F.data == "join")
async def cb_join(query: CallbackQuery):
    if not guard_chat(query):
        await query.answer()
        return
    game = GAMES.get(query.message.chat.id)
    if not game or game.started:
        await query.answer("Игра уже началась или не существует.", show_alert=True)
        return
    uid = query.from_user.id
    if uid in game.players:
        await query.answer("Вы уже в игре.")
        return
    game.players.append(uid)
    game.names[uid] = query.from_user.first_name
    game.hands[uid] = []
    await query.answer("Вы в игре!")


@router.callback_query(F.data == "begin")
async def cb_begin(query: CallbackQuery):
    if not guard_chat(query):
        await query.answer()
        return
    game = GAMES.get(query.message.chat.id)
    if not game or game.started:
        await query.answer("Нельзя начать.", show_alert=True)
        return
    if query.from_user.id != game.host_id:
        await query.answer("Начать может только создатель игры.", show_alert=True)
        return
    if len(game.players) < 2:
        await query.answer("Нужно минимум 2 игрока.", show_alert=True)
        return

    deck = new_deck()
    game.draw_pile = deck
    for p in game.players:
        game.hands[p] = [game.draw_pile.pop() for _ in range(7)]
    first = game.draw_pile.pop()
    while first[0] == "wild":
        game.draw_pile.insert(0, first)
        random.shuffle(game.draw_pile)
        first = game.draw_pile.pop()
    game.discard_pile = [first]
    game.current_color = first[0]
    game.started = True

    await query.answer("Игра началась!")
    await query.message.answer("🎉 Игра началась! Раздаю карты...")
    await push_status(query.bot, game)


@router.callback_query(F.data == "myhand")
async def cb_myhand(query: CallbackQuery):
    if not guard_chat(query):
        await query.answer()
        return
    game = GAMES.get(query.message.chat.id)
    if not game or not game.started:
        await query.answer("Игра ещё не началась.", show_alert=True)
        return
    uid = query.from_user.id
    if uid not in game.hands:
        await query.answer("Вы не участвуете в этой игре.", show_alert=True)
        return
    top = game.top()
    lines = []
    for i, c in enumerate(game.hands[uid], start=1):
        ok = "✅" if is_valid_move(c, top, game.current_color) else "▫️"
        lines.append(f"{ok} {i}. {card_label(c)}")
    text = "Ваши карты (✅ = можно сыграть /play N):\n" + "\n".join(lines)
    await query.answer(text=text, show_alert=True)


@router.callback_query(F.data.startswith("color:"))
async def cb_color(query: CallbackQuery):
    if not guard_chat(query):
        await query.answer()
        return
    game = GAMES.get(query.message.chat.id)
    if not game or game.awaiting_color_from != query.from_user.id:
        await query.answer("Не ваш выбор.", show_alert=True)
        return
    color = query.data.split(":", 1)[1]
    game.current_color = color
    game.awaiting_color_from = None
    await query.answer(f"Цвет: {COLOR_NAMES[color]}")
    await query.message.answer(f"Цвет выбран: {COLOR_NAMES[color]}")
    await push_status(query.bot, game)


async def main():
    if not UNO_BOT_TOKEN:
        raise SystemExit("Задайте UNO_BOT_TOKEN в config.py или переменной окружения.")
    bot = Bot(token=UNO_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("UNO bot starting, serving chat_id=%s", UNO_CHAT_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())