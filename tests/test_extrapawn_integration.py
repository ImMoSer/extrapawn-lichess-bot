"""Integration unit tests for Variant C MozeroExtraPawnEngine, greetings, config, challenges, and takebacks."""

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


def _make_sample_game(
    *,
    mode: str = "casual",
    variant: str = "Standard",
    initial_fen: str = "startpos",
    opp_rating: int | None = 1750,
) -> model.Game:
    is_from_pos = variant == "From Position"
    black_player: dict = {"name": "HumanPlayer", "title": None}
    if opp_rating is not None:
        black_player["rating"] = opp_rating
    payload = {
        "id": "game1234",
        "rated": mode == "rated",
        "variant": {"key": "fromPosition" if is_from_pos else "standard", "name": variant},
        "speed": "blitz",
        "perf": {"name": "Blitz"},
        "createdAt": 1700000000000,
        "clock": {"initial": 180000, "increment": 0},
        "white": {"name": "ExtraPawnCOM", "title": "BOT", "rating": 2200},
        "black": black_player,
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
            "BOT_BOOK_MAX_PLY": "10",
        }

    def test_startup_healthcheck_fails_fast(self) -> None:
        with (
            patch.dict(os.environ, self._env(), clear=True),
            patch.object(EngineHubClient, "check_health", side_effect=RuntimeError("hub down")),
        ):
            with self.assertRaises(RuntimeError):
                MozeroExtraPawnEngine([], {}, None, Configuration({}), None, False)

    def test_casual_vs_rated_routing_and_display_names(self) -> None:
        cases = [
            ("casual", None, "maia_1500", "MOZERO-1500", False),
            ("casual", 1800, "maia_1500", "MOZERO-1500", False),
            ("casual", 1900, "maia_1700", "MOZERO-1700", False),
            ("casual", 2100, "maia_1900", "MOZERO-1900", False),
            ("casual", 2300, "maia_2200", "MOZERO-2200", True),
            ("rated", 1400, "maia_2200", "MOZERO-2200", True),
            ("rated", None, "maia_2200", "MOZERO-2200", True),
        ]
        for mode, opp_rating, expected_engine, expected_display, expected_sig in cases:
            with self.subTest(mode=mode, opp_rating=opp_rating):
                game = _make_sample_game(mode=mode, opp_rating=opp_rating)
                with patch.dict(os.environ, self._env(), clear=True):
                    engine = MozeroExtraPawnEngine(
                        [], {"skip_startup_healthcheck": True}, None, Configuration({}), game, False
                    )
                self.assertEqual(engine.tier.engine_name, expected_engine)
                self.assertEqual(engine.name(), expected_display)

                book = MozerBookResponse(
                    total_games=500,
                    moves=[BookMoveEntry("e4", "e2e4", 500, 40.0, 30.0, 30.0, 20, "King's Pawn", "B00")],
                    styles={"grossmaster": "e2e4", "hustler": "e2e4", "schuler": "e2e4"},
                    wiki_name="Start Position",
                    wiki_eco=None,
                )
                board = chess.Board()
                limit = Limit(white_clock=180.0, black_clock=180.0)
                with patch.object(engine.tableservice, "get_mozer_book", return_value=book) as mock_book:
                    res1 = engine.search(board, limit, False, False, PLAY_RESULT_PLACEHOLDER)
                self.assertEqual(res1.move.uci(), "e2e4")
                mock_book.assert_called_once_with(board.fen(), significant_only=expected_sig)

                empty_book = MozerBookResponse(
                    total_games=0,
                    moves=[],
                    styles={"grossmaster": None, "hustler": None, "schuler": None},
                    wiki_name=None,
                    wiki_eco=None,
                )
                hub_res = BestMoveResponse(
                    best_move="d2d4",
                    engine=expected_engine,
                    mode="leelaHoldDraw",
                    source=expected_engine,
                    dtm=None,
                    time_real_ms=5.0,
                    player_tablebase=None,
                )
                board.push_uci("e2e4")
                board.push_uci("e7e5")
                with (
                    patch.object(engine.tableservice, "get_mozer_book", return_value=empty_book),
                    patch.object(engine.engine_hub, "get_bestmove", return_value=hub_res) as mock_hub,
                ):
                    res2 = engine.search(board, limit, False, False, PLAY_RESULT_PLACEHOLDER)
                self.assertEqual(res2.move.uci(), "d2d4")
                mock_hub.assert_called_once_with(
                    start_fen="startpos",
                    moves=["e2e4", "e7e5"],
                    engine=expected_engine,
                )
                engine.notify("quit")

    def test_probabilistic_memory_dropout_permanently_closes_book(self) -> None:
        game = _make_sample_game(mode="casual", opp_rating=1600)  # MOZERO-1500, memory_keep_prob=0.55
        with patch.dict(os.environ, self._env(), clear=True):
            engine = MozeroExtraPawnEngine([], {"skip_startup_healthcheck": True}, None, Configuration({}), game, False)

        board = chess.Board()
        for uci in ("e2e4", "e7e5", "g1f3", "b8c6"):
            board.push_uci(uci)

        maia_res = BestMoveResponse(
            best_move="f1c4",
            engine="maia_1500",
            mode="leelaHoldDraw",
            source="maia_1500",
            dtm=None,
            time_real_ms=3.0,
            player_tablebase=None,
        )
        with (
            patch.object(engine._rng, "random", return_value=0.99),
            patch.object(engine.tableservice, "get_mozer_book") as mock_book,
            patch.object(engine.engine_hub, "get_bestmove", return_value=maia_res) as mock_hub,
        ):
            res = engine.search(board, Limit(white_clock=180.0), False, False, PLAY_RESULT_PLACEHOLDER)
        self.assertTrue(engine._memory_dropped_out)
        mock_book.assert_not_called()
        mock_hub.assert_called_once()
        self.assertEqual(res.move.uci(), "f1c4")
        engine.notify("quit")

    def test_from_position_uses_mozero_full_power_and_skips_book(self) -> None:
        endgame_fen = "8/8/8/8/4k3/8/4P3/4K3 w - - 0 1"
        game = _make_sample_game(mode="casual", variant="From Position", initial_fen=endgame_fen, opp_rating=1400)
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

        self.assertEqual(engine.name(), "MOZERO-FullPower")
        board = chess.Board(endgame_fen)
        limit = Limit(white_clock=180.0, black_clock=180.0)
        with (
            patch.object(engine.tableservice, "get_mozer_book") as mock_book,
            patch.object(engine.engine_hub, "get_bestmove", return_value=mozero_res) as mock_hub,
        ):
            res = engine.search(board, limit, False, False, PLAY_RESULT_PLACEHOLDER)
        mock_book.assert_not_called()
        mock_hub.assert_called_once_with(start_fen=endgame_fen, moves=[], engine="mozero")
        self.assertEqual(res.move.uci(), "e1d2")
        self.assertIn("MOZERO-FullPower", str(res.info.get("string", "")))
        self.assertIn("DTM=19", str(res.info.get("string", "")))
        engine.notify("quit")

    def test_illegal_move_from_hub_raises(self) -> None:
        game = _make_sample_game()
        bad_res = BestMoveResponse(
            best_move="e1e8",
            engine="maia_1500",
            mode="leelaHoldDraw",
            source="maia_1500",
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
        engine.notify("quit")


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

        conv.send_message("player", f"Hi! Active engine: {engine.name()}")
        li_mock.chat.assert_called_once_with("game1234", "player", "Hi! Active engine: MOZERO-1500")
        engine.notify("quit")

    def test_config_extrapawn_yml_validation_and_engine_greetings(self) -> None:
        cfg_path = str(REPO_ROOT / "config.extrapawn.yml")
        with patch.dict(os.environ, {}, clear=True):
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
                self.assertEqual(eng.name(), "MOZERO-2200")
            mock_hub_health.assert_called_once()
            mock_tb_health.assert_called_once()

        with open(cfg_path, encoding="utf-8") as fh:
            raw_cfg = yaml.safe_load(fh)
        self.assertIn("{engine}", raw_cfg["greeting"]["hello"])
        self.assertIn("{engine}", raw_cfg["greeting"]["hello_spectators"])
        for profile_label in ("MOZERO-1500", "MOZERO-1700", "MOZERO-1900", "MOZERO-2200", "MOZERO-FullPower"):
            for key, template in raw_cfg["greeting"].items():
                rendered = template.format(
                    opponent="TwentyCharUserName__",
                    me="ExtraPawnCOM",
                    engine=profile_label,
                )
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
                mock_engine.name.return_value = "MOZERO-2200" if rated else "MOZERO-1500"
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
