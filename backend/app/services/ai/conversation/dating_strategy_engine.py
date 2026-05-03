"""
Dating strategy: maps relationship stage + thread context to the next conversational move.
Emphasizes coaching (what to aim for) rather than generic text. No persistence.
"""

from __future__ import annotations

from typing import Any, Literal

from app.services.ai.conversation.conversation_stage_engine import normalize_messages_for_stage

NextAction = Literal["continue", "flirt", "deepen", "suggest_meet", "wait"]

_ALLOWED_TAGS = frozenset(
    {
        "high_interest",
        "fast_replies",
        "mutual_topics",
        "playful_signals",
        "personal_depth",
        "low_pressure",
        "common_ground",
        "double_text_risk",
        "cooling_off",
        "stalled_thread",
        "meeting_window",
        "positive_energy",
    }
)


def _median_reply_minutes(norm: list[dict[str, Any]]) -> float | None:
    ts_list = sorted(m["created_at"] for m in norm if m.get("created_at"))
    if len(ts_list) < 3:
        return None
    deltas: list[float] = []
    for a, b in zip(ts_list, ts_list[1:]):
        deltas.append(abs((b - a).total_seconds()) / 60.0)
    if not deltas:
        return None
    return sorted(deltas)[len(deltas) // 2]


def plan_dating_strategy(
    *,
    stage_info: dict[str, Any],
    stage_messages: list[dict[str, Any]],
    last_text_role: str | None,
    hours_since_last_text: float | None,
    run_generation: bool,
    trail_me: int,
) -> dict[str, Any]:
    """
    Returns:
        next_action: continue | flirt | deepen | suggest_meet | wait
        reasoning_tags: short snake_case tags for analytics / UI
    """
    stage = str(stage_info.get("stage") or "warmup").strip().lower()
    mutuality = float(stage_info.get("mutuality_score") or 0.0)
    energy = float(stage_info.get("energy_score") or 0.0)
    norm = normalize_messages_for_stage(stage_messages)
    n = len(norm)
    med_min = _median_reply_minutes(norm)

    tags: list[str] = []

    if mutuality >= 0.52:
        tags.append("high_interest")
    if energy >= 0.5:
        tags.append("positive_energy")
    if med_min is not None and med_min <= 45:
        tags.append("fast_replies")
    if stage in {"engaged", "meeting_ready"}:
        tags.append("mutual_topics")

    if not run_generation:
        tags.append("cooling_off")
        out_tags = _dedupe_tags([*tags, "cooling_off"])
        return {"next_action": "wait", "reasoning_tags": out_tags}

    if last_text_role == "me" and trail_me >= 2:
        tags.append("double_text_risk")
        out_tags = _dedupe_tags(tags)
        return {"next_action": "wait", "reasoning_tags": out_tags}

    hrs = float(hours_since_last_text) if hours_since_last_text is not None else None
    if last_text_role == "me" and hrs is not None and hrs < 1.5 and trail_me >= 1:
        tags.append("double_text_risk")
        out_tags = _dedupe_tags(tags)
        return {"next_action": "wait", "reasoning_tags": out_tags}

    if stage == "opener":
        tags.append("low_pressure")
        action: NextAction = "continue"
    elif stage == "warmup":
        tags.append("common_ground")
        action = "continue"
    elif stage == "engaged":
        action = "deepen"
    elif stage == "flirty":
        tags.append("playful_signals")
        action = "flirt"
    elif stage == "connection":
        tags.append("personal_depth")
        action = "deepen"
    elif stage == "meeting_ready":
        tags.append("meeting_window")
        action = "suggest_meet"
    else:
        action = "continue"

    if n >= 2 and last_text_role == "partner" and hrs is not None and hrs > 36:
        tags.append("stalled_thread")

    out_tags = _dedupe_tags(tags)
    return {"next_action": action, "reasoning_tags": out_tags}


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        t = str(t or "").strip().lower()
        if not t or t not in _ALLOWED_TAGS:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:12]


def dating_strategy_prompt_block(strategy: dict[str, Any], *, locale: str = "en", plan_tier: str | None = None) -> str:
    """Coach the model: align suggestions with strategy (not generic filler)."""
    action = str(strategy.get("next_action") or "continue").strip().lower()
    tags = strategy.get("reasoning_tags") or []
    tag_line = ", ".join(str(t) for t in tags[:8]) if tags else "—"

    rules = {
        "continue": (
            "NEXT_MOVE: CONTINUE — stay light and curious; find hooks; no pressure or heavy asks. "
            "Each variant should invite a reply without sounding like an interview."
        ),
        "flirt": (
            "NEXT_MOVE: FLIRT — add tasteful playful tension; warm tease; still respectful and consent-forward. "
            "Keep each line specific to the transcript."
        ),
        "deepen": (
            "NEXT_MOVE: DEEPEN — expand one thread; add personality; one thoughtful angle per variant where natural. "
            "Avoid therapy-speak; stay early-dating appropriate."
        ),
        "suggest_meet": (
            "NEXT_MOVE: SUGGEST_MEET — at least ONE variant should gently propose a low-pressure in-person continuation "
            "(coffee, walk, quick drink). Example vibe only (translate to target LANGUAGE, do not quote verbatim): "
            "\"We should continue this over coffee 😄\". Never pressure, guilt, or assume consent."
        ),
        "wait": (
            "NEXT_MOVE: WAIT — if generating anyway, keep lines minimal and low-pressure; do not chase or stack questions."
        ),
    }
    body = rules.get(action, rules["continue"])
    tier = (plan_tier or "free").strip().lower()
    tier_hint = ""
    if tier == "premium_plus":
        tier_hint = (
            "- TIER: PREMIUM_PLUS — push one subtle proactive next-step (still consent-forward); "
            "stronger personalization from transcript; no manipulation.\n"
        )
    elif tier == "premium":
        tier_hint = "- TIER: PREMIUM — warmer flirt allowed; memory-aware phrasing when transcript supports it.\n"

    return (
        "\nDATING_STRATEGY_COACH (you are coaching the user's next message — align all three variants):\n"
        f"- signals: {tag_line}\n"
        f"- {body}\n"
        f"{tier_hint}"
        f"- locale_hint: {locale}\n"
    )
