"""Game-mode and opponent-rating routing to MOZERO engine profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HubEngineName = Literal["maia_1500", "maia_1700", "maia_1900", "maia_2200", "mozero"]
DisplayProfileName = Literal[
    "MOZERO-1500",
    "MOZERO-1700",
    "MOZERO-1900",
    "MOZERO-2200",
    "MOZERO-FullPower",
]


@dataclass(frozen=True)
class AdaptiveTierProfile:
    """MOZERO engine and Masters opening-book profile selected at game start."""

    engine_name: HubEngineName
    display_name: DisplayProfileName
    use_opening_book: bool
    significant_only: bool
    min_games: int
    top_n: int
    min_rel_cp: int
    max_cp_drop: int
    weight_exponent: float
    memory_keep_prob: float


TIER_1500 = AdaptiveTierProfile(
    engine_name="maia_1500",
    display_name="MOZERO-1500",
    use_opening_book=True,
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
    display_name="MOZERO-1700",
    use_opening_book=True,
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
    display_name="MOZERO-1900",
    use_opening_book=True,
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
    display_name="MOZERO-2200",
    use_opening_book=True,
    significant_only=True,
    min_games=20,
    top_n=4,
    min_rel_cp=-50,
    max_cp_drop=45,
    weight_exponent=0.85,
    memory_keep_prob=1.0,
)

TIER_FULL_POWER = AdaptiveTierProfile(
    engine_name="mozero",
    display_name="MOZERO-FullPower",
    use_opening_book=False,
    significant_only=True,
    min_games=20,
    top_n=4,
    min_rel_cp=-50,
    max_cp_drop=45,
    weight_exponent=0.85,
    memory_keep_prob=1.0,
)


def select_tier_for_rating(opponent_rating: int | None) -> AdaptiveTierProfile:
    """
    Select adaptive MOZERO tier for Casual Standard games:
    - <= 1800 or unrated (None) -> MOZERO-1500
    - 1801..2000 -> MOZERO-1700
    - 2001..2200 -> MOZERO-1900
    - > 2200 -> MOZERO-2200
    """
    if opponent_rating is None or opponent_rating <= 1800:
        return TIER_1500
    if opponent_rating <= 2000:
        return TIER_1700
    if opponent_rating <= 2200:
        return TIER_1900
    return TIER_2200


def select_tier_for_game(
    *,
    is_from_position: bool,
    is_rated: bool,
    opponent_rating: int | None,
) -> AdaptiveTierProfile:
    """
    Select active MOZERO profile using the 3-way Variant C policy:
    1. From Position (custom FEN) -> MOZERO-FullPower ('mozero' Elite-Leela 50n + strict SF d=12)
    2. Rated Standard -> fixed MOZERO-2200 ('maia_2200' + GM book, fair Glicko-2)
    3. Casual Standard -> adaptive MOZERO-1500..2200 matched to opponent_rating
    """
    if is_from_position:
        return TIER_FULL_POWER
    if is_rated:
        return TIER_2200
    return select_tier_for_rating(opponent_rating)
