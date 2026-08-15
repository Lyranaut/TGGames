import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8877933719:AAHFvZBK5dIIDzQVk1ZMvdTaCwJugWAUJWk")

STARTING_BALANCE = 1000     # стартовые фишки для нового игрока (выдаются автоматически)

BLACKJACK_MIN_BET = 10
POKER_MIN_BET = 10
SLOTS_MIN_BET = 10

ROULETTE_MIN_BET = 10
ROULETTE_BET_TIME = 30      # секунд открыт приём ставок перед спином
