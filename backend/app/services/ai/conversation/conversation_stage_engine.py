"""
Heuristic relationship stage from recent messages (no LLM).
Used to adapt AI tone and coaching; never stores raw chat.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from app.services.ai.topic_brain import TOPIC_KEYWORDS

ConversationStage = Literal["opener", "warmup", "engaged", "flirty", "connection", "meeting_ready"]

_FLIRT_MARKERS = (
    "😉",
    "😏",
    "🥰",
    "❤",
    "💋",
    "🔥",
    "cute",
    "handsome",
    " pretty",
    "attractive",
    "crush",
    "красив",
    "мил",
    "симпат",
    "флірт",
    "flirt",
    "kiss",
    "attrac",
)
_PERSONAL_MARKERS = (
    "family",
    "mom",
    "dad",
    "parent",
    "sister",
    "brother",
    "child",
    "feel ",
    "feeling",
    "honest",
    "trust",
    "vulnerable",
    "therapy",
    "anxiety",
    "scared",
    "dream",
    "childhood",
    "мама",
    "батьк",
    "сім'ї",
    "родител",
    "честно",
    "довір",
    "тривож",
    "сновид",
)
_MEETING_HINTS = (
    "meet",
    "coffee",
    "drink",
    "grab",
    "see you",
    "in person",
    "зустр",
    "кав",
    "побач",
    "свидан",
)


def _norm_role(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in ("me", "user", "self"):
        return "me"
    if s in ("them", "partner", "other"):
        return "partner"
    return "partner"


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, (int, float)):
        v = float(raw)
        sec = v / 1000.0 if v > 1e12 else v
        return datetime.fromtimestamp(sec, tz=UTC)
    s = str(raw).strip()
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        d = datetime.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d.astimezone(UTC)
    except Exception:
        return None


def normalize_messages_for_stage(messages: Any) -> list[dict[str, Any]]:
    """Normalize heterogeneous message shapes to role + text + optional created_at."""
    out: list[dict[str, Any]] = []
    for m in messages or []:
        if isinstance(m, (list, tuple)) and len(m) >= 2:
            role_raw, text_raw = m[0], m[1]
            ts_raw = m[2] if len(m) >= 3 else None
            text = str(text_raw or "").strip()
            if not text:
                continue
            out.append({"role": _norm_role(role_raw), "text": text[:2000], "created_at": _parse_ts(ts_raw)})
        elif isinstance(m, dict):
            role = m.get("role") or m.get("sender")
            text = str(m.get("text") or m.get("content") or "").strip()
            if not text:
                continue
            ts = m.get("created_at") or m.get("ts") or m.get("ts_ms")
            if isinstance(ts, (int, float)) and float(ts) > 1e12:
                ts = datetime.fromtimestamp(float(ts) / 1000.0, tz=UTC)
            out.append({"role": _norm_role(role), "text": text[:2000], "created_at": _parse_ts(ts)})
    return out


def _median_minutes_between(norm: list[dict[str, Any]]) -> float | None:
    ts_list = [m["created_at"] for m in norm if m.get("created_at")]
    if len(ts_list) < 3:
        return None
    ts_sorted = sorted(ts_list)
    deltas: list[float] = []
    for a, b in zip(ts_sorted, ts_sorted[1:]):
        deltas.append(abs((b - a).total_seconds()) / 60.0)
    if not deltas:
        return None
    return sorted(deltas)[len(deltas) // 2]


def detect_stage(messages: Any) -> dict[str, Any]:
    """
    Infer relationship stage and coarse engagement scores.

    Returns:
        stage: opener | warmup | engaged | flirty | connection | meeting_ready
        mutuality_score: 0..1
        energy_score: 0..1
    """
    norm = normalize_messages_for_stage(messages)
    n = len(norm)
    blob_me = " ".join(m["text"].lower() for m in norm if m["role"] == "me")
    blob_them = " ".join(m["text"].lower() for m in norm if m["role"] == "partner")
    blob = f"{blob_me} {blob_them}"

    def mutuality() -> float:
        me_c = sum(1 for m in norm if m["role"] == "me")
        p_c = sum(1 for m in norm if m["role"] == "partner")
        if me_c == 0 or p_c == 0:
            return 0.15
        s = 0.25
        ratio = min(me_c, p_c) / max(me_c, p_c)
        s += 0.35 * min(1.0, ratio / 0.9)
        me_q = "?" in blob_me
        them_q = "?" in blob_them
        if me_q and them_q:
            s += 0.2
        elif me_q or them_q:
            s += 0.08
        long_me = sum(1 for m in norm if m["role"] == "me" and len(m["text"]) >= 25)
        long_p = sum(1 for m in norm if m["role"] == "partner" and len(m["text"]) >= 25)
        if long_me and long_p:
            s += 0.2
        return max(0.0, min(1.0, s))

    def energy() -> float:
        e = 0.2
        if any(c in blob for c in ("😄", "😅", "lol", "haha", "!")):
            e += 0.22
        emoji = len(re.findall(r"[\U0001f300-\U0001fafF]", blob))
        e += min(0.28, emoji * 0.05)
        if len(norm) >= 6:
            e += 0.12
        med = _median_minutes_between(norm)
        if med is not None:
            if med <= 25:
                e += 0.28
            elif med <= 90:
                e += 0.14
        return max(0.0, min(1.0, e))

    mutuality_f = round(mutuality(), 3)
    energy_f = round(energy(), 3)

    if n < 3:
        return {"stage": "opener", "mutuality_score": mutuality_f, "energy_score": energy_f}

    q_count = blob.count("?")
    qa_warmup = q_count >= 2 and n <= 14

    shared_hits = 0
    for _tid, keys in TOPIC_KEYWORDS.items():
        hit_me = any(k in blob_me for k in keys)
        hit_them = any(k in blob_them for k in keys)
        if hit_me and hit_them:
            shared_hits += 1
    engaged = shared_hits >= 1

    flirt = any(x in blob for x in _FLIRT_MARKERS)

    personal = any(x in blob for x in _PERSONAL_MARKERS)

    med_min = _median_minutes_between(norm)
    fast = med_min is not None and med_min <= 45

    meeting_hint = any(x in blob for x in _MEETING_HINTS)

    meeting_ready = mutuality_f >= 0.58 and n >= 8 and fast and (engaged or flirt or meeting_hint)

    idx = 1
    if qa_warmup:
        idx = max(idx, 1)
    if engaged:
        idx = max(idx, 2)
    if flirt:
        idx = max(idx, 3)
    if personal:
        idx = max(idx, 4)
    if meeting_ready:
        idx = max(idx, 5)

    stage_map: tuple[ConversationStage, ...] = (
        "opener",
        "warmup",
        "engaged",
        "flirty",
        "connection",
        "meeting_ready",
    )
    stage: ConversationStage = stage_map[min(idx, 5)]

    return {"stage": stage, "mutuality_score": mutuality_f, "energy_score": energy_f}


def stage_ui_hints(stage: str) -> tuple[str, str]:
    """Suggested ChatBrainRequest.tone and conversation_mode."""
    s = str(stage or "").strip().lower()
    mapping: dict[str, tuple[str, str]] = {
        "opener": ("warm", "easy"),
        "warmup": ("playful", "easy"),
        "engaged": ("thoughtful", "playful"),
        "flirty": ("flirty", "flirty"),
        "connection": ("warm", "romantic"),
        "meeting_ready": ("confident", "confident"),
    }
    return mapping.get(s, ("auto", "easy"))


def stage_prompt_hint(stage: str, mutuality: float, energy: float) -> str:
    s = str(stage or "").strip().lower()
    guides = {
        "opener": "Stage is early: one easy, specific hook and a single clear question.",
        "warmup": "Stage is warming: light Q&A; mirror their energy; avoid heavy topics.",
        "engaged": "Shared interests detected: reference overlap naturally; deepen one thread.",
        "flirty": "Playful tension is OK: stay respectful; invite replies; no explicit content.",
        "connection": "Personal tone: acknowledge vulnerability lightly; avoid interrogation.",
        "meeting_ready": "Soft real-world nudge may fit if the transcript supports it; never pressure.",
    }
    g = guides.get(s, guides["warmup"])
    return (
        f"\nRELATIONSHIP_STAGE: {s} (mutuality~{mutuality:.2f}, energy~{energy:.2f}).\n"
        f"{g}\n"
    )
