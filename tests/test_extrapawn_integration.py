"""Integration unit tests for MozeroExtraPawnEngine, chat commands, config, challenges, and takebacks."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import chess
from chess.engine import Limit
import yaml

from extrapawn.clients import (
    BestMoveResponse,
    BookMoveEntry,
    EngineHubClient,
    MozerBookResponse,
    TableServiceClient,
)
from extrapawn.engine import MozeroExtraPawnEngine
from lib import config as bot_config
from lib import lichess, lichess_bot, model
from lib.blocklist import OnlineBlocklist
from lib.config import Configuration
from lib.conversation import ChatLine, Conversation
from lib.engine_wrapper import create_engine


REPO_ROOT = Path(__file__).resolve().parent.parent
PLAY_RESULT_PLACEHOLDER = chess.engine.PlayResult(None, None)


def _make_sample_game(*, mode: str = "casual", variant: str = "Standard", initial_fen: str = "startpos") -> model.Game:
    is_from_pos = variant == "From Position"
    payload = {
        "id": "game1234",
        "rated": mode == "rated",
        "variant": {"key": "fromPosition" if is_from_pos else "standard", "name": variant},
        "speed": "blitz",
        "perf": {"name": "Blitz"},
        "createdAt": 1700000000000,
        "clock": {"initial": 180000, "increment": 0},
        "white": {"name": "ExtraPawnCOM", "title": "BOT", "rating": 2200},
        "black": {"name": "HumanPlayer", "title": None, "rating": 1800},
        "initialFen": initial_fen,
        "state": {
            "moves": "",
            "wtime": 180000,
            "btime": 180000,
            "winc": 0,
            "binc": 0,
            "status": "started",
        },
    }
    return model.Game(payload, "ExtraPawnCOM", "https://lichess.org/", lichess_bot.seconds(30))


def _make_challenge_payload(
    *,
    is_bot: bool = False,
    rated: bool = True,
    variant_key: str = "standard",
    speed: str = "blitz",
    limit: int = 180,
    increment: int = 0,
    initial_fen: str = "startpos",
) -> dict:
    return {
        "id": "chlng123",
        "rated": rated,
        "variant": {"key": variant_key, "name": variant_key},
        "perf": {"name": speed.title()},
        "speed": speed,
        "timeControl": {"limit": limit, "increment": increment},
        "challenger": {
            "name": "OpponentBot" if is_bot else "HumanChallenger",
            "title": "BOT" if is_bot else None,
            "rating": 1800,
        },
        "destUser": {"name": "ExtraPawnCOM", "title": "BOT", "rating": 2200},
        "initialFen": initial_fen,
        "color": "random",
        "finalColor": "white",
    }


class TestMozeroExtraPawnEngine(unittest.TestCase):
    def _env(self) -> dict[str, str]:
        return {
            "MAIA_HUB_URL": "http://engine-hub:5000",
            "TABLESERVICE_URL": "http://tableservice:5000",
            "BOT_MIN_MOVE_DELAY_SEC": "0.0",
            "BOT_MAX_MOVE_DELAY_SEC": "0.0",
            "BOT_BOOK_MAX_PLY": "4",
        }

    def test_startup_healthcheck_fails_fast(self) -> None:
        with (
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(EngineHubClient, "check_health", side_effect=RuntimeError("hub down")),
        ):
            with self.assertRaises(RuntimeError):
                MozeroExtraPawnEngine([], {}, None, Configuration({}), None, False)

    def test_standard_uses_book_then_mozero_and_populates_stats(self) -> None:
        book = MozerBookResponse(
            total_games=500,
            moves=[BookMoveEntry("e4", "e2e4", 500, 40.0, 30.0, 30.0, 20, "King's Pawn", "B00")],
            styles={"grossmaster": "e2e4", "hustler": "e2e4", "schuler": "e2e4"},
            wiki_name="Start Position",
            wiki_eco=None,
        )
        empty_book = MozerBookResponse(
            total_games=0,
            moves=[],
            styles={"grossmaster": None, "hustler": None, "schuler": None},
            wiki_name=None,
            wiki_eco=None,
        )
        mozero_res = BestMoveResponse(
            best_move="d2d4",
            engine="mozero",
            mode="leelaHoldDraw",
            source="lc0",
            dtm=None,
            time_real_ms=35.0,
            player_tablebase=None,
        )
        game = _make_sample_game()
        with patch.dict(os.environ, self._env(), clear=True):
            engine = MozeroExtraPawnEngine([], {"skip_startup_healthcheck": True}, None, Configuration({}), game, False)

        board = chess.Board()
        limit = Limit(white_clock=180.0, black_clock=180.0)
        with patch.object(engine.tableservice, "get_mozer_book", return_value=book) as mock_book:
            res1 = engine.search(board, limit, False, False, PLAY_RESULT_PLACEHOLDER)
        self.assertEqual(res1.move.uci(), "e2e4")
        self.assertEqual(mock_book.call_count, 1)

        board.push_uci("e2e4")
        board.push_uci("e7e5")
        with (
            patch.object(engine.tableservice, "get_mozer_book", return_value=empty_book),
            patch.object(engine.engine_hub, "get_bestmove", return_value=mozero_res) as mock_hub,
        ):
            res2 = engine.search(board, limit, False, False, PLAY_RESULT_PLACEHOLDER)
        self.assertEqual(res2.move.uci(), "d2d4")
        mock_hub.assert_called_once_with(start_fen="startpos", moves=["e2e4", "e7e5"])

        engine.add_comment(res2, board)
        stats = engine.get_stats(for_chat=True)
        self.assertTrue(stats)
        joined = ", ".join(stats)
        self.assertIn("Mozero (leelaHoldDraw/lc0)", joined)
        self.assertLessEqual(len(joined), lichess.MAX_CHAT_MESSAGE_LEN)
        engine.notify("quit")

    def test_from_position_skips_book_and_passes_custom_fen(self) -> None:
        endgame_fen = "8/8/8/8/4k3/8/4P3/4K3 w - - 0 1"
        game = _make_sample_game(mode="casual", variant="From Position", initial_fen=endgame_fen)
        mozero_res = BestMoveResponse(
            best_move="e1d2",
            engine="mozero",
            mode="leelaPunishUser",
            source="gaviota",
            dtm=19,
            time_real_ms=4.2,
            player_tablebase=None,
        )
        with patch.dict(os.environ, self._env(), clear=True):
            engine = MozeroExtraPawnEngine([], {"skip_startup_healthcheck": True}, None, Configuration({}), game, False)

        board = chess.Board(endgame_fen)
        limit = Limit(white_clock=180.0, black_clock=180.0)
        with (
            patch.object(engine.tableservice, "get_mozer_book") as mock_book,
            patch.object(engine.engine_hub, "get_bestmove", return_value=mozero_res) as mock_hub,
        ):
            res = engine.search(board, limit, False, False, PLAY_RESULT_PLACEHOLDER)
        mock_book.assert_not_called()
        mock_hub.assert_called_once_with(start_fen=endgame_fen, moves=[])
        self.assertEqual(res.move.uci(), "e1d2")
        self.assertIn("DTM=19", str(res.info.get("string", "")))

    def test_illegal_move_from_hub_raises(self) -> None:
        game = _make_sample_game()
        bad_res = BestMoveResponse(
            best_move="e1e8",
            engine="mozero",
            mode="leelaHoldDraw",
            source="lc0",
            dtm=None,
            time_real_ms=10.0,
            player_tablebase=None,
        )
        env = self._env() | {"BOT_BOOK_MAX_PLY": "0"}
        with patch.dict(os.environ, env, clear=True):
            engine = MozeroExtraPawnEngine([], {"skip_startup_healthcheck": True}, None, Configuration({}), game, False)
        with patch.object(engine.engine_hub, "get_bestmove", return_value=bad_res):
            with self.assertRaises(RuntimeError):
                engine.search(chess.Board(), Limit(white_clock=180.0), False, False, PLAY_RESULT_PLACEHOLDER)


class TestChatAndConfigAndChallenges(unittest.TestCase):
    def test_chat_ignores_interactive_commands_while_greetings_work(self) -> None:
        game = _make_sample_game()
        with patch.dict(
            os.environ,
            {"MAIA_HUB_URL": "http://engine-hub:5000", "TABLESERVICE_URL": "http://tableservice:5000"},
            clear=True,
        ):
            engine = MozeroExtraPawnEngine([], {"skip_startup_healthcheck": True}, None, Configuration({}), game, False)

        li_mock = MagicMock()
        conv = Conversation(game, engine, li_mock, "1.0", [])

        for room in ("player", "spectator"):
            for msg in ("!help", "!style gambit", "!opening", "!info", "!eval", "!wait", "!name", ""):
                conv.react(ChatLine({"room": room, "username": "HumanPlayer", "text": msg}))
        li_mock.chat.assert_not_called()

        conv.send_message("player", "Hi! Good luck!")
        li_mock.chat.assert_called_once_with("game1234", "player", "Hi! Good luck!")

    def test_config_extrapawn_yml_validation_and_greetings(self) -> None:
        cfg_path = str(REPO_ROOT / "config.extrapawn.yml")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Exception):
                bot_config.load_config(cfg_path)

        with patch.dict(os.environ, {"LICHESS_BOT_TOKEN": "   "}, clear=True):
            with self.assertRaises(Exception):
                bot_config.load_config(cfg_path)

        with (
            patch.dict(
                os.environ,
                {
                    "LICHESS_BOT_TOKEN": "lip_test_valid_token_123",
                    "MAIA_HUB_URL": "http://engine-hub:5000",
                    "TABLESERVICE_URL": "http://tableservice:5000",
                },
                clear=True,
            ),
            patch.object(EngineHubClient, "check_health") as mock_hub_health,
            patch.object(TableServiceClient, "check_health") as mock_tb_health,
        ):
            loaded = bot_config.load_config(cfg_path)
            with create_engine(loaded) as eng:
                self.assertEqual(eng.name(), "ExtraPawn Mozero V5")
            mock_hub_health.assert_called_once()
            mock_tb_health.assert_called_once()

        with open(cfg_path, encoding="utf-8") as fh:
            raw_cfg = yaml.safe_load(fh)
        for key, template in raw_cfg["greeting"].items():
            rendered = template.format(opponent="TwentyCharUserName__", me="ExtraPawnCOM")
            self.assertLessEqual(len(rendered), lichess.MAX_CHAT_MESSAGE_LEN, f"greeting.{key} too long")
            for forbidden in ("!help", "!style", "!opening", "!info", "!eval"):
                self.assertNotIn(forbidden, rendered)

    def test_challenges_filter_humans_blitz_rapid_only(self) -> None:
        with patch.dict(os.environ, {"LICHESS_BOT_TOKEN": "lip_test_valid_token_123"}, clear=True):
            loaded = bot_config.load_config(str(REPO_ROOT / "config.extrapawn.yml"))
        user_profile = {"id": "extrapawncom", "username": "ExtraPawnCOM", "perfs": {}}
        blocklist = OnlineBlocklist([])

        accepted_cases = [
            _make_challenge_payload(is_bot=False, rated=True, variant_key="standard", speed="blitz", limit=180, increment=0),
            _make_challenge_payload(is_bot=False, rated=False, variant_key="standard", speed="rapid", limit=600, increment=5),
            _make_challenge_payload(
                is_bot=False,
                rated=False,
                variant_key="fromPosition",
                speed="blitz",
                limit=300,
                increment=2,
                initial_fen="8/8/8/8/4k3/8/4P3/4K3 w - - 0 1",
            ),
        ]
        for payload in accepted_cases:
            chlng = model.Challenge(payload, user_profile)
            ok, reason = chlng.is_supported(loaded.challenge, defaultdict(list), Counter(), blocklist, user_profile)
            self.assertTrue(ok, f"Expected accepted, got reason={reason} for {payload}")

        rejected_cases = [
            (_make_challenge_payload(is_bot=True, speed="blitz", limit=180), "noBot"),
            (_make_challenge_payload(is_bot=False, speed="bullet", limit=60), "timeControl"),
            (_make_challenge_payload(is_bot=False, speed="classical", limit=1800), "timeControl"),
            (_make_challenge_payload(is_bot=False, speed="correspondence", limit=0), "timeControl"),
        ]
        for payload, expected_reason in rejected_cases:
            chlng = model.Challenge(payload, user_profile)
            ok, reason = chlng.is_supported(loaded.challenge, defaultdict(list), Counter(), blocklist, user_profile)
            self.assertFalse(ok)
            self.assertEqual(reason, expected_reason)

    def test_record_takeback_creates_missing_directory(self) -> None:
        game = _make_sample_game(mode="casual")
        with tempfile.TemporaryDirectory() as tmp_dir:
            nested_dir = os.path.join(tmp_dir, "missing_logs")
            with patch.object(lichess_bot, "auto_log_directory", nested_dir):
                lichess_bot.record_takeback(game, 1)
                self.assertEqual(lichess_bot.read_takeback_record(game), 1)

    def test_rated_denies_takeback_while_casual_allows(self) -> None:
        for rated, expected_accept in ((True, False), (False, True)):
            with self.subTest(rated=rated), tempfile.TemporaryDirectory() as tmp_dir:
                initial = {
                    "id": "g1",
                    "rated": rated,
                    "variant": {"key": "standard", "name": "Standard"},
                    "speed": "blitz",
                    "perf": {"name": "Blitz"},
                    "createdAt": 1700000000000,
                    "clock": {"initial": 180000, "increment": 0},
                    "white": {"name": "ExtraPawnCOM", "title": "BOT", "rating": 2200},
                    "black": {"name": "HumanPlayer", "title": None, "rating": 1800},
                    "initialFen": "startpos",
                    "state": {
                        "type": "gameState",
                        "moves": "e2e4",
                        "wtime": 180000,
                        "btime": 180000,
                        "winc": 0,
                        "binc": 0,
                        "status": "started",
                    },
                }
                takeback_state = {
                    "type": "gameState",
                    "moves": "e2e4",
                    "wtime": 180000,
                    "btime": 180000,
                    "winc": 0,
                    "binc": 0,
                    "btakeback": True,
                    "status": "started",
                }
                end_state = {
                    "type": "gameState",
                    "moves": "e2e4",
                    "wtime": 180000,
                    "btime": 180000,
                    "winc": 0,
                    "binc": 0,
                    "status": "mate",
                    "winner": "white",
                }

                def _gen(chunks: list[bytes]):
                    yield from chunks

                stream_gen = _gen([
                    json.dumps(initial).encode("utf-8"),
                    json.dumps(takeback_state).encode("utf-8"),
                    json.dumps(end_state).encode("utf-8"),
                ])

                li_mock = MagicMock()
                li_mock.baseUrl = "https://lichess.org/"
                li_mock.accept_takeback.return_value = expected_accept
                li_mock.get_game_pgn.return_value = ""

                with patch.dict(os.environ, {"LICHESS_BOT_TOKEN": "lip_test_valid_token_123"}, clear=True):
                    cfg = bot_config.load_config(str(REPO_ROOT / "config.extrapawn.yml"))

                mock_engine = MagicMock()
                mock_engine.__enter__.return_value = mock_engine
                mock_engine.__exit__.return_value = None

                with (
                    patch.object(lichess_bot, "auto_log_directory", os.path.join(tmp_dir, "logs")),
                    patch.object(lichess_bot, "game_stream_lines", return_value=stream_gen),
                    patch.object(lichess_bot.engine_wrapper, "create_engine", return_value=mock_engine),
                    patch.object(lichess_bot, "thread_logging_configurer"),
                ):
                    lichess_bot.play_game.__wrapped__(
                        li_mock,
                        "g1",
                        queue.Queue(),
                        {"id": "extrapawncom", "username": "ExtraPawnCOM"},
                        cfg,
                        [],
                        queue.Queue(),
                        queue.Queue(),
                        queue.Queue(),
                    )
                li_mock.accept_takeback.assert_called_once_with("g1", expected_accept)


if __name__ == "__main__":
    unittest.main()
