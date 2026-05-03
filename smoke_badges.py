import json
import sys
import requests


BASE = "http://localhost:8000/api/v1"


def login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=10)
    if not r.ok:
        print("login failed", r.status_code, r.text)
    r.raise_for_status()
    return r.json()["access_token"]


def get(path: str, token: str):
    r = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    return r.json()


def post_json(path: str, token: str, payload: dict):
    r = requests.post(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=10,
    )
    return r


def main() -> int:
    a = login("taras@example.com")
    b = login("olena@example.com")
    me_a = get("/auth/me", a)
    me_b = get("/auth/me", b)

    print("B badges before:", get("/nav/badges", b))

    r = post_json("/messages/", a, {"receiver_id": me_b["user_id"], "content": "ping from A", "conversation_context": []})
    print("send status:", r.status_code)
    if not r.ok:
        print("send body:", r.text)
        return 2

    print("B badges after send:", get("/nav/badges", b))
    print("B conversations head:", get("/messages/conversations", b)[:1])

    t = requests.get(f"{BASE}/messages/{me_a['user_id']}", headers={"Authorization": f"Bearer {b}"}, timeout=10)
    print("open thread:", t.status_code, "messages:", len(t.json()) if t.ok else None)
    print("B badges after open:", get("/nav/badges", b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

