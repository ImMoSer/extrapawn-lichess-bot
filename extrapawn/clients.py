"""Typed HTTP clients for internal ExtraPawn services (engine-hub and TABLESERVICE)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import requests


@dataclass(frozen=True)
class PlayerTablebaseVerdict:
    """Post-move tablebase verdict returned by engine-hub."""

    wdl: int
    dtm: int | None
    fide_lost: bool
    source: str


@dataclass(frozen=True)
class BestMoveResponse:
    """Validated response payload from engine-hub POST /bestmove."""

    best_move: str
    engine: str
    mode: str
    source: str
    dtm: int | None
    time_real_ms: float
    player_tablebase: PlayerTablebaseVerdict | None


@dataclass(frozen=True)
class BookMoveEntry:
    """Candidate move entry from TABLESERVICE GET /opening/mozer_book."""

    san: str
    uci: str
    total: int
    win_p: float
    draw_p: float
    loss_p: float
    rel_cp: int | None
    name: str | None
    eco: str | None


@dataclass(frozen=True)
class MozerBookResponse:
    """Validated response payload from TABLESERVICE GET /opening/mozer_book."""

    total_games: int
    moves: list[BookMoveEntry]
    styles: dict[str, str | None]
    wiki_name: str | None
    wiki_eco: str | None


@dataclass(frozen=True)
class OpeningLookupResponse:
    """Validated opening identification from TABLESERVICE POST /opening/lookup."""

    eco: str | None
    name: str | None


def _clean_optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped == "-":
        return None
    return stripped


def _extract_style_uci(raw_style: Any) -> str | None:
    if isinstance(raw_style, dict):
        return _clean_optional_str(raw_style.get("uci"))
    return _clean_optional_str(raw_style)


class EngineHubClient:
    """Synchronous HTTP client for chessboard_engines (engine-hub)."""

    def __init__(self, base_url: str, timeout_sec: float) -> None:
        """Initialize client with persistent HTTP session."""
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self._session = requests.Session()

    def close(self) -> None:
        """Close the underlying requests session."""
        self._session.close()

    def check_health(self) -> None:
        """Fail-fast health check verifying engine-hub is reachable and ready."""
        try:
            resp = self._session.get(f"{self.base_url}/health", timeout=5.0)
        except requests.RequestException as exc:
            raise RuntimeError(f"engine-hub health check failed at {self.base_url}/health: {exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(
                f"engine-hub unhealthy at {self.base_url}/health: HTTP {resp.status_code} ({resp.text[:200]})"
            )

    def get_bestmove(
        self,
        start_fen: str,
        moves: list[str],
        engine: str = "maia_2200",
    ) -> BestMoveResponse:
        """Query MOZERO/Maia Bouncer on engine-hub; retries once only on transient transport errors."""
        payload = {"engine": engine, "start_fen": start_fen, "moves": moves}
        url = f"{self.base_url}/bestmove"
        last_exc: Exception | None = None

        for attempt in range(2):
            try:
                resp = self._session.post(url, json=payload, timeout=self.timeout_sec)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt == 0:
                    continue
                raise RuntimeError(f"engine-hub request failed after retry at {url}: {exc}") from exc
            except requests.RequestException as exc:
                raise RuntimeError(f"engine-hub request error at {url}: {exc}") from exc

            if resp.status_code != 200:
                raise RuntimeError(
                    f"engine-hub /bestmove returned HTTP {resp.status_code}: {resp.text[:300]}"
                )
            return self._parse_bestmove_response(resp.json())

        raise RuntimeError(f"engine-hub request failed at {url}: {last_exc}")

    def _parse_bestmove_response(self, data: Any) -> BestMoveResponse:
        if not isinstance(data, dict):
            raise RuntimeError(f"engine-hub /bestmove returned non-object payload: {type(data).__name__}")

        best_move = data.get("bestMove")
        if not isinstance(best_move, str) or not best_move.strip():
            raise RuntimeError(f"engine-hub /bestmove returned missing or empty bestMove: {data}")

        engine = data.get("engine")
        mode = data.get("mode")
        source = data.get("source")
        raw_dtm = data.get("dtm")
        raw_time_ms = data.get("timeRealMs", 0.0)

        player_tb: PlayerTablebaseVerdict | None = None
        raw_ptb = data.get("playerTablebase")
        if isinstance(raw_ptb, dict):
            ptb_wdl = raw_ptb.get("wdl")
            ptb_fide_lost = raw_ptb.get("fideLost")
            ptb_source = raw_ptb.get("source")
            ptb_dtm = raw_ptb.get("dtm")
            if isinstance(ptb_wdl, int) and isinstance(ptb_fide_lost, bool) and isinstance(ptb_source, str):
                player_tb = PlayerTablebaseVerdict(
                    wdl=ptb_wdl,
                    dtm=ptb_dtm if isinstance(ptb_dtm, int) else None,
                    fide_lost=ptb_fide_lost,
                    source=ptb_source,
                )

        return BestMoveResponse(
            best_move=best_move.strip(),
            engine=engine if isinstance(engine, str) and engine else "mozero",
            mode=mode if isinstance(mode, str) and mode else "mozero",
            source=source if isinstance(source, str) and source else "engine-hub",
            dtm=raw_dtm if isinstance(raw_dtm, int) else None,
            time_real_ms=float(raw_time_ms) if isinstance(raw_time_ms, (int, float)) else 0.0,
            player_tablebase=player_tb,
        )


class TableServiceClient:
    """Synchronous HTTP client for TABLESERVICE Masters Book & Opening Wiki."""

    def __init__(self, base_url: str, timeout_sec: float) -> None:
        """Initialize client with persistent HTTP session."""
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self._session = requests.Session()

    def close(self) -> None:
        """Close the underlying requests session."""
        self._session.close()

    def check_health(self) -> None:
        """Fail-fast health check verifying TABLESERVICE and Masters LMDB are ready."""
        try:
            resp = self._session.get(f"{self.base_url}/health", timeout=5.0)
        except requests.RequestException as exc:
            raise RuntimeError(f"TABLESERVICE health check failed at {self.base_url}/health: {exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(
                f"TABLESERVICE unhealthy at {self.base_url}/health: HTTP {resp.status_code} ({resp.text[:200]})"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"TABLESERVICE /health returned invalid JSON: {exc}") from exc
        if not isinstance(data, dict) or not bool(data.get("masters_ready")):
            raise RuntimeError(f"TABLESERVICE Masters LMDB is not ready: {data}")

    def get_mozer_book(self, fen: str, significant_only: bool = True) -> MozerBookResponse:
        """Fetch Masters LMDB + theory stats for a FEN from GET /opening/mozer_book."""
        url = f"{self.base_url}/opening/mozer_book"
        params = {"fen": fen, "significant_only": str(significant_only).lower()}
        try:
            resp = self._session.get(url, params=params, timeout=self.timeout_sec)
        except requests.RequestException as exc:
            raise RuntimeError(f"TABLESERVICE /opening/mozer_book request error: {exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(
                f"TABLESERVICE /opening/mozer_book returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        return self._parse_mozer_book_response(resp.json())

    def lookup_opening(
        self,
        fen: str,
        start_fen: str = "startpos",
        played_moves_uci: list[str] | None = None,
    ) -> OpeningLookupResponse:
        """Identify opening ECO and name via POST /opening/lookup."""
        url = f"{self.base_url}/opening/lookup"
        payload: dict[str, Any] = {
            "fen": fen,
            "start_fen": start_fen,
            "played_moves_uci": played_moves_uci or [],
        }
        try:
            resp = self._session.post(url, json=payload, timeout=self.timeout_sec)
        except requests.RequestException as exc:
            raise RuntimeError(f"TABLESERVICE /opening/lookup request error: {exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(
                f"TABLESERVICE /opening/lookup returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"TABLESERVICE /opening/lookup returned non-object payload: {type(data).__name__}")
        info = data.get("opening_info")
        if not isinstance(info, dict):
            return OpeningLookupResponse(eco=None, name=None)
        return OpeningLookupResponse(
            eco=_clean_optional_str(info.get("eco")),
            name=_clean_optional_str(info.get("name")),
        )

    def _parse_mozer_book_response(self, data: Any) -> MozerBookResponse:
        if not isinstance(data, dict):
            raise RuntimeError(f"TABLESERVICE /opening/mozer_book returned non-object payload: {type(data).__name__}")

        summary = data.get("summary")
        total_games = 0
        if isinstance(summary, dict) and isinstance(summary.get("total"), int):
            total_games = summary["total"]

        raw_moves = data.get("moves")
        moves: list[BookMoveEntry] = []
        if isinstance(raw_moves, list):
            for item in raw_moves:
                if not isinstance(item, dict):
                    continue
                uci = _clean_optional_str(item.get("uci"))
                san = _clean_optional_str(item.get("san")) or uci
                total = item.get("total")
                if uci is None or san is None or not isinstance(total, int):
                    continue
                rel_cp = item.get("rel_cp")
                moves.append(
                    BookMoveEntry(
                        san=san,
                        uci=uci,
                        total=total,
                        win_p=float(item.get("win_p", 0.0)),
                        draw_p=float(item.get("draw_p", 0.0)),
                        loss_p=float(item.get("loss_p", 0.0)),
                        rel_cp=rel_cp if isinstance(rel_cp, int) else None,
                        name=_clean_optional_str(item.get("name")),
                        eco=_clean_optional_str(item.get("eco")),
                    )
                )

        raw_styles = data.get("styles")
        styles_dict: dict[str, str | None] = {"grossmaster": None, "hustler": None, "schuler": None}
        if isinstance(raw_styles, dict):
            for key in ("grossmaster", "hustler", "schuler"):
                styles_dict[key] = _extract_style_uci(raw_styles.get(key))

        raw_wiki = data.get("wiki")
        wiki_name: str | None = None
        wiki_eco: str | None = None
        if isinstance(raw_wiki, dict):
            wiki_name = _clean_optional_str(raw_wiki.get("name"))
            wiki_eco = _clean_optional_str(raw_wiki.get("eco"))

        return MozerBookResponse(
            total_games=total_games,
            moves=moves,
            styles=styles_dict,
            wiki_name=wiki_name,
            wiki_eco=wiki_eco,
        )
