"""The game itself: a room's state machine, independent of networking and of any model.

Everything time-related takes `now` as an argument, and all content comes from a
`GameMaster`, so the engine is deterministic and easy to test.
"""

from __future__ import annotations

import random
import re
import secrets
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .matching import matches, normalise
from .models import MIN_PLAYERS, Audience, EmojiPuzzle, Fact, GameKind, Judgement, Question
from .safety import clean_name, mask_profanity

Phase = Literal["lobby", "preparing", "question", "reveal", "writing", "voting", "judging", "results", "final"]

MAX_PLAYERS = 10
QUESTION_SECONDS = 20
WRITING_SECONDS = 60
FAKE_SECONDS = 45
EMOJI_SECONDS = 30
VOTING_SECONDS = 25
REVEAL_SECONDS = 8
RESULTS_SECONDS = 12
TOKENS = ["#e4572e", "#2e86ab", "#f3a712", "#29bf12", "#a23b72", "#00a6a6", "#ff6f91", "#6c4bd8", "#f26419", "#3d9970"]


class GameMaster(Protocol):
    """Where questions, prompts and judgements come from (an LLM, or the offline bank)."""

    name: str

    async def trivia(self, topics: list[str], n: int, audience: Audience, avoid: list[str]) -> list[Question]: ...

    async def prompts(self, n: int, audience: Audience, avoid: list[str]) -> list[str]: ...

    async def judge(self, prompt: str, answers: dict[str, str], audience: Audience) -> Judgement: ...

    async def facts(self, n: int, audience: Audience, avoid: list[str]) -> list[Fact]: ...

    async def emoji(self, topics: list[str], n: int, audience: Audience, avoid: list[str]) -> list[EmojiPuzzle]: ...

    async def most_likely(self, n: int, audience: Audience, avoid: list[str]) -> list[str]: ...


