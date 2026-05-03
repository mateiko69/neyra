from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.message import Message
from app.models.app_setting import AppSetting
from app.models.user_ai_memory import UserAiMemory


_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF]")
_LAUGH_RE = re.compile(r"\b(lol|lmao|haha|hehe)\b", re.IGNORECASE)


def _safe_bucket_len(n: int) -> str:
    if n < 70:
        return "short"
    if n < 140:
        return "medium"
    return "long"


def _tone(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return "serious"
    has_emoji = bool(_EMOJI_RE.search(s))
    exclam = s.count("!")
    laugh = bool(_LAUGH_RE.search(s)) or ("😂" in s) or ("🤣" in s)
    return "playful" if (has_emoji or exclam >= 2 or laugh) else "serious"


@dataclass(frozen=True)
class LearningStats:
    processed: int
    users_updated: int


def _upsert_memory(db: Session, *, user_id: int, memory_type: str, key: str, value_json: dict[str, Any], confidence: float, source: str) -> None:
    now = datetime.now(UTC)
    row = (
        db.query(UserAiMemory)
        .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == str(memory_type), UserAiMemory.key == str(key))
        .first()
    )
    if not row:
        row = UserAiMemory(
            user_id=int(user_id),
            memory_type=str(memory_type),
            key=str(key)[:64],
            value_json=value_json or {},
            confidence_score=max(0.0, min(1.0, float(confidence))),
            source=str(source or "learning")[:64],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.value_json = value_json or {}
        row.confidence_score = max(0.0, min(1.0, float(confidence)))
        row.source = str(source or row.source or "learning")[:64]
        row.updated_at = now


def run_message_learning_tick(db: Session, *, lookback_days: int = 14, max_users: int = 600) -> LearningStats:
    """
    Learn from user behavior without storing raw text:
    - reply vs ignored outcomes for outgoing messages
    - patterns: short/medium/long + playful/serious
    Writes compact aggregates into UserAiMemory(memory_type="conversation_patterns", key="message_outcomes").
    """
    since = datetime.now(UTC) - timedelta(days=int(lookback_days or 14))

    # Get recent senders (cheap, bounded).
    sender_rows = (
        db.query(Message.sender_id)
        .filter(Message.created_at >= since, Message.is_demo_simulation.is_(False))
        .group_by(Message.sender_id)
        .limit(int(max_users or 600))
        .all()
    )
    sender_ids = [int(r[0]) for r in sender_rows if r and r[0]]

    processed = 0
    users_updated = 0

    # Global aggregates across all processed users (for cold-start).
    global_totals = {"replied": 0, "ignored": 0}
    global_by_len: dict[str, dict[str, int]] = {k: {"replied": 0, "ignored": 0} for k in ("short", "medium", "long")}
    global_by_tone: dict[str, dict[str, int]] = {k: {"replied": 0, "ignored": 0} for k in ("playful", "serious")}

    for uid in sender_ids:
        # Sample recent outgoing messages. We process content ephemerally and store only aggregates.
        msgs = (
            db.query(Message)
            .filter(Message.sender_id == uid, Message.created_at >= since, Message.is_demo_simulation.is_(False))
            .order_by(Message.created_at.desc())
            .limit(220)
            .all()
        )
        if not msgs:
            continue

        # Counters
        totals = {"replied": 0, "ignored": 0}
        by_len: dict[str, dict[str, int]] = {k: {"replied": 0, "ignored": 0} for k in ("short", "medium", "long")}
        by_tone: dict[str, dict[str, int]] = {k: {"replied": 0, "ignored": 0} for k in ("playful", "serious")}

        for m in msgs:
            if not m.content or m.voice_url:
                # Skip voice-only learning for now.
                continue
            processed += 1
            length_bucket = _safe_bucket_len(len(m.content))
            tone = _tone(m.content)

            # A reply counts if receiver sends any message back within 24h after this message.
            horizon = (m.created_at or since) + timedelta(hours=24)
            replied = (
                db.query(Message.id)
                .filter(
                    Message.sender_id == int(m.receiver_id),
                    Message.receiver_id == int(m.sender_id),
                    Message.created_at > m.created_at,
                    Message.created_at <= horizon,
                    Message.is_demo_simulation.is_(False),
                )
                .first()
                is not None
            )
            key = "replied" if replied else "ignored"
            totals[key] += 1
            by_len[length_bucket][key] += 1
            by_tone[tone][key] += 1
            global_totals[key] += 1
            global_by_len[length_bucket][key] += 1
            global_by_tone[tone][key] += 1

        denom = max(1, totals["replied"] + totals["ignored"])
        reply_rate = float(totals["replied"]) / float(denom)

        def _rate(row: dict[str, int]) -> float:
            d = max(1, int(row.get("replied", 0)) + int(row.get("ignored", 0)))
            return float(row.get("replied", 0)) / float(d)

        best_len = max(by_len.keys(), key=lambda k: _rate(by_len[k]))
        best_tone = max(by_tone.keys(), key=lambda k: _rate(by_tone[k]))

        payload = {
            "window_days": int(lookback_days or 14),
            "total": totals,
            "reply_rate": round(reply_rate, 4),
            "by_length": {k: {**v, "reply_rate": round(_rate(v), 4)} for k, v in by_len.items()},
            "by_tone": {k: {**v, "reply_rate": round(_rate(v), 4)} for k, v in by_tone.items()},
            "preferred_length": best_len,
            "preferred_tone": best_tone,
            "updated_at": datetime.now(UTC).isoformat(),
        }

        # Confidence increases with more samples; capped.
        conf = min(0.9, 0.45 + 0.45 * min(1.0, denom / 60.0))
        _upsert_memory(
            db,
            user_id=int(uid),
            memory_type="conversation_patterns",
            key="message_outcomes",
            value_json=payload,
            confidence=conf,
            source="learning:message_outcomes",
        )
        users_updated += 1

    # Store global baseline as well (AppSetting; not per-user).
    g_denom = max(1, global_totals["replied"] + global_totals["ignored"])
    g_reply_rate = float(global_totals["replied"]) / float(g_denom)

    def _g_rate(row: dict[str, int]) -> float:
        d = max(1, int(row.get("replied", 0)) + int(row.get("ignored", 0)))
        return float(row.get("replied", 0)) / float(d)

    g_best_len = max(global_by_len.keys(), key=lambda k: _g_rate(global_by_len[k]))
    g_best_tone = max(global_by_tone.keys(), key=lambda k: _g_rate(global_by_tone[k]))
    g_payload = {
        "window_days": int(lookback_days or 14),
        "total": global_totals,
        "reply_rate": round(g_reply_rate, 4),
        "by_length": {k: {**v, "reply_rate": round(_g_rate(v), 4)} for k, v in global_by_len.items()},
        "by_tone": {k: {**v, "reply_rate": round(_g_rate(v), 4)} for k, v in global_by_tone.items()},
        "preferred_length": g_best_len,
        "preferred_tone": g_best_tone,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    key = "learning:message_outcomes_global"
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row:
        row = AppSetting(key=key, value_json=json.dumps(g_payload, ensure_ascii=False))
        db.add(row)
    else:
        row.value_json = json.dumps(g_payload, ensure_ascii=False)

    db.commit()
    return LearningStats(processed=int(processed), users_updated=int(users_updated))

