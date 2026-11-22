# `service_info.md` — Архитектура и Спецификация Сервиса `extrapawn-lichess-bot`

> **Назначение:** Круглосуточный адаптивный Lichess-бот аккаунта **`ExtraPawnCOM`** (`https://lichess.org/@/ExtraPawnCOM`) на базе форка `lichess-bot`, автоматически подбирающий под рейтинг соперника одну из 4 человеческих нейросетей **`maia_1500 / maia_1700 / maia_1900 / maia_2200`** (`nodes = 1` в `chessboard_engines` с мягким `BouncerProfile` и полными таблицами `<= 5` фигур) и уровневый дебютный профиль из **`TABLESERVICE`** (`Masters LMDB`) по внутренней сети `dokploy-network`.  
> **Репозиторий GitHub:** `https://github.com/ImMoSer/extrapawn-lichess-bot`  
> **Глобальные стандарты:** [`GEMINI.md`](file:///c:/MY_APPS/CHESS_APP/GEMINI.md) · [`project_info.md`](file:///c:/MY_APPS/CHESS_APP/project_info.md)

---

## 1. Модульная структура (`extrapawn/` + минимальные хуки в `lib/`)

Вся логика интеграции с ExtraPawn изолирована в модульном пакете [`extrapawn/`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn) (`< 350` строк на файл) через протокол `protocol: "homemade"` (`MinimalEngine`):

- [`extrapawn/config.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/config.py) — Fail-Fast парсер и валидатор переменных окружения (`ExtraPawnConfig.from_env()`: `MAIA_HUB_URL`, `TABLESERVICE_URL`, `BOT_BOOK_*`, параметры человеческого темпа `BOT_*_MOVE_DELAY_SEC`, по умолчанию `0.05–0.20 с`).
- [`extrapawn/tiers.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/tiers.py) — маппинг рейтинга соперника в `AdaptiveTierProfile`:
  - `< 1600` → `maia_1500` (`significant_only=false`, `top_n=12`, `min_games=2`, `rel_cp >= -180`, `exp=0.25`, `memory_keep_prob=0.55`);
  - `1600–1799` → `maia_1700` (`significant_only=false`, `top_n=10`, `min_games=4`, `rel_cp >= -140`, `exp=0.40`, `memory_keep_prob=0.72`);
  - `1800–2049` → `maia_1900` (`significant_only=false`, `top_n=7`, `min_games=8`, `rel_cp >= -95`, `exp=0.60`, `memory_keep_prob=0.86`);
  - `>= 2050` или без рейтинга → `maia_2200` (`significant_only=true`, `top_n=4`, `min_games=20`, `rel_cp >= -50`, `exp=0.85`, `memory_keep_prob=1.0`).
- [`extrapawn/clients.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/clients.py) — строго типизированные HTTP-клиенты [`EngineHubClient`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/clients.py) (`GET /health`, `POST /bestmove` с явным именем `engine: "maia_*"`) и [`TableServiceClient`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/clients.py) (`GET /health`, `GET /opening/mozer_book`, `POST /opening/lookup`).
- [`extrapawn/opening_book.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/opening_book.py) — уровневая выборка дебютных ходов по параметрам `AdaptiveTierProfile` с защитой от 2x-повторов и поддержкой стилей (`auto`, `gm`, `sharp`, `gambit`).
- [`extrapawn/engine.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/engine.py) — [`MozeroExtraPawnEngine`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/engine.py): фиксирует тир на старте партии по `game.opponent.rating`, моделирует «человеческую память дебюта» с 3-го хода (`ply >= 4`: при выпадении выхода из памяти книга закрывается до конца партии) и вызывает соответствующий `maia_*` в `engine-hub` (`Elite-Leela-v2` на Lichess не используется).
- Минимальные точки врезки в upstream-ядро: [`homemade.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/homemade.py), [`lib/config.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/lib/config.py), [`lib/conversation.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/lib/conversation.py) (приветствия без интерактивных `!`-команд на Stage 1), [`lib/lichess_bot.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/lib/lichess_bot.py) (`0` takeback в `rated`, до `5` в `casual`).

---

## 2. Игровые, Fair-Play и Dokploy Инварианты

1. **Адаптивный интеллект и изоляция `Elite-Leela-v2`:** Lichess-бот использует исключительно лёгкие пулы `maia_1500..2200` (`nodes = 1`), оставляя тяжёлый профиль `"mozero"` (`50 nodes`) основному приложению `extrapawn.com`. В `<= 5` фигурах для всех тиров работает полная табличная логика `MOZERO` (`Syzygy / Gaviota`).
2. **Политика вызовов ([`config.extrapawn.yml`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/config.extrapawn.yml)):** только люди (`accept_bot: false`, `allow_matchmaking: false`), `blitz` + `rapid` (`max_base: 1800`, `max_increment: 30`), `rated` + `casual`, `standard` + `fromPosition`, `concurrency: 2`, `max_simultaneous_games_per_user: 1`. Задержка темпа `<= 200 мс` (`0.05–0.20 с`).
3. **Fair-Play и чат:** `takeback` строго запрещён в `rated` партиях и разрешён до `5` раз в `casual`; интерактивные команды в чате отключены (только приветствие/прощание `<= 140` символов).
4. **Переменные Dokploy (`.env_dokploy`):** `MAIA_HUB_URL=${{project.MAIA_HUB_URL}}`, `TABLESERVICE_URL=${{project.TABLESERVICE_URL}}`, секретный `LICHESS_BOT_TOKEN` задаётся в Dokploy Environment. Контейнер не открывает входящих портов.

---

## 3. Локальная проверка перед коммитом

```powershell
cd C:\MY_APPS\CHESS_APP\extrapawn-lichess-bot
python -m py_compile extrapawn/__init__.py extrapawn/config.py extrapawn/tiers.py extrapawn/clients.py extrapawn/opening_book.py extrapawn/engine.py homemade.py lib/config.py lib/conversation.py lib/lichess_bot.py tests/test_extrapawn.py tests/test_extrapawn_integration.py
docker compose config --quiet
docker build -t extrapawn-lichess-bot:verify .
docker run --rm extrapawn-lichess-bot:verify python3 -m unittest discover -s tests -p "test_*.py" -v
```
