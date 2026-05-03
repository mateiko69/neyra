from __future__ import annotations

import hashlib
import hmac
import time


def verify_paddle_signature(*, secret: str, raw_body: bytes, paddle_signature_header: str | None, max_age_s: int = 900) -> bool:
    sec = str(secret or "").strip()
    if not sec:
        return False
    hdr = str(paddle_signature_header or "").strip()
    if not hdr:
        return False
    parsed: dict[str, str] = {}
    for part in hdr.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        parsed[k.strip()] = v.strip()
    ts = parsed.get("ts") or parsed.get("t")
    sig = parsed.get("h1") or parsed.get("sig")
    if not ts or not sig:
        return False
    try:
        ts_int = int(ts)
    except Exception:
        return False
    now = int(time.time())
    if abs(now - ts_int) > int(max_age_s):
        return False
    payload = ts.encode("utf-8") + b":" + raw_body
    computed = hmac.new(sec.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, sig)
