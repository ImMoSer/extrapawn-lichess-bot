# `service_info.md` — Архитектура и Спецификация Сервиса `extrapawn-lichess-bot`

> **Назначение:** Круглосуточный Lichess-бот аккаунта **`ExtraPawnCOM`** (`https://lichess.org/@/ExtraPawnCOM`) на базе форка `lichess-bot`, подключающий гибридный спарринг-движок **`MOZERO Bouncer V5.0`** (`chessboard_engines`) и дебютную базу мастеров **`TABLESERVICE`** (`Masters LMDB` + `Opening Wiki`) по внутренней сети `dokploy-network`.  
> **Репозиторий GitHub:** `https://github.com/ImMoSer/extrapawn-lichess-bot`  
> **Глобальные стандарты:** [`GEMINI.md`](file:///c:/MY_APPS/CHESS_APP/GEMINI.md) · [`project_info.md`](file:///c:/MY_APPS/CHESS_APP/project_info.md)

---

## 1. Модульная структура (`extrapawn/` + минимальные хуки в `lib/`)

Вся логика интеграции с ExtraPawn изолирована в модульном пакете [`extrapawn/`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn) (`< 350` строк на файл) через протокол `protocol: "homemade"` (`MinimalEngine`):

- [`extrapawn/config.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/config.py) — Fail-Fast парсер и валидатор переменных окружения (`ExtraPawnConfig.from_env()`: `MAIA_HUB_URL`, `TABLESERVICE_URL`, `BOT_BOOK_*`, параметры человеческого темпа `BOT_*_MOVE_DELAY_SEC`).
- [`extrapawn/clients.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/clients.py) — строго типизированные HTTP-клиенты [`EngineHubClient`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/clients.py) (`GET /health`, `POST /bestmove` с ретраем только на сетевой обрыв/таймаут) и [`TableServiceClient`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/clients.py) (`GET /health`, `GET /opening/mozer_book`, `POST /opening/lookup`).
- [`extrapawn/opening_book.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/opening_book.py) — взвешенный случайный выбор хода по базе мастеров (`auto`) с оценкой качества `rel_cp` (`>= -75`, отсечение `> 60 cp` ниже лучшего), порогом популярности `5%`, защитой от 2x-повторов и поддержкой стилей (`gm`, `sharp`, `gambit`).
- [`extrapawn/engine.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/engine.py) — [`MozeroExtraPawnEngine`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/engine.py): на старте проверяет доступность `engine-hub` и `TABLESERVICE`; в `standard` партиях первые `BOT_BOOK_MAX_PLY` полуходов берёт из `TABLESERVICE`, затем и во всех `fromPosition` эндшпилях передаёт `start_fen` + `moves` в `engine-hub` (`engine: "mozero"`).
- [`extrapawn/chat.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/chat.py) — обработчик команд чата (`!help`, `!style auto|gm|sharp|gambit`, `!opening`, `!info`) с гарантированным ограничением ответа `<= 140` символов.
- Минимальные точки врезки в upstream-ядро: [`homemade.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/homemade.py) (реэкспорт `MozeroExtraPawnEngine`), [`lib/config.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/lib/config.py) (Fail-Fast запрет плейсхолдера/пустого `LICHESS_BOT_TOKEN`), [`lib/conversation.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/lib/conversation.py) (безопасный роутинг `!`-команд), [`lib/lichess_bot.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/lib/lichess_bot.py) (`0` takeback в `rated`, до `5` в `casual`, создание каталога для счётчика takeback).

---

## 2. Игровые, Fair-Play и Dokploy Инварианты

1. **Единый интеллект без дублирования:** в контейнере бота нет локальных весов `lc0`, `Stockfish` или таблиц — все вычисления выполняются через `MAIA_HUB_URL` и `TABLESERVICE_URL` по `dokploy-network`. `online_egtb` и встроенные книги `lichess-bot` отключены (`enabled: false`), чтобы не ломать характер `MOZERO Bouncer V5.0` и не зависеть от внешних лимитов.
2. **Политика вызовов ([`config.extrapawn.yml`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/config.extrapawn.yml)):** только люди (`accept_bot: false`, `allow_matchmaking: false`), `blitz` + `rapid` (`max_base: 1800`, `max_increment: 30`), `rated` + `casual`, `standard` + `fromPosition`, `concurrency: 2`, `max_simultaneous_games_per_user: 1`.
3. **Fair-Play:** `takeback` строго запрещён в `rated` партиях и разрешён до `5` раз в `casual`; `!eval` работает только для зрителей (`spectator`) и самого бота; все приветствия и ответы в чат укладываются в лимит Lichess `140` символов без спама.
4. **Переменные Dokploy (`.env_dokploy`):** `MAIA_HUB_URL=${{project.MAIA_HUB_URL}}`, `TABLESERVICE_URL=${{project.TABLESERVICE_URL}}`, секретный `LICHESS_BOT_TOKEN` задаётся в Dokploy Environment. Контейнер не открывает входящих портов.

---

## 3. Локальная проверка перед коммитом

```powershell
cd C:\MY_APPS\CHESS_APP\extrapawn-lichess-bot
python -m py_compile extrapawn/__init__.py extrapawn/config.py extrapawn/clients.py extrapawn/opening_book.py extrapawn/engine.py extrapawn/chat.py homemade.py lib/config.py lib/conversation.py lib/lichess_bot.py tests/test_extrapawn.py tests/test_extrapawn_integration.py
docker compose config --quiet
docker build -t extrapawn-lichess-bot:verify .
docker run --rm extrapawn-lichess-bot:verify python3 -m unittest discover -s tests -p "test_*.py" -v
```
