"""ExtraPawn chat command handler for lichess-bot."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from extrapawn.engine import MozeroExtraPawnEngine
from extrapawn.opening_book import VALID_BOOK_STYLES, BookStyle
from lib.lichess import MAX_CHAT_MESSAGE_LEN

if TYPE_CHECKING:
    from lib.conversation import ChatLine, Conversation


def truncate_chat(text: str, limit: int = MAX_CHAT_MESSAGE_LEN) -> str:
    """Truncate text so every chat reply strictly satisfies Lichess's 140-character limit."""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return f"{text[:limit - 3].rstrip()}..."


def _reply(conversation: Conversation, line: ChatLine, text: str) -> None:
    conversation.send_reply(line, truncate_chat(text))


def handle_extrapawn_command(conversation: Conversation, line: ChatLine, cmd: str) -> bool:
    """
    Handle ExtraPawn-specific chat commands.

    Returns True if handled, False to delegate to upstream Conversation commands.
    """
    parts = cmd.split()
    verb = parts[0] if parts else ""

    if verb in ("help", "commands"):
        _reply(
            conversation,
            line,
            "Commands: !style (auto|gm|sharp|gambit), !opening, !info, !wait, !name, !eval (spectators)",
        )
        return True

    if verb == "info":
        _reply(
            conversation,
            line,
            "Human-like neural bot (Mozero + Masters Book) by ExtraPawn. Train endgames & tactics: https://extrapawn.com",
        )
        return True

    if verb == "style":
        if not isinstance(conversation.engine, MozeroExtraPawnEngine):
            _reply(conversation, line, "Style switching is only available on ExtraPawn Mozero.")
            return True

        if len(parts) == 1:
            _reply(
                conversation,
                line,
                f"Current opening style: {conversation.engine.book_style}. Use: !style auto|gm|sharp|gambit",
            )
            return True

        if line.room != "player" and line.username != conversation.game.username:
            _reply(conversation, line, "Only the active player can change the opening style.")
            return True

        requested = parts[1]
        if requested in VALID_BOOK_STYLES:
            new_style = cast(BookStyle, requested)
            conversation.engine.set_book_style(new_style)
            _reply(conversation, line, f"Opening style set to: {new_style} (ExtraPawn Masters Book).")
        else:
            _reply(conversation, line, "Unknown style. Choose: auto, gm, sharp, gambit")
        return True

    if verb == "opening":
        if not isinstance(conversation.engine, MozeroExtraPawnEngine):
            return False
        start_fen = conversation.game.initial_fen or "startpos"
        raw_moves = conversation.game.state.get("moves", "")
        moves = [move for move in raw_moves.split() if move] if isinstance(raw_moves, str) else []
        summary = conversation.engine.get_opening_summary(start_fen, moves)
        _reply(conversation, line, summary)
        return True

    return False
