"""The game itself: a room's state machine, independent of networking and of any model.

Everything time-related takes `now` as an argument, and all content comes from a
`GameMaster`, so the engine is deterministic and easy to test.
"""

from __future__ import annotations

import random
import secrets
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .models import Audience, GameKind, Judgement, Question
from .safety import clean_name, mask_profanity

Phase = Literal["lobby", "preparing", "question", "reveal", "writing", "judging", "results", "final"]

MAX_PLAYERS = 10
QUESTION_SECONDS = 20
WRITING_SECONDS = 60
REVEAL_SECONDS = 8
RESULTS_SECONDS = 12
TOKENS = ["#e4572e", "#2e86ab", "#f3a712", "#29bf12", "#a23b72", "#00a6a6", "#ff6f91", "#6c4bd8", "#f26419", "#3d9970"]


class GameMaster(Protocol):
    """Where questions, prompts and judgements come from (an LLM, or the offline bank)."""

    name: str

    async def trivia(self, topics: list[str], n: int, audience: Audience, avoid: list[str]) -> list[Question]: ...

    async def prompts(self, n: int, audience: Audience, avoid: list[str]) -> list[str]: ...

    async def judge(self, prompt: str, answers: dict[str, str], audience: Audience) -> Judgement: ...


class GameError(Exception):
    """A rejected action, shown to the player who tried it."""


@dataclass
class Player:
    id: str
    name: str
    color: str
    token: str
    score: int = 0
    connected: bool = True
    last_points: int = 0


