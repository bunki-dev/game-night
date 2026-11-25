import asyncio

import pytest

from gamenight.engine import QUESTION_SECONDS, GameError, Room, RoomManager
from gamenight.gamemaster import OfflineGameMaster
from gamenight.protocol import handle


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def room():
    return Room(code="BCDF", gm=OfflineGameMaster(seed=1))


def test_join_rules(room):
    a = room.join("Sam", 0)
    with pytest.raises(GameError, match="already called"):
        room.join("sam", 0)
    with pytest.raises(GameError, match="name"):
        room.join("   ", 0)
    assert room.join("shithead", 0).name == "Player"  # rude names are replaced
    assert room.rejoin(a.token, 1).id == a.id
    with pytest.raises(GameError):
        room.rejoin("nope", 1)


def test_room_is_capped(room):
    for i in range(10):
        room.join(f"P{i}", 0)
    with pytest.raises(GameError, match="full"):
        room.join("Eleven", 0)


def test_trivia_round_scores_fast_correct_answers_higher(room):
    a, b, c = room.join("Ann", 0), room.join("Bo", 0), room.join("Cy", 0)
    run(room.start("trivia", 3, ["sport"], "family", now=0))
    assert room.phase == "question"
    q = room.questions[0]
    wrong = (q.answer_index + 1) % 4
    room.submit(a.id, {"choice": q.answer_index}, now=1)
    room.submit(b.id, {"choice": q.answer_index}, now=15)
    room.submit(c.id, {"choice": wrong}, now=2)
    assert run(room.tick(now=16))  # everyone answered: closes early
    assert room.phase == "reveal"
    assert room.players[a.id].score > room.players[b.id].score > room.players[c.id].score == 0


def test_phones_never_see_the_answer_early(room):
    p = room.join("Ann", 0)
    run(room.start("trivia", 2, [], "family", now=0))
    assert "answer_index" not in room.view(p.id, 1)["question"]
    assert "answer_index" not in room.view("host", 1)["question"]
    run(room.advance(now=2))
    assert "answer_index" in room.view(p.id, 3)["question"]


def test_cannot_answer_twice_or_out_of_range(room):
    p = room.join("Ann", 0)
    room.join("Bo", 0)
    run(room.start("trivia", 2, [], "family", now=0))
    with pytest.raises(GameError):
        room.submit(p.id, {"choice": 7}, now=1)
    room.submit(p.id, {"choice": 0}, now=1)
    with pytest.raises(GameError, match="locked in"):
        room.submit(p.id, {"choice": 1}, now=2)


def test_timer_closes_the_round_and_game_ends(room):
    room.join("Ann", 0)
    room.join("Bo", 0)
    run(room.start("trivia", 2, [], "family", now=0))
    t = QUESTION_SECONDS + 1
    for _ in range(2):
        run(room.tick(now=t))  # question -> reveal (time up)
        run(room.advance(now=t + 1))  # reveal -> next round or final
        t += QUESTION_SECONDS + 10
    assert room.phase == "final"


def test_hot_take_round_is_judged_with_a_bonus_for_the_best(room):
    a, b = room.join("Ann", 0), room.join("Bo", 0)
    run(room.start("hot_take", 1, [], "family", now=0))
    assert room.phase == "writing"
    room.submit(a.id, {"text": "A gym where the only machine is a hammock"}, now=5)
    room.submit(b.id, {"text": "zzz"}, now=6)
    run(room.tick(now=7))
    assert room.phase == "results"
    view = room.view("host", 8)
    assert {x["player_id"] for x in view["answers"]} == {a.id, b.id}
    top = view["answers"][0]
    assert room.players[top["player_id"]].last_points == top["score"] * 100 + 200


def test_hot_take_answers_are_masked(room):
    a = room.join("Ann", 0)
    room.join("Bo", 0)
    run(room.start("hot_take", 1, [], "family", now=0))
    room.submit(a.id, {"text": "what the fuck"}, now=1)
    assert "fuck" not in room.submissions[a.id]["text"]


