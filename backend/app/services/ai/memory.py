from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.ai_interaction_event import AiInteractionEvent
from app.models.user_ai_memory import UserAiMemory
from app.models.user_ai_profile import UserAiProfile
from app.services.ai.chat_brain_style_profile import apply_chat_brain_style_event, sync_partner_replied_to_style


_ALLOWED_MEMORY_TYPES = {
    "user_style",
    "dating_preferences",
    "conversation_patterns",
    "successful_openers",
    "avoided_topics",
    "partner_notes",
    "personalization",
}

_ALLOWED_EVENT_TYPES = {
    "option_shown",
    "option_selected",
    "option_edited",
    "edited",
    "message_sent",
    "partner_replied",
    "meeting_suggested",
    "meeting_accepted",
    "meeting_rejected",
    # Chat Brain — metadata must be aggregate-only (variant, lengths, flags); no message text.
    "cb_select",
    "cb_send",
    "cb_reply",
    "cb_copy",
    "cb_regen",
    "cb_edit",
}

# Public alias for API validation (same keys as `_ALLOWED_EVENT_TYPES`).
ALLOWED_AI_MEMORY_EVENT_TYPES = frozenset(_ALLOWED_EVENT_TYPES)

CHAT_BRAIN_EVENT_TYPES = frozenset({"cb_select", "cb_send", "cb_reply", "cb_copy", "cb_regen", "cb_edit"})

# Privacy: strip keys that look like raw text / sensitive details.
_BANNED_KEYS = {"raw_text", "full_text", "message", "messages", "chat", "content", "bio", "phone", "email"}
_SENSITIVE_PAT = re.compile(r"\b(sex|nude|hookup|religion|politic|health)\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+|00)\d{8,}|\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4,}\b")

PERSONALIZATION_MEMORY_TYPE = "personalization"
PERSONALIZATION_SUMMARY_KEY = "summary"
PERSONALIZATION_MAX_BYTES = 1024


