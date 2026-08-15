import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8735180557:AAGbpyQ1_DtEuF1fSP-wb9S7a4KVhM_phOY")

# ==== Крокодил ====
CROCODILE_MIN_PLAYERS = 3
CROCODILE_ROUND_TIME = 90          # секунд на объяснение одного слова

# ==== Виселица ====
HANGMAN_MAX_WRONG = 6               # сколько неверных букв допускается

# ==== Кто я? ====
WHOAMI_MIN_PLAYERS = 3

# ==== Элиас 2 на 2 ====
ELIAS_ROUND_TIME = 60               # секунд на один заход объяснения
ELIAS_ROUNDS_PER_TEAM = 2           # сколько заходов у каждой команды всего

# ==== Джекбокс-игра (заполни пропуск + голосование за самый смешной ответ) ====
FUNPROMPT_MIN_PLAYERS = 3
FUNPROMPT_ROUNDS = 3
FUNPROMPT_SUBMIT_TIME = 90          # секунд на отправку ответа в ЛС
FUNPROMPT_VOTE_TIME = 45            # секунд на голосование

# ==== Викторина ====
QUIZ_MIN_PLAYERS = 2
QUIZ_ROUNDS = 10
QUIZ_QUESTION_TIME = 30