GAME_NAMES = {
    "trivia": "Trivia",
    "hot_take": "Hot Take",
    "fake_out": "Fake Out",
    "most_likely": "Most Likely To",
    "emoji": "Emoji Decode",
}


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
    facts: list[Fact] = field(default_factory=list)
    puzzles: list[EmojiPuzzle] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)  # Fake Out: the truth and the fakes, shuffled
    seen: list[str] = field(default_factory=list)  # avoid repeats across games in this room
    rng: random.Random = field(default_factory=random.Random)
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
        need = MIN_PLAYERS.get(game)
        if need is None:
            raise GameError("Pick a game.")
        if len(self.players) < need:
            raise GameError(
                "Waiting for players." if need == 1 else f"{GAME_NAMES[game]} needs at least {need} players."
            )
        self.game, self.audience = game, audience
        self.topics = [mask_profanity(t)[:30] for t in topics if t.strip()][:4] or ["general knowledge"]
        self.total_rounds = max(1, min(rounds, 15))
        self.round_no = 0
        for p in self.players.values():
            p.score = p.last_points = 0
        self.phase, self.notice = "preparing", "The game master is writing your questions…"
        self._touch(now)
        try:
            n = self.total_rounds
            if game == "trivia":
                self.questions = await self.gm.trivia(self.topics, n, audience, self.seen)
                got = [q.prompt for q in self.questions]
            elif game == "hot_take":
                self.prompts = await self.gm.prompts(n, audience, self.seen)
                got = list(self.prompts)
            elif game == "fake_out":
                self.facts = await self.gm.facts(n, audience, self.seen)
                got = [f.prompt for f in self.facts]
            elif game == "emoji":
                self.puzzles = await self.gm.emoji(self.topics, n, audience, self.seen)
                got = [p.answer for p in self.puzzles]
            else:
                self.prompts = await self.gm.most_likely(n, audience, self.seen)
                got = list(self.prompts)
            self.total_rounds = min(n, len(got))
            self.seen += got
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
        if self.phase == "writing" and self.game == "fake_out":
            self._open_vote(now)
        elif self.phase in ("question", "writing", "voting"):
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
            limit = 60 if self.game in ("fake_out", "emoji") else 120
            if not 1 <= len(text) <= limit:
                raise GameError(f"Write something between 1 and {limit} characters.")
            if self.game == "emoji":
                if player_id in self.submissions:
                    raise GameError("You've already locked in a guess.")
            elif self.game == "fake_out":
                fact = self.facts[self.round_no - 1]
                if matches(text, fact.answer, fact.aliases):
                    raise GameError("That's actually the real answer! Write a fake one to fool the others.")
            self.submissions[player_id] = {"text": mask_profanity(text), "at": now}  # editable until time (not Emoji)
        elif self.phase == "voting":
            vote = str(payload.get("vote", ""))
            if player_id in self.submissions:
                raise GameError("You've already voted.")
            if self.game == "most_likely":
                if vote not in self.players:
                    raise GameError("Vote for someone in the room.")
                if vote == player_id:
                    raise GameError("You can't vote for yourself.")
            else:
                option = next((o for o in self.options if o["key"] == vote), None)
                if option is None:
                    raise GameError("Pick one of the answers.")
                if player_id in option["authors"]:
                    raise GameError("That's your own fake! Pick another.")
            self.submissions[player_id] = {"vote": vote, "at": now}
        else:
            raise GameError("Not taking answers right now.")
        self._touch(now)

    async def tick(self, now: float) -> bool:
        """Called regularly by the server. Returns True if the state changed."""
        before = self.version
        active = self._active_ids()
        everyone_in = (
            self.phase in ("question", "writing", "voting") and bool(active) and active <= set(self.submissions)
        )
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
        self.options = []
        if self.game == "trivia":
            self.phase, self.deadline = "question", now + QUESTION_SECONDS
        elif self.game == "most_likely":
            self.phase, self.deadline = "voting", now + VOTING_SECONDS
        else:
            seconds = {"fake_out": FAKE_SECONDS, "emoji": EMOJI_SECONDS}.get(self.game, WRITING_SECONDS)
            self.phase, self.deadline = "writing", now + seconds
        self.notice = ""
        self._touch(now)

    def _open_vote(self, now: float) -> None:
        """Fake Out: shuffle the real answer in with everyone's fakes (identical fakes share one card)."""
        fact = self.facts[self.round_no - 1]
        cards: dict[str, dict] = {normalise(fact.answer): {"text": fact.answer, "authors": [], "truth": True}}
        for pid, sub in self.submissions.items():
            if pid not in self.players:
                continue
            key = normalise(sub["text"])
            text = _match_style(sub["text"], fact.answer)
            card = cards.setdefault(key, {"text": text, "authors": [], "truth": False})
            if not card["truth"]:
                card["authors"].append(pid)
        if len(cards) == 1:  # nobody wrote a fake: just show the answer
            self.options = [{"key": "o0", **next(iter(cards.values()))}]
            self.submissions = {}
            self.phase, self.deadline = "results", now + RESULTS_SECONDS
            self._touch(now)
            return
        shuffled = list(cards.values())
        self.rng.shuffle(shuffled)
        self.options = [{"key": f"o{i}", **c} for i, c in enumerate(shuffled)]
        self.submissions = {}
        self.phase, self.deadline = "voting", now + VOTING_SECONDS
        self._touch(now)

    def _award(self, pid: str, points: int) -> None:
        if pid in self.players and points:
            self.players[pid].score += points
            self.players[pid].last_points += points

    async def _close_round(self, now: float) -> None:
        if self.game == "fake_out":
            for pid, sub in self.submissions.items():
                card = next((o for o in self.options if o["key"] == sub["vote"]), None)
                if card is None:
                    continue
                if card["truth"]:
                    self._award(pid, 500)
                else:
                    for author in card["authors"]:
                        self._award(author, 250)
            self.phase, self.deadline = "results", now + RESULTS_SECONDS
            self._touch(now)
            return
        if self.game == "most_likely":
            counts: dict[str, int] = {}
            for sub in self.submissions.values():
                counts[sub["vote"]] = counts.get(sub["vote"], 0) + 1
            if counts:
                top = max(counts.values())
                for pid, sub in self.submissions.items():
                    if counts[sub["vote"]] == top:
                        self._award(pid, 300)  # you read the room
            self.phase, self.deadline = "results", now + RESULTS_SECONDS
            self._touch(now)
            return
        if self.game == "emoji":
            puzzle = self.puzzles[self.round_no - 1]
            for pid, sub in self.submissions.items():
                sub["correct"] = matches(sub["text"], puzzle.answer, puzzle.aliases)
                if sub["correct"]:
                    elapsed = max(0.0, sub["at"] - self.round_started)
                    self._award(pid, 500 + round(500 * max(0.0, 1 - elapsed / EMOJI_SECONDS)))
            self.phase, self.deadline = "reveal", now + RESULTS_SECONDS
            self._touch(now)
            return
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
        if self.game == "trivia" and self.phase in ("question", "reveal") and self.questions:
            q = self.questions[self.round_no - 1]
            base["question"] = {"prompt": q.prompt, "options": q.options, "category": q.category}
            if self.phase == "reveal":
                base["question"] |= {"answer_index": q.answer_index, "explanation": q.explanation}
                base["picks"] = {pid: s["choice"] for pid, s in self.submissions.items()}
        if self.game == "fake_out" and self.facts and self.phase in ("writing", "voting", "results"):
            fact = self.facts[self.round_no - 1]
            base["prompt"] = fact.prompt
            if self.phase == "voting":
                base["options"] = [
                    {"key": o["key"], "text": o["text"], "mine": viewer in o["authors"]} for o in self.options
                ]
            if self.phase == "results":
                base["answer"] = fact.answer
                base["cards"] = [
                    {
                        "text": o["text"],
                        "truth": o["truth"],
                        "authors": o["authors"],
                        "voters": [pid for pid, s in self.submissions.items() if s["vote"] == o["key"]],
                    }
                    for o in sorted(self.options, key=lambda o: (not o["truth"], o["text"]))
                ]
            if viewer != "host" and viewer in self.submissions:
                base["my_submission"] = {k: v for k, v in self.submissions[viewer].items() if k != "at"}
            return base
        if self.game == "most_likely" and self.prompts and self.phase in ("voting", "results"):
            base["prompt"] = f"Who's most likely to {self.prompts[self.round_no - 1]}?"
            if self.phase == "results":
                tally: dict[str, list[str]] = {}
                for voter, s in self.submissions.items():
                    tally.setdefault(s["vote"], []).append(voter)
                base["tally"] = [
                    {"player_id": pid, "voters": voters}
                    for pid, voters in sorted(tally.items(), key=lambda kv: -len(kv[1]))
                    if pid in self.players
                ]
            if viewer != "host" and viewer in self.submissions:
                base["my_submission"] = {"vote": self.submissions[viewer]["vote"]}
            return base
        if self.game == "emoji" and self.puzzles and self.phase in ("writing", "reveal"):
            puzzle = self.puzzles[self.round_no - 1]
            base["emoji"] = {"emojis": puzzle.emojis, "category": puzzle.category}
            if self.phase == "reveal":
                base["answer"] = puzzle.answer
                base["guesses"] = [
                    {"player_id": pid, "text": s["text"], "correct": s.get("correct", False)}
                    for pid, s in self.submissions.items()
                    if pid in self.players
                ]
            if viewer != "host" and viewer in self.submissions:
                base["my_submission"] = {k: v for k, v in self.submissions[viewer].items() if k != "at"}
            return base
        if self.game == "hot_take" and self.phase in ("writing", "judging", "results") and self.prompts:
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


def _match_style(fake: str, truth: str) -> str:
    """Make a fake look like the real answer, so "a kerfuffle" next to "hands" doesn't give the truth away."""
    text = fake.strip().rstrip(".!")
    if not re.match(r"(?i)(a|an|the)\s", truth):
        text = re.sub(r"(?i)^(a|an|the)\s+", "", text) or text
    if truth[:1].islower() and text[:1].isupper() and not text[1:2].isupper():
        text = text[0].lower() + text[1:]
    return text


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
