# ФАЙЛ ДЛЯ ПАПКИ: table_bot
# КУДА ВСТАВЛЯТЬ: table_bot\games\hangman.py  (заменить весь файл целиком)

from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.dispatcher.event.bases import SkipHandler

from config import HANGMAN_MAX_WRONG
from core.registry import registry
from core.utils import effective_thread_id
from core.wordbank import draw_hangman_word

router = Router()

GAME_TYPE = "hangman"
games: dict = {}  # (chat_id, thread_id) -> HangmanGame

STAGES = [
    "```\n \n \n \n \n \n=====\n```",
    "```\n  +---+\n  |\n  |\n  |\n  |\n=====\n```",
    "```\n  +---+\n  |   |\n      |\n      |\n      |\n=====\n```",
    "```\n  +---+\n  |   |\n  O   |\n      |\n      |\n=====\n```",
    "```\n  +---+\n  |   |\n  O   |\n  |   |\n      |\n=====\n```",
    "```\n  +---+\n  |   |\n  O   |\n /|   |\n      |\n=====\n```",
    "```\n  +---+\n  |   |\n  O   |\n /|\\  |\n / \\  |\n=====\n```",
]


class HangmanGame:
    def __init__(self, chat_id, thread_id):
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.word = draw_hangman_word()
        self.guessed_letters: set = set()
        self.wrong_letters: set = set()

    def masked(self) -> str:
        return " ".join(letter if letter in self.guessed_letters else "_" for letter in self.word)

    @property
    def wrong_count(self) -> int:
        return len(self.wrong_letters)

    @property
    def is_won(self) -> bool:
        return all(letter in self.guessed_letters for letter in self.word)

    @property
    def is_lost(self) -> bool:
        return self.wrong_count >= HANGMAN_MAX_WRONG


def status_text(game: HangmanGame) -> str:
    stage = STAGES[min(game.wrong_count, len(STAGES) - 1)]
    wrong = ", ".join(sorted(game.wrong_letters)) if game.wrong_letters else "—"
    return (
        f"{stage}\n"
        f"Слово: <b>{game.masked()}</b>\n"
        f"Неверные буквы: {wrong} ({game.wrong_count}/{HANGMAN_MAX_WRONG})\n\n"
        "Пишите букву или всё слово целиком прямо в чат."
    )


@router.message(Command("hangman"))
async def cmd_hangman(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в групповом чате.")
        return

    thread_id = effective_thread_id(message)
    if registry.is_busy(message.chat.id, thread_id):
        await message.answer("В этом чате уже идёт другая игра. Дождитесь её окончания.")
        return

    game = HangmanGame(message.chat.id, thread_id)
    games[(message.chat.id, thread_id)] = game
    registry.occupy(message.chat.id, thread_id, GAME_TYPE)

    await message.answer(
        f"🎯 <b>Виселица!</b> Игра открыта для всех в чате — присоединяться не нужно.\n\n{status_text(game)}",
    )


@router.message(Command("hangman_stop"))
async def cmd_hangman_stop(message: Message):
    thread_id = effective_thread_id(message)
    key = (message.chat.id, thread_id)
    game = games.get(key)
    if game is None:
        await message.answer("Сейчас никто не играет в виселицу в этой ветке.")
        return
    await message.answer(f"🚫 Игра остановлена. Загаданное слово было: <b>{game.word}</b>.")
    games.pop(key, None)
    registry.release(message.chat.id, thread_id)


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message):
    if not message.text:
        raise SkipHandler
    key = (message.chat.id, effective_thread_id(message))
    game = games.get(key)
    if game is None:
        raise SkipHandler

    guess = message.text.strip().upper()
    if not guess or len(guess) > len(game.word) + 5:
        return

    bot = message.bot

    if guess == game.word:
        game.guessed_letters.update(game.word)
    elif len(guess) == 1 and guess.isalpha():
        if guess in game.guessed_letters or guess in game.wrong_letters:
            return
        if guess in game.word:
            game.guessed_letters.add(guess)
        else:
            game.wrong_letters.add(guess)
    else:
        return

    if game.is_won:
        await message.answer(f"🎉 Отгадано! Слово было: <b>{game.word}</b>. Победа общими усилиями!")
        games.pop(key, None)
        registry.release(game.chat_id, game.thread_id)
        return

    if game.is_lost:
        await message.answer(f"{STAGES[-1]}\n💀 Не повезло! Загаданное слово было: <b>{game.word}</b>.")
        games.pop(key, None)
        registry.release(game.chat_id, game.thread_id)
        return

    await bot.send_message(game.chat_id, status_text(game), message_thread_id=game.thread_id)