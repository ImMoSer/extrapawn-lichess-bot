"""Environment-driven configuration for ExtraPawn Lichess bot."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _parse_url(env_name: str, default: str) -> str:
    raw = os.getenv(env_name, default).strip()
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raise ValueError(f"{env_name} must start with 'http://' or 'https://', got '{raw}'.")
    return raw.rstrip("/")


def _parse_int(env_name: str, default: int, *, min_value: int) -> int:
    raw = os.getenv(env_name)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        raise ValueError(f"{env_name} must not be empty when set.")
    try:
        value = int(stripped)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer, got '{raw}'.") from exc
    if value < min_value:
        raise ValueError(f"{env_name} must be >= {min_value}, got {value}.")
    return value


def _parse_float(
    env_name: str,
    default: float,
    *,
    min_value: float,
    strictly_positive: bool = False,
) -> float:
    raw = os.getenv(env_name)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped:
        raise ValueError(f"{env_name} must not be empty when set.")
    try:
        value = float(stripped)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a float, got '{raw}'.") from exc
    if strictly_positive and value <= min_value:
        raise ValueError(f"{env_name} must be > {min_value}, got {value}.")
    if not strictly_positive and value < min_value:
        raise ValueError(f"{env_name} must be >= {min_value}, got {value}.")
    return value


@dataclass(frozen=True)
class ExtraPawnConfig:
    """Validated runtime configuration for ExtraPawn services and pacing."""

    maia_hub_url: str
    tableservice_url: str
    book_max_ply: int
    book_min_games: int
    book_top_n: int
    engine_timeout_sec: float
    book_timeout_sec: float
    min_move_delay_sec: float
    max_move_delay_sec: float
    low_time_threshold_sec: float

    @classmethod
    def from_env(cls) -> ExtraPawnConfig:
        """Load and strictly validate configuration from environment variables."""
        maia_hub_url = _parse_url("MAIA_HUB_URL", "http://engine-hub:5000")
        tableservice_url = _parse_url("TABLESERVICE_URL", "http://tableservice:5000")
        book_max_ply = _parse_int("BOT_BOOK_MAX_PLY", 20, min_value=0)
        book_min_games = _parse_int("BOT_BOOK_MIN_GAMES", 15, min_value=1)
        book_top_n = _parse_int("BOT_BOOK_TOP_N", 5, min_value=1)
        engine_timeout_sec = _parse_float("BOT_ENGINE_TIMEOUT_SEC", 15.0, min_value=0.0, strictly_positive=True)
        book_timeout_sec = _parse_float("BOT_BOOK_TIMEOUT_SEC", 2.5, min_value=0.0, strictly_positive=True)
        min_move_delay_sec = _parse_float("BOT_MIN_MOVE_DELAY_SEC", 0.05, min_value=0.0)
        max_move_delay_sec = _parse_float("BOT_MAX_MOVE_DELAY_SEC", 0.20, min_value=0.0)
        low_time_threshold_sec = _parse_float("BOT_LOW_TIME_THRESHOLD_SEC", 25.0, min_value=0.0)

        if max_move_delay_sec < min_move_delay_sec:
            raise ValueError(
                f"BOT_MAX_MOVE_DELAY_SEC ({max_move_delay_sec}) must be >= BOT_MIN_MOVE_DELAY_SEC ({min_move_delay_sec})."
            )

        return cls(
            maia_hub_url=maia_hub_url,
            tableservice_url=tableservice_url,
            book_max_ply=book_max_ply,
            book_min_games=book_min_games,
            book_top_n=book_top_n,
            engine_timeout_sec=engine_timeout_sec,
            book_timeout_sec=book_timeout_sec,
            min_move_delay_sec=min_move_delay_sec,
            max_move_delay_sec=max_move_delay_sec,
            low_time_threshold_sec=low_time_threshold_sec,
        )
