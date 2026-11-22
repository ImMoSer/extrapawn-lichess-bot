"""Homemade MinimalEngine adapter connecting lichess-bot to Mozero and TABLESERVICE."""

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
from lib import model
from lib.config import Configuration
from lib.engine_wrapper import FillerEngine, MinimalEngine
from lib.lichess_types import COMMANDS_TYPE, MOVE, OPTIONS_GO_EGTB_TYPE

logger = logging.getLogger(__name__)


class MozeroExtraPawnEngine(MinimalEngine):
    """Lichess-bot homemade engine backed by TABLESERVICE Masters Book and engine-hub mozero."""

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
        """Initialize HTTP clients, per-game book state, and startup health verification."""
        super().__init__(commands, options, stderr, draw_or_resign, game, debug, **popen_args)
        self.engine_name = "ExtraPawn Mozero V5"
        self.engine = FillerEngine(self, name=self.engine_name)
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
        self.book_style: BookStyle = "auto"
        self.last_opening_eco: str | None = None
        self.last_opening_name: str | None = None
        self._out_of_book_streak: int = 0
        self.last_mozero_response: BestMoveResponse | None = None

        skip_health = bool(options.get("skip_startup_healthcheck", False))
        if game is None and not skip_health:
            self.engine_hub.check_health()
            self.tableservice.check_health()

    def set_book_style(self, style: BookStyle) -> None:
        """Update the opening book style for this game and reset out-of-book streak."""
        self.book_style = style
        self._out_of_book_streak = 0

    def get_opening_summary(self, start_fen: str, moves: list[str]) -> str:
        """Return a concise opening description for chat (!opening)."""
        if self._is_from_position(start_fen):
            return "Custom position (From Position) - powered by ExtraPawn Mozero."

        board = chess.Board()
        for move_uci in moves:
            try:
                move_obj = chess.Move.from_uci(move_uci)
            except ValueError:
                break
            if not board.is_legal(move_obj):
                break
            board.push(move_obj)

        eco = self.last_opening_eco
        name = self.last_opening_name
        try:
            lookup = self.tableservice.lookup_opening(
                fen=board.fen(),
                start_fen="startpos",
                played_moves_uci=moves,
            )
            if lookup.name:
                name = lookup.name
                eco = lookup.eco
        except RuntimeError as exc:
            logger.warning(f"Opening lookup failed during !opening chat command: {exc}")

        if name and eco:
            return f"Opening: {eco} {name}"
        if name:
            return f"Opening: {name}"
        return "Opening not in theory database yet."

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
        target_delay = random.uniform(self.extrapawn_cfg.min_move_delay_sec, max_delay)
        remaining = target_delay - elapsed_sec
        if remaining > 0.0:
            time.sleep(remaining)

    def _try_masters_book(self, board: chess.Board, t0: float, time_limit: Limit) -> PlayResult | None:
        try:
            book = self.tableservice.get_mozer_book(board.fen(), significant_only=True)
        except RuntimeError as exc:
            logger.error(f"TABLESERVICE opening book failed, handing over to Mozero: {exc}")
            self._out_of_book_streak += 1
            return None

        if book.wiki_name:
            self.last_opening_name = book.wiki_name
            self.last_opening_eco = book.wiki_eco

        selected = choose_book_move(
            board=board,
            book=book,
            style=self.book_style,
            min_games=self.extrapawn_cfg.book_min_games,
            top_n=self.extrapawn_cfg.book_top_n,
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
                "string": f"lichess-bot-source:Masters Book ({selected.style_used})",
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
        """Choose a move from Masters Book (early standard games) or engine-hub MOZERO Bouncer V5.0."""
        t0 = time.perf_counter()
        start_fen = self._resolve_start_fen(board)
        moves = [move.uci() for move in board.move_stack]

        if (
            not self._is_from_position(start_fen)
            and len(moves) < self.extrapawn_cfg.book_max_ply
            and self._out_of_book_streak < 2
        ):
            book_result = self._try_masters_book(board, t0, time_limit)
            if book_result is not None:
                return book_result

        res = self.engine_hub.get_bestmove(start_fen=start_fen, moves=moves)
        try:
            move = chess.Move.from_uci(res.best_move)
        except ValueError as exc:
            raise RuntimeError(f"engine-hub returned invalid UCI move '{res.best_move}': {exc}") from exc
        if not board.is_legal(move):
            raise RuntimeError(f"engine-hub returned illegal move '{res.best_move}' for FEN '{board.fen()}'")

        self.last_mozero_response = res
        source_label = f"Mozero ({res.mode}/{res.source})"
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
