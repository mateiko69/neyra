"""
Meeting-driven conversation goal state (deterministic heuristic layer).

Feeds AIOrchestrator / timed-replies / chat-brain prompts with phase, drop-risk,
meeting-push mode, and (Premium+) user-facing telemetry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.services.ai.conversation.readiness_score import score_readiness

MeetingPushMode = Literal["none", "soft_hint", "strong_hint"]
Phase = Literal["ice", "connection", "comfort", "ready"]
Urgency = Literal["low", "medium", "high"]

_ACK_PAT = re.compile(r"^(ok|k|kk|lol|lmao|yeah|yep|yes|no|sure|nice|cool|nah|ага|ок|так)\b", re.I)


def _clamp_int(v: float | int, lo: int = 0, hi: int = 100) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return lo


def _norm_chat(messages: list[dict]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages or []:
        role = str(m.get("role") or "").strip().lower()
        role = "me" if role in {"me", "user", "self"} else "them"
        text = str(m.get("text") or "").strip()
        if text:
            out.append({"role": role, "text": text[:900]})
    return out


def _avg_len(role: str, rows: list[dict[str, str]], tail: int = 6) -> float:
    sub = [m["text"] for m in rows[-tail:] if m["role"] == role]
    if not sub:
        return 0.0
    return sum(len(x) for x in sub) / max(1, len(sub))


def _them_questions_recent(rows: list[dict[str, str]], n: int = 6) -> int:
    return sum(1 for m in rows[-n:] if m["role"] == "them" and "?" in m["text"])


def _me_short_chain(rows: list[dict[str, str]], tail: int = 4) -> int:
    c = 0
    for m in rows[-tail:]:
        if m["role"] != "me":
            continue
        t = m["text"].strip()
        if len(t) <= 18 or _ACK_PAT.match(t.lower()):
            c += 1
    return c


def _mutuality_from_rows(rows: list[dict[str, str]]) -> int:
    me_n = sum(1 for m in rows if m["role"] == "me")
    them_n = sum(1 for m in rows if m["role"] == "them")
    if me_n + them_n == 0:
        return 0
    ratio = min(me_n, them_n) / max(me_n, them_n, 1)
    q_me = sum(1 for m in rows[-12:] if m["role"] == "me" and "?" in m["text"])
    q_the = sum(1 for m in rows[-12:] if m["role"] == "them" and "?" in m["text"])
    balance = _clamp_int(40 + ratio * 40 + min(10, q_me * 2) + min(10, q_the * 2))
    return balance


def _resolve_phase(progress: int, rows: list[dict[str, str]]) -> Phase:
    if progress < 38 or len(rows) < 4:
        return "ice"
    if progress < 55:
        return "connection"
    if progress < 72:
        return "comfort"
    return "ready"


def _resolve_meeting_push(
    *,
    phase: Phase,
    drop_risk: int,
    readiness_score: int,
    plan_tier: str,
) -> MeetingPushMode:
    tier = (plan_tier or "free").strip().lower()
    if tier == "free":
        return "none"
    # Re-engage beats meeting push while drop risk dominates.
    if drop_risk > 62:
        return "none"
    if phase not in {"comfort", "ready"}:
        return "none"
    if readiness_score < 52:
        return "none"
    # Strong nudge once we're clearly in-date territory and engagement is steady.
    if phase == "ready" and readiness_score >= 78 and drop_risk <= 48:
        return "strong_hint" if tier == "premium_plus" else "soft_hint"
    # Soft public-meet cues can start slightly earlier on paid tiers during comfort phase.
    if phase == "ready" and readiness_score >= 58:
        return "soft_hint"
    if phase == "comfort" and readiness_score >= 60 and tier in {"premium", "premium_plus"}:
        return "soft_hint"
    return "none"


def _risk_label(drop_risk: int) -> str:
    if drop_risk >= 66:
        return "high"
    if drop_risk >= 38:
        return "medium"
    return "low"


def _meeting_chance_percent(progress: int, drop_risk: int) -> int:
    # Blend forward momentum with engagement safety.
    raw = 0.52 * float(progress) + 0.48 * float(max(0, 100 - drop_risk))
    return _clamp_int(raw)


def _best_next_move(state: "ConversationGoalState", *, locale: str) -> str:
    loc = (locale or "en").strip().lower()[:8]
    if state.reengage_recommended:
        if loc.startswith("uk"):
            return "Перезапусти розмову: нова легка тема + конкретне питання без тиску."
        if loc.startswith("ru"):
            return "Перезапусти диалог: новая лёгкая тема + конкретный вопрос без давления."
        return "Re-engage: fresh light topic + one concrete, easy question—no pressure."
    if state.phase == "ready" and state.meeting_push_mode != "none":
        if loc.startswith("uk"):
            return "Обережно підведи до короткої зустрічі в публічному місці — м’яко і з виходом."
        if loc.startswith("ru"):
            return "Мягко подведи к короткой встрече в публичном месте — с выходом, если не ок."
        return "Gently steer toward a short public meet—always leave an easy out."
    if state.phase == "comfort":
        if loc.startswith("uk"):
            return "Поглиб теплий тон: трохи особистого + одне чесне питання."
        return "Deepen warmth: one personal detail + one sincere question."
    if state.phase == "connection":
        if loc.startswith("uk"):
            return "Закріпи спільне: відзнач спільний інтерес і запропонуй простий вибір."
        return "Lock in shared ground: reflect one shared interest + offer a simple either/or."
    if loc.startswith("uk"):
        return "Тримай легкість: коротко, тепло, одне просте питання."
    return "Stay light: short, warm, one easy question."


@dataclass(frozen=True)
class ConversationGoalState:
    goal: Literal["get_meeting"]
    phase: Phase
    progress_score: int
    drop_risk: int
    urgency: Urgency
    meeting_push_mode: MeetingPushMode
    reengage_recommended: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "phase": self.phase,
            "progress_score": self.progress_score,
            "drop_risk": self.drop_risk,
            "urgency": self.urgency,
            "meeting_push_mode": self.meeting_push_mode,
            "reengage_recommended": self.reengage_recommended,
        }


def premium_plus_goal_metrics_public(state: ConversationGoalState, *, locale: str) -> dict[str, Any]:
    """UI bundle for Premium Plus clients only."""
    return {
        "best_next_move": _best_next_move(state, locale=locale),
        "meeting_chance_percent": _meeting_chance_percent(state.progress_score, state.drop_risk),
        "risk_level": _risk_label(state.drop_risk),
        "phase": state.phase,
        "urgency": state.urgency,
        "meeting_push_mode": state.meeting_push_mode,
        "drop_risk": state.drop_risk,
        "progress_score": state.progress_score,
    }


def goal_state_prompt_block(state: ConversationGoalState) -> str:
    """
    English system-prompt instructions (model output language still governed elsewhere).
    """
    lines = [
        "\n### CONVERSATION_GOAL_ENGINE (deterministic briefing — follow behavior, do not repeat verbatim)",
        f"- Strategic goal: {state.goal} (real-world meeting when trust is sufficient).",
        f"- Relationship phase: {state.phase}",
        "  • ice → very short replies, light questions, playful safety.",
        "  • connection → surface shared tastes/hobbies; slightly longer replies allowed.",
        "  • comfort → warmer personal tone, light respectful teasing, emotional resonance.",
        "  • ready → you may softly introduce low-pressure meeting ideas if meeting_push_mode allows.",
        f"- Engagement progress_score≈{state.progress_score}/100 (higher ⇒ closer to proposing a gentle meet).",
        f"- drop_risk≈{state.drop_risk}/100 (risk the chat will die).",
        f"- urgency: {state.urgency}",
        f"- meeting_push_mode: {state.meeting_push_mode}",
    ]
    if state.meeting_push_mode == "soft_hint":
        lines += [
            "- Meeting hint level: SOFT. Use understated in-person cues; never pressure.",
            "  Example vibes (adapt to OUTPUT language — do NOT copy verbatim):",
            '  • UA: «з тобою було б цікаво випити каву»',
            '  • UA: «мені здається вживу це ще краще зайде»',
        ]
    elif state.meeting_push_mode == "strong_hint":
        lines += [
            "- Meeting hint level: STRONG (still respectful, public, easy out).",
            "  Offer a clear but low-pressure plan window; reassure they can decline.",
        ]
    if state.reengage_recommended:
        lines += [
            "- REENGAGE MODE (drop risk elevated): prioritize curiosity + topic shift;",
            "  avoid pushing a meet until warmth returns; vary tone vs last messages.",
        ]
    lines.append(
        "- Always: move the thread forward, increase reply-ability, reduce drop_risk, never manipulate.\n"
    )
    return "\n".join(lines)


def hours_since_iso(iso: str | None) -> float | None:
    if not iso or not str(iso).strip():
        return None
    raw = str(iso).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - dt.astimezone(UTC)).total_seconds() / 3600.0)
    except Exception:
        return None


def compute_conversation_goal_state(
    messages: list[dict],
    *,
    plan_tier: str = "free",
    locale: str | None = None,
    draft: str | None = None,
    hours_since_last_message: float | None = None,
    who_sent_last: str | None = None,
    nudge_type: str | None = None,
    interest_stage: str | None = None,
    mutuality_score: int | None = None,
) -> ConversationGoalState:
    """
    Core deterministic goal state from recent chat transcript + coarse timing hints.
    """
    tier = (plan_tier or "free").strip().lower()
    if tier not in {"free", "premium", "premium_plus"}:
        tier = "free"

    rows_pre = _norm_chat(messages)

    readiness = score_readiness(
        messages=[{"role": m["role"], "text": m["text"]} for m in rows_pre],
        draft=draft,
        plan_tier=tier,
        locale=locale,
    )
    r_score = _clamp_int(readiness.score)

    n_msg = len(rows_pre)
    me_chars = sum(len(m["text"]) for m in rows_pre if m["role"] == "me")
    them_chars = sum(len(m["text"]) for m in rows_pre if m["role"] == "them")

    breadth = min(100, int(n_msg * 6 + min(38, (me_chars + them_chars) / max(18, n_msg or 1))))
    mutual_ext = mutuality_score if mutuality_score is not None else _mutuality_from_rows(rows_pre)
    progress = _clamp_int(0.45 * r_score + 0.32 * breadth + 0.23 * float(mutual_ext))

    phase = _resolve_phase(progress, rows_pre)

    drop = 28.0
    them_avg = _avg_len("them", rows_pre, 6)
    if them_avg > 0 and them_avg < 22:
        drop += 14.0
    if them_avg > 0 and them_avg < 12:
        drop += 12.0

    if _them_questions_recent(rows_pre, 8) == 0 and n_msg >= 3:
        drop += 16.0
    elif _them_questions_recent(rows_pre, 8) <= 1 and n_msg >= 6:
        drop += 8.0

    if _me_short_chain(rows_pre, 5) >= 2:
        drop += 14.0

    last_the = next((m for m in reversed(rows_pre) if m["role"] == "them"), None)
    if last_the and (_ACK_PAT.match(last_the["text"].strip().lower()) or len(last_the["text"]) <= 10):
        drop += 12.0

    if mutual_ext < 38:
        drop += 10.0

    wsl = (who_sent_last or "").strip().lower()
    h = hours_since_last_message
    if h is not None and h > 0:
        if wsl == "me" and h >= 18:
            drop += min(22.0, (h - 18) * 0.35)
        elif wsl == "them" and h >= 36:
            drop += min(16.0, (h - 36) * 0.25)

    nudge = (nudge_type or "").strip().lower()
    if nudge in {"revive", "reengage"}:
        drop += 18.0

    ist = (interest_stage or "").strip().lower()
    if ist == "cold":
        drop += 8.0

    # Long, balanced chats pull drop risk down.
    if n_msg >= 14 and them_avg >= 30 and _them_questions_recent(rows_pre, 10) >= 2:
        drop -= 12.0

    drop_risk = _clamp_int(drop)
    reengage = bool(drop_risk > 60)

    if drop_risk >= 72 or nudge == "revive":
        urgency: Urgency = "high"
    elif drop_risk >= 44 or (h or 0) >= 30:
        urgency = "medium"
    else:
        urgency = "low"

    meeting_mode = _resolve_meeting_push(
        phase=phase,
        drop_risk=drop_risk,
        readiness_score=r_score,
        plan_tier=tier,
    )

    return ConversationGoalState(
        goal="get_meeting",
        phase=phase,
        progress_score=progress,
        drop_risk=drop_risk,
        urgency=urgency,
        meeting_push_mode=meeting_mode,
        reengage_recommended=reengage,
    )
