"""Masters opening book move selection with quality guard and style modes."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Literal

import chess

from extrapawn.clients import BookMoveEntry, MozerBookResponse

BookStyle = Literal["auto", "gm", "sharp", "gambit"]

VALID_BOOK_STYLES: tuple[BookStyle, ...] = ("auto", "gm", "sharp", "gambit")

STYLE_TO_API_KEY: dict[str, str] = {
    "gm": "grossmaster",
    "sharp": "hustler",
    "gambit": "schuler",
}

MIN_REL_CP_GUARD = -75
MAX_REL_CP_DROP_FROM_BEST = 60
MIN_POPULARITY_SHARE_OF_TOP = 0.05
WEIGHT_EXPONENT = 0.7


@dataclass(frozen=True)
class SelectedBookMove:
    """Selected opening book move plus metadata for telemetry and chat."""

    move: chess.Move
    san: str
    total_games: int
    style_used: str
    eco: str | None
    opening_name: str | None


def _is_safe_book_move(board: chess.Board, uci: str) -> chess.Move | None:
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    if not board.is_legal(move):
        return None
    board.push(move)
    repeats = board.is_repetition(2)
    board.pop()
    if repeats:
        return None
    return move


def _find_entry_by_uci(moves: list[BookMoveEntry], uci: str) -> BookMoveEntry | None:
    for entry in moves:
        if entry.uci == uci:
            return entry
    return None


def _select_styled_move(
    board: chess.Board,
    book: MozerBookResponse,
    style: BookStyle,
    min_games: int,
) -> SelectedBookMove | None:
    api_key = STYLE_TO_API_KEY.get(style)
    if api_key is None or book.total_games < min_games:
        return None

    style_uci = book.styles.get(api_key)
    if not style_uci:
        return None

    move = _is_safe_book_move(board, style_uci)
    if move is None:
        return None

    entry = _find_entry_by_uci(book.moves, style_uci)
    return SelectedBookMove(
        move=move,
        san=entry.san if entry is not None else board.san(move),
        total_games=entry.total if entry is not None else book.total_games,
        style_used=style,
        eco=(entry.eco if entry is not None and entry.eco else book.wiki_eco),
        opening_name=(entry.name if entry is not None and entry.name else book.wiki_name),
    )


def choose_book_move(
    board: chess.Board,
    book: MozerBookResponse,
    style: BookStyle,
    min_games: int,
    top_n: int,
    rng: random.Random | None = None,
) -> SelectedBookMove | None:
    """
    Select an opening move from TABLESERVICE Masters book data.

    In 'gm', 'sharp', or 'gambit' style, prefers the corresponding TABLESERVICE
    style move and falls back to weighted random 'auto' if that style is absent.
    In 'auto' mode, selects weighted-randomly from top sound master moves.
    """
    if style != "auto":
        styled = _select_styled_move(board, book, style, min_games)
        if styled is not None:
            return styled

    candidates: list[tuple[BookMoveEntry, chess.Move]] = []
    for entry in book.moves:
        if entry.total < min_games:
            continue
        move = _is_safe_book_move(board, entry.uci)
        if move is not None:
            candidates.append((entry, move))

    if not candidates:
        return None

    cp_values = [entry.rel_cp for entry, _ in candidates if entry.rel_cp is not None]
    if cp_values:
        best_cp = max(cp_values)
        candidates = [
            (entry, move)
            for entry, move in candidates
            if entry.rel_cp is None
            or (entry.rel_cp >= MIN_REL_CP_GUARD and entry.rel_cp >= best_cp - MAX_REL_CP_DROP_FROM_BEST)
        ]

    if not candidates:
        return None

    candidates.sort(key=lambda pair: pair[0].total, reverse=True)
    candidates = candidates[:top_n]

    top_total = candidates[0][0].total
    candidates = [
        (entry, move)
        for entry, move in candidates
        if entry.total >= top_total * MIN_POPULARITY_SHARE_OF_TOP
    ]

    weights = [math.pow(entry.total, WEIGHT_EXPONENT) for entry, _ in candidates]
    chosen_entry, chosen_move = (rng or random).choices(candidates, weights=weights, k=1)[0]

    return SelectedBookMove(
        move=chosen_move,
        san=chosen_entry.san,
        total_games=chosen_entry.total,
        style_used="auto",
        eco=chosen_entry.eco or book.wiki_eco,
        opening_name=chosen_entry.name or book.wiki_name,
    )