def test_hot_take_needs_two_players(room):
    room.join("Ann", 0)
    with pytest.raises(GameError, match="at least 2 players"):
        run(room.start("hot_take", 3, [], "family", now=0))


def test_judge_failure_still_scores_everyone(room):
    class BrokenJudge(OfflineGameMaster):
        async def judge(self, prompt, answers, audience):
            raise RuntimeError("model down")

    room.gm = BrokenJudge(seed=1)
    a, b = room.join("Ann", 0), room.join("Bo", 0)
    run(room.start("hot_take", 1, [], "family", now=0))
    room.submit(a.id, {"text": "one"}, now=1)
    room.submit(b.id, {"text": "two"}, now=1)
    run(room.tick(now=2))
    assert room.phase == "results" and all(p.score > 0 for p in room.players.values())


def test_questions_do_not_repeat_across_games(room):
    room.join("Ann", 0)
    run(room.start("trivia", 10, [], "family", now=0))
    first = {q.prompt for q in room.questions}
    room.back_to_lobby(1)
    run(room.start("trivia", 10, [], "family", now=2))
    assert not first & {q.prompt for q in room.questions}


def test_protocol_permissions(room):
    p = room.join("Ann", 0)
    with pytest.raises(GameError, match="Only the TV"):
        run(handle(room, "player", p.id, {"type": "start", "game": "trivia"}, 0))
    run(handle(room, "host", None, {"type": "start", "game": "trivia", "rounds": 2, "topics": ["space"]}, 0))
    assert room.phase == "question" and room.topics == ["space"]
    with pytest.raises(GameError):
        run(handle(room, "host", None, {"type": "answer", "choice": 1}, 1))
    run(handle(room, "player", p.id, {"type": "answer", "choice": 1}, 1))
    with pytest.raises(GameError):
        run(handle(room, "player", p.id, {"type": "launch_missiles"}, 1))


def test_room_codes_and_cleanup():
    mgr = RoomManager(lambda: OfflineGameMaster(seed=1), idle_seconds=100)
    r = mgr.create(now=0)
    assert len(r.code) == 4 and not set(r.code) & set("AEIOUY")
    assert mgr.get(r.code.lower()) is r
    mgr.create(now=500)  # creating a room also clears idle ones
    with pytest.raises(GameError):
        mgr.get(r.code)


def test_profanity_filter_avoids_false_positives():
    from gamenight.safety import generated_text_ok, has_profanity, mask_profanity

    assert not has_profanity("Charles Dickens grew up in Sussex")
    assert has_profanity("what a shithead") and has_profanity("FUCKING hell")
    assert mask_profanity("oh shit") == "oh s***"
    assert not generated_text_ok("Which wine region is in South Australia?", "family")
    assert generated_text_ok("Which wine region is in South Australia?", "adults")


# ---------------------------------------------------------------- new games