@dataclass
class Room:
    code: str
    gm: GameMaster
    host_token: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    players: dict[str, Player] = field(default_factory=dict)
    phase: Phase = "lobby"
    game: GameKind = "trivia"
    audience: Audience = "family"
    topics: list[str] = field(default_factory=list)
    total_rounds: int = 0
    round_no: int = 0
    deadline: float | None = None
    round_started: float = 0.0
    questions: list[Question] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    submissions: dict[str, dict] = field(default_factory=dict)
    judgement: dict[str, dict] = field(default_factory=dict)
    seen: list[str] = field(default_factory=list)  # avoid repeats across games in this room
    notice: str = ""
    version: int = 0
    last_activity: float = 0.0

    # ---------- joining ----------

    def join(self, name: str, now: float) -> Player:
        if self.phase not in ("lobby", "final"):
            raise GameError("A game is in progress. Wait for the next one.")
        if len(self.players) >= MAX_PLAYERS:
            raise GameError(f"This room is full ({MAX_PLAYERS} players).")
        try:
            name = clean_name(name)
        except ValueError as e:
            raise GameError("Type a name to join.") from e
        if any(p.name.lower() == name.lower() for p in self.players.values()):
            raise GameError(f"Someone's already called {name}. Pick another name.")
        used = {p.color for p in self.players.values()}
        color = next(c for c in TOKENS if c not in used)
        player = Player(id=secrets.token_hex(4), name=name, color=color, token=secrets.token_urlsafe(16))
        self.players[player.id] = player
        self._touch(now)
        return player

    def rejoin(self, token: str, now: float) -> Player:
        for p in self.players.values():
            if secrets.compare_digest(p.token, token):
                p.connected = True
                self._touch(now)
                return p
        raise GameError("That seat has gone. Join again with your name.")

    def disconnect(self, player_id: str, now: float) -> None:
        if p := self.players.get(player_id):
            p.connected = False
            self._touch(now)

    def remove(self, player_id: str, now: float) -> None:
        if self.phase in ("lobby", "final") and player_id in self.players:
            del self.players[player_id]
            self._touch(now)

    # ---------- host controls ----------

    async def start(self, game: GameKind, rounds: int, topics: list[str], audience: Audience, now: float) -> None:
        if self.phase not in ("lobby", "final"):
            raise GameError("A game is already running.")
        if len(self.players) < (1 if game == "trivia" else 2):
            raise GameError("Hot Take needs at least two players." if game == "hot_take" else "Waiting for players.")
        self.game, self.audience = game, audience
        self.topics = [mask_profanity(t)[:30] for t in topics if t.strip()][:4] or ["general knowledge"]
        self.total_rounds = max(1, min(rounds, 15))
        self.round_no = 0
        for p in self.players.values():
            p.score = p.last_points = 0
        self.phase, self.notice = "preparing", "The game master is writing your questions…"
        self._touch(now)
        try:
            if game == "trivia":
                self.questions = await self.gm.trivia(self.topics, self.total_rounds, audience, self.seen)
                self.total_rounds = min(self.total_rounds, len(self.questions))
                self.seen += [q.prompt for q in self.questions]
            else:
                self.prompts = await self.gm.prompts(self.total_rounds, audience, self.seen)
                self.total_rounds = min(self.total_rounds, len(self.prompts))
                self.seen += self.prompts
        except Exception:
            self.phase = "lobby"
            self.notice = "The game master couldn't write this game. Try again or pick other topics."
            self._touch(now)
            raise
        if self.total_rounds == 0:
            self.phase, self.notice = "lobby", "No questions came back. Try other topics."
            self._touch(now)
            return
        self._begin_round(now)

    async def advance(self, now: float) -> None:
        """Move to the next phase (host's Next button, or a timer)."""
        if self.phase in ("question", "writing"):
            await self._close_round(now)
        elif self.phase in ("reveal", "results"):
            if self.round_no >= self.total_rounds:
                self.phase, self.deadline = "final", None
                self._touch(now)
            else:
                self._begin_round(now)

    def back_to_lobby(self, now: float) -> None:
        self.phase, self.deadline, self.notice = "lobby", None, ""
        self._touch(now)

    # ---------- players ----------

    def submit(self, player_id: str, payload: dict, now: float) -> None:
        if player_id not in self.players:
            raise GameError("You're not in this game.")
        if self.phase == "question":
            choice = payload.get("choice")
            if not isinstance(choice, int) or not 0 <= choice <= 3:
                raise GameError("Pick one of the four answers.")
            if player_id in self.submissions:
                raise GameError("You've already locked in.")
            self.submissions[player_id] = {"choice": choice, "at": now}
        elif self.phase == "writing":
            text = str(payload.get("text", "")).strip()
            if not 1 <= len(text) <= 120:
                raise GameError("Write something between 1 and 120 characters.")
            self.submissions[player_id] = {"text": mask_profanity(text), "at": now}  # can be edited until time
        else:
            raise GameError("Not taking answers right now.")
        self._touch(now)

    async def tick(self, now: float) -> bool:
        """Called regularly by the server. Returns True if the state changed."""
        before = self.version
        active = self._active_ids()
        everyone_in = self.phase in ("question", "writing") and bool(active) and active <= set(self.submissions)
        if self.deadline is not None and (now >= self.deadline or everyone_in):
            await self.advance(now)
        return self.version != before

    # ---------- internals ----------

    def _active_ids(self) -> set[str]:
        return {p.id for p in self.players.values() if p.connected}

    def _begin_round(self, now: float) -> None:
        self.round_no += 1
        self.submissions, self.judgement = {}, {}
        for p in self.players.values():
            p.last_points = 0
        self.round_started = now
        if self.game == "trivia":
            self.phase, self.deadline = "question", now + QUESTION_SECONDS
        else:
            self.phase, self.deadline = "writing", now + WRITING_SECONDS
        self.notice = ""
        self._touch(now)

    async def _close_round(self, now: float) -> None:
        if self.game == "trivia":
            q = self.questions[self.round_no - 1]
            for pid, sub in self.submissions.items():
                if sub["choice"] == q.answer_index and pid in self.players:
                    elapsed = max(0.0, sub["at"] - self.round_started)
                    points = 500 + round(500 * max(0.0, 1 - elapsed / QUESTION_SECONDS))
                    self.players[pid].score += points
                    self.players[pid].last_points = points
            self.phase, self.deadline = "reveal", now + REVEAL_SECONDS
            self._touch(now)
            return

        self.phase, self.deadline, self.notice = "judging", None, "The judge is deliberating…"
        self._touch(now)
        answers = {pid: s["text"] for pid, s in self.submissions.items() if pid in self.players}
        if answers:
            try:
                verdict = await self.gm.judge(self.prompts[self.round_no - 1], answers, self.audience)
                self.judgement = {
                    r.player_id: {"score": r.score, "comment": r.comment}
                    for r in verdict.results
                    if r.player_id in answers
                }
            except Exception:
                self.judgement = {}
            # Anyone the judge skipped still gets a fair middle score rather than nothing.
            for pid in answers:
                self.judgement.setdefault(pid, {"score": 5, "comment": "The judge lost this one under the couch."})
            best = max(j["score"] for j in self.judgement.values())
            for pid, j in self.judgement.items():
                points = j["score"] * 100 + (200 if j["score"] == best else 0)
                self.players[pid].score += points
                self.players[pid].last_points = points
        self.phase, self.deadline, self.notice = "results", now + RESULTS_SECONDS, ""
        self._touch(now)

    def _touch(self, now: float) -> None:
        self.version += 1
        self.last_activity = now

    # ---------- what each screen is allowed to see ----------

    def view(self, viewer: str, now: float) -> dict:
        """State for the TV ("host") or one player's phone. Phones never see answers early."""
        players = sorted(self.players.values(), key=lambda p: (-p.score, p.name))
        base = {
            "code": self.code,
            "phase": self.phase,
            "game": self.game,
            "audience": self.audience,
            "round": self.round_no,
            "total_rounds": self.total_rounds,
            "notice": self.notice,
            "seconds_left": None if self.deadline is None else max(0, round(self.deadline - now)),
            "game_master": self.gm.name,
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "color": p.color,
                    "score": p.score,
                    "connected": p.connected,
                    "last_points": p.last_points,
                    "answered": p.id in self.submissions,
                }
                for p in players
            ],
        }
        if self.phase in ("question", "reveal") and self.questions:
            q = self.questions[self.round_no - 1]
            base["question"] = {"prompt": q.prompt, "options": q.options, "category": q.category}
            if self.phase == "reveal":
                base["question"] |= {"answer_index": q.answer_index, "explanation": q.explanation}
                base["picks"] = {pid: s["choice"] for pid, s in self.submissions.items()}
        if self.phase in ("writing", "judging", "results") and self.prompts:
            base["prompt"] = self.prompts[self.round_no - 1]
            if self.phase == "results":
                base["answers"] = [
                    {"player_id": pid, "text": s["text"], **self.judgement.get(pid, {})}
                    for pid, s in sorted(
                        self.submissions.items(), key=lambda kv: -self.judgement.get(kv[0], {}).get("score", 0)
                    )
                ]
        if viewer != "host" and viewer in self.submissions:
            base["my_submission"] = {k: v for k, v in self.submissions[viewer].items() if k != "at"}
        return base


