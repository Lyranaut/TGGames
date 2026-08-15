from __future__ import annotations

import asyncio
import random

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import SPEECH_TIME, DISCUSSION_TIME, VOTE_TIME
from game.manager import GameManager
from game.models import Game, GameState
from game.cards import ROUND_CATEGORIES, CARD_LABELS, format_round_reveal, format_full_card

router = Router()

# (chat_id, thread_id) -> asyncio.Event, взводится когда текущий спикер написал сообщение
_speech_events: dict = {}


def alive_players(game: Game):
    return [p for p in game.players.values() if p.alive]


async def start_round(bot, game: Game, game_manager: GameManager, round_index: int):
    alive = alive_players(game)
    if len(alive) <= game.capacity:
        await end_game(bot, game, game_manager)
        return

    game.round_index = round_index
    game.round_number = round_index + 1
    game.state = GameState.ROUND_SPEECH
    game.speech_order = [p.user_id for p in alive]
    game.speech_index = 0

    if round_index < len(ROUND_CATEGORIES):
        keys = ROUND_CATEGORIES[round_index]
        labels = ", ".join(CARD_LABELS[k] for k in keys if k != "age")
        header = (
            f"🔄 <b>Раунд {game.round_number}</b>\n"
            f"В этом раунде каждый раскрывает: {labels}.\n"
            f"Живых игроков: {len(alive)}, мест в бункере: {game.capacity}."
        )
    else:
        header = (
            f"🔄 <b>Раунд {game.round_number}</b> (дополнительный, новых карт больше нет)\n"
            "Обсуждайте и агитируйте — все характеристики уже раскрыты.\n"
            f"Живых игроков: {len(alive)}, мест в бункере: {game.capacity}."
        )

    await bot.send_message(game.chat_id, header, message_thread_id=game.thread_id)
    await next_speaker(bot, game, game_manager)


async def next_speaker(bot, game: Game, game_manager: GameManager):
    if game.speech_index >= len(game.speech_order):
        await start_discussion(bot, game, game_manager)
        return

    speaker_id = game.speech_order[game.speech_index]
    player = game.players.get(speaker_id)
    if player is None or not player.alive:
        game.speech_index += 1
        await next_speaker(bot, game, game_manager)
        return

    if game.round_index < len(ROUND_CATEGORIES):
        keys = ROUND_CATEGORIES[game.round_index]
        reveal_text = format_round_reveal(player.cards, keys)
        hint = f"\n\nВаши карты для раскрытия в этом раунде:\n{reveal_text}"
    else:
        hint = "\n\nВ этом раунде новых карт нет — просто агитируйте за себя."

    await bot.send_message(
        game.chat_id,
        f"🎤 Слово предоставляется {player.mention}. {SPEECH_TIME} секунд.",
        message_thread_id=game.thread_id,
    )
    try:
        await bot.send_message(player.user_id, f"Сейчас ваш ход говорить в чате!{hint}")
    except Exception:
        pass

    key = (game.chat_id, game.thread_id)
    event = asyncio.Event()
    _speech_events[key] = event

    try:
        await asyncio.wait_for(event.wait(), timeout=SPEECH_TIME)
    except asyncio.TimeoutError:
        pass
    finally:
        _speech_events.pop(key, None)

    game.speech_index += 1
    await next_speaker(bot, game, game_manager)


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message, game_manager: GameManager):
    game = game_manager.get_for_message(message.chat.id, message.message_thread_id)
    if game is None or game.state != GameState.ROUND_SPEECH:
        return
    if game.speech_index >= len(game.speech_order):
        return

    current_speaker_id = game.speech_order[game.speech_index]
    if message.from_user.id != current_speaker_id:
        # Не текущий спикер пишет во время чужой речи — тихо удаляем,
        # без каких-либо предупреждений.
        try:
            await message.delete()
        except Exception:
            pass
        return

    key = (game.chat_id, game.thread_id)
    event = _speech_events.get(key)
    if event is not None:
        event.set()


async def start_discussion(bot, game: Game, game_manager: GameManager):
    game.state = GameState.ROUND_DISCUSSION
    await bot.send_message(
        game.chat_id,
        f"💬 Свободное обсуждение {DISCUSSION_TIME} секунд, дальше — голосование.",
        message_thread_id=game.thread_id,
    )
    await asyncio.sleep(DISCUSSION_TIME)
    await start_vote(bot, game, game_manager)


def vote_keyboard(game: Game) -> InlineKeyboardMarkup:
    buttons = []
    for p in alive_players(game):
        buttons.append([InlineKeyboardButton(
            text=p.full_name,
            callback_data=f"bvote:{game.chat_id}:{game.thread_id or 0}:{p.user_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def start_vote(bot, game: Game, game_manager: GameManager):
    game.state = GameState.ROUND_VOTE
    game.votes = {}
    await bot.send_message(
        game.chat_id,
        f"🗳 Голосование! Кого исключить из бункера? У вас {VOTE_TIME} секунд.",
        message_thread_id=game.thread_id,
        reply_markup=vote_keyboard(game),
    )
    await asyncio.sleep(VOTE_TIME)
    await resolve_vote(bot, game, game_manager)


@router.callback_query(F.data.startswith("bvote:"))
async def cb_vote(callback: CallbackQuery, game_manager: GameManager):
    _, chat_id, thread_id, target_id = callback.data.split(":")
    chat_id = int(chat_id)
    thread_id = int(thread_id) or None
    target_id = int(target_id)

    game = game_manager.get(chat_id, thread_id)
    if game is None or game.state != GameState.ROUND_VOTE:
        await callback.answer("Голосование уже завершено.", show_alert=True)
        return

    voter = game.players.get(callback.from_user.id)
    if voter is None or not voter.alive:
        await callback.answer("Голосовать могут только живые участники.", show_alert=True)
        return

    game.votes[voter.user_id] = target_id
    await callback.answer("Голос учтён.")


async def resolve_vote(bot, game: Game, game_manager: GameManager):
    tally: dict = {}
    for target in game.votes.values():
        tally[target] = tally.get(target, 0) + 1

    alive = alive_players(game)
    if not tally:
        # Никто не проголосовал — исключаем случайного, чтобы игра не зависала бесконечно.
        eliminated = random.choice(alive)
    else:
        max_votes = max(tally.values())
        top = [t for t, v in tally.items() if v == max_votes]
        eliminated = game.players[random.choice(top)]

    eliminated.alive = False
    reveal = format_full_card(eliminated.cards)
    await bot.send_message(
        game.chat_id,
        f"❌ Бункер не принял {eliminated.mention}. Его карточки:\n{reveal}",
        message_thread_id=game.thread_id,
    )

    if len(alive_players(game)) <= game.capacity:
        await end_game(bot, game, game_manager)
        return

    await start_round(bot, game, game_manager, round_index=game.round_index + 1)


async def end_game(bot, game: Game, game_manager: GameManager):
    survivors = alive_players(game)
    lines = ["🏁 <b>Игра окончена! Двери бункера закрыты.</b>", "", "Внутри остались:"]
    for p in survivors:
        lines.append(f"✅ {p.mention}\n{format_full_card(p.cards)}\n")

    await bot.send_message(game.chat_id, "\n".join(lines), message_thread_id=game.thread_id)
    game_manager.remove(game.chat_id, game.thread_id)