def test_fake_out_round(room):
    a, b, c = room.join("Ann", 0), room.join("Bo", 0), room.join("Cy", 0)
    run(room.start("fake_out", 1, [], "family", now=0))
    fact = room.facts[0]
    assert room.phase == "writing" and "___" in room.view("host", 0)["prompt"]
    with pytest.raises(GameError, match="real answer"):
        room.submit(a.id, {"text": fact.answer.upper()}, now=1)
    room.submit(a.id, {"text": "a bamboozle"}, now=1)
    room.submit(b.id, {"text": "a kerfuffle"}, now=2)
    room.submit(c.id, {"text": "A Kerfuffle!"}, now=3)  # same fake as Bo: shares a card
    run(room.tick(4))
    assert room.phase == "voting"
    texts = [o["text"] for o in room.options]
    assert len(texts) == 3 and fact.answer in texts
    if not fact.answer.lower().startswith(("a ", "an ", "the ")):
        assert "bamboozle" in texts  # article stripped so fakes look like the truth
    truth = next(o["key"] for o in room.options if o["truth"])
    bamboozle = next(o["key"] for o in room.options if a.id in o["authors"])
    kerfuffle = next(o["key"] for o in room.options if b.id in o["authors"])
    assert next(o for o in room.view(b.id, 4)["options"] if o["key"] == kerfuffle)["mine"] is True
    with pytest.raises(GameError, match="your own"):
        room.submit(a.id, {"vote": bamboozle}, now=5)
    room.submit(a.id, {"vote": truth}, now=5)  # +500
    room.submit(b.id, {"vote": bamboozle}, now=5)  # fooled: Ann +250
    room.submit(c.id, {"vote": bamboozle}, now=5)  # fooled again: Ann +250
    run(room.tick(6))
    assert room.phase == "results"
    assert a.score == 1000 and b.score == 0 and c.score == 0
    view = room.view("host", 6)
    assert view["answer"] == fact.answer
    assert view["cards"][0]["truth"] and view["cards"][0]["voters"] == [a.id]


def test_fake_out_with_no_fakes_skips_voting(room):
    room.join("Ann", 0), room.join("Bo", 0)
    run(room.start("fake_out", 1, [], "family", now=0))
    run(room.advance(1))
    assert room.phase == "results"


def test_most_likely_rewards_reading_the_room(room):
    a, b, c, d = (room.join(n, 0) for n in ("Ann", "Bo", "Cy", "Di"))
    with pytest.raises(GameError, match="at least 3"):
        r2 = Room(code="XYZW", gm=room.gm)
        r2.join("Solo", 0), r2.join("Duo", 0)
        run(r2.start("most_likely", 1, [], "family", now=0))
    run(room.start("most_likely", 1, [], "family", now=0))
    assert room.phase == "voting" and room.view("host", 0)["prompt"].startswith("Who's most likely to ")
    with pytest.raises(GameError, match="yourself"):
        room.submit(a.id, {"vote": a.id}, now=1)
    room.submit(a.id, {"vote": b.id}, now=1)
    room.submit(c.id, {"vote": b.id}, now=1)
    room.submit(d.id, {"vote": b.id}, now=1)
    room.submit(b.id, {"vote": c.id}, now=1)
    run(room.tick(2))
    assert room.phase == "results"
    assert [p.score for p in (a, b, c, d)] == [300, 0, 300, 300]
    assert room.view("host", 2)["tally"][0] == {"player_id": b.id, "voters": [a.id, c.id, d.id]}


def test_emoji_decode_is_forgiving_and_rewards_speed(room):
    a, b, c = room.join("Ann", 0), room.join("Bo", 0), room.join("Cy", 0)
    run(room.start("emoji", 1, [], "family", now=0))
    puzzle = room.puzzles[0]
    assert room.view(a.id, 0)["emoji"]["emojis"] == puzzle.emojis
    assert "answer" not in room.view(a.id, 0)
    room.submit(a.id, {"text": "the " + puzzle.answer.lower() + "!"}, now=2)
    with pytest.raises(GameError, match="already"):
        room.submit(a.id, {"text": "something else"}, now=3)
    room.submit(b.id, {"text": puzzle.answer}, now=20)
    room.submit(c.id, {"text": "definitely not it"}, now=4)
    run(room.tick(21))
    assert room.phase == "reveal"
    assert a.score > b.score > 0 and c.score == 0
    assert {g["player_id"]: g["correct"] for g in room.view("host", 21)["guesses"]} == {
        a.id: True,
        b.id: True,
        c.id: False,
    }


def test_switching_games_shows_only_the_current_game(room):
    a = room.join("Ann", 0)
    run(room.start("trivia", 1, [], "family", now=0))
    room.back_to_lobby(1)
    run(room.start("emoji", 1, [], "family", now=2))
    room.submit(a.id, {"text": "x"}, now=3)
    run(room.tick(40))
    assert "question" not in room.view("host", 40)
