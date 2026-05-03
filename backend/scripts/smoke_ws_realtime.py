from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from websocket import WebSocketApp


BASE = "http://localhost:8000/api/v1"
WS_BASE = "ws://localhost:8000/api/v1"


@dataclass
class Session:
    user_id: int
    token: str


def _headers(token: str | None = None) -> dict:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _post(path: str, payload: dict, token: str | None = None) -> dict:
    r = requests.post(f"{BASE}{path}", json=payload, headers=_headers(token), timeout=15)
    r.raise_for_status()
    return r.json()


def _get(path: str, token: str) -> dict:
    r = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    r.raise_for_status()
    return r.json()


def login(email: str, password: str) -> Session:
    out = _post("/auth/login", {"email": email, "password": password})
    token = str(out.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("login: no access_token")
    me = _get("/auth/me", token)
    uid = int(me.get("user_id") or 0)
    if uid < 1:
        raise RuntimeError("login: invalid user_id")
    return Session(user_id=uid, token=token)


def ws_token(sess: Session) -> str:
    out = _post("/ws/token", {}, sess.token)
    tok = str(out.get("ws_token") or "").strip()
    if not tok:
        raise RuntimeError("ws_token: missing ws_token")
    return tok


def main() -> int:
    started_at = time.time()

    print("SMOKE: ws realtime")

    # 1) login A / B
    a = login("taras@example.com", "password123")
    b = login("olena@example.com", "password123")
    print(f"- login: OK (A={a.user_id}, B={b.user_id})")

    # 2) get ws_token for B
    tok = ws_token(b)

    # Build WS URL. Rules: no main access token, and fail if ?token= appears.
    qs = urlencode({"ws_token": tok})
    url = f"{WS_BASE}/ws/chat/{b.user_id}?{qs}"
    if "?token=" in url or "&token=" in url:
        raise RuntimeError("WS URL contains forbidden ?token= parameter")
    # Debug (no secrets)
    print(f"- ws connect: {WS_BASE}/ws/chat/{{user_id}}?ws_token=… (user_id={b.user_id})")

    # 3) connect B, wait for message
    received: dict | None = None
    ws_open = False
    ws_err: str | None = None

    def on_open(_ws):
        nonlocal ws_open
        ws_open = True

    def on_message(_ws, message: str):
        nonlocal received
        try:
            data = json.loads(message)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        if data.get("type") != "message":
            return
        received = data

    def on_error(_ws, error):
        nonlocal ws_err
        ws_err = str(error)

    def on_close(_ws, status_code, msg):
        # noop
        return

    app = WebSocketApp(url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)

    # Run WS in background thread
    import threading

    t = threading.Thread(target=lambda: app.run_forever(ping_interval=20, ping_timeout=10), daemon=True)
    t.start()

    # Wait for open
    for _ in range(40):
        if ws_open:
            break
        if ws_err:
            raise RuntimeError(f"WS error before open: {ws_err}")
        time.sleep(0.1)
    if not ws_open:
        raise RuntimeError("WS did not open in time")

    before = _get("/nav/badges", b.token)

    # 4) A sends message to B via REST
    sent = _post(
        "/messages/",
        {"receiver_id": b.user_id, "content": "smoke: ws realtime delivery", "conversation_context": []},
        a.token,
    )
    sent_id = int(sent.get("id") or 0)
    if sent_id < 1:
        raise RuntimeError("REST send: missing message id")
    print(f"- rest send: OK (message_id={sent_id})")

    # 5) Assert B receives WS event
    deadline = time.time() + 10.0
    while time.time() < deadline and received is None:
        if ws_err:
            raise RuntimeError(f"WS error: {ws_err}")
        time.sleep(0.05)
    if received is None:
        raise RuntimeError("WS: did not receive message event within timeout")

    if int(received.get("receiver_id") or 0) != b.user_id:
        raise RuntimeError("WS: receiver_id mismatch")
    if int(received.get("sender_id") or 0) != a.user_id:
        raise RuntimeError("WS: sender_id mismatch")
    if str(received.get("content") or "").strip() != "smoke: ws realtime delivery":
        raise RuntimeError("WS: content mismatch")
    print("- ws delivery: OK")

    # 6) Assert /nav/badges increments for B
    after_send = _get("/nav/badges", b.token)
    if int(after_send.get("unread_messages") or 0) <= int(before.get("unread_messages") or 0):
        raise RuntimeError("badges: expected unread_messages to increase")
    if int(after_send.get("chat_threads_unread") or 0) <= int(before.get("chat_threads_unread") or 0):
        raise RuntimeError("badges: expected chat_threads_unread to increase")
    print("- badges increment: OK")

    # 7) B opens thread, assert badge clears
    _get(f"/messages/{a.user_id}", b.token)
    after_open = _get("/nav/badges", b.token)
    if int(after_open.get("unread_messages") or 0) != 0:
        raise RuntimeError("badges: expected unread_messages == 0 after opening thread")
    print("- badges clear after open: OK")

    try:
        app.close()
    except Exception:
        pass

    elapsed_ms = int((time.time() - started_at) * 1000)
    print(f"PASS (elapsed_ms={elapsed_ms})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("FAIL:", e, file=sys.stderr)
        raise

