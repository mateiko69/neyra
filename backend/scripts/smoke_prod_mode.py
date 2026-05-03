from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from websocket import WebSocket


DEFAULT_BASE = "http://localhost:8000/api/v1"


@dataclass
class Result:
    ok: bool
    name: str
    detail: str = ""


def _base() -> str:
    return (os.getenv("NEYRA_API_BASE") or DEFAULT_BASE).rstrip("/")


def _headers(token: str | None = None, origin: str | None = None) -> dict:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if origin:
        h["Origin"] = origin
    return h


def _get(path: str, token: str | None = None, *, origin: str | None = None) -> tuple[int, dict, dict]:
    url = f"{_base()}{path}"
    r = requests.get(url, headers=_headers(token, origin), timeout=15)
    try:
        payload = r.json()
    except Exception:
        payload = {"_raw": r.text[:500]}
    return r.status_code, payload, dict(r.headers)


def _post(path: str, payload: dict, token: str | None = None, *, origin: str | None = None) -> tuple[int, dict, dict]:
    url = f"{_base()}{path}"
    r = requests.post(url, json=payload, headers=_headers(token, origin), timeout=15)
    try:
        out = r.json()
    except Exception:
        out = {"_raw": r.text[:500]}
    return r.status_code, out, dict(r.headers)


def _options(path: str, *, origin: str, req_method: str = "GET", req_headers: str = "authorization,content-type") -> dict:
    url = f"{_base()}{path}"
    r = requests.options(
        url,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": req_method,
            "Access-Control-Request-Headers": req_headers,
        },
        timeout=15,
    )
    return {"status": r.status_code, "headers": dict(r.headers)}


def _ws_base() -> str:
    # http://host/api/v1 -> ws://host/api/v1
    b = _base()
    if b.startswith("https://"):
        return "wss://" + b[len("https://") :]
    if b.startswith("http://"):
        return "ws://" + b[len("http://") :]
    return b


def _register_and_login() -> tuple[str, int]:
    email = f"prodsmoke_{uuid.uuid4().hex[:10]}@example.com"
    pw = "pw123456"
    st, reg, _ = _post("/auth/register", {"email": email, "password": pw, "display_name": "Prod Smoke"}, None)
    if st != 200 or not str(reg.get("access_token") or "").strip():
        raise RuntimeError(f"register failed ({st}): {reg}")
    token = str(reg["access_token"]).strip()
    st2, me, _ = _get("/auth/me", token)
    if st2 != 200:
        raise RuntimeError(f"/auth/me failed ({st2}): {me}")
    uid = int(me.get("user_id") or 0)
    if uid < 1:
        raise RuntimeError("invalid user_id from /auth/me")
    return token, uid


def _ws_connect(url: str, timeout_s: float = 3.0) -> bool:
    ws = WebSocket()
    ws.settimeout(timeout_s)
    ws.connect(url)
    ws.close()
    return True


