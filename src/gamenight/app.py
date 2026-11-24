"""HTTP + WebSocket server. The TV and every phone hold one WebSocket each.

uvicorn gamenight.app:app --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .engine import GameError, Room, RoomManager
from .gamemaster import make_game_master
from .llm import get_llm
from .protocol import handle

TICK_SECONDS = 0.5
MAX_MESSAGE_BYTES = 2000
MAX_MESSAGES_PER_10S = 40


@dataclass(eq=False)
class Conn:
    ws: WebSocket
    role: str  # "host" | "player"
    player_id: str | None = None


class Hub:
    """Rooms plus the sockets attached to each, and the clock that drives timers."""

    def __init__(self) -> None:
        llm = get_llm()
        self.game_master_name = make_game_master(llm).name
        self.rooms = RoomManager(lambda: make_game_master(llm))
        self.conns: dict[str, set[Conn]] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.sent_version: dict[str, int] = {}

    def lock(self, code: str) -> asyncio.Lock:
        return self.locks.setdefault(code, asyncio.Lock())

    async def broadcast(self, room: Room) -> None:
        now = time.time()
        self.sent_version[room.code] = room.version
        for c in list(self.conns.get(room.code, ())):
            viewer = "host" if c.role == "host" else (c.player_id or "")
            try:
                await c.ws.send_json({"type": "state", "state": room.view(viewer, now)})
            except Exception:
                self.conns[room.code].discard(c)

    async def run_clock(self) -> None:
        last_second = 0
        while True:
            await asyncio.sleep(TICK_SECONDS)
            now = time.time()
            for room in self.rooms.all():
                lock = self.lock(room.code)
                if not lock.locked():
                    async with lock:
                        with contextlib.suppress(Exception):
                            await room.tick(now)
                # Push on change, and once a second while a countdown is showing.
                countdown = room.deadline is not None and int(now) != last_second
                if room.version != self.sent_version.get(room.code) or countdown:
                    await self.broadcast(room)
            last_second = int(now)
            for code in [c for c in self.conns if c not in {r.code for r in self.rooms.all()}]:
                self.conns.pop(code, None)
                self.locks.pop(code, None)


hub = Hub()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(hub.run_clock())
    yield
    task.cancel()


app = FastAPI(title="Game Night", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "game_master": hub.game_master_name, "rooms": len(hub.rooms)}


@app.post("/api/rooms")
def create_room() -> dict:
    try:
        room = hub.rooms.create(time.time())
    except GameError as e:
        raise HTTPException(503, str(e)) from e
    return {"code": room.code, "host_token": room.host_token, "game_master": room.gm.name}


@app.websocket("/ws/{code}")
async def socket(ws: WebSocket, code: str) -> None:
    await ws.accept()
    try:
        room = hub.rooms.get(code)
        conn = await _hello(ws, room)
    except (GameError, ValueError, TimeoutError) as e:
        message = str(e) if isinstance(e, GameError) else "Couldn't join. Try again."
        await ws.send_json({"type": "error", "message": message, "fatal": True})
        await ws.close()
        return
    except WebSocketDisconnect:
        return

    hub.conns.setdefault(room.code, set()).add(conn)
    await hub.broadcast(room)
    window_start, count = time.time(), 0
    try:
        while True:
            raw = await ws.receive_text()
            now = time.time()
            if now - window_start > 10:
                window_start, count = now, 0
            count += 1
            if len(raw) > MAX_MESSAGE_BYTES or count > MAX_MESSAGES_PER_10S:
                await ws.send_json({"type": "error", "message": "Slow down a little."})
                continue
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise ValueError
                async with hub.lock(room.code):
                    await handle(room, conn.role, conn.player_id, msg, now)
            except GameError as e:
                await ws.send_json({"type": "error", "message": str(e)})
            except ValueError:
                await ws.send_json({"type": "error", "message": "Bad message."})
            except Exception:
                await ws.send_json({"type": "error", "message": "Something went wrong. Try again."})
            await hub.broadcast(room)
    except WebSocketDisconnect:
        pass
    finally:
        hub.conns.get(room.code, set()).discard(conn)
        if conn.player_id:
            room.disconnect(conn.player_id, time.time())
        await hub.broadcast(room)


async def _hello(ws: WebSocket, room: Room) -> Conn:
    """First message identifies the screen: the TV (with its host token) or a phone."""
    msg = await asyncio.wait_for(ws.receive_json(), timeout=15)
    now = time.time()
    if not isinstance(msg, dict):
        raise GameError("Say hello first.")
    if msg.get("role") == "host":
        if not secrets.compare_digest(str(msg.get("token", "")), room.host_token):
            raise GameError("This screen isn't the host for that game.")
        await ws.send_json({"type": "welcome", "role": "host"})
        return Conn(ws, "host")
    if msg.get("token"):
        player = room.rejoin(str(msg["token"]), now)
    else:
        player = room.join(str(msg.get("name", "")), now)
    await ws.send_json({"type": "welcome", "role": "player", "player_id": player.id, "token": player.token})
    return Conn(ws, "player", player.id)


_dist = Path(os.getenv("GAMENIGHT_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
