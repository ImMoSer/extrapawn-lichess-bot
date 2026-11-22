# ExtraPawn Lichess Bot (`@ExtraPawnCOM`)

[![Play on Lichess](https://img.shields.io/badge/Lichess-%40ExtraPawnCOM-1f883d?logo=lichess&logoColor=white)](https://lichess.org/@/ExtraPawnCOM)
[![Platform](https://img.shields.io/badge/Train%20on-ExtraPawn.com-2563eb)](https://extrapawn.com)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)

Official **24/7 human-like neural sparring bot** of **[ExtraPawn.com](https://extrapawn.com)** on Lichess: **[lichess.org/@/ExtraPawnCOM](https://lichess.org/@/ExtraPawnCOM)**.

`@ExtraPawnCOM` is powered by ExtraPawn's hybrid **`MOZERO`** sparring system — combining human-calibrated neural networks (`Maia` & `Elite-Leela-v2`), a tier-matched Masters Opening Book, profile-aware tactical oversight (`Stockfish`), and exact 5-piece endgame tablebases (`Syzygy` & `Gaviota`). Instead of playing sterile computer moves or random artificial blunders, it plays natural, human-style chess tailored to how you train.

---

## How `@ExtraPawnCOM` Plays — The 3-Mode `MOZERO` System

At the start of every game, `@ExtraPawnCOM` selects its sparring profile automatically and announces the active **`MOZERO`** engine in the game chat:

| Game Mode | Active Engine Profile | Opening Book & Behavior | Takebacks |
| :--- | :--- | :--- | :--- |
| **Casual · Standard** (`Blitz` & `Rapid`) | **Adaptive to your Lichess rating:**<br>• `≤ 1800` / unrated → `MOZERO-1500`<br>• `1801–2000` → `MOZERO-1700`<br>• `2001–2200` → `MOZERO-1900`<br>• `> 2200` → `MOZERO-2200` | Tier-scaled Masters Opening Book with natural human opening-memory drop-out (`ply ≥ 4`) and rating-appropriate tactical resilience | Up to **5** |
| **Rated · Standard** (`Blitz` & `Rapid`) | **Fixed Master Tier:**<br>• `MOZERO-2200` for all opponents | Full GM/Masters Opening Book (`significant` lines) — 100% consistent strength for fair Glicko-2 ratings | **0** (Strict) |
| **From Position (`FEN`)** (`Casual` · `Blitz` & `Rapid`) | **Maximum Sparring Strength:**<br>• `MOZERO-FullPower` | `Elite-Leela-v2` + zonal `Stockfish` referee + exact `≤ 5`-piece `Syzygy / Gaviota` tablebase play & endgame swindle resistance | Up to **5** |

### Challenge Rules
- **Opponents:** Human players (`Blitz` and `Rapid` time controls).
- **Variants:** `Standard` and `From Position` (custom FEN).
- **Concurrency:** Up to 2 simultaneous games for instant sub-200ms move responses.

---

## Spar Any Endgame or Opening Position on Lichess (3 Steps)

Want to test whether you can convert a tricky rook endgame, hold a theoretical draw, or practice a sharp opening tabiya against uncompromising defense?

1. Open the **[Lichess Board Editor](https://lichess.org/editor)** (or any Lichess Analysis Board / Study) and set up your target position.
2. Click **Continue from here** → **Play with a friend**.
3. Select **Casual**, choose **Blitz** or **Rapid**, and challenge **`ExtraPawnCOM`** — **`MOZERO-FullPower`** activates automatically whenever a game starts from a custom FEN!

---

## Train Smarter on [ExtraPawn.com](https://extrapawn.com)

`@ExtraPawnCOM` is your live sparring partner on Lichess — for structured improvement, visit **[ExtraPawn.com](https://extrapawn.com)**:

- **Theoretical & Practical Endgames** — master exact endgame technique and convert realistic advantages under resistance.
- **Tactics & "Finish Him" Drills** — sharpen calculation and practice converting winning positions cleanly without allowing counterplay.
- **Woodpecker Method, Sprint & Classical Courses** — build automatic pattern recognition with spaced-repetition cycles and curated study tracks.
- **AI Chess Coach** — understand *why* moves work with clear explanations of plans, positional ideas, and critical mistakes.
- **Instant 1-Click Lichess Login** — sign in directly with your Lichess OAuth account and start training immediately.

---

## Repository Architecture (For Developers)

This repository is ExtraPawn's production Lichess BOT gateway, built as a modular `MinimalEngine` integration on top of [`lichess-bot`](https://github.com/lichess-bot-devs/lichess-bot).

Rather than bundling heavy neural weights or tablebases inside the bot container, `extrapawn-lichess-bot` operates as a lightweight, fail-fast event bridge communicating with ExtraPawn's internal microservices over an isolated Docker network:

- **[`extrapawn/`](extrapawn/)** — Custom ExtraPawn sparring package:
  - [`config.py`](extrapawn/config.py) — Strict fail-fast environment configuration (`MAIA_HUB_URL`, `TABLESERVICE_URL`, pacing & timeouts).
  - [`tiers.py`](extrapawn/tiers.py) — 3-mode `Variant C` routing (`MOZERO-1500 / -1700 / -1900 / -2200 / -FullPower`).
  - [`opening_book.py`](extrapawn/opening_book.py) — Tier-aware Masters Opening Book sampling, eval-loss filtering, probabilistic memory drop-out, and anti-repetition guard.
  - [`clients.py`](extrapawn/clients.py) — Resilient HTTP clients for `engine-hub` (neural + tactical arbiter inference) and `tableservice` (`LMDB` opening book + `Syzygy`/`Gaviota` tablebases).
  - [`engine.py`](extrapawn/engine.py) — `MozeroExtraPawnEngine(MinimalEngine)` orchestrating book lookup, neural/tablebase move selection, and chat telemetry.
- **[`config.extrapawn.yml`](config.extrapawn.yml)** — Production challenge filter, concurrency, takeback policy, and dynamic `{engine}` chat greetings.
- **[`tests/`](tests/)** — Unit and end-to-end integration test suites (`unittest`) covering tier routing, opening-book sampling, rated/casual takeback enforcement, and chat security.

---

## Acknowledgements

`@ExtraPawnCOM` and the `MOZERO` sparring stack stand on the shoulders of outstanding open-source chess software and research:

- **[lichess-bot](https://github.com/lichess-bot-devs/lichess-bot)** by `lichess-bot-devs` and the **[Lichess.org](https://lichess.org)** team for the Lichess BOT API and streaming framework.
- **[python-chess](https://github.com/niklasf/python-chess)** by Niklas Fiekas for move generation, FEN/PGN parsing, and board state validation.
- **[Leela Chess Zero (`lc0`)](https://lczero.org/)** for neural network chess inference.
- **[Maia Chess](https://github.com/CSSLab/maia-chess)** by the Computational Social Science Lab (University of Toronto) for pioneering human-calibrated neural chess models.
- **[CallOn84 / LeelaNets](https://github.com/CallOn84/LeelaNets)** for the `Elite-Leela-v2` neural network weights.
- **[Stockfish](https://stockfishchess.org/)** for tactical evaluation and arbiter safety bounds.

---

## License

This repository is free software distributed under the terms of the **GNU Affero General Public License v3.0 (`AGPL-3.0-or-later`)**, inherited from [`lichess-bot`](https://github.com/lichess-bot-devs/lichess-bot). See [`LICENSE`](LICENSE) for the full license text.
