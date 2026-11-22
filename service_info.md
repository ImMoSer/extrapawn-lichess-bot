# `service_info.md` — Архитектура и Спецификация Сервиса `extrapawn-lichess-bot`

> **Назначение:** Круглосуточный гибридный Lichess-бот аккаунта **`ExtraPawnCOM`** (`https://lichess.org/@/ExtraPawnCOM`), работающий по 3-контурной схеме **Вариант «C»**: адаптивный `MOZERO-1500 / -1700 / -1900 / -2200` в `Casual`, фиксированный мастерский `MOZERO-2200` в `Rated` (честный Glicko-2) и эталонный `MOZERO-FullPower` (`Elite-Leela-v2` `50 nodes` + `Stockfish d=12` + `Syzygy/Gaviota`) в `From Position` (заданный FEN).  
> **Репозиторий GitHub:** `https://github.com/ImMoSer/extrapawn-lichess-bot`  
> **Глобальные стандарты:** [`GEMINI.md`](file:///c:/MY_APPS/CHESS_APP/GEMINI.md) · [`project_info.md`](file:///c:/MY_APPS/CHESS_APP/project_info.md)

---

## 1. Модульная структура (`extrapawn/` + минимальные хуки в `lib/`)

Вся логика интеграции с ExtraPawn изолирована в модульном пакете [`extrapawn/`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn) (`< 350` строк на файл) через протокол `protocol: "homemade"` (`MinimalEngine`):

- [`extrapawn/config.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/config.py) — Fail-Fast парсер и валидатор переменных окружения (`ExtraPawnConfig.from_env()`: `MAIA_HUB_URL`, `TABLESERVICE_URL`, `BOT_BOOK_*`, темп хода `0.05–0.20 с`).
- [`extrapawn/tiers.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/tiers.py) — 3-контурная маршрутизация `select_tier_for_game()`:
  1. **`From Position` (кастомный FEN):** `MOZERO-FullPower` (`engine: "mozero"`, `use_opening_book=False`).
  2. **`Rated` (`Standard`):** фиксированный `MOZERO-2200` (`engine: "maia_2200"`, `significant_only=true`, `memory_keep_prob=1.0`) для любого соперника.
  3. **`Casual` (`Standard`):** адаптивно по `game.opponent.rating`:
     - `<= 1800` или без рейтинга → `MOZERO-1500` (`maia_1500`, `top_n=12`, `min_games=2`, `rel_cp >= -180`, `exp=0.25`, `memory_keep_prob=0.55`);
     - `1801–2000` → `MOZERO-1700` (`maia_1700`, `top_n=10`, `min_games=4`, `rel_cp >= -140`, `exp=0.40`, `memory_keep_prob=0.72`);
     - `2001–2200` → `MOZERO-1900` (`maia_1900`, `top_n=7`, `min_games=8`, `rel_cp >= -95`, `exp=0.60`, `memory_keep_prob=0.86`);
     - `> 2200` → `MOZERO-2200` (`maia_2200`, `top_n=4`, `min_games=20`, `rel_cp >= -50`, `exp=0.85`, `memory_keep_prob=1.0`).
- [`extrapawn/clients.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/clients.py) — строго типизированные HTTP-клиенты [`EngineHubClient`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/clients.py) и [`TableServiceClient`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/clients.py).
- [`extrapawn/opening_book.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/opening_book.py) — уровневая выборка дебютных ходов по параметрам `AdaptiveTierProfile` с защитой от 2x-повторов.
- [`extrapawn/engine.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/engine.py) — [`MozeroExtraPawnEngine`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/extrapawn/engine.py): выставляет `engine.name()` равным `MOZERO-1500 / -1700 / -1900 / -2200 / -FullPower` для приветствия в чате `{engine}`, моделирует «память дебюта» с `ply >= 4` и вызывает соответствующий движок в `engine-hub`.
- Минимальные точки врезки в upstream-ядро: [`homemade.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/homemade.py), [`lib/config.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/lib/config.py), [`lib/conversation.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/lib/conversation.py), [`lib/lichess_bot.py`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/lib/lichess_bot.py) (`{engine}` в `keyword_map`, `0` takeback в `rated`, до `5` в `casual`).

---

## 2. Игровые, Fair-Play и Dokploy Инварианты

1. **Честный Glicko-2 + защита ресурсов VPS:** в `Rated` сила бота строго фиксирована (`MOZERO-2200`), исключая rating farming; тяжёлый `MOZERO-FullPower` (`50 nodes`) включается только в `From Position`.
2. **Политика вызовов ([`config.extrapawn.yml`](file:///c:/MY_APPS/CHESS_APP/extrapawn-lichess-bot/config.extrapawn.yml)):** только люди (`accept_bot: false`, `allow_matchmaking: false`), `blitz` + `rapid` (`max_base: 1800`, `max_increment: 30`), `rated` + `casual`, `standard` + `fromPosition`, `concurrency: 2`, `max_simultaneous_games_per_user: 1`. Задержка темпа `<= 200 мс`.
3. **Приветствие и чат:** в начале партии бот сообщает активный профиль (`Hi {opponent}! Active engine: {engine}...`); интерактивные команды в чате отключены.
4. **Переменные Dokploy (`.env_dokploy`):** `MAIA_HUB_URL=${{project.MAIA_HUB_URL}}`, `TABLESERVICE_URL=${{project.TABLESERVICE_URL}}`, секретный `LICHESS_BOT_TOKEN` задаётся в Dokploy Environment.

---

## 3. Локальная проверка перед коммитом

```powershell
cd C:\MY_APPS\CHESS_APP\extrapawn-lichess-bot
.\.venv\Scripts\python.exe -m py_compile extrapawn/__init__.py extrapawn/config.py extrapawn/tiers.py extrapawn/clients.py extrapawn/opening_book.py extrapawn/engine.py homemade.py lib/config.py lib/conversation.py lib/lichess_bot.py tests/test_extrapawn.py tests/test_extrapawn_integration.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

*(При запущенном Docker Desktop дополнительно проверяется сборка образа: `docker compose config --quiet; docker build -t extrapawn-lichess-bot:verify .`)*

---

## 4. Единственная ветка `main` и синхронизация с `upstream`

В репозитории `ImMoSer/extrapawn-lichess-bot` используется **единственная основная ветка `main`** (Default Branch на GitHub и ветка автодеплоя в Dokploy; устаревшая ветка `master` удалена). Оригинальный репозиторий подключён как `upstream` (`https://github.com/lichess-bot-devs/lichess-bot.git`, где основная ветка называется `master`).

> **Важно:** Не используйте кнопку **«Sync fork»** в веб-интерфейсе GitHub напрямую в `main` без локального прогона тестов, так как `git push` в `main` мгновенно запускает продакшен-деплой в Dokploy.

Безопасное обновление ядра `lichess-bot` при выходе критических изменений Lichess BOT API:

```powershell
cd C:\MY_APPS\CHESS_APP\extrapawn-lichess-bot
git checkout main
git pull origin main
git fetch upstream
git merge upstream/master
# Если возник конфликт в публичном README.md — оставляем нашу витрину ExtraPawn:
# git checkout --ours README.md; git add README.md
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
git push origin main
```
