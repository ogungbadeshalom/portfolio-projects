"""End-to-end tests for the real-time chat app.

Exercises the real behaviour using the FastAPI TestClient:
register/login, rooms, and the live WebSocket protocol (presence, typing,
broadcast, persistence, ratelimiting, sanitization, auth rejection).
"""
from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from chat import auth
from conftest import register, connect_ws


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def test_register_returns_real_jwt(app_client):
    client = app_client
    data = register(client, "carol", "hunter2")
    # The token must round-trip through the real decoder.
    payload = auth.decode_access_token(data["access_token"])
    assert payload is not None
    user_id, username = payload
    assert username == "carol"
    assert isinstance(user_id, int)


def test_register_duplicate_returns_409(app_client):
    client = app_client
    register(client, "carol", "hunter2")
    res = client.post(
        "/api/auth/register", json={"username": "carol", "password": "other"}
    )
    assert res.status_code == 409


def test_login_success(app_client):
    client = app_client
    register(client, "dave", "strong-pw")
    res = client.post(
        "/api/auth/login", json={"username": "dave", "password": "strong-pw"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "dave"
    payload = auth.decode_access_token(data["access_token"])
    assert payload is not None and payload[1] == "dave"


def test_login_bad_password_returns_401(app_client):
    client = app_client
    register(client, "dave", "strong-pw")
    res = client.post(
        "/api/auth/login", json={"username": "dave", "password": "wrong"}
    )
    assert res.status_code == 401


# --------------------------------------------------------------------------- #
# Rooms
# --------------------------------------------------------------------------- #
def test_create_and_list_rooms(app_client):
    client = app_client
    bearer = {"Authorization": f"Bearer {register(client, 'erin', 'pw')['access_token']}"}
    created = client.post("/api/rooms", json={"name": "pets"}, headers=bearer)
    assert created.status_code == 201
    room = created.json()
    assert room["name"] == "pets"
    assert room["id"] > 0

    rooms = client.get("/api/rooms", headers=bearer).json()
    assert any(r["name"] == "pets" for r in rooms)


def test_rooms_require_auth(app_client):
    client = app_client
    assert client.get("/api/rooms").status_code == 401
    assert client.post("/api/rooms", json={"name": "x"}).status_code == 401


def test_duplicate_room_returns_409(app_client):
    client = app_client
    bearer = {"Authorization": f"Bearer {register(client, 'erin', 'pw')['access_token']}"}
    assert client.post("/api/rooms", json={"name": "pets"}, headers=bearer).status_code == 201
    res = client.post("/api/rooms", json={"name": "pets"}, headers=bearer)
    assert res.status_code == 409


# --------------------------------------------------------------------------- #
# WebSocket: broadcast
# --------------------------------------------------------------------------- #
def test_message_broadcast_to_other_client(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        assert ws_a.receive_json()["type"] == "presence"
        with connect_ws(client, rid, b["access_token"]) as ws_b:
            # ws_b gets its presence; ws_a sees the join + updated presence.
            assert ws_b.receive_json()["type"] == "presence"
            assert ws_a.receive_json()["type"] == "join"
            assert ws_a.receive_json()["type"] == "presence"

            ws_a.send_json({"type": "message", "text": "hello world"})
            # ws_b must receive the broadcast.
            msg = ws_b.receive_json()
            assert msg["type"] == "message"
            assert msg["text"] == "hello world"
            assert msg["user"] == "alice"


def test_presence_and_join_leave_announcements(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        first = ws_a.receive_json()
        assert first["type"] == "presence"
        assert first["online"] == ["alice"]

        with connect_ws(client, rid, b["access_token"]) as ws_b:
            assert ws_b.receive_json()["type"] == "presence"
            assert ws_a.receive_json()["type"] == "join"
            assert ws_a.receive_json() == {"type": "presence", "online": ["alice", "bob"]}
        # After ws_b exits, ws_a is told about the leave + updated presence.
        assert ws_a.receive_json()["type"] == "leave"
        assert ws_a.receive_json()["type"] == "presence"


def test_typing_not_echoed_to_sender(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        assert ws_a.receive_json()["type"] == "presence"
        with connect_ws(client, rid, b["access_token"]) as ws_b:
            assert ws_b.receive_json()["type"] == "presence"
            assert ws_a.receive_json()["type"] == "join"
            assert ws_a.receive_json()["type"] == "presence"

            ws_a.send_json({"type": "typing"})
            # ws_b sees the typing event.
            assert ws_b.receive_json() == {"type": "typing", "user": "alice"}

            # Send a message from ws_a; the next thing ws_a receives must be its
            # own message broadcast (NOT a typing echo), proving typing is
            # excluded from the sender.
            ws_a.send_json({"type": "message", "text": "marker"})
            assert ws_b.receive_json()["text"] == "marker"
            assert ws_a.receive_json()["text"] == "marker"


def test_message_history_persisted(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        assert ws_a.receive_json()["type"] == "presence"
        ws_a.send_json({"type": "message", "text": "persist me"})
        assert ws_a.receive_json()["text"] == "persist me"

    # Reconnect; history via REST endpoint reflects the message, oldest-first.
    history = client.get(
        f"/api/rooms/{rid}/messages",
        headers={"Authorization": f"Bearer {a['access_token']}"},
    ).json()
    assert len(history) == 1
    assert history[0]["text"] == "persist me"
    assert history[0]["username"] == "alice"


def test_message_history_oldest_first(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        assert ws_a.receive_json()["type"] == "presence"
        for i in range(5):
            ws_a.send_json({"type": "message", "text": f"msg {i}"})
            assert ws_a.receive_json()["text"] == f"msg {i}"
    history = client.get(
        f"/api/rooms/{rid}/messages",
        headers={"Authorization": f"Bearer {a['access_token']}"},
    ).json()
    texts = [m["text"] for m in history]
    assert texts == [f"msg {i}" for i in range(5)]


# --------------------------------------------------------------------------- #
# WebSocket: validation / rate limiting / sanitization
# --------------------------------------------------------------------------- #
def test_rate_limit_rejects_11th_message(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        assert ws_a.receive_json()["type"] == "presence"
        # 10 allowed messages each produce a broadcast echo to the sender.
        for i in range(10):
            ws_a.send_json({"type": "message", "text": f"ok {i}"})
            assert ws_a.receive_json()["type"] == "message"
        # The 11th must be rejected with an error to the sender.
        ws_a.send_json({"type": "message", "text": "too fast"})
        err = ws_a.receive_json()
        assert err["type"] == "error"
        assert "rate limit" in err["message"].lower()


def test_overlong_message_rejected(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        assert ws_a.receive_json()["type"] == "presence"
        long_text = "x" * 1001
        ws_a.send_json({"type": "message", "text": long_text})
        err = ws_a.receive_json()
        assert err["type"] == "error"
        assert "1000" in err["message"]


def test_html_is_sanitized(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        assert ws_a.receive_json()["type"] == "presence"
        with connect_ws(client, rid, b["access_token"]) as ws_b:
            assert ws_b.receive_json()["type"] == "presence"
            assert ws_a.receive_json()["type"] == "join"
            assert ws_a.receive_json()["type"] == "presence"

            ws_a.send_json({"type": "message", "text": "<script>alert(1)</script>"})
            received = ws_b.receive_json()
            assert received["type"] == "message"
            assert "<" not in received["text"]
            assert received["text"] == "alert(1)"


def test_malformed_json_sends_error(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        assert ws_a.receive_json()["type"] == "presence"
        ws_a.send_text("this is not json")
        assert ws_a.receive_json()["type"] == "error"


def test_unknown_message_type_sends_error(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with connect_ws(client, rid, a["access_token"]) as ws_a:
        assert ws_a.receive_json()["type"] == "presence"
        ws_a.send_json({"type": "bogus"})
        assert ws_a.receive_json()["type"] == "error"


# --------------------------------------------------------------------------- #
# WebSocket: authentication rejection
# --------------------------------------------------------------------------- #
def test_websocket_rejects_missing_token(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/rooms/{rid}") as ws:
            ws.receive_json()


def test_websocket_rejects_bad_token(two_users):
    client, a, b, room = two_users
    rid = room["id"]
    with pytest.raises(Exception):
        with connect_ws(client, rid, "garbage-token") as ws:
            ws.receive_json()