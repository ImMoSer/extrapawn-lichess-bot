"""Opponent-rating to Maia engine & opening book tier mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MaiaEngineName = Literal["maia_1500", "maia_1700", "maia_1900", "maia_2200"]


@dataclass(frozen=True)
class AdaptiveTierProfile:
    """Adaptive strength & opening book parameters matched to opponent's Lichess rating."""

    engine_name: MaiaEngineName
    significant_only: bool
    min_games: int
    top_n: int
    min_rel_cp: int
    max_cp_drop: int
    weight_exponent: float
    memory_keep_prob: float


TIER_1500 = AdaptiveTierProfile(
    engine_name="maia_1500",
    significant_only=False,
    min_games=2,
    top_n=12,
    min_rel_cp=-180,
    max_cp_drop=160,
    weight_exponent=0.25,
    memory_keep_prob=0.55,
)

TIER_1700 = AdaptiveTierProfile(
    engine_name="maia_1700",
    significant_only=False,
    min_games=4,
    top_n=10,
    min_rel_cp=-140,
    max_cp_drop=120,
    weight_exponent=0.40,
    memory_keep_prob=0.72,
)

TIER_1900 = AdaptiveTierProfile(
    engine_name="maia_1900",
    significant_only=False,
    min_games=8,
    top_n=7,
    min_rel_cp=-95,
    max_cp_drop=85,
    weight_exponent=0.60,
    memory_keep_prob=0.86,
)

TIER_2200 = AdaptiveTierProfile(
    engine_name="maia_2200",
    significant_only=True,
    min_games=20,
    top_n=4,
    min_rel_cp=-50,
    max_cp_drop=45,
    weight_exponent=0.85,
    memory_keep_prob=1.0,
)


def select_tier_for_rating(opponent_rating: int | None) -> AdaptiveTierProfile:
    """Select the adaptive Maia & opening-book tier for a challenger's rating."""
    if opponent_rating is None or opponent_rating >= 2050:
        return TIER_2200
    if opponent_rating < 1600:
        return TIER_1500
    if opponent_rating < 1800:
        return TIER_1700
    return TIER_1900
