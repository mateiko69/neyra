"""Server-side helpers for AI product analytics (suggestion waves, Redis-backed)."""

from __future__ import annotations

import json
from typing import Any

from app.services.ai.cache import get_redis

_AI_WAVE_KEY = "ai:wave:{sender_id}:{partner_id}"
_WAVE_TTL_S = 172800  # 48h — correlate suggestion panel → next user message


def mark_ai_suggestion_wave(sender_id: int, partner_id: int, payload: dict[str, Any]) -> None:
    """Remember last chat-brain surface so the next outbound message can emit user_replied_after_ai."""
    try:
        r = get_redis()
        key = _AI_WAVE_KEY.format(sender_id=int(sender_id), partner_id=int(partner_id))
        r.set(key, json.dumps(payload, default=str), ex=_WAVE_TTL_S)
    except Exception:
        pass


def pop_ai_suggestion_wave(sender_id: int, partner_id: int) -> dict[str, Any] | None:
    """Return pending wave context once, then clear (one reply event per suggestion wave)."""
    try:
        r = get_redis()
        key = _AI_WAVE_KEY.format(sender_id=int(sender_id), partner_id=int(partner_id))
        raw = r.get(key)
        if not raw:
            return None
        r.delete(key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(str(raw))
        return data if isinstance(data, dict) else None
    except Exception:
        return None
