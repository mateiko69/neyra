"""
Chat Brain user style profile: aggregate-only learning (no message bodies).
Stored in UserAiMemory memory_type=user_style key=global alongside existing keys.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.user_ai_memory import UserAiMemory

STYLE_KEYS = ("light", "flirty", "deep")
Tone = Literal["light", "flirty", "deep", "mixed"]
EmojiPref = Literal["low", "medium", "high"]
LenBucket = Literal["short", "medium", "long"]


def _empty_counters() -> dict[str, float]:
    return {k: 0.0 for k in STYLE_KEYS}


def default_style_profile() -> dict[str, Any]:
    return {
        "preferred_tone": "mixed",
        "avg_message_length": "medium",
        "emoji_preference": "medium",
        "successful_styles": _empty_counters(),
        "rejected_styles": _empty_counters(),
        "pick_counts": _empty_counters(),
        "brain_send_count": 0.0,
        "brain_reply_count": 0.0,
        "last_updated_at": None,
    }


def _touch(d: dict[str, Any]) -> None:
    d["last_updated_at"] = datetime.now(UTC).isoformat()


def _emoji_level_to_pref(level: float | None) -> EmojiPref:
    if level is None:
        return "medium"
    try:
        x = float(level)
    except (TypeError, ValueError):
        return "medium"
    if x < 0.33:
        return "low"
    if x > 0.66:
        return "high"
    return "medium"


def _pref_to_level(pref: str | None) -> float:
    p = (pref or "medium").strip().lower()
    if p == "low":
        return 0.2
    if p == "high":
        return 0.85
    return 0.5


def merge_profile_value(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_style_profile()
    if not raw:
        return base
    cur = dict(raw)
    for k, v in base.items():
        if k not in cur:
            cur[k] = v
    for k in STYLE_KEYS:
        if "successful_styles" in cur and isinstance(cur["successful_styles"], dict):
            cur["successful_styles"].setdefault(k, 0.0)
        if "rejected_styles" in cur and isinstance(cur["rejected_styles"], dict):
            cur["rejected_styles"].setdefault(k, 0.0)
        if "pick_counts" in cur and isinstance(cur["pick_counts"], dict):
            cur["pick_counts"].setdefault(k, 0.0)
    # Migrate legacy emoji_level → emoji_preference
    if cur.get("emoji_preference") in (None, "") and cur.get("emoji_level") is not None:
        cur["emoji_preference"] = _emoji_level_to_pref(cur.get("emoji_level"))
    pt = str(cur.get("preferred_tone") or "mixed").strip().lower()
    if pt not in {"light", "flirty", "deep", "mixed"}:
        pt = "mixed"
    cur["preferred_tone"] = pt
    for key in ("avg_message_length",):
        b = str(cur.get(key) or "medium").strip().lower()
        if b not in {"short", "medium", "long"}:
            b = "medium"
        cur[key] = b
    ep = str(cur.get("emoji_preference") or "medium").strip().lower()
    if ep not in {"low", "medium", "high"}:
        ep = "medium"
    cur["emoji_preference"] = ep
    return cur


def get_chat_brain_style_profile(db: Session, user_id: int) -> dict[str, Any]:
    """Load merged style profile for Chat Brain. Uses DB when present; else neutral default."""
    row = (
        db.query(UserAiMemory)
        .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == "user_style", UserAiMemory.key == "global")
        .first()
    )
    raw: dict[str, Any] | None = None
    if row and getattr(row, "value_json", None):
        v = row.value_json
        if isinstance(v, dict) and v:
            raw = dict(v)
    if not raw:
        raw = {"tone": "neutral", "style": "balanced"}
    return merge_profile_value(raw)


def style_public_summary(profile: dict[str, Any]) -> dict[str, Any]:
    """Safe subset for API / UI (no counters detail)."""
    p = merge_profile_value(profile)
    picks = p.get("pick_counts") or {}
    succ = p.get("successful_styles") or {}
    top = None
    best_score = -1.0
    for k in STYLE_KEYS:
        sc = float((succ.get(k) or 0.0)) + 0.25 * float((picks.get(k) or 0.0))
        if sc > best_score:
            best_score = sc
            top = k
    if best_score <= 0:
        top = None
    sends = float(p.get("brain_send_count") or 0)
    replies = float(p.get("brain_reply_count") or 0)
    return {
        "adapting": sends > 0 or sum(float(picks.get(k) or 0) for k in STYLE_KEYS) > 0,
        "top_style": top,
        "preferred_tone": p.get("preferred_tone") or "mixed",
        "emoji_preference": p.get("emoji_preference") or "medium",
        "avg_message_length": p.get("avg_message_length") or "medium",
        "reply_after_brain_rate": (replies / sends) if sends > 0 else None,
    }


def build_style_prompt_hint(profile: dict[str, Any]) -> str:
    p = merge_profile_value(profile)
    succ = p.get("successful_styles") or {}
    rej = p.get("rejected_styles") or {}
    parts = [
        f"USER_TONE_PREFERENCE={p.get('preferred_tone', 'mixed')}",
        f"USER_TYPICAL_LENGTH={p.get('avg_message_length', 'medium')}",
        f"USER_EMOJI_LEVEL={p.get('emoji_preference', 'medium')}",
        f"SUCCESS_COUNTS light={int(succ.get('light', 0))} flirty={int(succ.get('flirty', 0))} deep={int(succ.get('deep', 0))}",
        f"REJECT_SIGNALS light={rej.get('light', 0):.1f} flirty={rej.get('flirty', 0):.1f} deep={rej.get('deep', 0):.1f}",
    ]
    return " | ".join(parts)


def score_boost_from_profile(profile: dict[str, Any], variant: str) -> float:
    """Additive score for recommendation ranking."""
    p = merge_profile_value(profile)
    v = str(variant or "").strip().lower()
    if v not in STYLE_KEYS:
        return 0.0
    boost = 0.0
    pref = str(p.get("preferred_tone") or "mixed")
    if pref == v:
        boost += 0.85
    elif pref == "mixed":
        boost += 0.15
    succ = p.get("successful_styles") or {}
    picks = p.get("pick_counts") or {}
    tot_s = sum(float(succ.get(k) or 0) for k in STYLE_KEYS) + 1e-6
    tot_p = sum(float(picks.get(k) or 0) for k in STYLE_KEYS) + 1e-6
    boost += 1.2 * (float(succ.get(v) or 0) / tot_s)
    boost += 0.35 * (float(picks.get(v) or 0) / tot_p)
    rej = p.get("rejected_styles") or {}
    rj = float(rej.get(v) or 0)
    boost -= min(1.2, 0.25 * rj)
    return boost


def deep_extra_risk_from_profile(profile: dict[str, Any], text_count: int) -> bool:
    """Earlier 'risky' for deep if user historically gets ignored with deep early."""
    if text_count >= 5:
        return False
    p = merge_profile_value(profile)
    succ = p.get("successful_styles") or {}
    rej = p.get("rejected_styles") or {}
    s_deep = float(succ.get("deep") or 0)
    r_deep = float(rej.get("deep") or 0)
    if r_deep >= 2 and s_deep < 1:
        return True
    if r_deep - s_deep >= 1.5:
        return True
    return False


def _upsert_user_style(db: Session, user_id: int, mutator: Any) -> None:
    row = (
        db.query(UserAiMemory)
        .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == "user_style", UserAiMemory.key == "global")
        .first()
    )
    now = datetime.now(UTC)
    cur = merge_profile_value(row.value_json if row else {})
    mutator(cur)
    _touch(cur)
    if not row:
        row = UserAiMemory(
            user_id=int(user_id),
            memory_type="user_style",
            key="global",
            value_json=cur,
            confidence_score=0.55,
            source="chat_brain_style",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.value_json = cur
        row.updated_at = now
        row.source = "chat_brain_style"
    db.commit()


def _recompute_preferred_tone(cur: dict[str, Any]) -> None:
    picks = cur.get("pick_counts") or {}
    tot = sum(float(picks.get(k) or 0) for k in STYLE_KEYS)
    if tot < 2:
        return
    best = max(STYLE_KEYS, key=lambda k: float(picks.get(k) or 0))
    second = sorted(STYLE_KEYS, key=lambda k: float(picks.get(k) or 0), reverse=True)[1]
    top_v = float(picks.get(best) or 0)
    second_v = float(picks.get(second) or 0)
    if top_v / tot >= 0.42 and (top_v - second_v) / tot >= 0.12:
        cur["preferred_tone"] = best
    else:
        cur["preferred_tone"] = "mixed"


def _bump_success_style(cur: dict[str, Any], style: str) -> None:
    st = str(style or "").strip().lower()
    if st not in STYLE_KEYS:
        return
    ss = cur.setdefault("successful_styles", _empty_counters())
    ss[st] = float(ss.get(st) or 0) + 1.0


def apply_chat_brain_style_event(db: Session, *, user_id: int, event_type: str, meta: dict[str, Any]) -> None:
    """Profile updates from chat-brain signals. Partner replies: partner_replied + sync_partner_replied_to_style."""
    et = str(event_type or "").strip().lower()
    if et not in {"cb_select", "cb_send", "cb_copy", "cb_regen", "cb_edit"}:
        return

    def _bump_rejected(cur: dict[str, Any], style: str, w: float) -> None:
        st = str(style or "").strip().lower()
        if st not in STYLE_KEYS:
            return
        rs = cur.setdefault("rejected_styles", _empty_counters())
        rs[st] = float(rs.get(st) or 0) + w

    if et == "cb_select":

        def m(cur: dict[str, Any]) -> None:
            v = str(meta.get("variant") or meta.get("style") or "").strip().lower()
            if v not in STYLE_KEYS:
                return
            pc = cur.setdefault("pick_counts", _empty_counters())
            pc[v] = float(pc.get(v) or 0) + 1.0
            _recompute_preferred_tone(cur)

        _upsert_user_style(db, user_id, m)

    elif et == "cb_send":

        def m(cur: dict[str, Any]) -> None:
            v = str(meta.get("variant") or "").strip().lower()
            ln = int(meta.get("draft_length") or 0)
            if ln > 0:
                cur["avg_message_length"] = "short" if ln < 70 else "medium" if ln < 140 else "long"
            if meta.get("has_emoji"):
                lvl = _pref_to_level(str(cur.get("emoji_preference") or "medium"))
                cur["emoji_level"] = min(1.0, lvl + 0.06)
                cur["emoji_preference"] = _emoji_level_to_pref(cur.get("emoji_level"))
            cur["brain_send_count"] = float(cur.get("brain_send_count") or 0) + 1.0
            if v in STYLE_KEYS:
                cur["preferred_tone"] = v if float((cur.get("pick_counts") or {}).get(v) or 0) >= 1 else cur.get("preferred_tone", "mixed")

        _upsert_user_style(db, user_id, m)

    elif et == "cb_copy":

        def m(cur: dict[str, Any]) -> None:
            v = str(meta.get("variant") or "").strip().lower()
            if v not in STYLE_KEYS:
                return
            pc = cur.setdefault("pick_counts", _empty_counters())
            pc[v] = float(pc.get(v) or 0) + 0.35
            _recompute_preferred_tone(cur)

        _upsert_user_style(db, user_id, m)

    elif et == "cb_regen":

        def m(cur: dict[str, Any]) -> None:
            dropped = str(meta.get("dropped_variant") or meta.get("variant") or "").strip().lower()
            if dropped in STYLE_KEYS:
                _bump_rejected(cur, dropped, 0.6)

        _upsert_user_style(db, user_id, m)

    elif et == "cb_edit":

        def m(cur: dict[str, Any]) -> None:
            v = str(meta.get("variant") or "").strip().lower()
            if v in STYLE_KEYS:
                _bump_rejected(cur, v, 0.35)

        _upsert_user_style(db, user_id, m)


def sync_partner_replied_to_style(db: Session, *, user_id: int, meta: dict[str, Any]) -> None:
    """When partner_replied carries brain context, mirror success into user_style."""
    if str(meta.get("previous_source") or "").strip().lower() != "chat_brain":
        return
    v = str(meta.get("previous_style") or meta.get("variant") or "").strip().lower()
    if v not in STYLE_KEYS:
        return

    def m(cur: dict[str, Any]) -> None:
        _bump_success_style(cur, v)
        cur["brain_reply_count"] = float(cur.get("brain_reply_count") or 0) + 1.0

    _upsert_user_style(db, user_id, m)
