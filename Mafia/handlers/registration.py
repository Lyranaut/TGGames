from __future__ import annotations
 
import random
from collections import Counter
 
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
 
from config import MIN_PLAYERS
from game.manager import GameManager, effective_thread_id
from game.models import Game, GameState, Player, Role, ROLE_NAMES, ROLE_DESCRIPTIONS
from game.roles import assign_roles, parse_role_counts
from handlers.common import known_users
 
router = Router()
 
_SECRET_TRIGGER = "секретн"
 
ROLE_ORDER = [
    Role.MAFIA, Role.DON, Role.DETECTIVE, Role.DOCTOR,
    Role.COURTESAN, Role.MANIAC, Role.TWOFACED, Role.CIVILIAN,
]
 
 
def _format_role_counts(roles: list) -> str:
    counts = Counter(roles)
    lines = [
        f"{ROLE_NAMES[role]}: {counts[role]}"
        for role in ROLE_ORDER
        if counts[role] > 0
    ]
    return "🎭 <b>Состав ролей:</b>\n" + "\n".join(lines)
 
 
_DECOY_CANDIDATES = [Role.MAFIA, Role.DON, Role.DOCTOR, Role.DETECTIVE, Role.COURTESAN, Role.TWOFACED]
 
 
def _generate_decoy_roles() -> dict:
    """Полностью случайный, но правдоподобно выглядящий набор ролей.
 
    Используется в secret_mode вместо реального (все — маньяки): и в
    сообщении регистрации, и как пул для "публичных" fake_role игроков.
    """
    chosen = random.sample(_DECOY_CANDIDATES, k=random.randint(3, len(_DECOY_CANDIDATES)))
    return {role: (2 if role == Role.MAFIA and random.random() < 0.4 else 1) for role in chosen}
 
 
def registration_keyboard(game: Game) -> InlineKeyboardMarkup:
    reveal_text = "🔍 Роли умерших: показывать" if game.reveal_deaths else "🙈 Роли умерших: скрывать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Вступить ({len(game.players)})", callback_data="mafia_join")],
        [InlineKeyboardButton(text=reveal_text, callback_data="mafia_toggle_reveal")],
        [InlineKeyboardButton(text="▶️ Начать игру", callback_data="mafia_start")],
        [InlineKeyboardButton(text="🚫 Отменить", callback_data="mafia_cancel")],
    ])
 
 
def players_list_text(game: Game) -> str:
    if not game.players:
        return "пока никто не вступил"
    return "\n".join(f"{i + 1}. {p.full_name}" for i, p in enumerate(game.players.values()))
 
 
def roles_request_text(game: Game) -> str:
    return "\n".join(
        f"{ROLE_NAMES[role]}: {count}" for role, count in game.custom_roles.items()
    )
 
 
def registration_text(game: Game) -> str:
    min_players = max(MIN_PLAYERS, sum(game.custom_roles.values()))
    return (
        "🎭 <b>Мафия</b>\n"
        f"Роли:\n{roles_request_text(game)}\n(остальные — мирные жители)\n\n"
        "Нажмите «Вступить», чтобы участвовать.\n"
        "⚠️ Перед этим обязательно напишите мне в личные сообщения /start — "
        "иначе я не смогу прислать вам роль.\n\n"
        f"Минимум игроков: {min_players}\n\n"
        f"Участники:\n{players_list_text(game)}"
    )
 
 
def cancel_only_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Отменить", callback_data="mafia_cancel")],
    ])
 
 
@router.message(Command("mafia"))
async def cmd_mafia(message: Message, game_manager: GameManager):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эта команда работает только в групповом чате (в нужной ветке).")
        return
 
    thread_id = effective_thread_id(message)
    if game_manager.get(message.chat.id, thread_id) is not None:
        await message.answer("Игра уже создана в этой ветке. Дождитесь её окончания либо отмените (кнопка «Отменить»).")
        return
 
    game = game_manager.create(message.chat.id, thread_id, host_id=message.from_user.id)
    text = (
        "🎭 <b>Мафия</b>\n\n"
        f"{message.from_user.full_name}, напиши, какие роли и в каком количестве нужны в игре.\n"
        "Доступные роли: мафия, дон, доктор, комиссар, путана, маньяк, двуликий.\n"
        "Например: <code>мафия 2 доктор 1 комиссар 1 маньяк 1</code>\n\n"
        "Все, кому не хватит явной роли, станут мирными жителями."
    )
    sent = await message.answer(text, reply_markup=cancel_only_keyboard(game))
    game.reg_message_id = sent.message_id
 
 
async def _awaiting_role_setup(message: Message, game_manager: GameManager) -> bool:
    if not message.text:
        return False
    game = game_manager.get(message.chat.id, effective_thread_id(message))
    if game is None or game.state != GameState.REGISTRATION or game.custom_roles is not None:
        return False
    return message.from_user.id == game.host_id
 
 
