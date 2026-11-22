"""Homemade MinimalEngine adapter connecting lichess-bot to MOZERO profiles and TABLESERVICE."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import chess
from chess.engine import Limit, PlayResult

from extrapawn.clients import BestMoveResponse, EngineHubClient, TableServiceClient
from extrapawn.config import ExtraPawnConfig
from extrapawn.opening_book import BookStyle, choose_book_move
from extrapawn.tiers import TIER_FULL_POWER, AdaptiveTierProfile, select_tier_for_game
from lib import model
from lib.config import Configuration
from lib.engine_wrapper import FillerEngine, MinimalEngine
from lib.lichess_types import COMMANDS_TYPE, MOVE, OPTIONS_GO_EGTB_TYPE

logger = logging.getLogger(__name__)

BOOK_MEMORY_CHECK_START_PLY = 4


class MozeroExtraPawnEngine(MinimalEngine):
    """Lichess-bot homemade engine backed by TABLESERVICE Masters Book and MOZERO profiles on engine-hub."""

    def __init__(
        self,
        commands: COMMANDS_TYPE,
        options: OPTIONS_GO_EGTB_TYPE,
        stderr: int | None,
        draw_or_resign: Configuration,
        game: model.Game | None,
        debug: bool,
        **popen_args: str,
    ) -> None:
        """Initialize HTTP clients, Variant C MOZERO profile, book state, and startup health check."""
        super().__init__(commands, options, stderr, draw_or_resign, game, debug, **popen_args)
        self.game = game
        self.extrapawn_cfg = ExtraPawnConfig.from_env()
        self.engine_hub = EngineHubClient(
            base_url=self.extrapawn_cfg.maia_hub_url,
            timeout_sec=self.extrapawn_cfg.engine_timeout_sec,
        )
        self.tableservice = TableServiceClient(
            base_url=self.extrapawn_cfg.tableservice_url,
            timeout_sec=self.extrapawn_cfg.book_timeout_sec,
        )

        is_from_pos = bool(
            game is not None
            and (
                game.variant_name == "From Position"
                or (game.initial_fen and game.initial_fen.strip() not in ("", "startpos"))
            )
        )
        is_rated = bool(game is not None and game.mode == "rated")
        opp_rating = (
            game.opponent.rating
            if (game is not None and isinstance(game.opponent.rating, int))
            else None
        )
        self.tier: AdaptiveTierProfile = select_tier_for_game(
            is_from_position=is_from_pos,
            is_rated=is_rated,
            opponent_rating=opp_rating,
        )
        self.engine_name = self.tier.display_name if game is not None else "MOZERO-2200"
        self.engine = FillerEngine(self, name=self.engine_name)

        self.book_style: BookStyle = "auto"
        self.last_opening_eco: str | None = None
        self.last_opening_name: str | None = None
        self._out_of_book_streak: int = 0
        self._memory_dropped_out: bool = False
        self._rng = random.Random()
        self.last_mozero_response: BestMoveResponse | None = None

        if game is not None:
            logger.info(
                f"Game {game.id} ({game.mode}/{game.variant_name}) vs {game.opponent.name} "
                f"(rating={opp_rating}) -> active profile {self.tier.display_name} ({self.tier.engine_name})"
            )

        skip_health = bool(options.get("skip_startup_healthcheck", False))
        if game is None and not skip_health:
            self.engine_hub.check_health()
            self.tableservice.check_health()

    def set_book_style(self, style: BookStyle) -> None:
        """Update the opening book style for this game and reset out-of-book streak."""
        self.book_style = style
        self._out_of_book_streak = 0

    def _resolve_start_fen(self, board: chess.Board) -> str:
        if self.game is not None and self.game.initial_fen:
            raw = self.game.initial_fen.strip()
            if raw and raw != "startpos":
                return raw
            return "startpos"
        root_fen = board.root().fen()
        if root_fen == chess.STARTING_FEN:
            return "startpos"
        return root_fen

    def _is_from_position(self, start_fen: str) -> bool:
        if self.game is not None and self.game.variant_name == "From Position":
            return True
        return start_fen != "startpos"

    def _get_own_clock_sec(self, board: chess.Board, time_limit: Limit) -> float | None:
        if isinstance(time_limit.time, (int, float)):
            return float(time_limit.time)
        clock = time_limit.white_clock if board.turn == chess.WHITE else time_limit.black_clock
        if isinstance(clock, (int, float)):
            return float(clock)
        return None

    def _apply_human_pacing(self, board: chess.Board, time_limit: Limit, elapsed_sec: float) -> None:
        max_delay = self.extrapawn_cfg.max_move_delay_sec
        if max_delay <= 0.0:
            return
        own_clock = self._get_own_clock_sec(board, time_limit)
        if own_clock is None or own_clock <= self.extrapawn_cfg.low_time_threshold_sec:
            return
        target_delay = self._rng.uniform(self.extrapawn_cfg.min_move_delay_sec, max_delay)
        remaining = target_delay - elapsed_sec
        if remaining > 0.0:
            time.sleep(remaining)

    def _try_masters_book(
        self,
        board: chess.Board,
        active_tier: AdaptiveTierProfile,
        t0: float,
        time_limit: Limit,
    ) -> PlayResult | None:
        ply = len(board.move_stack)
        if ply >= BOOK_MEMORY_CHECK_START_PLY and active_tier.memory_keep_prob < 1.0:
            if self._rng.random() > active_tier.memory_keep_prob:
                self._memory_dropped_out = True
                logger.info(
                    f"Opening memory drop-out at ply {ply} for {active_tier.display_name}; "
                    f"handing over rest of game to {active_tier.engine_name}."
                )
                return None

        try:
            book = self.tableservice.get_mozer_book(
                board.fen(),
                significant_only=active_tier.significant_only,
            )
        except RuntimeError as exc:
            logger.error(f"TABLESERVICE opening book failed, handing over to {active_tier.display_name}: {exc}")
            self._out_of_book_streak += 1
            return None

        if book.wiki_name:
            self.last_opening_name = book.wiki_name
            self.last_opening_eco = book.wiki_eco

        selected = choose_book_move(
            board=board,
            book=book,
            tier=active_tier,
            style=self.book_style,
            rng=self._rng,
        )
        if selected is None:
            self._out_of_book_streak += 1
            return None

        self._out_of_book_streak = 0
        if selected.opening_name:
            self.last_opening_name = selected.opening_name
            self.last_opening_eco = selected.eco

        self._apply_human_pacing(board, time_limit, time.perf_counter() - t0)
        elapsed_total = time.perf_counter() - t0
        return PlayResult(
            selected.move,
            None,
            info={
                "string": f"lichess-bot-source:Masters Book ({active_tier.display_name}/{selected.style_used})",
                "time": elapsed_total,
            },
            draw_offered=False,
            resigned=False,
        )

    def search(
        self,
        board: chess.Board,
        time_limit: Limit,
        ponder: bool,  # noqa: ARG002
        draw_offered: bool,  # noqa: ARG002
        root_moves: MOVE,  # noqa: ARG002
    ) -> PlayResult:
        """Choose a move from tier-adapted Masters Book or engine-hub MOZERO profile."""
        t0 = time.perf_counter()
        start_fen = self._resolve_start_fen(board)
        moves = [move.uci() for move in board.move_stack]
        is_from_pos = self._is_from_position(start_fen)
        active_tier = TIER_FULL_POWER if is_from_pos else self.tier

        if (
            active_tier.use_opening_book
            and not is_from_pos
            and not self._memory_dropped_out
            and len(moves) < self.extrapawn_cfg.book_max_ply
            and self._out_of_book_streak < 2
        ):
            book_result = self._try_masters_book(board, active_tier, t0, time_limit)
            if book_result is not None:
                return book_result

        res = self.engine_hub.get_bestmove(
            start_fen=start_fen,
            moves=moves,
            engine=active_tier.engine_name,
        )
        try:
            move = chess.Move.from_uci(res.best_move)
        except ValueError as exc:
            raise RuntimeError(f"engine-hub returned invalid UCI move '{res.best_move}': {exc}") from exc
        if not board.is_legal(move):
            raise RuntimeError(f"engine-hub returned illegal move '{res.best_move}' for FEN '{board.fen()}'")

        self.last_mozero_response = res
        source_label = f"{active_tier.display_name} ({res.mode}/{res.source})"
        if res.dtm is not None and res.dtm != 0:
            source_label = f"{source_label} DTM={res.dtm}"

        self._apply_human_pacing(board, time_limit, time.perf_counter() - t0)
        return PlayResult(
            move,
            None,
            info={
                "string": f"lichess-bot-source:{source_label}",
                "time": res.time_real_ms / 1000.0,
            },
            draw_offered=False,
            resigned=False,
        )

    def notify(self, method_name: str, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        """Clean up HTTP client sessions when lichess-bot exits the engine wrapper."""
        if method_name in ("quit", "close", "__exit__"):
            self.engine_hub.close()
            self.tableservice.close()
        return None
