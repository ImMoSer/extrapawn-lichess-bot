"""Unit tests for extrapawn configuration, HTTP clients, and Masters book selection."""

from __future__ import annotations

import os
import random
import unittest
from unittest.mock import MagicMock, patch

import chess
import requests

from extrapawn.clients import (
    BookMoveEntry,
    EngineHubClient,
    MozerBookResponse,
    TableServiceClient,
)
from extrapawn.config import ExtraPawnConfig
from extrapawn.opening_book import choose_book_move


class TestExtraPawnConfig(unittest.TestCase):
    def test_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            cfg = ExtraPawnConfig.from_env()
        self.assertEqual(cfg.maia_hub_url, "http://engine-hub:5000")
        self.assertEqual(cfg.tableservice_url, "http://tableservice:5000")
        self.assertEqual(cfg.book_max_ply, 20)
        self.assertEqual(cfg.book_min_games, 15)
        self.assertEqual(cfg.book_top_n, 5)
        self.assertAlmostEqual(cfg.engine_timeout_sec, 15.0)
        self.assertAlmostEqual(cfg.min_move_delay_sec, 0.05)
        self.assertAlmostEqual(cfg.max_move_delay_sec, 0.20)

    def test_overrides_and_trailing_slash_stripped(self) -> None:
        env = {
            "MAIA_HUB_URL": "http://localhost:5005/",
            "TABLESERVICE_URL": "https://tables.internal:5006/",
            "BOT_BOOK_MAX_PLY": "16",
            "BOT_BOOK_MIN_GAMES": "25",
            "BOT_BOOK_TOP_N": "3",
            "BOT_MIN_MOVE_DELAY_SEC": "0.1",
            "BOT_MAX_MOVE_DELAY_SEC": "0.5",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = ExtraPawnConfig.from_env()
        self.assertEqual(cfg.maia_hub_url, "http://localhost:5005")
        self.assertEqual(cfg.tableservice_url, "https://tables.internal:5006")
        self.assertEqual(cfg.book_max_ply, 16)
        self.assertEqual(cfg.book_min_games, 25)
        self.assertEqual(cfg.book_top_n, 3)

    def test_fail_fast_invalid_env(self) -> None:
        bad_cases = [
            {"MAIA_HUB_URL": "ftp://engine-hub:5000"},
            {"TABLESERVICE_URL": "tableservice:5000"},
            {"BOT_BOOK_MAX_PLY": "abc"},
            {"BOT_BOOK_MAX_PLY": "-1"},
            {"BOT_BOOK_MIN_GAMES": "0"},
            {"BOT_ENGINE_TIMEOUT_SEC": "0"},
            {"BOT_MIN_MOVE_DELAY_SEC": "2.0", "BOT_MAX_MOVE_DELAY_SEC": "1.0"},
        ]
        for env in bad_cases:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    ExtraPawnConfig.from_env()


class TestClients(unittest.TestCase):
    def test_engine_hub_retries_once_on_connection_error(self) -> None:
        client = EngineHubClient("http://engine-hub:5000", timeout_sec=5.0)
        ok_resp = MagicMock(status_code=200)
        ok_resp.json.return_value = {
            "bestMove": "e2e4",
            "engine": "mozero",
            "mode": "leelaHoldDraw",
            "source": "lc0",
            "timeRealMs": 42.5,
        }
        with patch.object(
            client._session,
            "post",
            side_effect=[requests.ConnectionError("transient"), ok_resp],
        ) as mock_post:
            res = client.get_bestmove("startpos", [])
        self.assertEqual(res.best_move, "e2e4")
        self.assertEqual(mock_post.call_count, 2)
        client.close()

    def test_engine_hub_fails_fast_on_400(self) -> None:
        client = EngineHubClient("http://engine-hub:5000", timeout_sec=5.0)
        bad_resp = MagicMock(status_code=400, text="Illegal move")
        with patch.object(client._session, "post", return_value=bad_resp) as mock_post:
            with self.assertRaises(RuntimeError):
                client.get_bestmove("startpos", ["e2e5"])
        self.assertEqual(mock_post.call_count, 1)
        client.close()

    def test_tableservice_health_and_nested_styles_parsing(self) -> None:
        client = TableServiceClient("http://tableservice:5000", timeout_sec=2.0)
        unhealthy = MagicMock(status_code=200)
        unhealthy.json.return_value = {"status": "ok", "masters_ready": False}
        with patch.object(client._session, "get", return_value=unhealthy):
            with self.assertRaises(RuntimeError):
                client.check_health()

        book_resp = MagicMock(status_code=200)
        book_resp.json.return_value = {
            "summary": {"total": 1000},
            "moves": [
                {
                    "san": "e4",
                    "uci": "e2e4",
                    "total": 600,
                    "win_p": 38.0,
                    "draw_p": 34.0,
                    "loss_p": 28.0,
                    "rel_cp": 25,
                    "name": "King's Pawn",
                    "eco": "B00",
                }
            ],
            "styles": {
                "grossmaster": {"san": "e4", "uci": "e2e4"},
                "hustler": {"san": "c4", "uci": "c2c4"},
                "schuler": None,
            },
            "wiki": {"name": "Start Position", "eco": "-"},
        }
        with patch.object(client._session, "get", return_value=book_resp):
            parsed = client.get_mozer_book(chess.STARTING_FEN)
        self.assertEqual(parsed.total_games, 1000)
        self.assertEqual(parsed.styles["grossmaster"], "e2e4")
        self.assertEqual(parsed.styles["hustler"], "c2c4")
        self.assertIsNone(parsed.styles["schuler"])
        self.assertIsNone(parsed.wiki_eco)
        client.close()


class TestOpeningBookSelection(unittest.TestCase):
    def _sample_book(self) -> MozerBookResponse:
        return MozerBookResponse(
            total_games=10000,
            moves=[
                BookMoveEntry("e4", "e2e4", 4500, 38.0, 35.0, 27.0, 20, "King's Pawn", "B00"),
                BookMoveEntry("d4", "d2d4", 3500, 39.0, 36.0, 25.0, 22, "Queen's Pawn", "D00"),
                BookMoveEntry("c4", "c2c4", 1200, 37.0, 38.0, 25.0, 15, "English Opening", "A10"),
                BookMoveEntry("Nf3", "g1f3", 700, 36.0, 39.0, 25.0, 10, "Reti Opening", "A04"),
                BookMoveEntry("g4", "g2g4", 100, 20.0, 15.0, 65.0, -140, "Grob", "A00"),
                BookMoveEntry("a3", "a2a3", 10, 30.0, 30.0, 40.0, -10, "Anderssen", "A00"),
            ],
            styles={"grossmaster": "d2d4", "hustler": "c2c4", "schuler": None},
            wiki_name="Start Position",
            wiki_eco=None,
        )

    def test_auto_weighted_random_variety_and_quality_guard(self) -> None:
        board = chess.Board()
        book = self._sample_book()
        rng = random.Random(12345)
        seen_ucis: set[str] = set()
        for _ in range(50):
            chosen = choose_book_move(board, book, style="auto", min_games=15, top_n=5, rng=rng)
            self.assertIsNotNone(chosen)
            assert chosen is not None
            seen_ucis.add(chosen.move.uci())
        self.assertNotIn("g2g4", seen_ucis)
        self.assertNotIn("a2a3", seen_ucis)
        self.assertGreaterEqual(len(seen_ucis), 3)

    def test_styles_and_fallback_to_auto(self) -> None:
        board = chess.Board()
        book = self._sample_book()
        gm = choose_book_move(board, book, style="gm", min_games=15, top_n=5, rng=random.Random(1))
        sharp = choose_book_move(board, book, style="sharp", min_games=15, top_n=5, rng=random.Random(1))
        gambit = choose_book_move(board, book, style="gambit", min_games=15, top_n=5, rng=random.Random(1))
        assert gm is not None and sharp is not None and gambit is not None
        self.assertEqual(gm.move.uci(), "d2d4")
        self.assertEqual(gm.style_used, "gm")
        self.assertEqual(sharp.move.uci(), "c2c4")
        self.assertEqual(sharp.style_used, "sharp")
        self.assertEqual(gambit.style_used, "auto")

    def test_repetition_guard_and_empty_book(self) -> None:
        board = chess.Board()
        for uci in ("g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1"):
            board.push_uci(uci)
        book = MozerBookResponse(
            total_games=100,
            moves=[BookMoveEntry("Ng8", "f6g8", 100, 30.0, 40.0, 30.0, 0, None, None)],
            styles={"grossmaster": "f6g8", "hustler": None, "schuler": None},
            wiki_name=None,
            wiki_eco=None,
        )
        self.assertIsNone(choose_book_move(board, book, style="gm", min_games=15, top_n=5))


if __name__ == "__main__":
    unittest.main()