@router.message(F.chat.type.in_({"group", "supergroup"}), _awaiting_role_setup)
async def on_roles_message(message: Message, game_manager: GameManager):
    game = game_manager.get(message.chat.id, effective_thread_id(message))
 
    if _SECRET_TRIGGER in message.text.lower():
        game.secret_mode = True
        game.custom_roles = _generate_decoy_roles()
        sent = await message.answer(registration_text(game), reply_markup=registration_keyboard(game))
        game.reg_message_id = sent.message_id
        return
 
    role_counts, unknown = parse_role_counts(message.text)
    if not role_counts:
        return
 
    if unknown:
        await message.reply(
            "Не распознал роли: " + ", ".join(unknown) + ".\n"
            "Доступные роли: мафия, дон, доктор, комиссар, путана, маньяк, двуликий."
        )
        return
 
    game.custom_roles = role_counts
    sent = await message.answer(registration_text(game), reply_markup=registration_keyboard(game))
    game.reg_message_id = sent.message_id
 
 
async def refresh_registration_message(bot, game: Game):
    try:
        await bot.edit_message_text(
            registration_text(game),
            chat_id=game.chat_id,
            message_id=game.reg_message_id,
            reply_markup=registration_keyboard(game),
        )
    except TelegramBadRequest:
        pass
 
 
@router.callback_query(F.data == "mafia_join")
async def cb_join(callback: CallbackQuery, game_manager: GameManager):
    game = game_manager.get(callback.message.chat.id, effective_thread_id(callback.message))
    if game is None or game.state != GameState.REGISTRATION:
        await callback.answer("Регистрация закрыта.", show_alert=True)
        return
 
    user = callback.from_user
    if user.id in game.players:
        await callback.answer("Вы уже в игре.")
        return
 
    game.players[user.id] = Player(user_id=user.id, username=user.username, full_name=user.full_name)
    await callback.answer("Вы вступили в игру!")
    await refresh_registration_message(callback.bot, game)
 
 
@router.callback_query(F.data == "mafia_toggle_reveal")
async def cb_toggle_reveal(callback: CallbackQuery, game_manager: GameManager):
    game = game_manager.get(callback.message.chat.id, effective_thread_id(callback.message))
    if game is None or game.state != GameState.REGISTRATION:
        await callback.answer()
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("Эту настройку меняет только тот, кто создал игру.", show_alert=True)
        return
 
    game.reveal_deaths = not game.reveal_deaths
    await callback.answer()
    await callback.message.edit_text(registration_text(game), reply_markup=registration_keyboard(game))
 
 
@router.callback_query(F.data == "mafia_cancel")
async def cb_cancel(callback: CallbackQuery, game_manager: GameManager):
    game = game_manager.get(callback.message.chat.id, effective_thread_id(callback.message))
    if game is None:
        await callback.answer()
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("Отменить игру может только тот, кто её создал.", show_alert=True)
        return
 
    game_manager.remove(game.chat_id, game.thread_id)
    await callback.answer("Игра отменена.")
    await callback.message.edit_text("🚫 Игра отменена.")
 
 
@router.callback_query(F.data == "mafia_start")
async def cb_start(callback: CallbackQuery, game_manager: GameManager):
    game = game_manager.get(callback.message.chat.id, effective_thread_id(callback.message))
    if game is None or game.state != GameState.REGISTRATION:
        await callback.answer("Игра уже идёт или отменена.", show_alert=True)
        return
 
    if callback.from_user.id != game.host_id:
        await callback.answer("Начать игру может только тот, кто её создал.", show_alert=True)
        return
 
    min_players = max(MIN_PLAYERS, sum(game.custom_roles.values()))
    if len(game.players) < min_players:
        await callback.answer(f"Нужно минимум {min_players} игроков.", show_alert=True)
        return
 
    unreachable = [p for p in game.players.values() if p.user_id not in known_users]
    if unreachable:
        names = ", ".join(p.full_name for p in unreachable)
        await callback.answer("Не все игроки написали мне в личку.", show_alert=True)
        await callback.message.answer(
            "Эти игроки должны написать мне в личные сообщения /start, прежде чем можно "
            f"будет начать игру:\n{names}"
        )
        return
 
    await callback.answer()
 
    assign_roles(list(game.players.values()), game.custom_roles)
    if game.secret_mode:
        # Игроки видят fake_role (обманку) — реальная роль у всех одна: маньяк.
        for player in game.players.values():
            player.fake_role = player.role
            player.role = Role.MANIAC
    game.day_number = 0
 
    display_roles = [p.fake_role for p in game.players.values()] if game.secret_mode \
        else [p.role for p in game.players.values()]
    start_text = (
        "🎲 Игра начинается! Роли разосланы в личные сообщения.\n\n"
        + _format_role_counts(display_roles)
    )
    await callback.message.edit_text(start_text)
 
    bot = callback.bot
    failed = []
    for player in game.players.values():
        role_text = f"Твоя роль: <b>{ROLE_NAMES[player.role]}</b>\n\n{ROLE_DESCRIPTIONS[player.role]}"
        try:
            await bot.send_message(player.user_id, role_text)
        except TelegramForbiddenError:
            failed.append(player)
 
    if failed:
        names = ", ".join(p.full_name for p in failed)
        await bot.send_message(
            game.chat_id,
            f"⚠️ Не удалось написать в личку: {names}. Игра продолжится, но эти игроки "
            "не смогут выполнять ночные действия, пока не напишут мне /start.",
            message_thread_id=game.thread_id,
        )
 
    from handlers.night import start_night
    await start_night(bot, game, game_manager)
 