class RoomManager:
    """Creates rooms with short, unambiguous codes and clears out idle ones."""

    ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"  # no vowels, so codes never spell words

    def __init__(self, gm_factory, max_rooms: int = 500, idle_seconds: int = 3 * 3600, rng=None):
        self._rooms: dict[str, Room] = {}
        self._gm_factory = gm_factory
        self._max = max_rooms
        self._idle = idle_seconds
        self._rng = rng or random.SystemRandom()

    def create(self, now: float) -> Room:
        self.cleanup(now)
        if len(self._rooms) >= self._max:
            raise GameError("Too many games running right now. Try again shortly.")
        while True:
            code = "".join(self._rng.choice(self.ALPHABET) for _ in range(4))
            if code not in self._rooms:
                break
        room = Room(code=code, gm=self._gm_factory(), last_activity=now)
        self._rooms[code] = room
        return room

    def get(self, code: str) -> Room:
        room = self._rooms.get(code.upper().strip())
        if room is None:
            raise GameError("No game with that code. Check the TV.")
        return room

    def cleanup(self, now: float) -> None:
        for code in [c for c, r in self._rooms.items() if now - r.last_activity > self._idle]:
            del self._rooms[code]

    def __len__(self) -> int:
        return len(self._rooms)

    def all(self) -> list[Room]:
        return list(self._rooms.values())
