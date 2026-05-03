"""
Admin engagement agent: metrics + AI-suggested openers/revives.
Never exposes private message content; never sends messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.analytics_event import AnalyticsEvent
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.services.ai.gemini_client import GeminiClient
from app.services.ai.safe_ai import log_ai_fallback_triggered
from app.services.match_engine import MatchEngine

log = logging.getLogger("neyra.engagement")

STALL_EVENTS = ("stall_detected", "ai_stall_detected", "conversation_stall_detected")
REVIVE_EVENTS = ("revive_used", "ai_revive_used", "conversation_revive_used")


def _pair_filter(a_id: Any, b_id: Any):
    return or_(
        and_(Message.sender_id == a_id, Message.receiver_id == b_id),
        and_(Message.sender_id == b_id, Message.receiver_id == a_id),
    )


def _display_name(db: Session, uid: int) -> str:
    p = db.query(Profile).filter(Profile.user_id == int(uid)).first()
    return str(getattr(p, "display_name", "") or "").strip() or f"user_{uid}"


def engagement_overview(db: Session) -> dict[str, Any]:
    now = datetime.now(UTC)
    cutoff_dead = now - timedelta(days=3)
    stale_cutoff = now - timedelta(days=3)
    since_30d = now - timedelta(days=30)

    total_matches = int(db.query(Match).count())

    has_any_msg = db.query(Message.id).filter(_pair_filter(Match.user_a_id, Match.user_b_id)).exists()
    matches_with_message = int(db.query(Match).filter(has_any_msg).count())
    first_message_rate = float(matches_with_message) / float(max(1, total_matches))

    ab = db.query(Message.id).filter(and_(Message.sender_id == Match.user_a_id, Message.receiver_id == Match.user_b_id)).exists()
    ba = db.query(Message.id).filter(and_(Message.sender_id == Match.user_b_id, Message.receiver_id == Match.user_a_id)).exists()
    replied_both = int(db.query(Match).filter(ab, ba).count())
    reply_rate = float(replied_both) / float(max(1, total_matches))

    no_msg_exists = ~db.query(Message.id).filter(_pair_filter(Match.user_a_id, Match.user_b_id)).exists()
    dead_chats_count = int(db.query(Match).filter(Match.created_at < cutoff_dead).filter(no_msg_exists).count())

    chats_no_first_message = int(db.query(Match).filter(no_msg_exists).count())

    stale_count = 0
    sample = db.query(Match).order_by(Match.id.desc()).limit(400).all()
    for m in sample:
        a, b = int(m.user_a_id), int(m.user_b_id)
        last = (
            db.query(Message.created_at)
            .filter(_pair_filter(a, b))
            .order_by(Message.created_at.desc())
            .limit(1)
            .scalar()
        )
        if last and last < stale_cutoff:
            stale_count += 1

    deltas_h: list[float] = []
    for m in db.query(Match).order_by(Match.id.desc()).limit(400):
        a, b = int(m.user_a_id), int(m.user_b_id)
        first = (
            db.query(Message)
            .filter(_pair_filter(a, b))
            .order_by(Message.created_at.asc())
            .first()
        )
        if first and m.created_at:
            try:
                dh = (first.created_at - m.created_at).total_seconds() / 3600.0
                if dh >= 0:
                    deltas_h.append(float(dh))
            except Exception:
                continue
    avg_time_to_first_message_hours = float(sum(deltas_h) / len(deltas_h)) if deltas_h else None

    stall_n = int(
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.name.in_(STALL_EVENTS), AnalyticsEvent.created_at >= since_30d)
        .count()
    )
    revive_n = int(
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.name.in_(REVIVE_EVENTS), AnalyticsEvent.created_at >= since_30d)
        .count()
    )
    revive_success_rate = float(revive_n) / float(stall_n) if stall_n > 0 else None

    issues: list[str] = []
    if chats_no_first_message:
        issues.append(f"{chats_no_first_message} mutual match(es) have no messages yet")
    if stale_count:
        issues.append(f"{stale_count} chat(s) in sample with last message older than 3 days")

    return {
        "generated_at": now.isoformat(),
        "window_note": "Rates use all matches unless noted; stale chat count is sampled (last 400 matches).",
        "first_message_rate": round(first_message_rate, 4),
        "reply_rate": round(reply_rate, 4),
        "dead_chats_count": int(dead_chats_count),
        "chats_no_first_message_count": int(chats_no_first_message),
        "stale_chats_sample_count": int(stale_count),
        "matches_sampled_for_stale": len(sample),
        "avg_time_to_first_message_hours": round(avg_time_to_first_message_hours, 2) if avg_time_to_first_message_hours is not None else None,
        "revive_success_rate": round(revive_success_rate, 4) if revive_success_rate is not None else None,
        "revive_events_30d": int(revive_n),
        "stall_events_30d": int(stall_n),
        "total_matches": int(total_matches),
        "matches_with_any_message": int(matches_with_message),
        "issues": issues[:12],
    }


class _EngagementLLMRow(BaseModel):
    model_config = {"extra": "ignore"}

    type: str = Field(..., description="first_message_nudge | revive_chat | ai_message_suggestion | weak_match_hint")
    match_id: int
    user_id: int | None = None
    suggestion: str | None = None
    suggestions: list[str] = Field(default_factory=list)


class _EngagementLLMOut(BaseModel):
    model_config = {"extra": "ignore"}

    actions: list[_EngagementLLMRow] = Field(default_factory=list)


class _TonePackOut(BaseModel):
    """Three opener lines: light / flirty / deep (admin-only suggestions)."""

    model_config = {"extra": "ignore"}

    light: str = ""
    flirty: str = ""
    deep: str = ""


class _SingleLineOut(BaseModel):
    model_config = {"extra": "ignore"}

    message: str = ""


def _compat_score(db: Session, m: Match) -> float | None:
    pa = db.query(Profile).filter(Profile.user_id == int(m.user_a_id)).first()
    pb = db.query(Profile).filter(Profile.user_id == int(m.user_b_id)).first()
    if not pa or not pb:
        return None
    try:
        s, _ = MatchEngine.score(pa, pb)
        return float(s or 0)
    except Exception:
        return None


def _collect_candidates(db: Session, *, max_each: int = 12) -> dict[str, list[dict[str, Any]]]:
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=3)
    out: dict[str, list[dict[str, Any]]] = {"no_first_message": [], "dead_stale": [], "weak_match": []}

    matches = db.query(Match).order_by(Match.id.desc()).limit(350).all()
    for m in matches:
        mid = int(m.id)
        a, b = int(m.user_a_id), int(m.user_b_id)
        cnt = int(db.query(Message).filter(_pair_filter(a, b)).count())
        score = _compat_score(db, m)

        if cnt == 0 and len(out["no_first_message"]) < max_each:
            out["no_first_message"].append(
                {
                    "match_id": mid,
                    "user_a_id": a,
                    "user_b_id": b,
                    "user_a_name": _display_name(db, a),
                    "user_b_name": _display_name(db, b),
                    "compatibility_score": score,
                }
            )
        elif cnt > 0:
            last = (
                db.query(Message.created_at)
                .filter(_pair_filter(a, b))
                .order_by(Message.created_at.desc())
                .limit(1)
                .scalar()
            )
            if last and last < stale_cutoff and len(out["dead_stale"]) < max_each:
                out["dead_stale"].append(
                    {
                        "match_id": mid,
                        "user_a_id": a,
                        "user_b_id": b,
                        "user_a_name": _display_name(db, a),
                        "user_b_name": _display_name(db, b),
                        "last_message_at": last.isoformat(),
                        "compatibility_score": score,
                    }
                )

    weak_seen: set[int] = set()
    for m in matches:
        if len(out["weak_match"]) >= max_each:
            break
        mid = int(m.id)
        if mid in weak_seen:
            continue
        sc = _compat_score(db, m)
        if sc is not None and sc < 42:
            weak_seen.add(mid)
            a, b = int(m.user_a_id), int(m.user_b_id)
            out["weak_match"].append(
                {
                    "match_id": mid,
                    "user_a_id": a,
                    "user_b_id": b,
                    "user_a_name": _display_name(db, a),
                    "user_b_name": _display_name(db, b),
                    "compatibility_score": sc,
                }
            )

    return out


def _fallback_actions(candidates: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for row in candidates.get("no_first_message") or []:
        tones = {
            "light": "Привіт! Помітив(ла) наш матч — якщо ок, розкажеш одне цікаве про свій день? 😊",
            "flirty": "Схоже, ми з тобою добре «клікнули» в матчі — готовий(а) перевірити це в чаті? 😉",
            "deep": "Привіт. Що для тебе зараз важливіше в знайомствах — спокій, пригода чи щось третє?",
        }
        actions.append(
            {
                "type": "ai_message_suggestion",
                "match_id": int(row["match_id"]),
                "user_id": int(row["user_a_id"]),
                "user_a_name": row.get("user_a_name"),
                "user_b_name": row.get("user_b_name"),
                "suggestions": [tones["light"], tones["flirty"], tones["deep"]],
                "tones": tones,
            }
        )
    for row in candidates.get("dead_stale") or []:
        actions.append(
            {
                "type": "revive_chat",
                "match_id": int(row["match_id"]),
                "user_a_name": row.get("user_a_name"),
                "user_b_name": row.get("user_b_name"),
                "last_message_at": row.get("last_message_at"),
                "suggestion": "Привіт знову — якщо ще актуально, давай продовжимо розмову коротким планом на вихідні?",
            }
        )
    for row in candidates.get("weak_match") or []:
        actions.append(
            {
                "type": "weak_match_hint",
                "match_id": int(row["match_id"]),
                "user_a_name": row.get("user_a_name"),
                "user_b_name": row.get("user_b_name"),
                "suggestion": "Compatibility looks weak in scoring — consider refreshing profiles or running admin compatibility recompute.",
            }
        )
    return actions[:24]


def _gemini_actions_payload(candidates: dict[str, list[dict[str, Any]]]) -> str:
    slim: dict[str, Any] = {}
    for k, rows in candidates.items():
        slim[k] = [
            {
                "match_id": r.get("match_id"),
                "user_a_id": r.get("user_a_id"),
                "user_b_id": r.get("user_b_id"),
                "a": r.get("user_a_name"),
                "b": r.get("user_b_name"),
                "compat": r.get("compatibility_score"),
                "last_message_at": r.get("last_message_at"),
            }
            for r in rows
        ]
    return json.dumps(slim, ensure_ascii=False)


async def _call_gemini_for_actions(user_payload: str) -> _EngagementLLMOut | None:
    if not GeminiClient.enabled():
        return None
    system = (
        "You are a dating-app engagement assistant for admins. "
        "Output ONLY valid JSON with shape: {\"actions\":[{\"type\":\"...\",\"match_id\":int,\"user_id\":int|null,"
        "\"suggestion\":string|null,\"suggestions\":[string,...]}]}.\n"
        "Rules: no sexual content, no harassment, short natural messages (max ~120 chars each). "
        "Use Ukrainian if names look Ukrainian, otherwise English.\n"
        "Types:\n"
        "- first_message_nudge: one user_id to nudge first + single suggestion opener.\n"
        "- ai_message_suggestion: match_id + exactly 3 strings in suggestions IN ORDER: [light, flirty, deep].\n"
        "- revive_chat: match_id + single suggestion to reopen politely.\n"
        "- weak_match_hint: match_id + suggestion mentioning improving profiles or admin recompute (no blame).\n"
        "Do not include private chat history; only use provided names and ids."
    )
    user = f"CANDIDATES_JSON:\n{user_payload}\nProduce concise actions covering distinct match_ids."
    try:
        client = GeminiClient()
        raw = await client.generate_json(
            system_prompt=system,
            user_prompt=user,
            out_model=_EngagementLLMOut,
            timeout_s=25.0,
            max_retries=0,
            temperature=0.55,
            max_output_tokens=1200,
        )
        return raw if isinstance(raw, _EngagementLLMOut) else None
    except Exception as e:
        log_ai_fallback_triggered(
            endpoint="engagement/actions",
            locale=None,
            reason=type(e).__name__,
            error_message=str(e),
            provider="gemini",
        )
        return None


def build_engagement_actions(db: Session, *, use_ai: bool = True) -> dict[str, Any]:
    candidates = _collect_candidates(db)
    merged: list[dict[str, Any]] = []
    llm_had_actions = False

    if use_ai:
        try:
            out = asyncio.run(_call_gemini_for_actions(_gemini_actions_payload(candidates)))
        except RuntimeError:
            out = None
        if out and out.actions:
            llm_had_actions = True
            for a in out.actions[:24]:
                row: dict[str, Any] = {
                    "type": str(a.type or "").strip(),
                    "match_id": int(a.match_id),
                }
                if a.user_id is not None:
                    row["user_id"] = int(a.user_id)
                if a.suggestion:
                    row["suggestion"] = str(a.suggestion)[:500]
                if a.suggestions:
                    row["suggestions"] = [str(s)[:500] for s in a.suggestions[:6]]
                merged.append(row)

    if not merged:
        merged = _fallback_actions(candidates)

    for a in merged:
        _normalize_tones(a)
    _enrich_actions(merged, candidates)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "candidates_summary": {k: len(v) for k, v in candidates.items()},
        "actions": merged,
        "ai_used": bool(llm_had_actions),
    }


def _normalize_tones(a: dict[str, Any]) -> None:
    if str(a.get("type") or "") != "ai_message_suggestion":
        return
    ex = a.get("tones")
    if isinstance(ex, dict) and (ex.get("light") or ex.get("flirty") or ex.get("deep")):
        return
    s = a.get("suggestions") or []
    if len(s) >= 3:
        a["tones"] = {"light": str(s[0])[:500], "flirty": str(s[1])[:500], "deep": str(s[2])[:500]}


def _enrich_actions(actions: list[dict[str, Any]], candidates: dict[str, list[dict[str, Any]]]) -> None:
    by_mid: dict[int, dict[str, Any]] = {}
    for bucket in candidates.values():
        for row in bucket:
            by_mid[int(row["match_id"])] = row
    for a in actions:
        try:
            mid = int(a.get("match_id") or 0)
        except Exception:
            continue
        row = by_mid.get(mid)
        if not row:
            continue
        a.setdefault("user_a_name", row.get("user_a_name"))
        a.setdefault("user_b_name", row.get("user_b_name"))
        if row.get("last_message_at") and not a.get("last_message_at"):
            a["last_message_at"] = row.get("last_message_at")


def engagement_targets(db: Session, *, max_each: int = 12) -> dict[str, Any]:
    c = _collect_candidates(db, max_each=max_each)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "counts": {k: len(v) for k, v in c.items()},
        "no_first_message": c["no_first_message"],
        "stale_chats": c["dead_stale"],
        "weak_matches": c["weak_match"],
    }


def public_match_context(db: Session, match_id: int) -> dict[str, Any] | None:
    m = db.query(Match).filter(Match.id == int(match_id)).first()
    if not m:
        return None
    a, b = int(m.user_a_id), int(m.user_b_id)
    cnt = int(db.query(Message).filter(_pair_filter(a, b)).count())
    last_raw = None
    if cnt > 0:
        last_raw = (
            db.query(Message.created_at)
            .filter(_pair_filter(a, b))
            .order_by(Message.created_at.desc())
            .limit(1)
            .scalar()
        )
    last_iso = last_raw.isoformat() if last_raw else None
    return {
        "match_id": int(m.id),
        "user_a_id": a,
        "user_b_id": b,
        "user_a_name": _display_name(db, a),
        "user_b_name": _display_name(db, b),
        "compatibility_score": _compat_score(db, m),
        "messages_count": cnt,
        "last_message_at": last_iso,
    }


async def _call_gemini_tone_pack(base_context: str) -> _TonePackOut | None:
    if not GeminiClient.enabled():
        return None
    system = (
        "Output ONLY valid JSON: {\"light\":\"\",\"flirty\":\"\",\"deep\":\"\"}. "
        "Three first-message lines for a dating app match who have NOT chatted yet. "
        "light=friendly/casual, flirty=playful but respectful, deep=thoughtful. "
        "Each max ~130 characters. Ukrainian if names look Ukrainian, else English. "
        "No sexual content, no harassment. Do not quote private messages — only public names/ids context."
    )
    try:
        client = GeminiClient()
        raw = await client.generate_json(
            system_prompt=system,
            user_prompt=base_context,
            out_model=_TonePackOut,
            timeout_s=22.0,
            max_retries=0,
            temperature=0.6,
            max_output_tokens=500,
        )
        return raw if isinstance(raw, _TonePackOut) else None
    except Exception as e:
        log_ai_fallback_triggered(
            endpoint="engagement/tone_pack",
            locale=None,
            reason=type(e).__name__,
            error_message=str(e),
            provider="gemini",
        )
        return None


async def _call_gemini_single_message(base_context: str, instructions: str) -> str | None:
    if not GeminiClient.enabled():
        return None
    system = (
        "Output ONLY valid JSON: {\"message\":\"...\"}. "
        + instructions
        + " No sexual content, no harassment. Never include private chat transcripts."
    )
    try:
        client = GeminiClient()
        raw = await client.generate_json(
            system_prompt=system,
            user_prompt=base_context,
            out_model=_SingleLineOut,
            timeout_s=20.0,
            max_retries=0,
            temperature=0.55,
            max_output_tokens=300,
        )
        if isinstance(raw, _SingleLineOut) and (raw.message or "").strip():
            return str(raw.message).strip()[:500]
    except Exception as e:
        log_ai_fallback_triggered(
            endpoint="engagement/single_message",
            locale=None,
            reason=type(e).__name__,
            error_message=str(e),
            provider="gemini",
        )
        return None
    return None


def _fallback_tone_pack() -> dict[str, str]:
    return {
        "light": "Hey — we matched! If you’re up for it, what’s one good thing that happened to you this week?",
        "flirty": "Okay, we officially matched — should we test if the chat chemistry is as good as the algorithm says? 😉",
        "deep": "Hi! I’m curious — when you’re meeting someone new, what helps you feel comfortable opening up?",
    }


def _fallback_revive(na: str, nb: str) -> str:
    return (
        f"Hi again {na} & {nb} — no pressure, but if you’re still interested, "
        "want to pick one small topic and continue from there?"
    )[:500]


def _fallback_opener() -> str:
    return "Hey! Glad we matched — what’s something you’re looking forward to this month?"[:500]


def generate_engagement_copy(
    db: Session,
    *,
    match_id: int,
    kind: str,
    use_ai: bool = True,
) -> dict[str, Any]:
    """
    On-demand copy for one match. Never reads or returns private message bodies.
    kind: tones | opener | revive
    """
    k = str(kind or "").strip().lower()
    if k not in {"tones", "opener", "revive"}:
        return {"ok": False, "error": "invalid_kind"}
    ctx = public_match_context(db, match_id)
    if not ctx:
        return {"ok": False, "error": "match_not_found"}
    cnt = int(ctx.get("messages_count") or 0)
    if k == "tones" and cnt > 0:
        return {"ok": False, "error": "tones_only_when_no_messages", "detail": "Use revive when the chat already has messages."}
    if k == "opener" and cnt > 0:
        return {"ok": False, "error": "opener_only_when_no_messages"}
    if k == "revive" and cnt == 0:
        return {"ok": False, "error": "revive_requires_prior_messages"}

    pair = f'{ctx["user_a_name"]} · {ctx["user_b_name"]}'
    base = (
        f"Match {match_id}. Pair: {pair}. User ids: {ctx['user_a_id']}, {ctx['user_b_id']}. "
        f"Compatibility estimate: {ctx.get('compatibility_score')}. Total messages (count only): {cnt}."
    )
    if ctx.get("last_message_at"):
        base += f" Last message timestamp (no content): {ctx['last_message_at']}."

    ai_used = False
    out: dict[str, Any] = {
        "ok": True,
        "match_id": int(match_id),
        "kind": k,
        "pair_label": pair,
        "user_a_name": ctx.get("user_a_name"),
        "user_b_name": ctx.get("user_b_name"),
        "last_message_at": ctx.get("last_message_at"),
        "messages_count": cnt,
        "ai_used": False,
    }

    async def _run() -> None:
        nonlocal ai_used
        if not use_ai:
            return
        if k == "tones":
            pack = await _call_gemini_tone_pack(base)
            if pack and (pack.light or pack.flirty or pack.deep):
                ai_used = True
                out["tones"] = {"light": (pack.light or "")[:500], "flirty": (pack.flirty or "")[:500], "deep": (pack.deep or "")[:500]}
        elif k == "opener":
            msg = await _call_gemini_single_message(
                base,
                "One strong, natural first message. Max ~160 characters.",
            )
            if msg:
                ai_used = True
                out["opener"] = msg
        elif k == "revive":
            msg = await _call_gemini_single_message(
                base,
                "One polite message to gently reopen a conversation gone quiet. Acknowledge time passed without guilt-tripping. Max ~200 characters.",
            )
            if msg:
                ai_used = True
                out["revive_message"] = msg

    try:
        asyncio.run(_run())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_run())
        finally:
            try:
                loop.close()
            except Exception:
                pass

    if k == "tones":
        t = out.get("tones")
        if not isinstance(t, dict) or not any(str(t.get(x) or "").strip() for x in ("light", "flirty", "deep")):
            out["tones"] = _fallback_tone_pack()
    elif k == "opener":
        if not str(out.get("opener") or "").strip():
            out["opener"] = _fallback_opener()
    elif k == "revive":
        if not str(out.get("revive_message") or "").strip():
            out["revive_message"] = _fallback_revive(str(ctx.get("user_a_name") or ""), str(ctx.get("user_b_name") or ""))

    out["ai_used"] = bool(use_ai and ai_used)
    return out
