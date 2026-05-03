from __future__ import annotations

import sys
from dataclasses import dataclass

import requests


BASE = "http://localhost:8000/api/v1"


@dataclass
class Session:
    user_id: int
    token: str


def _post(path: str, json: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(f"{BASE}{path}", json=json, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()


def _get(path: str, token: str) -> dict:
    r = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    return r.json()


def login(email: str, password: str) -> Session:
    token_out = _post("/auth/login", {"email": email, "password": password})
    token = str(token_out.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("login: no access_token returned")
    me = _get("/auth/me", token)
    uid = int(me.get("user_id") or 0)
    if uid < 1:
        raise RuntimeError("login: invalid user_id from /auth/me")
    return Session(user_id=uid, token=token)


def main() -> int:
    # Use seeded matched users.
    a = login("taras@example.com", "password123")
    b = login("anna@example.com", "password123")

    before = _get("/nav/badges", b.token)
    print("B badges before:", before)

    msg = _post(
        "/messages/",
        {"receiver_id": b.user_id, "content": "smoke: unread badge check", "conversation_context": []},
        a.token,
    )
    print("A -> B sent message id:", msg.get("id"))

    after_send = _get("/nav/badges", b.token)
    print("B badges after send:", after_send)
    if int(after_send.get("unread_messages") or 0) <= int(before.get("unread_messages") or 0):
        raise RuntimeError("Expected B unread_messages to increase after receiving message")

    # Opening thread should mark read (GET /messages/{partnerId} touches ThreadReadState).
    _get(f"/messages/{a.user_id}", b.token)
    after_open = _get("/nav/badges", b.token)
    print("B badges after open thread:", after_open)
    if int(after_open.get("unread_messages") or 0) != 0:
        raise RuntimeError("Expected B unread_messages == 0 after opening thread")

    print("OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("FAIL:", e, file=sys.stderr)
        raise