def _safe_json(obj: Any, *, max_bytes: int = 4000) -> dict:
    """Keep only JSON-serializable dict with safe keys/values, size-bounded."""
    if not isinstance(obj, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in obj.items():
        key = str(k or "").strip()
        if not key or key.lower() in _BANNED_KEYS:
            continue
        if _SENSITIVE_PAT.search(key):
            continue
        # allow only primitive / small lists / dicts
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[key] = v
        elif isinstance(v, list):
            safe_list: list[Any] = []
            for it in v[:20]:
                if isinstance(it, (str, int, float, bool)) or it is None:
                    safe_list.append(it)
            out[key] = safe_list
        elif isinstance(v, dict):
            out[key] = _safe_json(v, max_bytes=max_bytes)
        # else: drop
    # bound size
    try:
        b = json.dumps(out, ensure_ascii=False).encode("utf-8")
        if len(b) <= max_bytes:
            return out
        # shrink by dropping largest keys
        for kk in list(out.keys())[::-1]:
            out.pop(kk, None)
            b2 = json.dumps(out, ensure_ascii=False).encode("utf-8")
            if len(b2) <= max_bytes:
                break
    except Exception:
        return {}
    return out


def _strip_pii_scalar(s: str, max_len: int = 80) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = _EMAIL_RE.sub("", s)
    s = _PHONE_RE.sub("", s)
    s = re.sub(r"\d{10,}", "", s)
    s = " ".join(s.split())
    return s[:max_len]


def _merge_unique_short_strings(cur: list[Any], incoming: list[Any], *, max_items: int, max_each: int) -> list[str]:
    seen = {str(x).strip().lower() for x in cur if x is not None and str(x).strip()}
    out: list[str] = [str(x).strip() for x in cur if x is not None and str(x).strip()][:max_items]
    for it in incoming:
        s = _strip_pii_scalar(str(it), max_each)
        if len(s) < 2:
            continue
        sl = s.lower()
        if sl in seen:
            continue
        seen.add(sl)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _default_personalization_summary() -> dict[str, Any]:
    return {
        "tone_preference": "playful",
        "interests": [],
        "avoid": [],
        "flirt_level": 0.35,
        "languages": [],
        "notes": [],
    }


def _cap_personalization_dict(cur: dict[str, Any]) -> dict[str, Any]:
    out = dict(cur)
    tp = str(out.get("tone_preference") or "playful").strip().lower()
    if tp not in {"playful", "direct", "deep"}:
        tp = "playful"
    out["tone_preference"] = tp
    try:
        fl = float(out.get("flirt_level"))
    except (TypeError, ValueError):
        fl = 0.35
    out["flirt_level"] = max(0.0, min(1.0, fl))
    for k in ("interests", "avoid", "languages", "notes"):
        lst = out.get(k)
        if not isinstance(lst, list):
            out[k] = []
            continue
        out[k] = [_strip_pii_scalar(str(x), 48) for x in lst if x is not None and str(x).strip()]
        out[k] = [x for x in out[k] if len(x) >= 2][:20]
    for _ in range(80):
        try:
            raw = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except Exception:
            return _default_personalization_summary()
        if len(raw) <= PERSONALIZATION_MAX_BYTES:
            return out
        if out.get("notes"):
            out["notes"] = out["notes"][:-1]
            continue
        if out.get("avoid"):
            out["avoid"] = out["avoid"][:-1]
            continue
        if out.get("interests"):
            out["interests"] = out["interests"][:-1]
            continue
        if out.get("languages"):
            out["languages"] = out["languages"][:-1]
            continue
        out = _default_personalization_summary()
        break
    return out


def _variant_to_tone(variant: Any) -> tuple[str | None, bool]:
    """Map UI style keys to personalization tone; second flag = bump flirt_level."""
    v = str(variant or "").strip().lower()
    if v == "light":
        return "playful", False
    if v == "flirty":
        return "playful", True
    if v == "deep":
        return "deep", False
    if v == "direct":
        return "direct", False
    if v == "curious":
        return "playful", False
    return None, False


def merge_personalization_summary(db: Session, *, user_id: int, event_type: str, meta: dict[str, Any]) -> None:
    """Merge privacy-safe aggregates into a single ≤1KB JSON profile (no chat bodies)."""
    et = str(event_type or "").strip()
    if et not in _ALLOWED_EVENT_TYPES or et == "option_shown":
        return
    row = (
        db.query(UserAiMemory)
        .filter(
            UserAiMemory.user_id == int(user_id),
            UserAiMemory.memory_type == PERSONALIZATION_MEMORY_TYPE,
            UserAiMemory.key == PERSONALIZATION_SUMMARY_KEY,
        )
        .first()
    )
    cur: dict[str, Any]
    if row and isinstance(row.value_json, dict):
        cur = {**_default_personalization_summary(), **row.value_json}
    else:
        cur = _default_personalization_summary()

    tp = meta.get("tone_preference")
    if isinstance(tp, str) and tp.strip().lower() in {"playful", "direct", "deep"}:
        cur["tone_preference"] = tp.strip().lower()
    if isinstance(meta.get("interests"), list):
        cur["interests"] = _merge_unique_short_strings(cur.get("interests") or [], meta["interests"], max_items=12, max_each=40)
    if isinstance(meta.get("avoid"), list):
        cur["avoid"] = _merge_unique_short_strings(cur.get("avoid") or [], meta["avoid"], max_items=8, max_each=40)
    if isinstance(meta.get("languages"), list):
        cur["languages"] = _merge_unique_short_strings(cur.get("languages") or [], meta["languages"], max_items=6, max_each=8)
    if isinstance(meta.get("notes"), list):
        cur["notes"] = _merge_unique_short_strings(cur.get("notes") or [], meta["notes"], max_items=8, max_each=72)
    if isinstance(meta.get("flirt_level"), (int, float)):
        cur["flirt_level"] = max(0.0, min(1.0, float(meta["flirt_level"])))
    for hint_key in ("memory_hint", "profile_hint"):
        mh = meta.get(hint_key)
        if isinstance(mh, str) and mh.strip():
            note = _strip_pii_scalar(mh, 72)
            if note:
                cur["notes"] = _merge_unique_short_strings(cur.get("notes") or [], [note], max_items=8, max_each=72)

    v, bump_flirt = _variant_to_tone(meta.get("variant") or meta.get("style") or meta.get("selected_style"))
    if et == "partner_replied":
        v2, bump2 = _variant_to_tone(meta.get("previous_style") or meta.get("previous_variant") or meta.get("variant"))
        if v2:
            cur["tone_preference"] = v2
            if bump2:
                cur["flirt_level"] = min(1.0, float(cur.get("flirt_level") or 0.35) + 0.02)
    elif et in ("option_selected", "message_sent", "cb_select", "cb_send", "cb_copy"):
        if v:
            cur["tone_preference"] = v
            if bump_flirt:
                cur["flirt_level"] = min(1.0, float(cur.get("flirt_level") or 0.35) + 0.04)
    if et in ("option_edited", "edited", "cb_edit"):
        cur["notes"] = _merge_unique_short_strings(cur.get("notes") or [], ["tweaks_suggestions"], max_items=8, max_each=48)
    if et == "cb_regen":
        cur["notes"] = _merge_unique_short_strings(cur.get("notes") or [], ["likes_new_variants"], max_items=8, max_each=48)
    if et == "message_sent" and meta.get("has_emoji"):
        cur["flirt_level"] = min(1.0, float(cur.get("flirt_level") or 0.35) + 0.02)

    cur = _cap_personalization_dict(cur)
    _upsert_memory(
        db,
        user_id=int(user_id),
        memory_type=PERSONALIZATION_MEMORY_TYPE,
        key=PERSONALIZATION_SUMMARY_KEY,
        value_json=cur,
        confidence_score=0.72,
        source="event_learning",
    )


def get_personalization_context(db: Session, *, user_id: int) -> dict[str, Any]:
    row = (
        db.query(UserAiMemory)
        .filter(
            UserAiMemory.user_id == int(user_id),
            UserAiMemory.memory_type == PERSONALIZATION_MEMORY_TYPE,
            UserAiMemory.key == PERSONALIZATION_SUMMARY_KEY,
        )
        .first()
    )
    if not row:
        return {"summary_json": _default_personalization_summary(), "updated_at": None}
    summary = row.value_json if isinstance(row.value_json, dict) else _default_personalization_summary()
    updated = row.updated_at.isoformat() if getattr(row, "updated_at", None) else None
    return {"summary_json": _cap_personalization_dict(dict(summary)), "updated_at": updated}


def personalization_prompt_suffix(db: Session, *, user_id: int) -> str:
    row = (
        db.query(UserAiMemory)
        .filter(
            UserAiMemory.user_id == int(user_id),
            UserAiMemory.memory_type == PERSONALIZATION_MEMORY_TYPE,
            UserAiMemory.key == PERSONALIZATION_SUMMARY_KEY,
        )
        .first()
    )
    if not row or not isinstance(row.value_json, dict):
        return ""
    blob = _cap_personalization_dict(dict(row.value_json))
    try:
        line = json.dumps(blob, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return ""
    if len(line) > 900:
        line = line[:897] + "…"
    return f"\nUSER_PERSONALIZATION_MEMORY (aggregate profile, no raw chat stored): {line}\n"


def log_ai_event(
    db: Session,
    *,
    user_id: int,
    partner_user_id: int | None,
    event_type: str,
    metadata: dict | None = None,
    thread_id: str | None = None,
) -> None:
    et = str(event_type or "").strip()
    if et not in _ALLOWED_EVENT_TYPES:
        return
    safe_meta = _safe_json(metadata or {})
    tid = str(thread_id or "").strip()[:64] or None
    row = AiInteractionEvent(
        user_id=int(user_id),
        partner_user_id=int(partner_user_id) if partner_user_id is not None else None,
        thread_id=tid,
        event_type=et,
        metadata_json=safe_meta,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    # Lightweight learning updates (no raw text).
    try:
        _apply_event_learning(db, user_id=int(user_id), partner_user_id=int(partner_user_id) if partner_user_id is not None else None, event_type=et, meta=safe_meta)
    except Exception:
        pass
    try:
        merge_personalization_summary(db, user_id=int(user_id), event_type=et, meta=safe_meta)
    except Exception:
        pass
    try:
        if et in CHAT_BRAIN_EVENT_TYPES and et != "cb_reply":
            apply_chat_brain_style_event(db, user_id=int(user_id), event_type=et, meta=safe_meta)
        elif et in CHAT_BRAIN_EVENT_TYPES and et == "cb_reply":
            # Logged for admin aggregates only; learning uses partner_replied + sync.
            pass
    except Exception:
        pass
    db.commit()


def _apply_event_learning(db: Session, *, user_id: int, partner_user_id: int | None, event_type: str, meta: dict) -> None:
    # Update a few compact memories as requested.
    if event_type == "option_selected":
        style = str(meta.get("style") or "").strip().lower()
        if style in {"light", "flirty", "deep"}:
            # bump preferred_tone
            row = db.query(UserAiMemory).filter(UserAiMemory.user_id == user_id, UserAiMemory.memory_type == "user_style", UserAiMemory.key == "global").first()
            current = (row.value_json or {}) if row else {}
            current["preferred_tone"] = style
            conf = float(row.confidence_score or 0.55) if row else 0.55
            conf = min(1.0, conf + 0.05)
            _upsert_memory(db, user_id=user_id, memory_type="user_style", key="global", value_json=current, confidence_score=conf, source="event:option_selected")

    if event_type in ("option_edited", "edited"):
        lvl = str(meta.get("edit_distance_level") or "").strip().lower()
        if lvl == "high":
            row = db.query(UserAiMemory).filter(UserAiMemory.user_id == user_id, UserAiMemory.memory_type == "user_style", UserAiMemory.key == "global").first()
            current = (row.value_json or {}) if row else {}
            conf = float(row.confidence_score or 0.55) if row else 0.55
            conf = max(0.0, conf - 0.08)
            _upsert_memory(db, user_id=user_id, memory_type="user_style", key="global", value_json=current, confidence_score=conf, source="event:option_edited")

    if event_type == "message_sent":
        # update style + emoji + length bucket (behavior-only)
        style = str(meta.get("selected_style") or "").strip().lower()
        length = int(meta.get("final_length") or 0)
        has_emoji = bool(meta.get("has_emoji"))
        row = db.query(UserAiMemory).filter(UserAiMemory.user_id == user_id, UserAiMemory.memory_type == "user_style", UserAiMemory.key == "global").first()
        current = (row.value_json or {}) if row else {}
        if style in {"light", "flirty", "deep"}:
            current["preferred_tone"] = style
        current["avg_message_length"] = "short" if length and length < 70 else "medium" if length < 140 else "long" if length else current.get("avg_message_length", "medium")
        if has_emoji:
            current["emoji_level"] = max(0.0, min(1.0, float(current.get("emoji_level") or 0.0) + 0.05))
        conf = float(row.confidence_score or 0.6) if row else 0.6
        conf = min(1.0, conf + 0.02)
        _upsert_memory(db, user_id=user_id, memory_type="user_style", key="global", value_json=current, confidence_score=conf, source="event:message_sent")

    if event_type == "partner_replied":
        prev_style = str(meta.get("previous_style") or "").strip().lower()
        # store success weights per style
        row = db.query(UserAiMemory).filter(UserAiMemory.user_id == user_id, UserAiMemory.memory_type == "successful_openers", UserAiMemory.key == "global").first()
        current = (row.value_json or {}) if row else {}
        if prev_style in {"light", "flirty", "deep"}:
            key = f"{prev_style}_success"
            current[key] = float(current.get(key) or 0.0) + 1.0
            _upsert_memory(db, user_id=user_id, memory_type="successful_openers", key="global", value_json=current, confidence_score=0.6, source="event:partner_replied")
        try:
            sync_partner_replied_to_style(db, user_id=user_id, meta=meta)
        except Exception:
            pass

    if event_type == "meeting_rejected":
        row = db.query(UserAiMemory).filter(UserAiMemory.user_id == user_id, UserAiMemory.memory_type == "dating_preferences", UserAiMemory.key == "global").first()
        current = (row.value_json or {}) if row else {}
        current["avoids_direct_meeting_too_early"] = True
        _upsert_memory(db, user_id=user_id, memory_type="dating_preferences", key="global", value_json=current, confidence_score=0.65, source="event:meeting_rejected")


def _upsert_memory(
    db: Session,
    *,
    user_id: int,
    memory_type: str,
    key: str,
    value_json: dict,
    confidence_score: float,
    source: str,
) -> UserAiMemory:
    mt = str(memory_type or "").strip()
    if mt not in _ALLOWED_MEMORY_TYPES:
        raise ValueError("invalid memory_type")
    k = str(key or "").strip()[:64]
    if not k:
        raise ValueError("invalid key")
    now = datetime.now(UTC)
    safe_val = _safe_json(value_json or {})
    row = (
        db.query(UserAiMemory)
        .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == mt, UserAiMemory.key == k)
        .first()
    )
    if not row:
        row = UserAiMemory(
            user_id=int(user_id),
            memory_type=mt,
            key=k,
            value_json=safe_val,
            confidence_score=max(0.0, min(1.0, float(confidence_score))),
            source=str(source or "system")[:64],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.value_json = safe_val
        row.confidence_score = max(0.0, min(1.0, float(confidence_score)))
        row.source = str(source or row.source or "system")[:64]
        row.updated_at = now
    db.commit()
    return row


def update_user_ai_memory(db: Session, *, user_id: int, partner_user_id: int | None = None) -> None:
    """
    Best-effort memory refresh from aggregates we already have:
    - user_style from UserAiProfile
    This avoids storing raw chats. Other memory types are updated via events later.
    Merges into existing user_style.global so Chat Brain counters are preserved.
    """
    from app.services.ai.chat_brain_style_profile import merge_profile_value

    prof = db.query(UserAiProfile).filter(UserAiProfile.user_id == int(user_id)).first()
    if prof:
        avg_len = float(getattr(prof, "avg_message_length", 0.0) or 0.0)
        length_bucket = "short" if avg_len and avg_len < 70 else "medium" if avg_len and avg_len < 140 else "long" if avg_len else "medium"
        emoji_level = float(getattr(prof, "emoji_usage_level", 0.0) or 0.0)
        preferred = str(getattr(prof, "preferred_style", "") or "light")
        row = (
            db.query(UserAiMemory)
            .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == "user_style", UserAiMemory.key == "global")
            .first()
        )
        base = merge_profile_value(row.value_json if row else {})
        base["preferred_tone"] = preferred if preferred in {"light", "flirty", "deep"} else base.get("preferred_tone", "mixed")
        base["avg_message_length"] = length_bucket
        base["emoji_level"] = max(0.0, min(1.0, emoji_level))
        base["emoji_preference"] = base.get("emoji_preference") or "medium"
        _upsert_memory(
            db,
            user_id=int(user_id),
            memory_type="user_style",
            key="global",
            value_json=base,
            confidence_score=0.75 if int(getattr(prof, "samples", 0) or 0) >= 5 else 0.55,
            source="ai_learning",
        )


def get_user_ai_memory(db: Session, *, user_id: int) -> dict:
    rows = db.query(UserAiMemory).filter(UserAiMemory.user_id == int(user_id)).all()
    out: dict[str, dict] = {}
    for r in rows:
        mt = str(r.memory_type or "")
        key = str(r.key or "")
        if mt not in _ALLOWED_MEMORY_TYPES:
            continue
        out.setdefault(mt, {})
        out[mt][key] = {"value": r.value_json or {}, "confidence": float(r.confidence_score or 0.0)}
    return out


def get_partner_context_memory(db: Session, *, user_id: int, partner_user_id: int) -> dict:
    # Store partner-specific notes only.
    rows = (
        db.query(UserAiMemory)
        .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == "partner_notes", UserAiMemory.key == f"partner:{int(partner_user_id)}")
        .all()
    )
    if not rows:
        return {}
    r = rows[0]
    return {"partner_notes": {"value": r.value_json or {}, "confidence": float(r.confidence_score or 0.0)}}


def build_memory_context_for_prompt(db: Session, *, user_id: int, partner_user_id: int | None = None) -> dict:
    """
    Compact memory injection payload. Do not include raw text. Do not include confidence scores.
    """
    mem = get_user_ai_memory(db, user_id=user_id)
    partner_mem = get_partner_context_memory(db, user_id=user_id, partner_user_id=int(partner_user_id)) if partner_user_id else {}

    def _take(mt: str, key: str = "global") -> dict:
        try:
            return dict((mem.get(mt) or {}).get(key) or {}).get("value") or {}
        except Exception:
            return {}

    payload = {
        "user_style": _take("user_style"),
        "dating_preferences": _take("dating_preferences"),
        "conversation_patterns": {
            **(_take("conversation_patterns") or {}),
            "message_outcomes": _take("conversation_patterns", "message_outcomes") or {},
        },
        "successful_openers": _take("successful_openers"),
        "avoided_topics": _take("avoided_topics"),
        "personalization": _take(PERSONALIZATION_MEMORY_TYPE, PERSONALIZATION_SUMMARY_KEY),
    }
    if partner_mem.get("partner_notes"):
        payload["partner_notes"] = dict(partner_mem["partner_notes"].get("value") or {})
    return {"AI_MEMORY": payload}


def delete_user_ai_memory(db: Session, *, user_id: int) -> int:
    n1 = db.query(UserAiMemory).filter(UserAiMemory.user_id == int(user_id)).delete(synchronize_session=False)
    n2 = db.query(AiInteractionEvent).filter(AiInteractionEvent.user_id == int(user_id)).delete(synchronize_session=False)
    db.commit()
    return int(n1 or 0) + int(n2 or 0)

