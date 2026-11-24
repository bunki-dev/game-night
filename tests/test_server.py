"""End-to-end over real WebSockets: a TV and two phones play a round. Needs fastapi + httpx."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from gamenight.app import app  # noqa: E402


def next_state(ws, predicate=lambda s: True, limit=30):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == "state" and predicate(msg["state"]):
            return msg["state"]
    raise AssertionError("expected state never arrived")


def test_full_trivia_round_over_websockets():
    with TestClient(app) as client:
        room = client.post("/api/rooms").json()
        code = room["code"]
        with client.websocket_connect(f"/ws/{code}") as tv:
            tv.send_json({"role": "host", "token": room["host_token"]})
            assert tv.receive_json()["type"] == "welcome"
            with client.websocket_connect(f"/ws/{code}") as p1, client.websocket_connect(f"/ws/{code}") as p2:
                p1.send_json({"role": "player", "name": "Ann"})
                me = p1.receive_json()
                assert me["type"] == "welcome" and me["token"]
                p2.send_json({"role": "player", "name": "Bo"})
                assert p2.receive_json()["type"] == "welcome"

                tv.send_json({"type": "start", "game": "trivia", "rounds": 1, "topics": ["space"]})
                state = next_state(tv, lambda s: s["phase"] == "question")
                assert "answer_index" not in state["question"]

                p1.send_json({"type": "answer", "choice": 0})
                p2.send_json({"type": "answer", "choice": 1})
                reveal = next_state(tv, lambda s: s["phase"] == "reveal")
                assert "answer_index" in reveal["question"]

                tv.send_json({"type": "next"})
                final = next_state(tv, lambda s: s["phase"] == "final")
                assert {p["name"] for p in final["players"]} == {"Ann", "Bo"}


def test_wrong_host_token_and_unknown_room_are_refused():
    with TestClient(app) as client:
        code = client.post("/api/rooms").json()["code"]
        with client.websocket_connect(f"/ws/{code}") as ws:
            ws.send_json({"role": "host", "token": "guess"})
            msg = ws.receive_json()
            assert msg["type"] == "error" and msg["fatal"]
        with client.websocket_connect("/ws/ZZZZ") as ws:
            assert ws.receive_json()["type"] == "error"


def test_players_cannot_drive_the_game():
    with TestClient(app) as client:
        code = client.post("/api/rooms").json()["code"]
        with client.websocket_connect(f"/ws/{code}") as p:
            p.send_json({"role": "player", "name": "Sneaky"})
            p.receive_json()
            p.send_json({"type": "start", "game": "trivia"})
            msgs = [p.receive_json() for _ in range(2)]
            assert any(m["type"] == "error" and "Only the TV" in m["message"] for m in msgs)
