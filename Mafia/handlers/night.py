from __future__ import annotations

import asyncio
import random

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import NIGHT_ACTION_TIMEOUT
from game.manager import GameManager
from game.models import Game, GameState, Role, ROLE_NAMES

router = Router()

MAFIA_TEAM = (Role.MAFIA, Role.DON)


def alive_players(game: Game, exclude: int | None = None):
    return [p for p in game.players.values() if p.alive and p.user_id != exclude]


def target_keyboard(game: Game, action: str, exclude: int | None = None) -> InlineKeyboardMarkup:
    buttons = []
    for p in alive_players(game, exclude=exclude):
        buttons.append([InlineKeyboardButton(
            text=p.full_name,
            callback_data=f"night:{action}:{game.chat_id}:{game.thread_id or 0}:{p.user_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def start_night(bot, game: Game, game_manager: GameManager):
    game.state = GameState.NIGHT
    game.day_number += 1
    game.night_actions = {}

    await bot.send_message(
        game.chat_id,
        f"🌙 Наступает ночь {game.day_number}. Город засыпает — у активных ролей есть "
        f"{NIGHT_ACTION_TIMEOUT} секунд, чтобы сделать выбор в личных сообщениях с ботом.",
        message_thread_id=game.thread_id,
    )

    mafia_team = [p for p in alive_players(game) if p.role in MAFIA_TEAM]
    doctor_players = [p for p in alive_players(game) if p.role == Role.DOCTOR]
    detective_players = [p for p in alive_players(game) if p.role == Role.DETECTIVE]
    courtesan_players = [p for p in alive_players(game) if p.role == Role.COURTESAN]
    maniac_players = [p for p in alive_players(game) if p.role == Role.MANIAC]

    for p in mafia_team:
        try:
            await bot.send_message(
                p.user_id, "🔪 Выберите, кого убить этой ночью:",
                reply_markup=target_keyboard(game, "kill", exclude=p.user_id),
            )
        except Exception:
            pass

    for p in doctor_players:
        healed_self_last_night = game.last_heal_targets.get(p.user_id) == p.user_id
        text = "💉 Выберите, кого вылечить этой ночью:"
        if healed_self_last_night:
            text += "\n(прошлой ночью вы лечили себя — сегодня себя выбрать нельзя)"
        try:
            await bot.send_message(
                p.user_id, text,
                reply_markup=target_keyboard(game, "heal", exclude=p.user_id if healed_self_last_night else None),
            )
        except Exception:
            pass

    for p in detective_players:
        try:
            await bot.send_message(
                p.user_id, "🕵️ Выберите, чью роль проверить этой ночью:",
                reply_markup=target_keyboard(game, "check", exclude=p.user_id),
            )
        except Exception:
            pass

    for p in courtesan_players:
        try:
            await bot.send_message(
                p.user_id,
                "💋 Кого навестите этой ночью? (его ночное действие будет заблокировано)",
                reply_markup=target_keyboard(game, "courtesan", exclude=p.user_id),
            )
        except Exception:
            pass

    for p in maniac_players:
        try:
            await bot.send_message(
                p.user_id, "🔦 Выберите жертву этой ночью:",
                reply_markup=target_keyboard(game, "maniac", exclude=p.user_id),
            )
        except Exception:
            pass

    await asyncio.sleep(NIGHT_ACTION_TIMEOUT)
    await resolve_night(bot, game, game_manager)


@router.callback_query(F.data.startswith("night:"))
async def cb_night_action(callback: CallbackQuery, game_manager: GameManager):
    _, action, chat_id, thread_id, target_id = callback.data.split(":")
    chat_id = int(chat_id)
    thread_id = int(thread_id) or None
    target_id = int(target_id)

    game = game_manager.get(chat_id, thread_id)
    if game is None or game.state != GameState.NIGHT:
        await callback.answer("Ночь уже закончилась.", show_alert=True)
        return

    player = game.players.get(callback.from_user.id)
    if player is None or not player.alive:
        await callback.answer()
        return

    if action == "kill" and player.role in MAFIA_TEAM:
        game.night_actions.setdefault("kill_votes", {})[player.user_id] = target_id
        await callback.answer("Голос учтён.")
    elif action == "heal" and player.role == Role.DOCTOR:
        if target_id == player.user_id and game.last_heal_targets.get(player.user_id) == player.user_id:
            await callback.answer("Нельзя лечить себя две ночи подряд.", show_alert=True)
            return
        game.night_actions.setdefault("heal", {})[player.user_id] = target_id
        await callback.answer("Выбор сохранён.")
    elif action == "check" and player.role == Role.DETECTIVE:
        game.night_actions["check"] = target_id
        target = game.players.get(target_id)
        if target.role == Role.DON:
            is_mafia = False  # дон обманывает проверку
        elif target.role == Role.TWOFACED:
            is_mafia = True  # двуликий ложно светится мафией
        else:
            is_mafia = target.role in MAFIA_TEAM
        await callback.answer(
            f"{target.full_name}: {'МАФИЯ 🔪' if is_mafia else 'не мафия ✅'}",
            show_alert=True,
        )
    elif action == "courtesan" and player.role == Role.COURTESAN:
        game.night_actions.setdefault("courtesan", {})[player.user_id] = target_id
        await callback.answer("Вы навестили этого игрока.")
    elif action == "maniac" and player.role == Role.MANIAC:
        game.night_actions.setdefault("maniac_kill", {})[player.user_id] = target_id
        await callback.answer("Жертва выбрана.")
    else:
        await callback.answer()
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


async def resolve_night(bot, game: Game, game_manager: GameManager):
    # courtesan_id -> кого она навестила (её "клиент"); может быть несколько
    # путан за игру, если так выпал случайный support-слот.
    courtesan_visits = game.night_actions.get("courtesan", {})
    blocked_ids = set(courtesan_visits.values())

    kill_votes = game.night_actions.get("kill_votes", {})
    kill_votes = {voter: target for voter, target in kill_votes.items() if voter not in blocked_ids}

    victim_id = None
    if kill_votes:
        tally: dict = {}
        for target in kill_votes.values():
            tally[target] = tally.get(target, 0) + 1
        max_votes = max(tally.values())
        top = [t for t, v in tally.items() if v == max_votes]
        victim_id = random.choice(top)

    heal_votes = game.night_actions.get("heal", {})
    game.last_heal_targets = dict(heal_votes)
    heal_votes = {doc_id: t for doc_id, t in heal_votes.items() if doc_id not in blocked_ids}
    healed_ids = set(heal_votes.values())

    maniac_votes = game.night_actions.get("maniac_kill", {})
    maniac_votes = {man_id: t for man_id, t in maniac_votes.items() if man_id not in blocked_ids}
    maniac_targets = set(maniac_votes.values())

    deaths = set()
    if victim_id is not None and victim_id not in healed_ids and victim_id in game.players:
        deaths.add(victim_id)
    for target in maniac_targets:
        if target is not None and target not in healed_ids and target in game.players:
            deaths.add(target)

    # Если путана этой ночью погибла от рук мафии/маньяка — её "клиент"
    # (кого она навестила) тоже гибнет, если его не спас доктор.
    client_deaths = set()
    for courtesan_id, client_id in courtesan_visits.items():
        if courtesan_id in deaths and client_id not in healed_ids and client_id in game.players:
            client_deaths.add(client_id)
    deaths |= client_deaths

    lines = [f"☀️ Наступает день {game.day_number}."]
    victims = []
    if deaths:
        for uid in deaths:
            victim = game.players[uid]
            victim.alive = False
            victims.append(victim)
            note = " (был(а) клиентом погибшей путаны этой ночью)" if uid in client_deaths else ""
            role_note = ""
            if game.reveal_deaths:
                shown_role = victim.fake_role if game.secret_mode else victim.role
                role_note = f" Роль: {ROLE_NAMES[shown_role]}."
            lines.append(f"Этой ночью погиб(ла) {victim.mention}.{role_note}{note}")
    else:
        lines.append("Этой ночью никто не погиб.")

    await bot.send_message(game.chat_id, "\n".join(lines), message_thread_id=game.thread_id)

    if victims:
        from handlers.day import wait_for_last_words
        for victim in victims:
            await wait_for_last_words(bot, game, victim)

    if await check_win(bot, game, game_manager):
        return

    from handlers.day import start_day
    await start_day(bot, game, game_manager)


async def check_win(bot, game: Game, game_manager: GameManager) -> bool:
    alive = [p for p in game.players.values() if p.alive]

    if game.secret_mode:
        if len(alive) <= 1:
            winner_text = f"🔦 {alive[0].mention} побеждает — все остальные погибли!" if alive else "Никто не выжил — ничья."
            await announce_end(bot, game, winner_text)
            game_manager.remove(game.chat_id, game.thread_id)
            return True
        return False

    mafia_alive = sum(1 for p in alive if p.role in MAFIA_TEAM)
    maniac_alive = sum(1 for p in alive if p.role == Role.MANIAC)
    civilians_alive = len(alive) - mafia_alive - maniac_alive

    if maniac_alive > 0 and len(alive) <= 2:
        await announce_end(bot, game, "🔦 Маньяк победил! Он остался один на один с последним соперником (либо единственным живым).")
        game_manager.remove(game.chat_id, game.thread_id)
        return True

    if mafia_alive == 0 and maniac_alive == 0:
        await announce_end(bot, game, "🎉 Мирные жители победили! Вся мафия обезврежена.")
        game_manager.remove(game.chat_id, game.thread_id)
        return True

    if mafia_alive > 0 and mafia_alive >= civilians_alive + maniac_alive:
        await announce_end(bot, game, "🔪 Мафия победила! Мафия составляет большинство среди живых.")
        game_manager.remove(game.chat_id, game.thread_id)
        return True

    return False


async def announce_end(bot, game: Game, message: str):
    roles_text = "\n".join(
        f"{p.full_name} — {ROLE_NAMES[p.role]}{'' if p.alive else ' (погиб)'}"
        for p in game.players.values()
    )
    await bot.send_message(
        game.chat_id,
        f"{message}\n\nРоли всех игроков:\n{roles_text}",
        message_thread_id=game.thread_id,
    )
