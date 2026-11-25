"""Message handling, separate from the WebSocket plumbing so it can be tested directly.

Client -> server messages:
    host:   {"type": "start", "game": "trivia"|"hot_take"|"fake_out"|"most_likely"|"emoji", "rounds": n,
             "topics": [...], "audience": ...}
            {"type": "next"}  {"type": "lobby"}  {"type": "kick", "player_id": id}
    player: {"type": "answer", "choice": 0-3}, {"type": "answer", "text": "..."} or {"type": "answer", "vote": key}
Server -> client: {"type": "state", "state": {...}}, {"type": "error", "message": "..."}
"""

from __future__ import annotations

from .engine import GameError, Room
from .models import GAMES

HOST_ACTIONS = {"start", "next", "lobby", "kick"}


async def handle(room: Room, role: str, player_id: str | None, msg: dict, now: float) -> None:
    kind = msg.get("type")
    if not isinstance(kind, str):
        raise GameError("Bad message.")
    if kind in HOST_ACTIONS and role != "host":
        raise GameError("Only the TV can do that.")

    if kind == "start":
        game = msg.get("game")
        if game not in GAMES:
            raise GameError("Pick a game.")
        audience = msg.get("audience") if msg.get("audience") in ("family", "adults") else "family"
        topics = [str(t) for t in msg.get("topics", []) if isinstance(t, str)][:4]
        rounds = msg.get("rounds", 8)
        await room.start(game, int(rounds) if isinstance(rounds, int) else 8, topics, audience, now)
    elif kind == "next":
        await room.advance(now)
    elif kind == "lobby":
        room.back_to_lobby(now)
    elif kind == "kick":
        room.remove(str(msg.get("player_id", "")), now)
    elif kind == "answer":
        if role != "player" or player_id is None:
            raise GameError("Join the game on your phone to answer.")
        room.submit(player_id, msg, now)
    elif kind == "ping":
        return
    else:
        raise GameError("Unknown message.")
