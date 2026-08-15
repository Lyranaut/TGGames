from __future__ import annotations
 
import asyncio
 
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
 
from config import DAY_SPEECH_TIME, DAY_FREE_DISCUSSION_TIME, DAY_VOTE_TIME, LAST_WORDS_TIME
from game.manager import GameManager, effective_thread_id
from game.models import Game, GameState, ROLE_NAMES
 
router = Router()
 
# (chat_id, thread_id) -> asyncio.Event, взводится когда текущий спикер написал сообщение
_speech_events: dict = {}
# (chat_id, thread_id) -> asyncio.Event, взводится когда умерший сказал последнее слово
_last_word_events: dict = {}
 
 
async def start_day(bot, game: Game, game_manager: GameManager):
    game.state = GameState.DAY_SPEECH
    game.speech_order = [p.user_id for p in game.players.values() if p.alive]
    game.speech_index = 0
 
    await bot.send_message(
        game.chat_id,
        "Обсуждение: каждый живой игрок по очереди высказывается "
        f"(1 сообщение, {DAY_SPEECH_TIME} секунд на ход).",
        message_thread_id=game.thread_id,
    )
 
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
 
    await bot.send_message(
        game.chat_id,
        f"🎤 Слово предоставляется {player.mention}. {DAY_SPEECH_TIME} секунд.",
        message_thread_id=game.thread_id,
    )
 
    key = (game.chat_id, game.thread_id)
    event = asyncio.Event()
    _speech_events[key] = event
 
    try:
        await asyncio.wait_for(event.wait(), timeout=DAY_SPEECH_TIME)
    except asyncio.TimeoutError:
        pass
    finally:
        _speech_events.pop(key, None)
 
    game.speech_index += 1
    await next_speaker(bot, game, game_manager)
 
 
async def wait_for_last_words(bot, game: Game, victim) -> None:
    """Даёт погибшему игроку LAST_WORDS_TIME секунд на последнее слово в чате.
 
    Пока идёт последнее слово, сообщения всех остальных участников тихо
    удаляются — по той же логике, что и во время обычной речи по очереди.
    """
    game.pending_last_word_id = victim.user_id
 
    await bot.send_message(
        game.chat_id,
        f"🕯 {victim.mention}, у вас есть {LAST_WORDS_TIME} секунд на последнее слово.",
        message_thread_id=game.thread_id,
    )
 
    key = (game.chat_id, game.thread_id)
    event = asyncio.Event()
    _last_word_events[key] = event
 
    try:
        await asyncio.wait_for(event.wait(), timeout=LAST_WORDS_TIME)
    except asyncio.TimeoutError:
        pass
    finally:
        _last_word_events.pop(key, None)
        game.pending_last_word_id = None
 
 
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message, game_manager: GameManager):
    game = game_manager.get(message.chat.id, effective_thread_id(message))
    if game is None:
        return
 
    # Последнее слово имеет приоритет — оно может идти в любой фазе
    # (обычно сразу после ночи, ещё до объявления дня).
    if game.pending_last_word_id is not None:
        key = (game.chat_id, game.thread_id)
        if message.from_user.id == game.pending_last_word_id:
            event = _last_word_events.get(key)
            if event is not None:
                event.set()
        else:
            try:
                await message.delete()
            except Exception:
                pass
        return
 
    if game.state != GameState.DAY_SPEECH:
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
    game.state = GameState.DAY_DISCUSSION
    await bot.send_message(
        game.chat_id,
        f"💬 Свободное обсуждение {DAY_FREE_DISCUSSION_TIME} секунд, дальше — голосование.",
        message_thread_id=game.thread_id,
    )
    await asyncio.sleep(DAY_FREE_DISCUSSION_TIME)
    await start_vote(bot, game, game_manager)
 
 
def vote_keyboard(game: Game) -> InlineKeyboardMarkup:
    buttons = []
    for p in game.players.values():
        if not p.alive:
            continue
        buttons.append([InlineKeyboardButton(
            text=p.full_name,
            callback_data=f"vote:{game.chat_id}:{game.thread_id or 0}:{p.user_id}",
        )])
    buttons.append([InlineKeyboardButton(
        text="Пропустить",
        callback_data=f"vote:{game.chat_id}:{game.thread_id or 0}:0",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
 
 
async def start_vote(bot, game: Game, game_manager: GameManager):
    game.state = GameState.DAY_VOTE
    game.votes = {}
    await bot.send_message(
        game.chat_id,
        f"🗳 Голосование! У вас {DAY_VOTE_TIME} секунд, чтобы выбрать, кого казнить.",
        message_thread_id=game.thread_id,
        reply_markup=vote_keyboard(game),
    )
    await asyncio.sleep(DAY_VOTE_TIME)
    await resolve_vote(bot, game, game_manager)
 
 
@router.callback_query(F.data.startswith("vote:"))
async def cb_vote(callback: CallbackQuery, game_manager: GameManager):
    _, chat_id, thread_id, target_id = callback.data.split(":")
    chat_id = int(chat_id)
    thread_id = int(thread_id) or None
    target_id = int(target_id)
 
    game = game_manager.get(chat_id, thread_id)
    if game is None or game.state != GameState.DAY_VOTE:
        await callback.answer("Голосование уже завершено.", show_alert=True)
        return
 
    voter = game.players.get(callback.from_user.id)
    if voter is None or not voter.alive:
        await callback.answer("Голосовать могут только живые игроки.", show_alert=True)
        return
 
    game.votes[voter.user_id] = target_id
    await callback.answer("Голос учтён.")
 
 
async def resolve_vote(bot, game: Game, game_manager: GameManager):
    tally: dict = {}
    for target in game.votes.values():
        if target == 0:
            continue
        tally[target] = tally.get(target, 0) + 1
 
    executed = None
    if not tally:
        await bot.send_message(
            game.chat_id, "Город не сумел договориться — никто не казнён.",
            message_thread_id=game.thread_id,
        )
    else:
        max_votes = max(tally.values())
        top = [t for t, v in tally.items() if v == max_votes]
        if len(top) > 1:
            await bot.send_message(
                game.chat_id, "Голоса разделились поровну — никто не казнён.",
                message_thread_id=game.thread_id,
            )
        else:
            executed = game.players[top[0]]
            executed.alive = False
 
            role_note = ""
            if game.reveal_deaths:
                shown_role = executed.fake_role if game.secret_mode else executed.role
                role_note = f" Роль: {ROLE_NAMES[shown_role]}."
 
            await bot.send_message(
                game.chat_id,
                f"⚖️ Город решил казнить {executed.mention}.{role_note}",
                message_thread_id=game.thread_id,
            )
 
    if executed is not None:
        await wait_for_last_words(bot, game, executed)
 
    from handlers.night import check_win, start_night
    if await check_win(bot, game, game_manager):
        return
    await start_night(bot, game, game_manager)
 