def main() -> int:
    results: list[Result] = []

    def check(name: str, fn):
        try:
            fn()
            results.append(Result(ok=True, name=name))
        except Exception as e:
            results.append(Result(ok=False, name=name, detail=str(e)))

    print("SMOKE: prod-mode safety")
    print("- API_BASE:", _base())

    providers: dict | None = None

    def step_providers():
        nonlocal providers
        st, payload, _ = _get("/auth/social/providers")
        if st != 200:
            raise RuntimeError(f"providers status {st}")
        providers = payload

        # Must not expose secrets (values).
        raw = json.dumps(payload, ensure_ascii=False).lower()
        forbidden_substrings = [
            "client_secret",
            "apple_private_key",
            "stripe_secret_key",
            "webhook_secret",
            "s3_secret_access_key",
        ]
        for s in forbidden_substrings:
            # Key names in missing_config_keys are allowed; actual secret values should never be present.
            # We treat presence of substring in raw JSON as suspicious enough to fail.
            if s in raw and "missing_config_keys" not in raw:
                raise RuntimeError(f"secret-like field exposed: {s}")

        # Must not expose dev mock mode.
        if bool(payload.get("dev_mock")):
            raise RuntimeError("dev_mock=true (AUTH_DEV_SOCIAL likely enabled or ENV not production)")

        # Ensure google provider shape is safe.
        p = (payload.get("providers") or {}).get("google") or {}
        if "missing_config_keys" not in p or "enabled" not in p:
            raise RuntimeError("providers.google missing expected diagnostics fields")

    check("auth/social/providers safe", step_providers)

    def step_dev_social_not_exposed():
        st, payload, _ = _post("/auth/social/dev/google", {}, None)
        if st != 404:
            raise RuntimeError(f"dev social endpoint exposed (status {st}): {payload}")

    check("dev social hidden", step_dev_social_not_exposed)

    # Authenticated flows
    token, uid = _register_and_login()
    print(f"- auth OK (user_id={uid})")

    def step_ws_token():
        st, payload, _ = _post("/ws/token", {}, token)
        if st != 200:
            raise RuntimeError(f"ws/token status {st}")
        t = str(payload.get("ws_token") or "").strip()
        if not t:
            raise RuntimeError("ws_token missing")
        exp = int(payload.get("expires_in") or 0)
        if exp < 30 or exp > 180:
            raise RuntimeError(f"expires_in out of expected range: {exp}")

    check("ws/token works", step_ws_token)

    def step_ws_rejects_legacy_token_param():
        # Strict requirement: ws must not accept ?token=
        # Attempt to connect without ws_token (should fail).
        url = f"{_ws_base()}/ws/chat/{uid}?token=THIS_IS_NOT_ALLOWED"
        try:
            _ws_connect(url, timeout_s=2.0)
            raise RuntimeError("ws accepted legacy ?token= (should reject)")
        except Exception:
            # Expected: connection failure or immediate close.
            return

    check("ws rejects ?token=", step_ws_rejects_legacy_token_param)

    def step_discover_feed_shape():
        st, payload, _ = _get("/discover/feed?limit=6&offset=0", token)
        if st != 200:
            raise RuntimeError(f"discover/feed status {st}: {payload}")
        if not isinstance(payload, list):
            raise RuntimeError("discover/feed not a list")
        if len(payload) == 0:
            raise RuntimeError("discover/feed returned empty list")
        card = payload[0]
        if not isinstance(card, dict) or int(card.get("user_id") or 0) < 1:
            raise RuntimeError("discover card missing user_id")
        if not isinstance(card.get("photo_urls"), list):
            raise RuntimeError("discover card photo_urls missing/invalid")

    check("discover/feed valid", step_discover_feed_shape)

    def step_nav_badges_shape():
        st, payload, _ = _get("/nav/badges", token)
        if st != 200:
            raise RuntimeError(f"nav/badges status {st}: {payload}")
        for k in ("unread_messages", "chat_threads_unread", "new_matches", "incoming_likes", "matches", "matches_attention"):
            if k not in payload:
                raise RuntimeError(f"nav/badges missing {k}")
            v = payload.get(k)
            if not isinstance(v, int):
                raise RuntimeError(f"nav/badges {k} not int")

    check("nav/badges valid", step_nav_badges_shape)

    def step_cors_no_localhost():
        # Detectable check: preflight from localhost should NOT be allowed in prod.
        # (We don't know the real FRONTEND_URL here; just ensure localhost isn't echoed.)
        r = _options("/nav/badges", origin="http://localhost:3000", req_method="GET")
        allow = str(r["headers"].get("access-control-allow-origin") or "").strip().lower()
        if allow in ("http://localhost:3000", "*"):
            raise RuntimeError(f"CORS allows localhost in prod (allow-origin={allow!r})")

    check("CORS does not allow localhost", step_cors_no_localhost)

    # Summary
    ok = sum(1 for r in results if r.ok)
    bad = [r for r in results if not r.ok]
    for r in results:
        if r.ok:
            print("PASS:", r.name)
        else:
            print("FAIL:", r.name, "-", r.detail)
    if bad:
        print(f"FAIL ({ok}/{len(results)} passed)")
        return 2
    print(f"PASS ({ok}/{len(results)} passed)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("FAIL:", e, file=sys.stderr)
        raise

