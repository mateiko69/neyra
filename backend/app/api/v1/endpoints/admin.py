from datetime import UTC, datetime, timedelta
from typing import Any
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Body
from fastapi.responses import FileResponse
from app.api.deps import get_db, get_admin_user, get_admin_actor
from app.models.device_token import DeviceToken
from app.models.user import User
from app.models.profile import Profile
from app.models.match import Match
from app.models.message import Message
from app.models.analytics_event import AnalyticsEvent
from app.models.ai_interaction_event import AiInteractionEvent
from app.services.analytics import track_event
from app.core.config import settings
from app.utils.datetime_utc import to_utc_aware
from app.services.ai.diagnostics import (
    get_fallback_count_24h,
    get_gemini_cache_stats_today,
    get_gemini_calls_minute,
    get_gemini_calls_today,
    get_gemini_retry_scheduled_today,
    get_gemini_success_fail_today,
    get_last_gemini_error,
    get_last_gemini_quota_error,
    get_last_provider_used,
    incr_fallback_24h,
    set_last_gemini_error,
    set_last_provider_used,
)
from app.services.ai.gemini_client import GeminiClient, GeminiError
from app.services.ai.safe_ai import log_ai_fallback_triggered
from pydantic import BaseModel
from app.services.engagement.agent import (
    build_engagement_actions,
    engagement_overview,
    engagement_targets,
    generate_engagement_copy,
)
from app.services.localization.report import load_localization_report
from app.services.localization.coverage import compute_localization_coverage
from app.services.localization.runtime_agent import apply_localization_agent_safe_fix, run_localization_agent_scan
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
import logging
import time
from sqlalchemy import text
from app.services.ai.diagnostics import ai_provider_operator_notice, get_fallback_count_24h, get_last_gemini_error
from app.services.ai.cache import get_redis
from app.services.system.uptime import uptime_seconds
from app.services.system.errors import api_errors_last_24h, last_errors, record_system_error
from app.services.system.full_analysis import build_full_system_analysis
from app.services.ai.health_snapshot import build_system_doctor_ai_extension, gemini_alert_bucket_should_emit
from sqlalchemy import or_
import json
from datetime import UTC, datetime, timedelta
from app.models.subscription import Subscription
from app.models.user_report import UserReport
from app.models.user_ai_memory import UserAiMemory
from app.models.swipe import Swipe
from app.models.analytics_event import AnalyticsEvent
from app.models.ai_interaction_event import AiInteractionEvent
from app.services.ai.diagnostics import get_last_gemini_quota_error
from app.models.promo_code import PromoCode
from app.models.referral_reward_grant import ReferralRewardGrant
from app.services.referral_rewards import referral_abuse_flags
from sqlalchemy.exc import IntegrityError
from app.services.match_engine import MatchEngine
from sqlalchemy import and_
from app.services.telegram_menu_qa import scan_telegram_bot_module
from app.services.e2e_qa import run_e2e_qa_scan
from app.services.qa.qa_agent import run_qa, load_latest_report, format_report
from app.services.demo_behavior import regenerate_demo_personalities
from app.services.demo_mode import (
    clear_demo_conversations,
    demo_mode_status,
    ensure_demo_profiles,
    regenerate_demo_profiles,
    set_demo_live_settings,
    set_demo_mode_enabled,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _actor_meta(admin_actor: User | dict) -> dict:
    if isinstance(admin_actor, dict):
        return {"actor_type": admin_actor.get("type") or "service", "actor_name": admin_actor.get("name") or "telegram_admin_bot"}
    return {"actor_type": "user", "actor_name": str(getattr(admin_actor, "email", "") or "")}


def _actor_user_id(admin_actor: User | dict) -> int | None:
    if isinstance(admin_actor, dict):
        return None
    try:
        return int(getattr(admin_actor, "id", None))
    except Exception:
        return None

def _is_production_env() -> bool:
    env = str(getattr(settings, "ENV", "") or "").strip().lower()
    return env in ("production", "prod")


def _ensure_not_production() -> None:
    if _is_production_env():
        raise HTTPException(status_code=403, detail="Not allowed in production")


def _ensure_localization_gemini_tools_allowed() -> None:
    """Allow Gemini disk-writes from admin only outside production, unless explicitly overridden."""
    if _is_production_env() and not bool(getattr(settings, "LOCALIZATION_DEV_TOOLS_ENABLED", False)):
        raise HTTPException(
            status_code=403,
            detail="Localization Gemini tools are blocked in production unless LOCALIZATION_DEV_TOOLS_ENABLED=true",
        )


def _rate(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return float(num) / float(den)


def _retention_last_tick_redis() -> dict | None:
    try:
        r = get_redis()
        if not r:
            return None
        raw = r.get("retention:last_tick_stats")
        if not raw:
            return None
        s = raw.decode() if isinstance(raw, bytes) else str(raw)
        out = json.loads(s)
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def _safe_int(x) -> int:
    try:
        return int(x or 0)
    except Exception:
        return 0


def _meta(d: dict | None) -> dict:
    return d if isinstance(d, dict) else {}

@router.get("/dashboard")
def admin_dashboard(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    return {
        "users": db.query(User).count(),
        "profiles": db.query(Profile).count(),
        "matches": db.query(Match).count(),
        "messages": db.query(Message).count(),
        "analytics_events": db.query(AnalyticsEvent).count(),
    }

@router.get("/events")
def recent_events(limit: int = 50, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    rows = db.query(AnalyticsEvent).order_by(AnalyticsEvent.id.desc()).limit(limit).all()
    return [{"id": x.id, "name": x.name, "user_id": x.user_id, "payload_json": x.payload_json} for x in rows]


@router.get("/funnel")
def funnel(days: int = 7, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """
    Lightweight conversion funnel diagnostics aggregated from AnalyticsEvent.
    Counts only (no message content).
    """
    days = max(1, min(int(days or 7), 90))
    since = datetime.now(UTC) - timedelta(days=days)

    funnel_events = [
        "social_login_success",
        "onboarding_completed",
        "ai_compatibility_used_in_match_feed",
        "first_match_created",
        "first_message_prompt_shown",
        "ai_opener_used_after_match",
        "first_message_sent",
        "first_message_ai_assisted",
        "first_reply_received",
        "first_message_followup_suggested",
    ]

    rows = (
        db.query(
            AnalyticsEvent.name.label("name"),
            func.count(AnalyticsEvent.id).label("events"),
            func.count(func.distinct(AnalyticsEvent.user_id)).label("users"),
        )
        .filter(AnalyticsEvent.created_at >= since)
        .filter(AnalyticsEvent.name.in_(funnel_events))
        .group_by(AnalyticsEvent.name)
        .all()
    )
    by_name = {r.name: {"events": int(r.events or 0), "users": int(r.users or 0)} for r in rows}
    for n in funnel_events:
        by_name.setdefault(n, {"events": 0, "users": 0})

    def u(name: str) -> int:
        return int(by_name.get(name, {}).get("users") or 0)

    stages = [
        {"key": "login", "label": "Social login success", "event": "social_login_success", "users": u("social_login_success")},
        {"key": "onboarding", "label": "Onboarding completed", "event": "onboarding_completed", "users": u("onboarding_completed")},
        {"key": "discover", "label": "Discover viewed (AI used)", "event": "ai_compatibility_used_in_match_feed", "users": u("ai_compatibility_used_in_match_feed")},
        {"key": "match", "label": "First match created", "event": "first_match_created", "users": u("first_match_created")},
        {"key": "message", "label": "First message sent", "event": "first_message_sent", "users": u("first_message_sent")},
        {"key": "reply", "label": "First reply received", "event": "first_reply_received", "users": u("first_reply_received")},
    ]

    def rate(num: int, den: int) -> float | None:
        if den <= 0:
            return None
        return float(num) / float(den)

    conversions: list[dict] = []
    for i in range(1, len(stages)):
        a = stages[i - 1]
        b = stages[i]
        conversions.append(
            {
                "from": a["key"],
                "to": b["key"],
                "from_users": a["users"],
                "to_users": b["users"],
                "rate": rate(b["users"], a["users"]),
            }
        )

    ai_assisted_users = u("first_message_ai_assisted")
    first_message_users = u("first_message_sent")
    ai_split = {
        "first_message_users": first_message_users,
        "ai_assisted_users": ai_assisted_users,
        "non_ai_users": max(0, first_message_users - ai_assisted_users),
        "ai_assisted_rate": rate(ai_assisted_users, first_message_users),
    }

    return {
        "window_days": days,
        "since": since.isoformat(),
        "events": by_name,
        "stages": stages,
        "conversions": conversions,
        "ai_split": ai_split,
    }


@router.get("/ai-product-metrics")
def ai_product_metrics(days: int = 7, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """
    AI assist product metrics: suggestion funnel, mode conversion, chat drop-off by stage.
    Uses AnalyticsEvent only (no message content).
    """
    days = max(1, min(int(days or 7), 90))
    since = datetime.now(UTC) - timedelta(days=days)
    names = [
        "ai_suggestion_shown",
        "ai_suggestion_used",
        "ai_rewrite_used",
        "stage_detected",
        "meeting_suggested",
        "user_replied_after_ai",
    ]

    rows = (
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.created_at >= since, AnalyticsEvent.name.in_(names))
        .order_by(AnalyticsEvent.id.asc())
        .all()
    )

    def parse_payload(row: AnalyticsEvent) -> dict[str, Any]:
        try:
            data = json.loads(row.payload_json or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    counts: dict[str, int] = {n: 0 for n in names}
    distinct_users: dict[str, set[int]] = {n: set() for n in names}

    shown_by_mode: dict[str, int] = {}
    used_by_mode: dict[str, int] = {}
    replied_by_mode: dict[str, int] = {}

    events_by_pair: dict[tuple[int, int], list[tuple[datetime, str, dict[str, Any]]]] = {}

    for row in rows:
        name = str(row.name or "")
        if name in counts:
            counts[name] += 1
        uid = int(row.user_id or 0)
        if uid and name in distinct_users:
            distinct_users[name].add(uid)
        pl = parse_payload(row)
        mode_key = str(pl.get("conversation_mode") or pl.get("mode") or "unknown").strip() or "unknown"

        if name == "ai_suggestion_shown":
            shown_by_mode[mode_key] = shown_by_mode.get(mode_key, 0) + 1
            pid = int(pl.get("partner_user_id") or 0)
            if uid and pid:
                events_by_pair.setdefault((uid, pid), []).append((row.created_at, name, pl))
        elif name == "ai_suggestion_used":
            used_by_mode[mode_key] = used_by_mode.get(mode_key, 0) + 1
        elif name == "user_replied_after_ai":
            replied_by_mode[mode_key] = replied_by_mode.get(mode_key, 0) + 1
            pid = int(pl.get("partner_user_id") or 0)
            if uid and pid:
                events_by_pair.setdefault((uid, pid), []).append((row.created_at, name, pl))

    def rate(num: int, den: int) -> float | None:
        if den <= 0:
            return None
        return float(num) / float(den)

    mode_keys = sorted(set(shown_by_mode) | set(used_by_mode) | set(replied_by_mode))
    mode_funnel = []
    for m in mode_keys:
        s = int(shown_by_mode.get(m, 0))
        u = int(used_by_mode.get(m, 0))
        r = int(replied_by_mode.get(m, 0))
        mode_funnel.append(
            {
                "mode": m,
                "ai_suggestion_shown": s,
                "ai_suggestion_used": u,
                "user_replied_after_ai": r,
                "use_rate_vs_shown": rate(u, s),
                "reply_rate_vs_shown": rate(r, s),
            }
        )

    dropoff_by_stage: dict[str, int] = {}
    engaged_by_stage: dict[str, int] = {}
    for _pair, evs in events_by_pair.items():
        evs_sorted = sorted(evs, key=lambda x: x[0])
        last_shown_pl: dict[str, Any] | None = None
        last_shown_ts: datetime | None = None
        for ts, ev_name, ev_pl in evs_sorted:
            if ev_name == "ai_suggestion_shown":
                last_shown_pl = ev_pl
                last_shown_ts = ts
        if last_shown_pl is None or last_shown_ts is None:
            continue
        has_reply_after = any(
            ts >= last_shown_ts and ev_name == "user_replied_after_ai" for ts, ev_name, _ in evs_sorted
        )
        stage = str(last_shown_pl.get("conversation_stage") or "unknown").strip() or "unknown"
        if has_reply_after:
            engaged_by_stage[stage] = engaged_by_stage.get(stage, 0) + 1
        else:
            dropoff_by_stage[stage] = dropoff_by_stage.get(stage, 0) + 1

    return {
        "window_days": days,
        "since": since.isoformat(),
        "counts": counts,
        "distinct_users": {k: len(v) for k, v in distinct_users.items()},
        "totals": {
            "use_rate_vs_shown": rate(counts["ai_suggestion_used"], counts["ai_suggestion_shown"]),
            "reply_rate_vs_shown": rate(counts["user_replied_after_ai"], counts["ai_suggestion_shown"]),
            "rewrite_rate_vs_messages_note": "ai_rewrite_used is counted on send with assist_meta.kind=rewrite; compare to message_sent separately.",
        },
        "mode_funnel": mode_funnel,
        "chat_dropoff_last_stage": dropoff_by_stage,
        "chat_replied_after_suggestion_by_stage": engaged_by_stage,
    }


@router.get("/ai-ops-insights")
def ai_ops_insights(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """
    Runtime AI ops: Gemini success/fail (best-effort Redis), retries, fallbacks, quota hints.
    Includes push/retention diagnostics (no message content).
    """
    sf = get_gemini_success_fail_today()
    success = int(sf.get("success") or 0)
    fail = int(sf.get("fail") or 0)
    total = success + fail
    device_token_rows = int(db.execute(select(func.count()).select_from(DeviceToken)).scalar() or 0)
    device_distinct_users = int(db.execute(select(func.count(func.distinct(DeviceToken.user_id)))).scalar() or 0)
    return {
        "gemini": {
            "calls_today": get_gemini_calls_today(),
            "calls_last_minute": get_gemini_calls_minute(),
            "cache": get_gemini_cache_stats_today(),
            "success_today": success,
            "fail_today": fail,
            "success_rate_today": _rate(success, total),
            "retry_scheduled_today": get_gemini_retry_scheduled_today(),
            "last_error": get_last_gemini_error(),
            "last_quota_error": get_last_gemini_quota_error(),
            "last_provider": get_last_provider_used(),
        },
        "fallback": {
            "count_24h": get_fallback_count_24h(),
        },
        "locale_debug": {
            "note": "Use server logs with event=ai_locale_context for ui_locale_raw vs ai_locale_normalized per endpoint.",
        },
        "production_monitor": {
            "api_spam": "Browser: NEXT_PUBLIC_DEBUG_API=1 → [neyra][api-hot] for /nav/badges and /messages; apiFetch dedupes in-flight GETs.",
            "auth_401": "First 401 clears token, sets authSessionTerminated, single redirect to /login; further apiFetch throws until new login.",
            "gemini_retries": "Single HTTP attempt per generate_json (no in-request retry). Use fallback on failure.",
            "fallback_analyzer": "fallback.count_24h + AiInteractionEvent; server ai_fallback_used analytics.",
            "retention_growth": "runtime.retention_last_tick + logs retention_tick_candidates, growth_engine_* (push needs DeviceToken rows).",
        },
        "runtime": {
            "device_token_rows": device_token_rows,
            "device_distinct_users": device_distinct_users,
            "retention_last_tick": _retention_last_tick_redis(),
            "polling_ux": {
                "tip": "If users_considered=0, retention only iterates users with at least one DeviceToken row.",
                "health_ready": "Docker compose healthcheck hits /health/ready; increase interval to reduce log noise.",
                "frontend": "Nav badges + chat polls pause when tab hidden; min poll intervals ≥5s; see CHAT_*_POLL_MS / BADGE_POLL_INTERVAL_MS.",
            },
        },
    }


@router.get("/ai-quality")
def ai_quality(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """
    Aggregated AI Copilot quality dashboard.
    No raw messages; no per-user memory exposure.
    """
    now = datetime.now(UTC)
    rows = db.query(AiInteractionEvent).all()

    total = len(rows)
    counts: dict[str, int] = {}
    style_sent: dict[str, int] = {"light": 0, "flirty": 0, "deep": 0}
    style_replied: dict[str, int] = {"light": 0, "flirty": 0, "deep": 0}
    style_shown: dict[str, int] = {"light": 0, "flirty": 0, "deep": 0}
    style_selected: dict[str, int] = {"light": 0, "flirty": 0, "deep": 0}
    sources: dict[str, dict[str, int]] = {}

    event_users: set[int] = set()
    first_event_at: dict[int, datetime] = {}

    for r in rows:
        et = str(getattr(r, "event_type", "") or "").strip()
        counts[et] = counts.get(et, 0) + 1
        uid = int(getattr(r, "user_id", 0) or 0)
        if uid:
            event_users.add(uid)
            dt = getattr(r, "created_at", None)
            if dt is not None:
                if getattr(dt, "tzinfo", None) is None:
                    dt = dt.replace(tzinfo=UTC)
                prev = first_event_at.get(uid)
                if prev is None or dt < prev:
                    first_event_at[uid] = dt

        meta = _meta(getattr(r, "metadata_json", None))
        src = str(meta.get("source") or "").strip() or "unknown"
        sources.setdefault(src, {"shown": 0, "selected": 0, "edited": 0, "sent": 0, "partner_replied": 0, "meeting_suggested": 0, "meeting_rejected": 0})
        if et == "option_shown":
            sources[src]["shown"] += 1
        elif et == "option_selected":
            sources[src]["selected"] += 1
        elif et == "option_edited":
            sources[src]["edited"] += 1
        elif et == "message_sent":
            sources[src]["sent"] += 1
        elif et == "partner_replied":
            sources[src]["partner_replied"] += 1
        elif et == "meeting_suggested":
            sources[src]["meeting_suggested"] += 1
        elif et == "meeting_rejected":
            sources[src]["meeting_rejected"] += 1

        # style breakdowns
        if et == "option_selected":
            style = str(meta.get("style") or "").strip().lower()
            if style in style_selected:
                style_selected[style] += 1
        if et == "option_shown":
            # when shown, style isn't explicit; attribute to source only
            pass
        if et == "message_sent":
            style = str(meta.get("selected_style") or "").strip().lower()
            if style in style_sent:
                style_sent[style] += 1
        if et == "partner_replied":
            style = str(meta.get("previous_style") or "").strip().lower()
            if style in style_replied:
                style_replied[style] += 1

    options_shown = _safe_int(counts.get("option_shown"))
    options_selected = _safe_int(counts.get("option_selected"))
    options_edited = _safe_int(counts.get("option_edited"))
    message_sent = _safe_int(counts.get("message_sent"))
    partner_replied = _safe_int(counts.get("partner_replied"))
    meeting_suggested = _safe_int(counts.get("meeting_suggested"))
    meeting_rejected = _safe_int(counts.get("meeting_rejected"))

    selection_rate = _rate(options_selected, options_shown)
    edited_rate = _rate(options_edited, options_selected)
    partner_reply_rate = _rate(partner_replied, message_sent)
    meeting_suggestion_rate = _rate(meeting_suggested, message_sent)
    meeting_rejected_rate = _rate(meeting_rejected, meeting_suggested)

    # Styles reply rate = replies / sent
    styles_out: dict[str, dict] = {}
    for st in ["light", "flirty", "deep"]:
        sent = int(style_sent.get(st) or 0)
        rep = int(style_replied.get(st) or 0)
        styles_out[st] = {"shown": int(style_shown.get(st) or 0), "selected": int(style_selected.get(st) or 0), "partner_replied": rep, "reply_rate": _rate(rep, sent)}

    # Sources summary
    sources_out: dict[str, dict] = {}
    for src, c in sources.items():
        sources_out[src] = {
            "shown": int(c.get("shown") or 0),
            "selected": int(c.get("selected") or 0),
            "selection_rate": _rate(int(c.get("selected") or 0), int(c.get("shown") or 0)),
            "edited": int(c.get("edited") or 0),
            "edited_rate": _rate(int(c.get("edited") or 0), int(c.get("selected") or 0)),
            "sent": int(c.get("sent") or 0),
            "partner_replied": int(c.get("partner_replied") or 0),
            "partner_reply_rate": _rate(int(c.get("partner_replied") or 0), int(c.get("sent") or 0)),
        }

    # Quality flags
    quality_flags: list[dict] = []
    if edited_rate > 0.45:
        quality_flags.append({"type": "high_edit_rate", "message": "Користувачі часто редагують AI-відповіді — стиль треба покращити"})
    if selection_rate < 0.20 and options_shown >= 20:
        quality_flags.append({"type": "low_selection_rate", "message": "Користувачі рідко обирають варіанти — підказки слабкі"})
    if partner_reply_rate < 0.25 and message_sent >= 20:
        quality_flags.append({"type": "low_partner_reply_rate", "message": "Партнери рідко відповідають після AI-повідомлень — тексти неефективні"})
    if meeting_rejected_rate > 0.30 and meeting_suggested >= 10:
        quality_flags.append({"type": "meeting_too_aggressive", "message": "Запрошення на зустріч часто відхиляють — meeting engine занадто агресивний"})
    # Flirty much worse
    if styles_out["flirty"]["reply_rate"] + 0.12 < min(styles_out["light"]["reply_rate"], styles_out["deep"]["reply_rate"]) and (style_sent.get("flirty") or 0) >= 10:
        quality_flags.append({"type": "flirty_underperforming", "message": "Флірт-стиль дає гірші відповіді партнера — можливо, занадто крінжово"})

    # Premium block (best-effort, current entitlement)
    free_ai_users = 0
    premium_ai_users = 0
    trial_started_after_ai = 0
    premium_conversion_after_ai = 0
    if event_users:
        users = db.query(User).filter(User.id.in_(list(event_users))).all()
        for u in users:
            pu = to_utc_aware(getattr(u, "premium_until", None))
            is_premium = bool(pu is not None and pu > now)
            if is_premium:
                premium_ai_users += 1
            else:
                free_ai_users += 1
            ts = getattr(u, "trial_started_at", None)
            if ts and getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=UTC)
            first = first_event_at.get(int(u.id))
            if ts and first and first <= ts:
                trial_started_after_ai += 1
            # naive "conversion": premium active and had AI events before premium_until was set (proxy)
            if is_premium and first:
                premium_conversion_after_ai += 1

    return {
        "summary": {
            "ai_events_total": int(total),
            "options_shown": int(options_shown),
            "options_selected": int(options_selected),
            "selection_rate": selection_rate,
            "edited_rate": edited_rate,
            "partner_reply_rate": partner_reply_rate,
            "meeting_suggestion_rate": meeting_suggestion_rate,
            "meeting_rejected_rate": meeting_rejected_rate,
        },
        "styles": styles_out,
        "sources": sources_out,
        "quality_flags": quality_flags,
        "premium": {
            "free_ai_users": int(free_ai_users),
            "premium_ai_users": int(premium_ai_users),
            "trial_started_after_ai": int(trial_started_after_ai),
            "premium_conversion_after_ai": int(premium_conversion_after_ai),
        },
    }


@router.get("/localization-quality")
def localization_quality(admin_actor: User | dict = Depends(get_admin_actor)):
    """Read-only localization diagnostics generated by scripts/localization_agent.py."""
    return load_localization_report()


@router.get("/localization/coverage")
def admin_localization_coverage(admin_actor: User | dict = Depends(get_admin_actor)):
    """Per-locale translation coverage vs frontend/locales/en.json (filesystem only, no secrets)."""
    return compute_localization_coverage()


def _backend_project_root() -> Path:
    """Directory that contains the Python package `app` (e.g. NEYRA/backend or /app in Docker)."""
    return Path(__file__).resolve().parents[4]


def _repo_root() -> Path:
    """Monorepo root (NEYRA) under NEYRA/backend/app/...; otherwise backend image / project root (/app)."""
    br = _backend_project_root()
    if br.name == "backend" and (br / "app").is_dir():
        return br.parent
    return br


def _admin_monorepo_root_if_any() -> Path | None:
    """If this file lives under <repo>/backend/app/..., return <repo>; else None (Docker /app-only layout)."""
    br = _backend_project_root()
    if br.name == "backend" and (br / "app").is_dir():
        return br.parent
    return None


BACKUP_RESTORE_PHRASE = "RESTORE NEYRA BACKUP"
_BACKUP_ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _backup_dir() -> Path:
    mr = _admin_monorepo_root_if_any()
    if mr is not None:
        return (mr / "backups").resolve()
    return (_backend_project_root() / "backups").resolve()


def _normalize_database_url(url: str) -> str:
    """Normalize SQLAlchemy/async DSNs for backend detection and pg_dump."""
    u = str(url or "").strip()
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://") :]
    if "://" in u:
        scheme, rest = u.split("://", 1)
        if "+" in scheme:
            scheme = scheme.split("+", 1)[0]
        u = f"{scheme}://{rest}"
    return u


def _database_kind() -> str:
    url = _normalize_database_url(str(getattr(settings, "DATABASE_URL", "") or ""))
    if url.startswith("sqlite"):
        return "sqlite"
    if url.startswith("postgresql://"):
        return "postgresql"
    return "unknown"


def _parse_postgres_dsn(url: str) -> dict[str, Any]:
    u = _normalize_database_url(url)
    parts = urlsplit(u)
    if parts.scheme not in {"postgresql", "postgres"}:
        raise HTTPException(status_code=400, detail={"error": "invalid_database_url", "detail": "expected postgresql DSN"})
    user = unquote(parts.username or "postgres")
    password = unquote(parts.password or "") if parts.password else ""
    host = parts.hostname or "localhost"
    port = int(parts.port or 5432)
    path = (parts.path or "/").lstrip("/").split("?", 1)[0]
    dbname = unquote(path) if path else "postgres"
    return {"user": user, "password": password, "host": host, "port": port, "dbname": dbname}


def _sqlite_db_path() -> Path:
    url = str(getattr(settings, "DATABASE_URL", "") or "")
    if not _normalize_database_url(url).startswith("sqlite"):
        raise HTTPException(
            status_code=400,
            detail={"error": "not_supported", "detail": "file restore applies to SQLite only; use psql for PostgreSQL .sql dumps"},
        )
    path = url.split("sqlite:///")[-1] if "sqlite:///" in url else url.split("sqlite://")[-1]
    if not path or path == ":memory:":
        raise HTTPException(status_code=400, detail={"error": "not_supported", "detail": "file-backed sqlite database required"})
    br = _backend_project_root()
    if path.startswith("./"):
        return (br / path[2:]).resolve()
    return Path(path).resolve()


def _backup_type_for_filename(filename: str) -> str:
    low = str(filename or "").lower()
    if low.endswith(".sqlite"):
        return "sqlite"
    if low.endswith(".db"):
        return "sqlite"
    if low.endswith(".sql"):
        return "postgresql"
    return "unknown"


def _backup_metadata(path: Path) -> dict:
    st = path.stat()
    return {
        "filename": path.name,
        "created_at": datetime.fromtimestamp(float(st.st_mtime), UTC).isoformat(),
        "size_bytes": int(st.st_size),
        "type": _backup_type_for_filename(path.name),
        "environment": str(getattr(settings, "ENV", "") or ""),
    }


def _validate_backup_filename(filename: str) -> str:
    name = str(filename or "").strip()
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail={"error": "invalid_filename"})
    if "/" in name or "\\" in name or Path(name).name != name:
        raise HTTPException(status_code=400, detail={"error": "invalid_filename"})
    if any(ch not in _BACKUP_ALLOWED_CHARS for ch in name):
        raise HTTPException(status_code=400, detail={"error": "invalid_filename"})
    if _backup_type_for_filename(name) not in {"sqlite", "postgresql"}:
        raise HTTPException(status_code=400, detail={"error": "invalid_filename"})
    return name


def _safe_backup_path(filename: str, *, must_exist: bool = True) -> Path:
    safe_name = _validate_backup_filename(filename)
    base = _backup_dir()
    candidate = (base / safe_name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail={"error": "invalid_filename"})
    if must_exist and not candidate.exists():
        raise HTTPException(status_code=404, detail={"error": "backup_not_found"})
    if must_exist and not candidate.is_file():
        raise HTTPException(status_code=404, detail={"error": "backup_not_found"})
    return candidate


def _log_backup_action(db: Session, admin_actor: User | dict, payload: dict) -> None:
    try:
        track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={**(payload or {}), **_actor_meta(admin_actor)})
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        record_system_error("admin_backup_action_log_failed", str(e))


def _copy_sqlite_backup(prefix: str = "neyra_backup") -> dict:
    src = _sqlite_db_path()
    if not src.exists():
        logger.warning("sqlite_backup_aborted db_missing path=%s", src)
        raise HTTPException(status_code=404, detail={"error": "db_file_not_found"})
    dst_dir = _backup_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    dst = (dst_dir / f"{prefix}_{ts}.sqlite").resolve()
    suffix = 1
    while dst.exists():
        dst = (dst_dir / f"{prefix}_{ts}_{suffix}.sqlite").resolve()
        suffix += 1
    logger.info("sqlite_backup_started src=%s dst_dir=%s", src, dst_dir)
    try:
        import shutil

        shutil.copy2(src, dst)
    except Exception as e:
        logger.exception("sqlite_backup_failed src=%s dst=%s", src, dst)
        record_system_error("backup_db_failed", str(e))
        raise HTTPException(status_code=500, detail={"error": "backup_failed"})
    meta = _backup_metadata(dst)
    logger.info("sqlite_backup_finished file=%s size_bytes=%s", meta["filename"], meta["size_bytes"])
    return {
        "filename": meta["filename"],
        "size_bytes": meta["size_bytes"],
        "created_at": meta["created_at"],
    }


def _pg_dump_backup(prefix: str = "neyra_backup") -> dict[str, Any]:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise HTTPException(
            status_code=500,
            detail={"error": "pg_dump_not_found", "detail": "pg_dump is not installed or not on PATH; install postgresql-client in the API image"},
        )
    url = str(getattr(settings, "DATABASE_URL", "") or "")
    info = _parse_postgres_dsn(url)
    dst_dir = _backup_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}.sql"
    dst = (dst_dir / filename).resolve()
    suffix_n = 1
    while dst.exists():
        filename = f"{prefix}_{ts}_{suffix_n}.sql"
        dst = (dst_dir / filename).resolve()
        suffix_n += 1
    env = os.environ.copy()
    if info.get("password"):
        env["PGPASSWORD"] = str(info["password"])
    cmd = [
        pg_dump,
        "-h",
        str(info["host"]),
        "-p",
        str(info["port"]),
        "-U",
        str(info["user"]),
        "-d",
        str(info["dbname"]),
        "--no-owner",
        "--no-acl",
        "-F",
        "p",
        "-f",
        str(dst),
    ]
    logger.info("pg_dump_backup_started dst=%s host=%s db=%s", dst, info["host"], info["dbname"])
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        try:
            if dst.exists():
                dst.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=504, detail={"error": "backup_timeout", "detail": "pg_dump exceeded time limit"})
    except OSError as e:
        raise HTTPException(status_code=500, detail={"error": "pg_dump_failed", "detail": f"failed to run pg_dump: {e}"}) from e
    if proc.returncode != 0:
        try:
            if dst.exists():
                dst.unlink()
        except Exception:
            pass
        err_tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-2000:]
        hint = err_tail or f"exit code {proc.returncode}"
        raise HTTPException(status_code=500, detail={"error": "pg_dump_failed", "detail": hint})
    if not dst.exists() or dst.stat().st_size < 1:
        try:
            if dst.exists():
                dst.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail={"error": "backup_empty", "detail": "pg_dump did not produce a non-empty file"})
    meta = _backup_metadata(dst)
    logger.info("pg_dump_backup_finished file=%s size_bytes=%s", meta["filename"], meta["size_bytes"])
    return {
        "filename": meta["filename"],
        "size_bytes": meta["size_bytes"],
        "created_at": meta["created_at"],
    }


def _create_db_backup(prefix: str) -> dict[str, Any]:
    kind = _database_kind()
    if kind == "sqlite":
        return _copy_sqlite_backup(prefix=prefix)
    if kind == "postgresql":
        return _pg_dump_backup(prefix=prefix)
    raise HTTPException(
        status_code=400,
        detail={"error": "not_supported", "detail": f"backup not implemented for database kind: {kind}"},
    )


@router.post("/localization/scan")
def localization_scan(
    admin_actor: User | dict = Depends(get_admin_actor),
):
    """Run offline localization scan and return report (dev/non-prod only)."""
    _ensure_not_production()
    script = _repo_root() / "scripts" / "localization_agent.py"
    if not script.exists():
        raise HTTPException(status_code=404, detail="localization_agent.py not found")
    try:
        subprocess.run([sys.executable, str(script), "--scan"], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail={"error": "scan_failed", "stderr": (e.stderr or "")[-2000:]})
    return load_localization_report()


@router.post("/localization/fix")
def localization_fix(
    admin_actor: User | dict = Depends(get_admin_actor),
    payload: dict = Body(default_factory=dict),
):
    """Run safe localization auto-fix (high confidence) and return updated report (dev/non-prod only)."""
    _ensure_not_production()
    confirm = bool(payload.get("confirm"))
    if not confirm:
        raise HTTPException(status_code=400, detail={"error": "confirm_required"})
    script = _repo_root() / "scripts" / "localization_agent.py"
    if not script.exists():
        raise HTTPException(status_code=404, detail="localization_agent.py not found")
    try:
        subprocess.run([sys.executable, str(script), "--fix"], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail={"error": "fix_failed", "stderr": (e.stderr or "")[-2000:]})
    return load_localization_report()


@router.get("/localization-agent/scan")
def admin_localization_agent_scan(admin_actor: User | dict = Depends(get_admin_actor)):
    """Runtime localization quality scan (JSON files + heuristics). No user data."""
    return run_localization_agent_scan()


@router.post("/localization-agent/fix")
def admin_localization_agent_fix(
    admin_actor: User | dict = Depends(get_admin_actor),
    payload: dict = Body(default_factory=dict),
):
    """Safe auto-fix: fill missing keys from English, fix obvious placeholders, UK city Latin→Cyrillic. Dev/staging only."""
    _ensure_not_production()
    if not bool(payload.get("confirm")):
        raise HTTPException(status_code=400, detail={"error": "confirm_required"})
    mode = str(payload.get("mode") or "safe").strip().lower()
    out = apply_localization_agent_safe_fix(confirm=True, mode=mode)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out)
    return out


def _run_gemini_localize_script(*, locales_csv: str | None, limit: int | None) -> dict[str, Any]:
    repo = _repo_root()
    script = repo / "frontend" / "scripts" / "gemini-localize-all.mjs"
    if not script.exists():
        raise HTTPException(status_code=404, detail="gemini-localize-all.mjs not found")
    cmd: list[str] = ["node", str(script)]
    if locales_csv:
        cmd.extend(["--locales", locales_csv])
    if limit is not None and limit > 0:
        cmd.extend(["--limit", str(int(limit))])
    env = {**os.environ}
    if (settings.GEMINI_API_KEY or "").strip():
        env["GEMINI_API_KEY"] = str(settings.GEMINI_API_KEY).strip()
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(repo / "frontend"),
            timeout=3600,
        )
    except subprocess.TimeoutExpired as e:
        raise HTTPException(status_code=504, detail={"error": "gemini_localize_timeout", "stderr": (e.stderr or "")[-2000:]})
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "gemini_localize_failed", "stderr": (e.stderr or "")[-4000:]},
        )
    report_path = repo / "reports" / "localization_report.json"
    report: Any = None
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            report = {"path": str(report_path), "note": "could_not_parse"}
    return {"ok": True, "report": report}


@router.post("/localization/gemini/translate")
def admin_localization_gemini_translate(
    admin_actor: User | dict = Depends(get_admin_actor),
    payload: dict = Body(default_factory=dict),
):
    """
    Run `frontend/scripts/gemini-localize-all.mjs` for one or more comma-separated locales.
    Writes locale JSON + `reports/localization_report.json` on the API host filesystem.
    """
    _ensure_localization_gemini_tools_allowed()
    locales_csv = str(payload.get("locales") or payload.get("locale") or "").strip()
    if not locales_csv:
        raise HTTPException(status_code=400, detail={"error": "locale_or_locales_required"})
    raw_limit = payload.get("limit")
    limit: int | None = None
    try:
        if raw_limit is not None and str(raw_limit).strip() != "":
            limit = max(0, int(raw_limit))
    except Exception:
        limit = None
    return _run_gemini_localize_script(locales_csv=locales_csv, limit=limit)


@router.post("/localization/gemini/translate-all")
def admin_localization_gemini_translate_all(
    admin_actor: User | dict = Depends(get_admin_actor),
    payload: dict = Body(default_factory=dict),
):
    """Run Gemini localize for every non-English locale (same script, no `--locales`)."""
    _ensure_localization_gemini_tools_allowed()
    raw_limit = payload.get("limit")
    limit: int | None = None
    try:
        if raw_limit is not None and str(raw_limit).strip() != "":
            limit = max(0, int(raw_limit))
    except Exception:
        limit = None
    return _run_gemini_localize_script(locales_csv=None, limit=limit)


@router.get("/system-doctor")
def system_doctor(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    now = time.time()
    # API status is true if this handler runs.
    api_status = "ok"

    # DB status: basic SELECT 1.
    database_status = "unknown"
    alembic_revision = None
    try:
        db.execute(text("SELECT 1"))
        database_status = "ok"
        try:
            row = db.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            alembic_revision = row[0] if row else None
        except Exception:
            alembic_revision = None
    except Exception as e:
        database_status = "error"
        record_system_error("db_error", str(e))

    # Redis status
    redis_status = "disabled"
    try:
        r = get_redis()
        redis_status = "ok" if r.ping() else "error"
    except Exception:
        redis_status = "disabled"

    users_count = db.query(User).count()
    profiles_count = db.query(Profile).count()
    matches_count = db.query(Match).count()
    messages_count = db.query(Message).count()

    gemini_model = str(getattr(settings, "GEMINI_MODEL", "") or "").strip() or None
    provider = str(getattr(settings, "AI_PROVIDER", "") or "").strip().lower()
    has_gemini_key = bool(str(getattr(settings, "GEMINI_API_KEY", "") or "").strip())
    gemini_status = "ok" if (provider == "gemini" and has_gemini_key) else ("disabled" if not has_gemini_key else "not_active")

    fb_ct = int(get_fallback_count_24h() or 0)
    ai_ext = build_system_doctor_ai_extension(
        gemini_status=gemini_status,
        has_gemini_key=has_gemini_key,
        provider_name=provider,
        fallback_count_24h=fb_ct,
    )

    return {
        "api_status": api_status,
        "database_status": database_status,
        "redis_status": redis_status,
        "alembic_revision": alembic_revision,
        "users_count": int(users_count),
        "profiles_count": int(profiles_count),
        "matches_count": int(matches_count),
        "messages_count": int(messages_count),
        "gemini_status": gemini_status,
        "gemini_model": gemini_model,
        "ai_provider_notice": ai_provider_operator_notice(),
        "last_gemini_error": get_last_gemini_error(),
        "ai_fallback_count_24h": fb_ct,
        "api_errors_24h": int(api_errors_last_24h() or 0),
        "last_10_errors": last_errors(10),
        "uptime_seconds": int(uptime_seconds()),
        "environment": str(getattr(settings, "ENV", "") or ""),
        **ai_ext,
    }


@router.get("/system/full-analysis")
def admin_system_full_analysis(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """Aggregate owner-readable system analysis (reuses admin agents; partial failures are warnings)."""
    return build_full_system_analysis(admin_actor, db)


@router.post("/system/backup-db")
def system_backup_db(
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    """Create a DB backup (SQLite file copy or PostgreSQL pg_dump; allowed in all ENV)."""
    if not bool(payload.get("confirm")):
        raise HTTPException(status_code=400, detail={"error": "confirm_required"})
    created = _create_db_backup(prefix="db_backup")
    _log_backup_action(db, admin_actor, {"action": "backup_db", "filename": created["filename"], "size_bytes": created["size_bytes"]})
    return {"ok": True, "backup_path": str((_backup_dir() / created["filename"]).resolve())}


@router.get("/backups")
def admin_backups_list(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    base = _backup_dir()
    base.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in base.iterdir():
        if not path.is_file():
            continue
        try:
            _validate_backup_filename(path.name)
            rows.append(_backup_metadata(path))
        except HTTPException:
            continue
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    _log_backup_action(db, admin_actor, {"action": "backups_list", "count": len(rows)})
    return rows


@router.post("/backups/create")
def admin_backups_create(
    payload: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    """Create backup file (SQLite copy or PostgreSQL pg_dump). Allowed in production; destructive restore stays blocked separately."""
    _require_confirm(payload)
    logger.info("admin_backup_create_request")
    t0 = time.perf_counter()
    try:
        created = _create_db_backup(prefix="neyra_backup")
    except HTTPException:
        logger.warning("admin_backup_create_http_error")
        raise
    except Exception:
        logger.exception("admin_backup_create_unexpected_error")
        raise
    duration_s = round(time.perf_counter() - t0, 3)
    logger.info(
        "admin_backup_create_ok filename=%s size_bytes=%s duration_s=%s",
        created["filename"],
        created["size_bytes"],
        duration_s,
    )
    _log_backup_action(db, admin_actor, {"action": "backup_create", "filename": created["filename"], "size_bytes": created["size_bytes"]})
    sz = int(created["size_bytes"])
    return {
        "success": True,
        "filename": created["filename"],
        "size": sz,
        "size_bytes": sz,
        "duration": duration_s,
        "duration_seconds": duration_s,
        "created_at": created["created_at"],
    }


@router.get("/backups/{filename}/download")
def admin_backups_download(filename: str, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    path = _safe_backup_path(filename)
    _log_backup_action(db, admin_actor, {"action": "backup_download", "filename": path.name, "size_bytes": int(path.stat().st_size)})
    return FileResponse(path=str(path), filename=path.name, media_type="application/octet-stream")


@router.post("/backups/{filename}/restore")
def admin_backups_restore(
    filename: str,
    payload: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _ensure_not_production()
    _require_confirm(payload)
    if str(payload.get("confirm_phrase") or "") != BACKUP_RESTORE_PHRASE:
        raise HTTPException(status_code=400, detail={"error": "restore_phrase_required"})

    if _database_kind() == "postgresql":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "not_supported",
                "detail": "restore via API is SQLite-only; for PostgreSQL apply the .sql dump with psql (or your ops pipeline)",
            },
        )

    backup_path = _safe_backup_path(filename)
    if _backup_type_for_filename(backup_path.name) != "sqlite":
        raise HTTPException(status_code=400, detail={"error": "invalid_filename", "detail": "restore expects a .sqlite backup"})

    db_path = _sqlite_db_path()
    if not db_path.exists():
        raise HTTPException(status_code=404, detail={"error": "db_file_not_found"})

    _log_backup_action(db, admin_actor, {"action": "backup_restore", "phase": "started", "filename": backup_path.name})
    pre_restore = _copy_sqlite_backup(prefix="pre_restore")
    try:
        try:
            db.close()
        except Exception:
            pass
        import shutil

        shutil.copy2(backup_path, db_path)
    except Exception as e:
        record_system_error("backup_restore_failed", str(e))
        raise HTTPException(status_code=500, detail={"error": "restore_failed"})
    _log_backup_action(db, admin_actor, {"action": "backup_restore", "phase": "completed", "filename": backup_path.name, "pre_restore_filename": pre_restore["filename"]})
    return {"ok": True, "restored": True, "filename": backup_path.name, "pre_restore_filename": pre_restore["filename"]}


_AUDIT_REDACT_KEYS = tuple(
    sorted(
        {
            "access_key",
            "api_key",
            "authorization",
            "bearer",
            "chat",
            "content",
            "credential",
            "credentials",
            "email",
            "message",
            "messages",
            "password",
            "phone",
            "private",
            "private_key",
            "raw_message",
            "raw_messages",
            "secret",
            "text",
            "token",
            "webhook_secret",
        }
    )
)

_AUDIT_CATEGORY_ACTIONS: dict[str, set[str]] = {
    "premium": {"grant_premium", "revoke_premium", "grant_all_dev_premium", "create_promo_code"},
    "user": {"grant_premium", "revoke_premium", "reset_ai_memory", "ban_user", "unban_user"},
    "system": {"backup_db", "backup_create", "backup_download", "backup_restore", "backups_list", "clear_cache", "run_migrations", "autopilot_execute", "restore_backup"},
    "safety": {"ban_user", "unban_user", "dismiss_report", "resolve_report"},
    "backup": {"backup_db", "backup_create", "backup_download", "backup_restore", "backups_list", "restore_backup"},
    "localization": {"localization_fix", "localization_scan"},
}


def _audit_redact(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            low = key_s.lower()
            if any(marker in low for marker in _AUDIT_REDACT_KEYS):
                out["redacted"] = "[redacted]"
            else:
                out[key_s] = _audit_redact(item, depth + 1)
        return out
    if isinstance(value, list):
        return [_audit_redact(item, depth + 1) for item in value[:100]]
    if isinstance(value, str):
        low = value.lower()
        if any(marker in low for marker in ("api_key", "authorization", "bearer ", "password", "private chat", "private_key", "raw_messages", "secret", "token")):
            return "[redacted]"
        if len(value) > 500:
            return value[:497] + "..."
    return value


def _audit_parse_payload(payload_json: Any) -> dict:
    try:
        payload = json.loads(str(payload_json or "{}"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _audit_action(payload: dict) -> str:
    action = str(payload.get("action") or payload.get("action_id") or "unknown").strip()
    if action == "backup_restore":
        return "restore_backup"
    return action or "unknown"


def _audit_target_type(action: str, payload: dict) -> str:
    explicit = str(payload.get("target_type") or "").strip()
    if explicit:
        return explicit[:64]
    action_l = action.lower()
    if "backup" in action_l or action_l == "restore_backup":
        return "backup"
    if "premium" in action_l or "promo" in action_l:
        return "premium"
    if "ban" in action_l or "report" in action_l or "safety" in action_l:
        return "safety"
    if "user" in action_l or "memory" in action_l:
        return "user"
    if "localization" in action_l or "l10n" in action_l:
        return "localization"
    if "match" in action_l:
        return "matches"
    if action_l in {"clear_cache", "run_migrations", "autopilot_execute"} or "system" in action_l:
        return "system"
    return "system"


def _audit_target_id(payload: dict) -> str:
    for key in ("target_id", "target_user_id", "reported_user_id", "report_id", "filename", "code", "action_id"):
        if key in payload and payload.get(key) not in (None, ""):
            return _founder_clean_text(payload.get(key), 120)
    return ""


def _audit_status(payload: dict) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"success", "failed", "pending"}:
        return status
    phase = str(payload.get("phase") or "").strip().lower()
    if phase in {"started", "start", "running"}:
        return "pending"
    if phase in {"failed", "error"}:
        return "failed"
    return "success"


def _audit_filter_match(action_filter: str, action: str, target_type: str) -> bool:
    flt = str(action_filter or "").strip().lower()
    action_l = str(action or "").strip().lower()
    target_l = str(target_type or "").strip().lower()
    if not flt:
        return True
    if flt in _AUDIT_CATEGORY_ACTIONS:
        return action_l in _AUDIT_CATEGORY_ACTIONS[flt] or target_l == flt
    return action_l == flt


def _audit_event_item(event: AnalyticsEvent) -> dict:
    payload = _audit_parse_payload(event.payload_json)
    action = _audit_action(payload)
    target_type = _audit_target_type(action, payload)
    safe_payload = _audit_redact(payload)
    if isinstance(safe_payload, dict):
        safe_payload.pop("action", None)
    return {
        "id": int(event.id),
        "created_at": event.created_at.isoformat() if getattr(event, "created_at", None) else "",
        "admin_user_id": int(event.user_id or 0),
        "action": action,
        "target_type": target_type,
        "target_id": _audit_target_id(payload),
        "status": _audit_status(payload),
        "metadata": safe_payload if isinstance(safe_payload, dict) else {},
    }


@router.get("/audit-log")
def admin_audit_log(
    limit: int = 20,
    offset: int = 0,
    action_type: str | None = None,
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    rows = db.query(AnalyticsEvent).filter(AnalyticsEvent.name == "admin_action").order_by(AnalyticsEvent.id.desc()).all()
    items = [_audit_event_item(row) for row in rows]
    filtered = [row for row in items if _audit_filter_match(action_type or "", str(row.get("action") or ""), str(row.get("target_type") or ""))]
    return {
        "items": filtered[offset : offset + limit],
        "total": len(filtered),
    }


@router.post("/system/clear-cache")
def system_clear_cache(
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    _ensure_not_production()
    if not bool(payload.get("confirm")):
        raise HTTPException(status_code=400, detail={"error": "confirm_required"})
    cleared = {"redis": False}
    try:
        r = get_redis()
        r.flushdb()
        cleared["redis"] = True
    except Exception:
        cleared["redis"] = False
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "clear_cache", **cleared, **_actor_meta(admin_actor)})
    return {"ok": True, "cleared": cleared}


@router.post("/system/run-migrations")
def system_run_migrations(
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
    payload: dict = Body(default_factory=dict),
):
    _ensure_not_production()
    if not bool(payload.get("confirm")):
        raise HTTPException(status_code=400, detail={"error": "confirm_required"})
    # Run alembic from the directory that contains `app/` (NEYRA/backend or /app in Docker).
    backend_dir = _backend_project_root()
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=str(backend_dir), check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        record_system_error("migrations_failed", (e.stderr or e.stdout or "")[:2000])
        raise HTTPException(status_code=500, detail={"error": "migrations_failed"})
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "run_migrations", **_actor_meta(admin_actor)})
    return {"ok": True}


@router.get("/users/search")
def admin_users_search(q: str, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    query = (q or "").strip()
    if not query:
        return []

    # Search by id if numeric, else by email/display_name.
    users_q = db.query(User)
    if query.isdigit():
        users_q = users_q.filter(User.id == int(query))
    else:
        like = f"%{query.lower()}%"
        users_q = users_q.filter(or_(User.email.ilike(like), Profile.display_name.ilike(like))).join(Profile, isouter=True)

    users = users_q.limit(20).all()
    out = []
    now = datetime.now(UTC)
    for u in users:
        p = getattr(u, "profile", None)
        premium_until = getattr(u, "premium_until", None)
        pu = to_utc_aware(premium_until)
        is_premium = bool(pu is not None and pu > now)
        out.append(
            {
                "id": int(u.id),
                "email": str(getattr(u, "email", "") or ""),
                "display_name": str(getattr(p, "display_name", "") or ""),
                "age": getattr(p, "age", None),
                "city": str(getattr(p, "city", "") or ""),
                "is_premium": is_premium,
                "premium_until": premium_until.isoformat() if premium_until else None,
                "is_banned": bool(getattr(u, "is_banned", False)),
                "created_at": getattr(u, "created_at", None).isoformat() if getattr(u, "created_at", None) else None,
                "last_active_at": getattr(u, "last_active_at", None).isoformat() if getattr(u, "last_active_at", None) else (getattr(u, "matches_last_seen_at", None).isoformat() if getattr(u, "matches_last_seen_at", None) else None),
            }
        )
    return out


@router.get("/users/{user_id}")
def admin_user_details(user_id: int, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == int(user_id)).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    p = db.query(Profile).filter(Profile.user_id == int(user_id)).first()
    photos_count = 0
    if p and getattr(p, "photo_urls", None):
        photos_count = len([x for x in str(p.photo_urls).split(",") if x.strip()])

    matches_count = db.query(Match).filter(or_(Match.user_a_id == int(user_id), Match.user_b_id == int(user_id))).count()
    messages_count = db.query(Message).filter(or_(Message.sender_id == int(user_id), Message.receiver_id == int(user_id))).count()
    reports_count = db.query(UserReport).filter(UserReport.reported_user_id == int(user_id)).count()
    ai_memory_exists = db.query(UserAiMemory.id).filter(UserAiMemory.user_id == int(user_id)).limit(1).first() is not None
    subs = db.query(Subscription).filter(Subscription.user_id == int(user_id)).order_by(Subscription.id.desc()).first()

    now = datetime.now(UTC)
    premium_until = getattr(u, "premium_until", None)
    pu = to_utc_aware(premium_until)
    is_premium = bool(pu is not None and pu > now)

    card = {
        "user": {
            "id": int(u.id),
            "email": str(getattr(u, "email", "") or ""),
            "is_active": bool(getattr(u, "is_active", True)),
            "is_deleted": bool(getattr(u, "is_deleted", False)),
            "is_banned": bool(getattr(u, "is_banned", False)),
            "created_at": getattr(u, "created_at", None).isoformat() if getattr(u, "created_at", None) else None,
            "last_active_at": getattr(u, "last_active_at", None).isoformat() if getattr(u, "last_active_at", None) else (getattr(u, "matches_last_seen_at", None).isoformat() if getattr(u, "matches_last_seen_at", None) else None),
            "premium_until": premium_until.isoformat() if premium_until else None,
            "is_premium": is_premium,
        },
        "profile": p and {
            "display_name": p.display_name,
            "age": p.age,
            "city": p.city,
            "bio_len": len((p.bio or "").strip()),
            "preferred_language": getattr(p, "preferred_language", "en"),
        },
        "photos_count": int(photos_count),
        "matches_count": int(matches_count),
        "messages_count": int(messages_count),
        "reports_count": int(reports_count),
        "ai_memory_exists": bool(ai_memory_exists),
        "subscription": subs
        and {
            "provider": subs.provider,
            "status": subs.status,
            "plan_code": subs.plan_code,
            "start_date": subs.start_date.isoformat() if subs.start_date else None,
            "end_date": subs.end_date.isoformat() if subs.end_date else None,
        },
    }
    return card


def _require_confirm(payload: dict) -> None:
    if not bool(payload.get("confirm")):
        raise HTTPException(status_code=400, detail={"error": "confirm_required"})


@router.get("/demo-mode")
def admin_demo_mode_status(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    status = demo_mode_status(db)
    if bool(status.get("enabled")) and int(status.get("demo_profiles") or 0) == 0:
        try:
            ensure_demo_profiles(db)
            status = demo_mode_status(db)
        except Exception as e:
            record_system_error("demo_mode_seed_failed", str(e))
    return status


@router.post("/demo-mode/toggle")
def admin_demo_mode_toggle(payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    enabled = bool(payload.get("enabled"))
    set_demo_mode_enabled(db, enabled)
    seeded = 0
    if enabled:
        seeded = int(ensure_demo_profiles(db) or 0)
    track_event(
        db,
        "admin_action",
        user_id=_actor_user_id(admin_actor),
        payload={"action": "demo_mode_toggle", "enabled": enabled, "demo_profiles": seeded, **_actor_meta(admin_actor)},
    )
    return {"ok": True, **demo_mode_status(db)}


@router.post("/demo-mode/regenerate")
def admin_demo_mode_regenerate(payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    result = regenerate_demo_profiles(db)
    track_event(
        db,
        "admin_action",
        user_id=_actor_user_id(admin_actor),
        payload={"action": "demo_mode_regenerate", **result, **_actor_meta(admin_actor)},
    )
    return {"ok": True, **result, **demo_mode_status(db)}


@router.post("/demo-mode/clear-conversations")
def admin_demo_mode_clear_conversations(payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    result = clear_demo_conversations(db)
    track_event(
        db,
        "admin_action",
        user_id=_actor_user_id(admin_actor),
        payload={"action": "demo_mode_clear_conversations", **result, **_actor_meta(admin_actor)},
    )
    return {"ok": True, **result, **demo_mode_status(db)}


@router.post("/demo-mode/live-behavior")
def admin_demo_mode_live_behavior(payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    kw: dict = {}
    if "enabled" in payload:
        kw["enabled"] = bool(payload.get("enabled"))
    if "ignore_rate" in payload:
        kw["ignore_rate"] = float(payload.get("ignore_rate") or 0.3)
    if "ignore_rate_delta" in payload:
        kw["ignore_rate_delta"] = float(payload.get("ignore_rate_delta") or 0.0)
    if "speed" in payload and str(payload.get("speed") or "").strip():
        kw["speed"] = str(payload.get("speed")).strip().lower()
    if not kw:
        raise HTTPException(status_code=400, detail={"error": "no_fields"})
    live = set_demo_live_settings(db, **kw)
    track_event(
        db,
        "admin_action",
        user_id=_actor_user_id(admin_actor),
        payload={"action": "demo_live_behavior", **live, **_actor_meta(admin_actor)},
    )
    return {"ok": True, "live_behavior": live, **demo_mode_status(db)}


@router.post("/demo-mode/regenerate-personalities")
def admin_demo_mode_regenerate_personalities(payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    n = int(regenerate_demo_personalities(db))
    track_event(
        db,
        "admin_action",
        user_id=_actor_user_id(admin_actor),
        payload={"action": "demo_regenerate_personalities", "count": n, **_actor_meta(admin_actor)},
    )
    return {"ok": True, "regenerated": n, **demo_mode_status(db)}


@router.post("/users/{user_id}/grant-premium")
def admin_grant_premium(user_id: int, payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    days = int(payload.get("days") or 7)
    days = max(1, min(365, days))
    u = db.query(User).filter(User.id == int(user_id)).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    now = datetime.now(UTC)
    current = to_utc_aware(getattr(u, "premium_until", None))
    base = current if current is not None and current > now else now
    u.premium_until = base + timedelta(days=days)
    db.add(u)
    db.commit()
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "grant_premium", "target_user_id": int(user_id), "days": days, **_actor_meta(admin_actor)})
    return {"ok": True, "premium_until": u.premium_until.isoformat() if u.premium_until else None}


@router.post("/users/{user_id}/revoke-premium")
def admin_revoke_premium(user_id: int, payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    u = db.query(User).filter(User.id == int(user_id)).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.premium_until = None
    db.add(u)
    db.commit()
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "revoke_premium", "target_user_id": int(user_id), **_actor_meta(admin_actor)})
    return {"ok": True}


@router.post("/users/{user_id}/reset-ai-memory")
def admin_reset_ai_memory(user_id: int, payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    deleted = db.query(UserAiMemory).filter(UserAiMemory.user_id == int(user_id)).delete()
    db.commit()
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "reset_ai_memory", "target_user_id": int(user_id), "deleted": int(deleted or 0), **_actor_meta(admin_actor)})
    return {"ok": True, "deleted": int(deleted or 0)}


@router.post("/users/{user_id}/ban")
def admin_ban_user(user_id: int, payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    reason = str(payload.get("reason") or "").strip()[:240]
    if not reason:
        raise HTTPException(status_code=400, detail={"error": "reason_required"})
    u = db.query(User).filter(User.id == int(user_id)).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.is_banned = True
    db.add(u)
    db.commit()
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "ban_user", "target_user_id": int(user_id), "reason": reason, **_actor_meta(admin_actor)})
    return {"ok": True}


@router.post("/users/{user_id}/unban")
def admin_unban_user(user_id: int, payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    u = db.query(User).filter(User.id == int(user_id)).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.is_banned = False
    db.add(u)
    db.commit()
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "unban_user", "target_user_id": int(user_id), **_actor_meta(admin_actor)})
    return {"ok": True}


@router.get("/reports")
def admin_reports(
    status: str = "open",
    limit: int = 50,
    offset: int = 0,
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    st = (status or "open").strip().lower()
    if st not in {"open", "dismissed", "resolved"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    limit = max(1, min(100, int(limit or 50)))
    offset = max(0, int(offset or 0))
    demo_ids = [
        int(row[0])
        for row in db.query(User.id).filter(User.is_demo == True).all()  # noqa: E712
        if row and row[0]
    ]

    reports_q = db.query(UserReport).filter(UserReport.status == st)
    if demo_ids:
        reports_q = reports_q.filter(~UserReport.reporter_id.in_(demo_ids), ~UserReport.reported_user_id.in_(demo_ids))

    rows = reports_q.order_by(UserReport.id.desc()).offset(offset).limit(limit).all()
    # Precompute report counts for reported users (within returned page only).
    reported_ids = [int(r.reported_user_id) for r in rows]
    counts = {}
    if reported_ids:
        from sqlalchemy import func

        agg = (
            db.query(UserReport.reported_user_id, func.count(UserReport.id))
            .filter(UserReport.reported_user_id.in_(reported_ids))
            .group_by(UserReport.reported_user_id)
            .all()
        )
        counts = {int(uid): int(cnt) for uid, cnt in agg}

    # Map user names
    profiles = db.query(Profile.user_id, Profile.display_name).filter(Profile.user_id.in_(reported_ids)).all() if reported_ids else []
    name_by_id = {int(uid): str(name or "") for uid, name in profiles}

    out = []
    for r in rows:
        out.append(
            {
                "report_id": int(r.id),
                "reported_user_id": int(r.reported_user_id),
                "reported_user_name": name_by_id.get(int(r.reported_user_id), ""),
                "reporter_user_id": int(r.reporter_id),
                "reason": str(r.reason or ""),
                "category": str(getattr(r, "category", "other") or "other"),
                "status": str(getattr(r, "status", "open") or "open"),
                "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
                "reports_count_for_user": int(counts.get(int(r.reported_user_id), 0)),
            }
        )
    return out


@router.get("/reports/{report_id}")
def admin_report_detail(report_id: int, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    r = db.query(UserReport).filter(UserReport.id == int(report_id)).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    demo_ids = {
        int(row[0])
        for row in db.query(User.id).filter(User.is_demo == True).all()  # noqa: E712
        if row and row[0]
    }
    if int(r.reported_user_id) in demo_ids or int(r.reporter_id) in demo_ids:
        raise HTTPException(status_code=404, detail="Report not found")
    reported_user = db.query(User).filter(User.id == int(r.reported_user_id)).first()
    reporter_user = db.query(User).filter(User.id == int(r.reporter_id)).first()
    reported_profile = db.query(Profile).filter(Profile.user_id == int(r.reported_user_id)).first()
    reporter_profile = db.query(Profile).filter(Profile.user_id == int(r.reporter_id)).first()

    previous_reports = db.query(UserReport).filter(UserReport.reported_user_id == int(r.reported_user_id)).count()

    category = str(getattr(r, "category", "other") or "other").lower()
    recommendation = {"action": "none", "confidence": 0.5, "reason": "insufficient data"}
    if previous_reports >= 3 or category in {"scam", "minor"}:
        recommendation = {"action": "ban", "confidence": 0.85, "reason": "high risk category or repeated reports"}
    elif category in {"harassment", "hate", "nudity", "impersonation"}:
        recommendation = {"action": "warn", "confidence": 0.7, "reason": "moderation needed"}

    return {
        "report": {
            "report_id": int(r.id),
            "reported_user_id": int(r.reported_user_id),
            "reporter_user_id": int(r.reporter_id),
            "reason": str(r.reason or ""),
            "category": str(getattr(r, "category", "other") or "other"),
            "status": str(getattr(r, "status", "open") or "open"),
            "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
        },
        "reported_user": {
            "id": int(reported_user.id) if reported_user else int(r.reported_user_id),
            "email": str(getattr(reported_user, "email", "") or "") if reported_user else "",
            "is_banned": bool(getattr(reported_user, "is_banned", False)) if reported_user else False,
            "profile": reported_profile
            and {"display_name": reported_profile.display_name, "age": reported_profile.age, "city": reported_profile.city, "preferred_language": getattr(reported_profile, "preferred_language", "en")},
        },
        "reporter_user": {
            "id": int(reporter_user.id) if reporter_user else int(r.reporter_id),
            "email": str(getattr(reporter_user, "email", "") or "") if reporter_user else "",
            "profile": reporter_profile and {"display_name": reporter_profile.display_name, "age": reporter_profile.age, "city": reporter_profile.city},
        },
        "previous_reports_count": int(previous_reports),
        "moderation_recommendation": recommendation,
    }


@router.post("/reports/{report_id}/dismiss")
def admin_report_dismiss(report_id: int, payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    r = db.query(UserReport).filter(UserReport.id == int(report_id)).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    r.status = "dismissed"
    db.add(r)
    db.commit()
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "dismiss_report", "report_id": int(report_id), "reported_user_id": int(r.reported_user_id), **_actor_meta(admin_actor)})
    return {"ok": True}


@router.post("/reports/{report_id}/resolve")
def admin_report_resolve(report_id: int, payload: dict = Body(default_factory=dict), admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    _require_confirm(payload)
    action = str(payload.get("action") or "none").strip().lower()
    if action not in {"warn", "ban", "none"}:
        raise HTTPException(status_code=400, detail="Invalid action")
    r = db.query(UserReport).filter(UserReport.id == int(report_id)).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    r.status = "resolved"
    db.add(r)
    if action == "ban":
        u = db.query(User).filter(User.id == int(r.reported_user_id)).first()
        if u:
            u.is_banned = True
            db.add(u)
    db.commit()
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "resolve_report", "report_id": int(report_id), "moderation_action": action, "reported_user_id": int(r.reported_user_id), **_actor_meta(admin_actor)})
    return {"ok": True, "action": action}


@router.get("/stats/overview")
def admin_stats_overview(
    period: str = "today",
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    p = (period or "today").strip().lower()
    if p not in {"today", "7d", "30d"}:
        raise HTTPException(status_code=400, detail="Invalid period")

    now = datetime.now(UTC)
    if p == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif p == "7d":
        since = now - timedelta(days=7)
    else:
        since = now - timedelta(days=30)

    demo_ids = [
        int(r[0])
        for r in db.query(User.id).filter(User.is_demo == True).all()  # noqa: E712
        if r and r[0]
    ]

    users_total = int(db.query(User).filter(User.is_demo == False).count())  # noqa: E712
    users_new = int(db.query(User).filter(User.is_demo == False, User.created_at >= since).count())  # noqa: E712

    # Active users: best-effort based on last_active_at (or matches_last_seen_at).
    active_users = int(
        db.query(User.id)
        .filter(User.is_demo == False)  # noqa: E712
        .filter(
            or_(
                User.last_active_at >= since,
                User.matches_last_seen_at >= since,
            )
        )
        .count()
    )

    real_profiles_q = db.query(Profile).join(User, User.id == Profile.user_id).filter(User.is_demo == False, Profile.is_demo_profile == False)  # noqa: E712
    profiles_total = int(real_profiles_q.count())
    completed_profiles = int(real_profiles_q.filter(Profile.onboarding_completed == True).count())  # noqa: E712
    verified_profiles = int(real_profiles_q.filter(Profile.verified == True).count())  # noqa: E712
    completed_rate = float(completed_profiles) / float(profiles_total) if profiles_total else 0.0
    verified_rate = float(verified_profiles) / float(profiles_total) if profiles_total else 0.0

    likes_q = db.query(Swipe).filter(Swipe.liked == True, Swipe.created_at >= since)  # noqa: E712
    matches_q = db.query(Match).filter(Match.created_at >= since)
    messages_q = db.query(Message).filter(Message.created_at >= since)
    if demo_ids:
        likes_q = likes_q.filter(~Swipe.swiper_id.in_(demo_ids), ~Swipe.target_user_id.in_(demo_ids))
        matches_q = matches_q.filter(~Match.user_a_id.in_(demo_ids), ~Match.user_b_id.in_(demo_ids))
        messages_q = messages_q.filter(~Message.sender_id.in_(demo_ids), ~Message.receiver_id.in_(demo_ids))
    likes = int(likes_q.count())
    matches = int(matches_q.count())
    messages = int(messages_q.count())

    # Active chats: distinct sender/receiver pairs with messages in period (no content).
    from sqlalchemy import func

    if db.bind and db.bind.dialect.name == "sqlite":
        active_q = db.query(func.count(func.distinct(func.printf("%d-%d", func.min(Message.sender_id, Message.receiver_id), func.max(Message.sender_id, Message.receiver_id))))).filter(Message.created_at >= since)
    else:
        active_q = db.query(func.count(func.distinct(func.concat(func.least(Message.sender_id, Message.receiver_id), "-", func.greatest(Message.sender_id, Message.receiver_id))))).filter(Message.created_at >= since)
    if demo_ids:
        active_q = active_q.filter(~Message.sender_id.in_(demo_ids), ~Message.receiver_id.in_(demo_ids))
    active_chats = int(active_q.scalar() or 0)

    # Dead chats: matches whose latest message is older than 7 days.
    dead_cutoff = now - timedelta(days=7)
    # Compute latest message time per pair via SQL (best-effort).
    if db.bind and db.bind.dialect.name == "sqlite":
        pair = func.printf("%d-%d", func.min(Message.sender_id, Message.receiver_id), func.max(Message.sender_id, Message.receiver_id))
        last_by_pair = select(pair.label("pair"), func.max(Message.created_at).label("last_at")).group_by(pair).subquery()
        match_pair = func.printf("%d-%d", func.min(Match.user_a_id, Match.user_b_id), func.max(Match.user_a_id, Match.user_b_id))
        dead_q = (
            db.query(Match.id)
            .outerjoin(last_by_pair, last_by_pair.c.pair == match_pair)
            .filter(Match.created_at <= now)
            .filter(or_(last_by_pair.c.last_at == None, last_by_pair.c.last_at < dead_cutoff))  # noqa: E711
        )
        if demo_ids:
            dead_q = dead_q.filter(~Match.user_a_id.in_(demo_ids), ~Match.user_b_id.in_(demo_ids))
        dead_chats = int(dead_q.count())
    else:
        pair = func.concat(func.least(Message.sender_id, Message.receiver_id), "-", func.greatest(Message.sender_id, Message.receiver_id))
        last_by_pair = select(pair.label("pair"), func.max(Message.created_at).label("last_at")).group_by(pair).subquery()
        match_pair = func.concat(func.least(Match.user_a_id, Match.user_b_id), "-", func.greatest(Match.user_a_id, Match.user_b_id))
        dead_q = (
            db.query(Match.id)
            .outerjoin(last_by_pair, last_by_pair.c.pair == match_pair)
            .filter(Match.created_at <= now)
            .filter(or_(last_by_pair.c.last_at == None, last_by_pair.c.last_at < dead_cutoff))  # noqa: E711
        )
        if demo_ids:
            dead_q = dead_q.filter(~Match.user_a_id.in_(demo_ids), ~Match.user_b_id.in_(demo_ids))
        dead_chats = int(dead_q.count())

    # AI metrics
    ai_calls = int(db.query(AnalyticsEvent).filter(AnalyticsEvent.name == "ai_request_success", AnalyticsEvent.created_at >= since).count())
    fallback_events = int(db.query(AnalyticsEvent).filter(AnalyticsEvent.name == "ai_fallback_used", AnalyticsEvent.created_at >= since).count())
    fallback_count = int(get_fallback_count_24h() or 0) if p == "today" else fallback_events
    # Gemini errors: best-effort (no full error table). Count 1 if quota error observed recently in today.
    gemini_errors = 1 if (p == "today" and bool(get_last_gemini_quota_error())) else 0

    shown = int(db.query(AiInteractionEvent).filter(AiInteractionEvent.event_type == "option_shown", AiInteractionEvent.created_at >= since).count())
    selected = int(db.query(AiInteractionEvent).filter(AiInteractionEvent.event_type == "option_selected", AiInteractionEvent.created_at >= since).count())
    sent = int(db.query(AiInteractionEvent).filter(AiInteractionEvent.event_type == "message_sent", AiInteractionEvent.created_at >= since).count())
    partner_replied = int(db.query(AiInteractionEvent).filter(AiInteractionEvent.event_type == "partner_replied", AiInteractionEvent.created_at >= since).count())
    reply_selected_rate = float(selected) / float(shown) if shown else 0.0
    partner_reply_after_ai_rate = float(partner_replied) / float(sent) if sent else 0.0

    # Premium
    trial_users = int(db.query(User).filter(User.is_demo == False, User.trial_started_at != None, User.trial_started_at >= since).count())  # noqa: E711,E712
    premium_users = int(db.query(User).filter(User.is_demo == False, User.premium_until != None, User.premium_until > now).count())  # noqa: E711,E712
    expired_trials = int(
        db.query(User)
        .filter(User.is_demo == False)  # noqa: E712
        .filter(User.trial_started_at != None)  # noqa: E711
        .filter(User.trial_started_at >= since)
        .filter(or_(User.premium_until == None, User.premium_until < now))  # noqa: E711
        .count()
    )
    # Best-effort conversion: trial users in period who now have active subscription.
    converted = 0
    if trial_users:
        has_active_paid = exists(
            select(1)
            .select_from(Subscription)
            .where(
                Subscription.user_id == User.id,
                Subscription.status == "active",
                Subscription.plan_code != "free",
            )
        )
        converted = int(
            db.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.is_demo == False,  # noqa: E712
                    User.trial_started_at.isnot(None),
                    User.trial_started_at >= since,
                    has_active_paid,
                )
            ).scalar()
            or 0
        )
    conversion_rate = float(converted) / float(trial_users) if trial_users else 0.0

    # Safety
    reports_q = db.query(UserReport)
    if demo_ids:
        reports_q = reports_q.filter(~UserReport.reporter_id.in_(demo_ids), ~UserReport.reported_user_id.in_(demo_ids))
    open_reports = int(reports_q.filter(UserReport.status == "open").count())
    new_reports = int(reports_q.filter(UserReport.created_at >= since).count())
    banned_users = int(db.query(User).filter(User.is_demo == False, User.is_banned == True).count())  # noqa: E712

    return {
        "period": p,
        "users": {
            "total": users_total,
            "new": users_new,
            "active": active_users,
            "completed_profiles_rate": completed_rate,
            "verified_profiles_rate": verified_rate,
        },
        "dating": {
            "likes": likes,
            "matches": matches,
            "messages": messages,
            "active_chats": active_chats,
            "dead_chats": dead_chats,
        },
        "ai": {
            "ai_calls": ai_calls,
            "fallback_count": fallback_count,
            "gemini_errors": gemini_errors,
            "reply_selected_rate": reply_selected_rate,
            "partner_reply_after_ai_rate": partner_reply_after_ai_rate,
        },
        "premium": {
            "trial_users": trial_users,
            "premium_users": premium_users,
            "expired_trials": expired_trials,
            "conversion_rate": conversion_rate,
        },
        "safety": {
            "open_reports": open_reports,
            "new_reports": new_reports,
            "banned_users": banned_users,
        },
    }


_CHAT_BRAIN_AGG_EVENTS = frozenset({"cb_select", "cb_send", "cb_reply", "cb_copy", "cb_regen", "cb_edit"})


def _cb_variant_from_meta(meta: dict) -> str | None:
    if not isinstance(meta, dict):
        return None
    v = str(meta.get("variant") or meta.get("previous_style") or meta.get("style") or "").strip().lower()
    return v if v in {"light", "flirty", "deep"} else None


@router.get("/stats/chat-brain-style")
def admin_chat_brain_style_stats(
    period: str = "7d",
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    """
    Aggregate-only Chat Brain style learning metrics. No message bodies or private chat text.
    """
    p = (period or "7d").strip().lower()
    if p not in {"today", "7d", "30d"}:
        raise HTTPException(status_code=400, detail="Invalid period")

    now = datetime.now(UTC)
    if p == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif p == "7d":
        since = now - timedelta(days=7)
    else:
        since = now - timedelta(days=30)

    rows = (
        db.query(AiInteractionEvent)
        .filter(AiInteractionEvent.created_at >= since, AiInteractionEvent.event_type.in_(list(_CHAT_BRAIN_AGG_EVENTS)))
        .all()
    )
    counts = {k: 0 for k in _CHAT_BRAIN_AGG_EVENTS}
    style_pick = {"light": 0, "flirty": 0, "deep": 0}
    style_reply = {"light": 0, "flirty": 0, "deep": 0}
    for r in rows:
        et = str(r.event_type or "")
        if et in counts:
            counts[et] += 1
        meta = r.metadata_json if isinstance(r.metadata_json, dict) else {}
        v = _cb_variant_from_meta(meta)
        if et in {"cb_select", "cb_send", "cb_copy"} and v:
            style_pick[v] += 1
        if et == "cb_reply" and v:
            style_reply[v] += 1

    pr_rows = (
        db.query(AiInteractionEvent)
        .filter(AiInteractionEvent.created_at >= since, AiInteractionEvent.event_type == "partner_replied")
        .all()
    )
    brain_pr = 0
    for r in pr_rows:
        meta = r.metadata_json if isinstance(r.metadata_json, dict) else {}
        if str(meta.get("previous_source") or "").strip().lower() != "chat_brain":
            continue
        brain_pr += 1
        v = _cb_variant_from_meta(meta)
        if v:
            style_reply[v] += 1

    sends = int(counts.get("cb_send") or 0)
    replies = int(counts.get("cb_reply") or 0) + brain_pr
    reply_after_brain_rate = float(replies) / float(sends) if sends else 0.0
    total_pick = sum(style_pick.values())
    total_reply_styles = sum(style_reply.values())
    top_pick = max(style_pick, key=lambda k: style_pick[k]) if total_pick else None
    top_success = max(style_reply, key=lambda k: style_reply[k]) if total_reply_styles else None

    return {
        "period": p,
        "since": since.isoformat(),
        "event_counts": counts,
        "reply_after_brain_rate": reply_after_brain_rate,
        "brain_assisted_sends": sends,
        "brain_followup_replies_observed": replies,
        "style_distribution_picks": style_pick,
        "style_distribution_replies": style_reply,
        "top_picked_style": top_pick if total_pick else None,
        "top_successful_style": top_success if total_reply_styles else None,
        "note": "aggregate_only_no_private_content",
    }


@router.get("/premium/overview")
def admin_premium_overview(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    # Trial users: trial_started_at set and premium_until still active (and no paid subscription).
    active_paid_ids = set(
        uid for (uid,) in db.query(Subscription.user_id).filter(Subscription.status == "active", Subscription.plan_code != "free").all()
    )

    trial_users = int(
        db.query(User)
        .filter(User.trial_started_at != None)  # noqa: E711
        .filter(User.premium_until != None)  # noqa: E711
        .filter(User.premium_until > now)
        .count()
    )
    premium_users = int(db.query(User).filter(User.premium_until != None, User.premium_until > now).count())  # noqa: E711
    expired_trials = int(db.query(User).filter(User.trial_started_at != None, User.premium_until != None, User.premium_until < now).count())  # noqa: E711

    exp24 = now + timedelta(hours=24)
    exp3d = now + timedelta(days=3)
    expiring_trials_24h = int(
        db.query(User)
        .filter(User.trial_started_at != None, User.premium_until != None)  # noqa: E711
        .filter(User.premium_until > now, User.premium_until <= exp24)
        .count()
    )
    expiring_trials_3d = int(
        db.query(User)
        .filter(User.trial_started_at != None, User.premium_until != None)  # noqa: E711
        .filter(User.premium_until > now, User.premium_until <= exp3d)
        .count()
    )

    # Conversion: trial users who have an active paid subscription now.
    trial_total = int(db.query(User).filter(User.trial_started_at != None).count())  # noqa: E711
    converted = 0
    if active_paid_ids:
        converted = int(db.query(User).filter(User.trial_started_at != None, User.id.in_(active_paid_ids)).count())  # noqa: E711
    conversion_rate = float(converted) / float(trial_total) if trial_total else 0.0

    # Best-effort revenue: no price fields in DB in this build.
    premium_revenue_best_effort = 0

    # Top paywall sources: aggregate AnalyticsEvent.paywall_shown payload.source (best-effort parsing).
    since = now - timedelta(days=30)
    rows = db.query(AnalyticsEvent.payload_json).filter(AnalyticsEvent.name == "paywall_shown", AnalyticsEvent.created_at >= since).all()
    counts: dict[str, int] = {}
    import json as _json

    for (payload_json,) in rows:
        try:
            p = _json.loads(payload_json or "{}")
        except Exception:
            p = {}
        src = str((p or {}).get("source") or (p or {}).get("surface") or (p or {}).get("reason") or "unknown")[:64]
        counts[src] = counts.get(src, 0) + 1
    top_paywall_sources = sorted([{"source": k, "count": v} for k, v in counts.items()], key=lambda x: x["count"], reverse=True)[:8]

    since30 = now - timedelta(days=30)
    ref_grants_30d = int(
        db.query(func.count(ReferralRewardGrant.id)).filter(ReferralRewardGrant.created_at >= since30).scalar() or 0
    )
    ref_days_30d = int(
        db.query(func.coalesce(func.sum(ReferralRewardGrant.premium_days), 0))
        .filter(ReferralRewardGrant.created_at >= since30)
        .scalar()
        or 0
    )
    top_ref_grant_rows = (
        db.query(ReferralRewardGrant.user_id, func.count(ReferralRewardGrant.id))
        .filter(ReferralRewardGrant.created_at >= since30)
        .group_by(ReferralRewardGrant.user_id)
        .order_by(func.count(ReferralRewardGrant.id).desc())
        .limit(5)
        .all()
    )
    top_referrers_by_rewards = [
        {"user_id": int(uid), "rewards_granted": int(cnt)} for uid, cnt in top_ref_grant_rows if uid is not None
    ]
    referral_abuse_30d = referral_abuse_flags(db, since30)

    return {
        "trial_users": trial_users,
        "premium_users": premium_users,
        "expired_trials": expired_trials,
        "expiring_trials_24h": expiring_trials_24h,
        "expiring_trials_3d": expiring_trials_3d,
        "conversion_rate": conversion_rate,
        "premium_revenue_best_effort": premium_revenue_best_effort,
        "top_paywall_sources": top_paywall_sources,
        "referral_rewards": {
            "grants_last_30d": ref_grants_30d,
            "premium_days_granted_last_30d": ref_days_30d,
            "top_referrers_by_grants": top_referrers_by_rewards,
            "abuse_flags": referral_abuse_30d,
        },
    }


@router.get("/premium/expiring-trials")
def admin_premium_expiring_trials(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    soon = now + timedelta(days=3)
    users = (
        db.query(User)
        .filter(User.trial_started_at != None, User.premium_until != None)  # noqa: E711
        .filter(User.premium_until > now, User.premium_until <= soon)
        .order_by(User.premium_until.asc())
        .limit(200)
        .all()
    )
    out = []
    for u in users:
        p = db.query(Profile).filter(Profile.user_id == int(u.id)).first()
        out.append(
            {
                "id": int(u.id),
                "email": str(u.email or ""),
                "display_name": str(getattr(p, "display_name", "") or ""),
                "premium_until": u.premium_until.isoformat() if u.premium_until else None,
                "trial_started_at": u.trial_started_at.isoformat() if u.trial_started_at else None,
            }
        )
    return out


@router.post("/premium/grant-all-dev")
def admin_premium_grant_all_dev(
    payload: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _ensure_not_production()
    _require_confirm(payload)
    days = int(payload.get("days") or 30)
    days = max(1, min(365, days))
    now = datetime.now(UTC)
    until = now + timedelta(days=days)
    # Safe definition of "dev users": example.com emails.
    updated = (
        db.query(User)
        .filter(User.email.ilike("%@example.com"))
        .update({User.premium_until: until}, synchronize_session=False)
    )
    db.commit()
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "grant_all_dev_premium", "days": days, "updated": int(updated or 0), **_actor_meta(admin_actor)})
    return {"ok": True, "updated_users": int(updated or 0), "premium_until": until.isoformat()}


@router.post("/premium/create-promo-code")
def admin_promo_create(
    payload: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _ensure_not_production()
    _require_confirm(payload)
    code = str(payload.get("code") or "").strip().upper()[:64]
    if not code or len(code) < 3:
        raise HTTPException(status_code=400, detail={"error": "invalid_code"})
    days = int(payload.get("days") or 7)
    days = max(1, min(365, days))
    max_uses = int(payload.get("max_uses") or 1)
    max_uses = max(1, min(100000, max_uses))
    row = PromoCode(code=code, days=days, max_uses=max_uses, uses_count=0, is_active=True)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"error": "code_exists"})
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "create_promo_code", "code": code, "days": days, "max_uses": max_uses, **_actor_meta(admin_actor)})
    return {"ok": True, "code": code, "days": days, "max_uses": max_uses}


def _match_pair_filter(a_col, b_col):
    return or_(
        and_(Message.sender_id == a_col, Message.receiver_id == b_col),
        and_(Message.sender_id == b_col, Message.receiver_id == a_col),
    )


@router.get("/match-quality/overview")
def admin_match_quality_overview(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    since_7d = now - timedelta(days=7)
    start_today = datetime(now.year, now.month, now.day, tzinfo=UTC)

    total_matches = int(db.query(Match).count())
    matches_today = int(db.query(Match).filter(Match.created_at >= start_today).count())

    likes_7d = int(db.query(Swipe).filter(Swipe.liked == True, Swipe.created_at >= since_7d).count())  # noqa: E712
    matches_7d = int(db.query(Match).filter(Match.created_at >= since_7d).count())
    mutual_like_rate = _rate(matches_7d, likes_7d)

    # Dead chats: matches older than 3d with no messages between pair.
    cutoff_dead = now - timedelta(days=3)
    no_msg_exists = ~db.query(Message.id).filter(_match_pair_filter(Match.user_a_id, Match.user_b_id)).exists()
    dead_chats_count = int(db.query(Match).filter(Match.created_at < cutoff_dead).filter(no_msg_exists).count())

    # Active chats: at least one message in last 7d.
    msg_recent_exists = db.query(Message.id).filter(_match_pair_filter(Match.user_a_id, Match.user_b_id), Message.created_at >= since_7d).exists()
    active_chats_count = int(db.query(Match).filter(msg_recent_exists).count())

    # Reply rate: both sides have sent at least one message (ever) for the match.
    ab_exists = db.query(Message.id).filter(and_(Message.sender_id == Match.user_a_id, Message.receiver_id == Match.user_b_id)).exists()
    ba_exists = db.query(Message.id).filter(and_(Message.sender_id == Match.user_b_id, Message.receiver_id == Match.user_a_id)).exists()
    replied_count = int(db.query(Match).filter(ab_exists, ba_exists).count())
    reply_rate = _rate(replied_count, total_matches)

    # Compatibility metrics (best-effort sampling; uses existing compatibility engine, no storage).
    sample_matches = db.query(Match).order_by(Match.id.desc()).limit(250).all()
    scores: list[float] = []
    covered = 0
    weak_score = 0
    for m in sample_matches:
        pa = db.query(Profile).filter(Profile.user_id == int(m.user_a_id)).first()
        pb = db.query(Profile).filter(Profile.user_id == int(m.user_b_id)).first()
        if not pa or not pb:
            continue
        covered += 1
        try:
            s, _reasons = MatchEngine.score(pa, pb)
            s = float(s or 0)
        except Exception:
            continue
        scores.append(s)
        if s < 40:
            weak_score += 1

    average_compatibility_score = float(sum(scores) / len(scores)) if scores else 0.0
    ai_match_coverage_rate = _rate(covered, len(sample_matches))

    # Weak matches count: approximate from sample (low score) + all-time dead chats.
    weak_matches_count = int(weak_score) + int(dead_chats_count)

    issues: dict[str, int] = {
        "dead_chat_no_messages_3d": int(dead_chats_count),
        "low_compatibility_score_lt_40_sample": int(weak_score),
        "missing_profile_sample": int(max(0, len(sample_matches) - covered)),
    }
    top_match_issues = sorted([{"issue": k, "count": int(v)} for k, v in issues.items()], key=lambda x: x["count"], reverse=True)[:8]

    return {
        "total_matches": total_matches,
        "matches_today": matches_today,
        "mutual_like_rate": mutual_like_rate,
        "average_compatibility_score": average_compatibility_score,
        "weak_matches_count": weak_matches_count,
        "dead_chats_count": dead_chats_count,
        "active_chats_count": active_chats_count,
        "reply_rate": reply_rate,
        "ai_match_coverage_rate": ai_match_coverage_rate,
        "top_match_issues": top_match_issues,
    }


@router.get("/match-quality/weak-matches")
def admin_match_quality_weak_matches(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    since = now - timedelta(days=30)
    matches = db.query(Match).filter(Match.created_at >= since).order_by(Match.id.desc()).limit(200).all()
    out: list[dict] = []
    for m in matches:
        a = int(m.user_a_id)
        b = int(m.user_b_id)
        pa = db.query(Profile).filter(Profile.user_id == a).first()
        pb = db.query(Profile).filter(Profile.user_id == b).first()
        score = None
        reasons: list[str] = []
        if pa and pb:
            try:
                s, rs = MatchEngine.score(pa, pb)
                score = float(s or 0)
                reasons = [str(x) for x in (rs or [])][:4]
            except Exception:
                score = None
        msg_q = db.query(Message).filter(_match_pair_filter(a, b))
        messages_count = int(msg_q.count())
        last_message_at = msg_q.order_by(Message.created_at.desc()).with_entities(Message.created_at).first()
        last_dt = last_message_at[0] if last_message_at else None
        if last_dt is not None and getattr(last_dt, "tzinfo", None) is None:
            last_dt = last_dt.replace(tzinfo=UTC)

        reason = "ok"
        if messages_count == 0 and m.created_at < (now - timedelta(days=3)):
            reason = "dead_chat_no_messages_3d"
        elif score is None:
            reason = "missing_compatibility_inputs"
        elif score < 40:
            reason = "low_compatibility_score"
        elif messages_count > 0 and (last_dt is None or last_dt < (now - timedelta(days=14))):
            reason = "stale_chat_14d"

        if reason == "ok":
            continue

        out.append(
            {
                "match_id": int(m.id),
                "users": {
                    "a": {"id": a, "display_name": (pa.display_name if pa else ""), "age": (pa.age if pa else None), "city": (pa.city if pa else "")},
                    "b": {"id": b, "display_name": (pb.display_name if pb else ""), "age": (pb.age if pb else None), "city": (pb.city if pb else "")},
                },
                "compatibility_score": score,
                "compatibility_reasons": reasons,
                "messages_count": messages_count,
                "last_message_at": last_dt.isoformat() if last_dt else None,
                "reason": reason,
            }
        )

    return out


@router.get("/match-quality/dead-chats")
def admin_match_quality_dead_chats(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    cutoff_dead = now - timedelta(days=3)
    no_msg_exists = ~db.query(Message.id).filter(_match_pair_filter(Match.user_a_id, Match.user_b_id)).exists()
    matches = (
        db.query(Match)
        .filter(Match.created_at < cutoff_dead)
        .filter(no_msg_exists)
        .order_by(Match.created_at.desc())
        .limit(200)
        .all()
    )
    out: list[dict] = []
    for m in matches:
        a = int(m.user_a_id)
        b = int(m.user_b_id)
        pa = db.query(Profile).filter(Profile.user_id == a).first()
        pb = db.query(Profile).filter(Profile.user_id == b).first()
        out.append(
            {
                "match_id": int(m.id),
                "users": {
                    "a": {"id": a, "display_name": (pa.display_name if pa else ""), "age": (pa.age if pa else None), "city": (pa.city if pa else "")},
                    "b": {"id": b, "display_name": (pb.display_name if pb else ""), "age": (pb.age if pb else None), "city": (pb.city if pb else "")},
                },
                "messages_count": 0,
                "last_message_at": None,
                "reason": "dead_chat_no_messages_3d",
            }
        )
    return out


@router.post("/match-quality/recompute")
def admin_match_quality_recompute(
    payload: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _require_confirm(payload)
    # Best-effort: warm/re-evaluate compatibility for recent matches; no DB writes, no message content.
    matches = db.query(Match).order_by(Match.id.desc()).limit(300).all()
    processed = 0
    failed = 0
    for m in matches:
        pa = db.query(Profile).filter(Profile.user_id == int(m.user_a_id)).first()
        pb = db.query(Profile).filter(Profile.user_id == int(m.user_b_id)).first()
        if not pa or not pb:
            continue
        try:
            MatchEngine.score(pa, pb)
            processed += 1
        except Exception:
            failed += 1
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={"action": "match_quality_recompute", "processed": processed, "failed": failed, **_actor_meta(admin_actor)})
    return {"ok": True, "processed": int(processed), "failed": int(failed)}


def _period_since(period: str) -> tuple[str, datetime]:
    p = (period or "today").strip().lower()
    now = datetime.now(UTC)
    if p == "7d":
        return "7d", now - timedelta(days=7)
    if p == "30d":
        return "30d", now - timedelta(days=30)
    if p == "today":
        start_today = datetime(now.year, now.month, now.day, tzinfo=UTC)
        return "today", start_today
    return "today", datetime(now.year, now.month, now.day, tzinfo=UTC)


@router.get("/conversation-quality/overview")
def admin_conversation_quality_overview(
    period: str = "today",
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    p, since = _period_since(period)

    rows = db.query(AiInteractionEvent).filter(AiInteractionEvent.created_at >= since).all()
    counts: dict[str, int] = {}
    style_sent: dict[str, int] = {"light": 0, "flirty": 0, "deep": 0}
    style_replied: dict[str, int] = {"light": 0, "flirty": 0, "deep": 0}
    style_selected: dict[str, int] = {"light": 0, "flirty": 0, "deep": 0}
    style_shown: dict[str, int] = {"light": 0, "flirty": 0, "deep": 0}

    duplicate_events = 0
    for r in rows:
        et = str(getattr(r, "event_type", "") or "").strip()
        counts[et] = counts.get(et, 0) + 1
        meta = _meta(getattr(r, "metadata_json", None))

        if bool(meta.get("duplicate")) or bool(meta.get("is_duplicate")):
            duplicate_events += 1

        if et == "option_selected":
            style = str(meta.get("style") or "").strip().lower()
            if style in style_selected:
                style_selected[style] += 1
        if et == "message_sent":
            style = str(meta.get("selected_style") or "").strip().lower()
            if style in style_sent:
                style_sent[style] += 1
        if et == "partner_replied":
            style = str(meta.get("previous_style") or "").strip().lower()
            if style in style_replied:
                style_replied[style] += 1

    ai_options_shown = _safe_int(counts.get("option_shown"))
    ai_options_selected = _safe_int(counts.get("option_selected"))
    ai_options_edited = _safe_int(counts.get("option_edited"))
    message_sent_after_ai = _safe_int(counts.get("message_sent"))
    partner_reply_after_ai = _safe_int(counts.get("partner_replied"))
    meeting_suggested_count = _safe_int(counts.get("meeting_suggested"))
    meeting_rejected_count = _safe_int(counts.get("meeting_rejected"))

    selection_rate = _rate(ai_options_selected, ai_options_shown)
    edited_rate = _rate(ai_options_edited, ai_options_selected)
    partner_reply_rate = _rate(partner_reply_after_ai, message_sent_after_ai)

    duplicate_rate = _rate(duplicate_events, ai_options_selected)

    # Best-effort: analytics events for stall/revive if present (may be 0 in current build).
    stall_detected_count = int(
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.created_at >= since)
        .filter(AnalyticsEvent.name.in_(["stall_detected", "ai_stall_detected", "conversation_stall_detected"]))
        .count()
    )
    revive_used_count = int(
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.created_at >= since)
        .filter(AnalyticsEvent.name.in_(["revive_used", "ai_revive_used", "conversation_revive_used"]))
        .count()
    )

    styles_out: dict[str, dict] = {}
    for st in ["light", "flirty", "deep"]:
        sent = int(style_sent.get(st) or 0)
        rep = int(style_replied.get(st) or 0)
        styles_out[st] = {
            "shown": int(style_shown.get(st) or 0),
            "selected": int(style_selected.get(st) or 0),
            "sent": sent,
            "partner_replied": rep,
            "reply_rate": _rate(rep, sent),
        }

    issues: list[dict] = []
    if edited_rate > 0.45 and ai_options_selected >= 20:
        issues.append({"type": "high_edit_rate", "severity": "medium", "message": "Users edit AI replies too often"})
    if partner_reply_rate < 0.25 and message_sent_after_ai >= 20:
        issues.append({"type": "low_reply_rate", "severity": "high", "message": "Partner reply rate after AI is low"})
    if duplicate_rate > 0.10 and ai_options_selected >= 20:
        issues.append({"type": "duplicate_reply_issues", "severity": "medium", "message": "Duplicate / repetitive AI replies detected too often"})
    if meeting_rejected_count >= 10 and _rate(meeting_rejected_count, meeting_suggested_count) > 0.30:
        issues.append({"type": "meeting_too_early", "severity": "medium", "message": "Meeting suggestions are rejected too often"})

    recommendations: list[dict[str, str]] = []
    if stall_detected_count > 0:
        recommendations.append(
            {
                "id": "revive_dead_chats",
                "title": "Revive stalled conversations",
                "reason": f"Detected {stall_detected_count} stall signal(s) in the window; revive usage is {revive_used_count}.",
                "action": "Nudge users with matches that went quiet (push, in-app, or reopen chip). Open Match Quality → Dead chats for targets.",
            }
        )
    if partner_reply_rate < 0.38 and message_sent_after_ai >= 6:
        recommendations.append(
            {
                "id": "first_message_cta",
                "title": "Strengthen first-message CTAs",
                "reason": f"Partner reply rate after AI-assisted sends is {partner_reply_rate:.0%} (sample {int(message_sent_after_ai)}).",
                "action": "Show a short suggested opener or icebreaker chip right after a mutual match; A/B test tone and timing.",
            }
        )
    recommendations.append(
        {
            "id": "recompute_compatibility",
            "title": "Refresh match compatibility scores",
            "reason": "Periodic recompute keeps ranking aligned with profile changes (no private message reads).",
            "action": "Telegram: Match Quality → Recompute compatibility (confirm). Or Autopilot → recompute_matches.",
        }
    )
    # De-duplicate by id (recompute always last)
    seen_r: set[str] = set()
    dedup_recs: list[dict[str, str]] = []
    for row in recommendations:
        rid = str(row.get("id") or "")
        if rid in seen_r:
            continue
        seen_r.add(rid)
        dedup_recs.append(row)
    recommendations = dedup_recs[:6]

    return {
        "period": p,
        "summary": {
            "ai_options_shown": int(ai_options_shown),
            "ai_options_selected": int(ai_options_selected),
            "selection_rate": selection_rate,
            "edited_rate": edited_rate,
            "message_sent_after_ai": int(message_sent_after_ai),
            "partner_reply_after_ai": int(partner_reply_after_ai),
            "partner_reply_rate": partner_reply_rate,
            "duplicate_rate": duplicate_rate,
            "stall_detected_count": int(stall_detected_count),
            "revive_used_count": int(revive_used_count),
            "meeting_suggested_count": int(meeting_suggested_count),
            "meeting_rejected_count": int(meeting_rejected_count),
        },
        "styles": styles_out,
        "issues": issues,
        "recommendations": recommendations,
    }


@router.get("/conversation-quality/issues")
def admin_conversation_quality_issues(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    # Default to last 7 days for issue diagnostics.
    _p, since = _period_since("7d")
    overview = admin_conversation_quality_overview(period="7d", admin_actor=admin_actor, db=db)
    summ = (overview or {}).get("summary") or {}
    edited_rate = float(summ.get("edited_rate") or 0.0)
    partner_reply_rate = float(summ.get("partner_reply_rate") or 0.0)
    duplicate_rate = float(summ.get("duplicate_rate") or 0.0)
    meeting_suggested = int(summ.get("meeting_suggested_count") or 0)
    meeting_rejected = int(summ.get("meeting_rejected_count") or 0)

    meeting_rejected_rate = _rate(meeting_rejected, meeting_suggested)

    return {
        "duplicate_reply_issues": float(duplicate_rate),
        "high_edit_rate": float(edited_rate),
        "low_reply_rate": float(partner_reply_rate),
        "meeting_too_early": float(meeting_rejected_rate),
        "stalled_chats_count": int(
            db.query(AnalyticsEvent)
            .filter(AnalyticsEvent.created_at >= since)
            .filter(AnalyticsEvent.name.in_(["stall_detected", "ai_stall_detected", "conversation_stall_detected"]))
            .count()
        ),
    }


@router.get("/engagement/overview")
def admin_engagement_overview(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """Aggregate engagement metrics (no private message content)."""
    return engagement_overview(db)


@router.get("/engagement/actions")
def admin_engagement_actions(
    use_ai: bool = True,
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    """Suggested engagement actions (AI copy when configured; otherwise templates). Never sends messages."""
    return build_engagement_actions(db, use_ai=bool(use_ai))


@router.post("/engagement/execute")
def admin_engagement_execute(
    payload: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    """
    Log an engagement run. Default simulate=true (audit only).
    confirm=true required when simulate=false. Never delivers user messages from this endpoint.
    """
    simulate = bool(payload.get("simulate", True))
    confirm = bool(payload.get("confirm"))
    if not simulate and not confirm:
        raise HTTPException(status_code=400, detail={"error": "confirm_required_when_simulate_false"})
    if confirm:
        _require_confirm(payload)
    body = {
        "action": "engagement_execute",
        "simulate": simulate,
        "confirm": confirm,
        "filters": payload.get("action_types") or payload.get("filters") or [],
        "note": "No user messages sent by this endpoint.",
    }
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={**body, **_actor_meta(admin_actor)})
    return {
        "ok": True,
        "simulate": simulate,
        "confirm": confirm,
        "message": "Engagement execute logged. No messages were delivered to users.",
    }


class EngagementGenerateBody(BaseModel):
    """On-demand engagement copy; never returns private chat text."""

    match_id: int
    kind: str
    use_ai: bool = True


@router.get("/engagement/targets")
def admin_engagement_targets(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """Concrete match rows (names, ids, last activity timestamps) for admin UX — no message bodies."""
    return engagement_targets(db)


@router.post("/engagement/generate")
def admin_engagement_generate(
    body: EngagementGenerateBody,
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    """Generate light/flirty/deep lines, a single opener, or a revive draft for one match (suggestions only)."""
    res = generate_engagement_copy(db, match_id=int(body.match_id), kind=str(body.kind), use_ai=bool(body.use_ai))
    if not res.get("ok"):
        err = str(res.get("error") or "bad_request")
        if err == "match_not_found":
            raise HTTPException(status_code=404, detail=res)
        raise HTTPException(status_code=400, detail=res)
    return res


AUTOPILOT_ACTIONS: dict[str, dict[str, str]] = {
    "clear_cache": {
        "title": "Clear Redis cache",
        "impact": "medium",
        "risk": "low",
        "action_endpoint": "/api/v1/admin/system/clear-cache",
    },
    "run_migrations": {
        "title": "Run database migrations",
        "impact": "high",
        "risk": "medium",
        "action_endpoint": "/api/v1/admin/system/run-migrations",
    },
    "recompute_matches": {
        "title": "Recompute match compatibility",
        "impact": "high",
        "risk": "low",
        "action_endpoint": "/api/v1/admin/match-quality/recompute",
    },
    "localization_scan": {
        "title": "Run localization scan",
        "impact": "medium",
        "risk": "low",
        "action_endpoint": "/api/v1/admin/localization/scan",
    },
}

_AUTOPILOT_PRODUCTION_BLOCKLIST = {
    "grant-all-dev",
    "grant_all_dev",
    "grant_all_dev_premium",
    "db_reset",
    "reset_db",
    "db-reset",
    "destructive_script",
    "destructive_scripts",
}

_SENSITIVE_RESULT_KEYS = (
    "api_key",
    "access_key",
    "authorization",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "token",
    "webhook_secret",
)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _sanitize_autopilot_result(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            low = key_s.lower()
            if any(marker in low for marker in _SENSITIVE_RESULT_KEYS):
                out[key_s] = "[redacted]"
            else:
                out[key_s] = _sanitize_autopilot_result(item, depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize_autopilot_result(item, depth + 1) for item in value[:200]]
    if isinstance(value, str):
        if len(value) > 4000:
            return value[:4000] + "...[truncated]"
        low = value.lower()
        if "bearer " in low or "api_key=" in low or "password=" in low:
            return "[redacted]"
    return value


def _autopilot_suggestion(action_id: str, reason: str) -> dict:
    action = AUTOPILOT_ACTIONS[action_id]
    return {
        "id": action_id,
        "title": action["title"],
        "reason": reason,
        "impact": action["impact"],
        "risk": action["risk"],
        "action_endpoint": action["action_endpoint"],
    }


def _append_unique_suggestion(suggestions: list[dict], action_id: str, reason: str) -> None:
    if action_id not in AUTOPILOT_ACTIONS:
        return
    if any(item.get("id") == action_id for item in suggestions):
        return
    suggestions.append(_autopilot_suggestion(action_id, reason))


def _localization_issue_count(report: dict) -> int:
    summary = report.get("summary") if isinstance(report, dict) else {}
    if not isinstance(summary, dict):
        return 0
    total = 0
    for key in ("missing_locale_files", "locales_missing_keys_locales", "hardcoded_strings", "prompt_issues"):
        total += _safe_int(summary.get(key))
    return total


def _log_autopilot_action(db: Session, admin_actor: User | dict, payload: dict) -> None:
    try:
        track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={**(payload or {}), **_actor_meta(admin_actor)})
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        record_system_error("admin_action_log_failed", str(e))


def _execute_autopilot_action(action_id: str, admin_actor: User | dict, db: Session) -> Any:
    payload = {"confirm": True}
    if action_id == "clear_cache":
        return system_clear_cache(admin_actor, db, payload)
    if action_id == "run_migrations":
        return system_run_migrations(admin_actor, db, payload)
    if action_id == "recompute_matches":
        return admin_match_quality_recompute(payload, admin_actor, db)
    if action_id == "localization_scan":
        return localization_scan(admin_actor)
    raise HTTPException(status_code=404, detail={"error": "unknown_action"})


@router.get("/autopilot/suggestions")
def admin_autopilot_suggestions(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    suggestions: list[dict] = []

    sysd = system_doctor(admin_actor=admin_actor, db=db)
    mq = admin_match_quality_overview(admin_actor=admin_actor, db=db)
    l10n = localization_quality(admin_actor=admin_actor)
    aiq = ai_quality(admin_actor=admin_actor, db=db)
    conv = admin_conversation_quality_overview(period="7d", admin_actor=admin_actor, db=db)
    cache_stats = get_gemini_cache_stats_today()

    redis_ok = str((sysd or {}).get("redis_status") or "") == "ok"
    cache_hits = _safe_int((cache_stats or {}).get("hits"))
    cache_misses = _safe_int((cache_stats or {}).get("misses"))
    cache_total = cache_hits + cache_misses
    cache_hit_rate = _safe_float((cache_stats or {}).get("hit_rate"))
    fallback_24h = _safe_int((sysd or {}).get("ai_fallback_count_24h"))
    api_errors_24h = _safe_int((sysd or {}).get("api_errors_24h"))
    if redis_ok and cache_total >= 10 and cache_hit_rate < 0.30:
        _append_unique_suggestion(
            suggestions,
            "clear_cache",
            f"Cache hit ratio is low ({round(cache_hit_rate * 100)}%) with {cache_misses} misses today",
        )
    elif redis_ok and (fallback_24h > 0 or api_errors_24h > 0):
        _append_unique_suggestion(
            suggestions,
            "clear_cache",
            f"Recent fallback/errors detected (fallback_24h={fallback_24h}, api_errors_24h={api_errors_24h})",
        )

    database_status = str((sysd or {}).get("database_status") or "")
    alembic_revision = (sysd or {}).get("alembic_revision")
    if database_status != "ok" or not alembic_revision:
        _append_unique_suggestion(
            suggestions,
            "run_migrations",
            "Pending migrations detected or Alembic revision is unavailable",
        )

    weak_matches = _safe_int((mq or {}).get("weak_matches_count"))
    dead_chats = _safe_int((mq or {}).get("dead_chats_count"))
    if weak_matches > 0:
        _append_unique_suggestion(
            suggestions,
            "recompute_matches",
            f"High weak matches count ({weak_matches})",
        )
    elif dead_chats > 0:
        _append_unique_suggestion(
            suggestions,
            "recompute_matches",
            f"Dead chats detected ({dead_chats})",
        )

    localization_issues = _localization_issue_count(l10n if isinstance(l10n, dict) else {})
    conv_issues = (conv or {}).get("issues") if isinstance(conv, dict) else []
    ai_flags = (aiq or {}).get("quality_flags") if isinstance(aiq, dict) else []
    if localization_issues > 0 or bool((l10n or {}).get("missing")):
        _append_unique_suggestion(
            suggestions,
            "localization_scan",
            f"Mixed language strings detected ({localization_issues} localization issues)",
        )
    elif any(str((flag or {}).get("type") or "").startswith("localization") for flag in (ai_flags or [])):
        _append_unique_suggestion(
            suggestions,
            "localization_scan",
            "AI quality flags indicate localization issues",
        )
    elif any(str((issue or {}).get("type") or "") in {"duplicate_reply_issues", "high_edit_rate"} for issue in (conv_issues or [])):
        _append_unique_suggestion(
            suggestions,
            "localization_scan",
            "Conversation quality indicates copy or language consistency issues",
        )

    return {"suggestions": suggestions}


@router.post("/autopilot/execute")
def admin_autopilot_execute(
    payload: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    action_id = str(payload.get("action_id") or "").strip()
    if not bool(payload.get("confirm")):
        raise HTTPException(status_code=400, detail={"error": "confirm_required"})
    if _is_production_env() and action_id in _AUTOPILOT_PRODUCTION_BLOCKLIST:
        raise HTTPException(status_code=403, detail={"error": "blocked_in_production"})
    if action_id not in AUTOPILOT_ACTIONS:
        raise HTTPException(status_code=404, detail={"error": "unknown_action"})

    action = AUTOPILOT_ACTIONS[action_id]
    _log_autopilot_action(
        db,
        admin_actor,
        {
            "action": "autopilot_execute",
            "action_id": action_id,
            "phase": "started",
            "action_endpoint": action["action_endpoint"],
        },
    )
    try:
        result = _execute_autopilot_action(action_id, admin_actor=admin_actor, db=db)
    except HTTPException as e:
        _log_autopilot_action(
            db,
            admin_actor,
            {
                "action": "autopilot_execute",
                "action_id": action_id,
                "phase": "failed",
                "status_code": int(e.status_code),
                "action_endpoint": action["action_endpoint"],
            },
        )
        raise
    except Exception as e:
        _log_autopilot_action(
            db,
            admin_actor,
            {
                "action": "autopilot_execute",
                "action_id": action_id,
                "phase": "failed",
                "error": e.__class__.__name__,
                "action_endpoint": action["action_endpoint"],
            },
        )
        raise

    safe_result = _sanitize_autopilot_result(result)
    _log_autopilot_action(
        db,
        admin_actor,
        {
            "action": "autopilot_execute",
            "action_id": action_id,
            "phase": "completed",
            "action_endpoint": action["action_endpoint"],
        },
    )
    return {
        "ok": True,
        "status": "executed",
        "action_id": action_id,
        "action_endpoint": action["action_endpoint"],
        "result": safe_result,
    }


@router.get("/growth/overview")
def admin_growth_overview(
    period: str = "today",
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    p, since = _period_since(period)
    now = datetime.now(UTC)

    new_users = int(db.query(User).filter(User.created_at >= since).count())

    # Acquisition breakdown: best-effort from Profile fields created during onboarding window.
    prof_rows = (
        db.query(Profile.preferred_language, Profile.country_code)
        .join(User, User.id == Profile.user_id)
        .filter(User.created_at >= since)
        .all()
    )
    by_locale: dict[str, int] = {}
    by_country: dict[str, int] = {}
    for (lang, cc) in prof_rows:
        l = (str(lang or "").strip().lower() or "unknown")[:8]
        c = (str(cc or "").strip().upper() or "unknown")[:4]
        by_locale[l] = by_locale.get(l, 0) + 1
        by_country[c] = by_country.get(c, 0) + 1

    # Top sources: from analytics events payload.source for social_login_success / onboarding_completed (best-effort)
    src_counts: dict[str, int] = {}
    import json as _json

    src_rows = db.query(AnalyticsEvent.name, AnalyticsEvent.payload_json).filter(
        AnalyticsEvent.created_at >= since, AnalyticsEvent.name.in_(["social_login_success", "onboarding_completed"])
    ).all()
    for (_name, payload_json) in src_rows:
        try:
            pj = _json.loads(payload_json or "{}")
        except Exception:
            pj = {}
        src = str((pj or {}).get("source") or (pj or {}).get("provider") or (pj or {}).get("campaign") or "unknown")[:64]
        src_counts[src] = src_counts.get(src, 0) + 1

    # Activation proxies (window-based).
    completed_profiles = int(
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(User.created_at >= since)
        .filter(Profile.onboarding_completed == True)  # noqa: E712
        .count()
    )
    profiles_total = int(db.query(Profile).join(User, User.id == Profile.user_id).filter(User.created_at >= since).count())
    profile_completed_rate = _rate(completed_profiles, max(1, profiles_total))

    # Photo added rate: best-effort: photo_urls non-empty.
    photo_added = int(
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(User.created_at >= since)
        .filter(func.length(func.trim(Profile.photo_urls)) > 0)
        .count()
    )
    photo_added_rate = _rate(photo_added, max(1, profiles_total))

    thin_bio_count = int(
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(User.created_at >= since, func.coalesce(func.length(func.trim(Profile.bio)), 0) < 20)
        .count()
    )
    thin_bio_rate = _rate(thin_bio_count, max(1, profiles_total))

    verif_pending_count = int(
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(User.created_at >= since, Profile.verification_status == "pending")
        .count()
    )
    verif_none_completed_count = int(
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(User.created_at >= since, Profile.onboarding_completed == True, Profile.verification_status == "none")  # noqa: E712
        .count()
    )
    missing_photo_count = max(0, profiles_total - photo_added)

    # First actions from analytics funnel events (users count).
    def _users_for_event(name: str) -> int:
        return int(
            db.query(func.count(func.distinct(AnalyticsEvent.user_id)))
            .filter(AnalyticsEvent.created_at >= since, AnalyticsEvent.name == name)
            .scalar()
            or 0
        )

    first_like_rate = _rate(_users_for_event("first_like_sent"), max(1, new_users))
    first_match_rate = _rate(_users_for_event("first_match_created"), max(1, new_users))
    first_message_rate = _rate(_users_for_event("first_message_sent"), max(1, new_users))

    # Retention (best-effort window): active = any analytics event in window.
    active_users = int(db.query(func.count(func.distinct(AnalyticsEvent.user_id))).filter(AnalyticsEvent.created_at >= since).scalar() or 0)
    returning_users = int(
        db.query(func.count(func.distinct(AnalyticsEvent.user_id)))
        .filter(AnalyticsEvent.created_at >= since, AnalyticsEvent.name == "app_open")
        .scalar()
        or 0
    )
    day_1_retention_best_effort = _rate(returning_users, max(1, new_users))

    # Dead users: signed up before window but no analytics events in window.
    # Use EXISTS instead of IN_(subquery) to avoid SA "coercing Subquery" warnings.
    dead_users_count = int(
        db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.created_at < since,
                ~exists(
                    select(1)
                    .select_from(AnalyticsEvent)
                    .where(
                        AnalyticsEvent.user_id == User.id,
                        AnalyticsEvent.created_at >= since,
                    )
                ),
            )
        ).scalar()
        or 0
    )

    # Monetization (current state + window paywall events).
    premium_users = int(db.query(User).filter(User.premium_until != None, User.premium_until > now).count())  # noqa: E711
    trial_users = int(db.query(User).filter(User.trial_started_at != None, User.premium_until != None, User.premium_until > now).count())  # noqa: E711
    paywall_views = int(db.query(AnalyticsEvent).filter(AnalyticsEvent.created_at >= since, AnalyticsEvent.name == "paywall_shown").count())

    # Premium conversion: trial_started users who have active paid subscription.
    active_paid_ids = set(
        uid for (uid,) in db.query(Subscription.user_id).filter(Subscription.status == "active", Subscription.plan_code != "free").all()
    )
    trial_total = int(db.query(User).filter(User.trial_started_at != None).count())  # noqa: E711
    converted = int(db.query(User).filter(User.trial_started_at != None, User.id.in_(list(active_paid_ids) or [0])).count())  # noqa: E711
    premium_conversion_rate = _rate(converted, trial_total)

    # Top paywall sources (window)
    pw_rows = db.query(AnalyticsEvent.payload_json).filter(AnalyticsEvent.created_at >= since, AnalyticsEvent.name == "paywall_shown").all()
    pw_counts: dict[str, int] = {}
    for (payload_json,) in pw_rows:
        try:
            pj = _json.loads(payload_json or "{}")
        except Exception:
            pj = {}
        src = str((pj or {}).get("source") or (pj or {}).get("surface") or (pj or {}).get("reason") or "unknown")[:64]
        pw_counts[src] = pw_counts.get(src, 0) + 1

    # Recommendations (top 5)
    recs: list[dict] = []
    if profiles_total >= 5 and photo_added_rate < 0.42:
        recs.append(
            {
                "priority": "high",
                "title": "Stronger photo onboarding",
                "reason": f"Photo add rate ~{photo_added_rate:.0%} among new profiles in this window",
                "action": "Add guided photo capture with examples; bottleneck: missing_photo",
            }
        )
    if profiles_total >= 5 and thin_bio_rate > 0.38:
        recs.append(
            {
                "priority": "medium",
                "title": "Bio quality prompts",
                "reason": f"~{thin_bio_rate:.0%} of new profiles have very short bios (<20 chars)",
                "action": "Offer templates and a minimum length hint; bottleneck: thin_bio",
            }
        )
    if profiles_total >= 5:
        verif_gap_rate = _rate(verif_pending_count + verif_none_completed_count, max(1, profiles_total))
        if verif_gap_rate > 0.30:
            recs.append(
                {
                    "priority": "medium",
                    "title": "Verification prompts",
                    "reason": f"Verification pending/none still high for new profiles (~{verif_gap_rate:.0%})",
                    "action": "Explain trust benefits and simplify verification; bottleneck: verification",
                }
            )
    if profile_completed_rate < 0.55 and new_users >= 10:
        recs.append({"priority": "high", "title": "Improve onboarding", "reason": "Profile completion is low", "action": "Show stronger photo/bio prompts"})
    if first_message_rate < 0.25 and new_users >= 10:
        recs.append({"priority": "high", "title": "Improve first message", "reason": "First message rate is low", "action": "Add better opener suggestions and prompts"})
    if first_match_rate < 0.15 and new_users >= 10:
        recs.append({"priority": "medium", "title": "Improve matching", "reason": "First match rate is low", "action": "Tune discovery ranking and reduce friction to like"})
    if paywall_views >= 50 and premium_conversion_rate < 0.05:
        recs.append({"priority": "medium", "title": "Fix paywall conversion", "reason": "High paywall views but low conversion", "action": "Test pricing/offer copy and reduce early paywall frequency"})
    if day_1_retention_best_effort < 0.20 and new_users >= 10:
        recs.append({"priority": "medium", "title": "Improve retention", "reason": "Return rate is low", "action": "Add daily nudges and better post-onboarding engagement"})

    # Locale opportunity: top locale not 'en'/'uk' with >=5 signups
    if by_locale:
        top_loc = max(by_locale.items(), key=lambda kv: kv[1])
        if top_loc[0] not in {"en", "uk"} and top_loc[1] >= 5:
            recs.append({"priority": "low", "title": "Localize growth surfaces", "reason": f"Growing locale: {top_loc[0]}", "action": "Review onboarding/paywall copy for this locale"})

    recs = recs[:5]

    invite_link_copied = int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(AnalyticsEvent.created_at >= since, AnalyticsEvent.name == "invite_link_copied")
        .scalar()
        or 0
    )
    invite_native_share_clicked = int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(AnalyticsEvent.created_at >= since, AnalyticsEvent.name == "invite_native_share_clicked")
        .scalar()
        or 0
    )
    referred_signups = int(
        db.query(func.count(User.id))
        .filter(User.created_at >= since, User.referred_by_user_id.isnot(None))
        .scalar()
        or 0
    )
    top_ref_rows = (
        db.query(User.referred_by_user_id, func.count(User.id))
        .filter(User.created_at >= since, User.referred_by_user_id.isnot(None))
        .group_by(User.referred_by_user_id)
        .order_by(func.count(User.id).desc())
        .limit(5)
        .all()
    )
    top_referrers: list[dict] = []
    for rid, cnt in top_ref_rows:
        if rid is None:
            continue
        ru = db.query(User).filter(User.id == int(rid)).first()
        top_referrers.append(
            {
                "user_id": int(rid),
                "referral_code": str(getattr(ru, "referral_code", "") or "") if ru else "",
                "referred_count": int(cnt),
            }
        )
    invite_actions = invite_link_copied + invite_native_share_clicked
    referral_conversion_rate = _rate(referred_signups, max(1, invite_actions))

    referral_premium_grants = int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(AnalyticsEvent.created_at >= since, AnalyticsEvent.name == "referral_premium_granted")
        .scalar()
        or 0
    )
    referral_rewards_claimed = int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(AnalyticsEvent.created_at >= since, AnalyticsEvent.name == "referral_reward_claimed")
        .scalar()
        or 0
    )
    referral_abuse = referral_abuse_flags(db, since)

    return {
        "period": p,
        "acquisition": {
            "new_users": int(new_users),
            "signups_by_locale": by_locale,
            "signups_by_country": by_country,
            "top_sources": src_counts,
        },
        "activation": {
            "profile_completed_rate": float(profile_completed_rate),
            "photo_added_rate": float(photo_added_rate),
            "first_like_rate": float(first_like_rate),
            "first_match_rate": float(first_match_rate),
            "first_message_rate": float(first_message_rate),
        },
        "retention": {
            "active_users": int(active_users),
            "returning_users": int(returning_users),
            "day_1_retention_best_effort": float(day_1_retention_best_effort),
            "dead_users_count": int(dead_users_count),
        },
        "monetization": {
            "premium_users": int(premium_users),
            "trial_users": int(trial_users),
            "paywall_views": int(paywall_views),
            "premium_conversion_rate": float(premium_conversion_rate),
            "top_paywall_sources": pw_counts,
        },
        "onboarding": {
            "bottlenecks": {
                "missing_photo_count": int(missing_photo_count),
                "thin_bio_count": int(thin_bio_count),
                "verification_pending_count": int(verif_pending_count),
                "verification_none_after_complete_count": int(verif_none_completed_count),
            },
            "rates": {
                "photo_added_rate": float(photo_added_rate),
                "thin_bio_rate": float(thin_bio_rate),
            },
        },
        "referrals": {
            "invite_link_copied": int(invite_link_copied),
            "invite_native_share_clicked": int(invite_native_share_clicked),
            "referred_signups": int(referred_signups),
            "top_referrers": top_referrers,
            "invite_conversion_rate": float(referral_conversion_rate),
            "referral_rewards": {
                "premium_grants_in_period": int(referral_premium_grants),
                "manual_claims_in_period": int(referral_rewards_claimed),
                "abuse_flags": referral_abuse,
            },
        },
        "recommendations": recs,
    }


@router.get("/growth/recommendations")
def admin_growth_recommendations(
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    # Use 7d overview as basis, return only top 5 recommendations.
    ov = admin_growth_overview(period="7d", admin_actor=admin_actor, db=db)
    return (ov or {}).get("recommendations") or []


def _lvl(x: float, *, low: float, high: float) -> str:
    """Map metric to impact level label (generic)."""
    try:
        v = float(x)
    except Exception:
        v = 0.0
    if v >= high:
        return "low"
    if v >= low:
        return "medium"
    return "high"


def _clamp_score(x: float) -> int:
    try:
        return int(max(0, min(100, round(float(x)))))
    except Exception:
        return 0


@router.get("/product-manager/daily-brief")
def admin_product_manager_daily_brief(
    period: str = "today",
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    p, _since = _period_since(period)

    # Reuse existing admin computations (no HTTP, no private content).
    stats = admin_stats_overview(period=p, admin_actor=admin_actor, db=db)
    growth = admin_growth_overview(period=p, admin_actor=admin_actor, db=db)
    aiq = ai_quality(admin_actor=admin_actor, db=db)
    conv = admin_conversation_quality_overview(period=p, admin_actor=admin_actor, db=db)
    mq = admin_match_quality_overview(admin_actor=admin_actor, db=db)
    prem = admin_premium_overview(admin_actor=admin_actor, db=db)
    sysd = system_doctor(admin_actor=admin_actor, db=db)
    l10n = localization_quality(admin_actor=admin_actor)

    # Safety: use counts only from existing stats.
    safety = (stats or {}).get("safety") or {}

    # Extract signals (all aggregate).
    users = (stats or {}).get("users") or {}
    dating = (stats or {}).get("dating") or {}
    ai = (stats or {}).get("ai") or {}
    prem_stats = (stats or {}).get("premium") or {}

    profile_completed_rate = float((growth or {}).get("activation", {}).get("profile_completed_rate") or 0.0)
    first_message_rate = float((growth or {}).get("activation", {}).get("first_message_rate") or 0.0)
    first_match_rate = float((growth or {}).get("activation", {}).get("first_match_rate") or 0.0)
    return_rate = float((growth or {}).get("retention", {}).get("day_1_retention_best_effort") or 0.0)

    ai_edit_rate = float(((conv or {}).get("summary") or {}).get("edited_rate") or 0.0)
    ai_partner_reply_rate = float(((conv or {}).get("summary") or {}).get("partner_reply_rate") or 0.0)
    paywall_views = int((growth or {}).get("monetization", {}).get("paywall_views") or 0)
    premium_conv = float((growth or {}).get("monetization", {}).get("premium_conversion_rate") or 0.0)

    dead_chats = int((mq or {}).get("dead_chats_count") or 0)
    reply_rate = float((mq or {}).get("reply_rate") or 0.0)
    gem_errs = int((aiq or {}).get("summary", {}).get("gemini_errors", 0) or 0) if isinstance(aiq, dict) else 0
    fallback_24h = int((sysd or {}).get("ai_fallback_count_24h") or 0)
    open_reports = int(safety.get("open_reports") or 0)

    # Localization quality: report has lists; use counts only.
    l10n_issues = 0
    try:
        if isinstance(l10n, dict):
            l10n_issues = int(len(l10n.get("issues") or [])) if isinstance(l10n.get("issues"), list) else int(l10n.get("issues_count") or 0)
    except Exception:
        l10n_issues = 0

    # Compute health score 0..100 (deterministic, best-effort).
    # Start from 100 and subtract penalties.
    score = 100.0
    score -= min(40.0, max(0.0, (0.55 - profile_completed_rate) * 60.0))
    score -= min(25.0, max(0.0, (0.25 - first_message_rate) * 80.0))
    score -= min(20.0, max(0.0, (0.15 - first_match_rate) * 80.0))
    score -= min(20.0, max(0.0, (0.20 - return_rate) * 80.0))
    score -= min(15.0, max(0.0, (ai_edit_rate - 0.45) * 50.0))
    score -= min(15.0, max(0.0, (0.25 - ai_partner_reply_rate) * 60.0))
    score -= min(15.0, max(0.0, (premium_conv < 0.05 and paywall_views >= 50) * 15.0))
    score -= min(10.0, max(0.0, (dead_chats > 50) * 10.0))
    score -= min(15.0, max(0.0, (fallback_24h > 10) * 15.0))
    score -= min(10.0, max(0.0, (open_reports > 20) * 10.0))
    score -= min(10.0, max(0.0, (l10n_issues > 20) * 10.0))
    health_score = _clamp_score(score)

    priorities: list[dict] = []
    risks: list[dict] = []
    wins: list[dict] = []
    next_actions: list[dict] = []

    def add(area: str, title: str, reason: str, impact: str, effort: str, action: str, metric_signal: str) -> None:
        priorities.append(
            {
                "area": area,
                "title": title,
                "reason": reason,
                "impact": impact,
                "effort": effort,
                "recommended_action": action,
                "metric_signal": metric_signal,
            }
        )

    # Prioritization heuristics (high impact / low effort first).
    if fallback_24h > 10 or gem_errs > 0:
        add(
            "ai",
            "Stabilize AI infra",
            "Fallback/errors are elevated and can degrade user trust + retention.",
            "high",
            "medium",
            "Investigate provider errors, add retries/caching, and reduce failure-prone prompts.",
            f"fallback_24h={fallback_24h}, gemini_errors={gem_errs}",
        )
        risks.append({"title": "AI reliability risk", "detail": f"fallback_24h={fallback_24h}, gemini_errors={gem_errs}"})

    if profile_completed_rate < 0.55:
        add(
            "onboarding",
            "Improve onboarding completion",
            "Low profile completion reduces matching and messaging.",
            "high",
            "low",
            "Add stronger photo/bio prompts and progressive onboarding nudges.",
            f"profile_completed_rate={profile_completed_rate:.2f}",
        )

    if first_message_rate < 0.25:
        add(
            "chat",
            "Increase first message rate",
            "Users aren’t starting chats after matching.",
            "high",
            "low",
            "Improve opener prompts, highlight AI openers, and add 1-tap send.",
            f"first_message_rate={first_message_rate:.2f}",
        )

    if dead_chats > 50 or reply_rate < 0.25:
        add(
            "chat",
            "Reduce dead chats",
            "Many matches don’t convert into conversations.",
            "medium",
            "low",
            "Add revive/timing nudges and improve match-to-chat UI prompts.",
            f"dead_chats_count={dead_chats}, reply_rate={reply_rate:.2f}",
        )

    if ai_edit_rate > 0.45:
        add(
            "ai",
            "Improve AI reply quality (reduce edits)",
            "High edit rate suggests AI tone/wording mismatch.",
            "medium",
            "medium",
            "Tune prompts by style, add better constraints, and A/B test generated options.",
            f"ai_edit_rate={ai_edit_rate:.2f}",
        )

    if paywall_views >= 50 and premium_conv < 0.05:
        add(
            "premium",
            "Fix paywall conversion",
            "Users see paywall often but convert rarely.",
            "medium",
            "medium",
            "Test offer copy/pricing, adjust trial length, and delay paywall until value is shown.",
            f"paywall_views={paywall_views}, premium_conversion_rate={premium_conv:.2f}",
        )

    if open_reports > 20:
        add(
            "safety",
            "Prioritize safety moderation",
            "High open reports can harm retention and brand trust.",
            "high",
            "medium",
            "Triage reports daily, improve auto-ban thresholds, and add friction for repeat offenders.",
            f"open_reports={open_reports}",
        )
        risks.append({"title": "Safety risk", "detail": f"open_reports={open_reports}"})

    if l10n_issues > 20:
        add(
            "localization",
            "Fix localization regressions",
            "Localization issues can reduce activation in non-English locales.",
            "medium",
            "low",
            "Run scan, fix high-confidence items, and add locale-specific QA checks.",
            f"localization_issues={l10n_issues}",
        )

    # Wins (simple positives)
    try:
        if float(prem.get("conversion_rate") or 0.0) >= 0.08:
            wins.append({"title": "Premium conversion is healthy", "metric": f"conversion_rate={float(prem.get('conversion_rate') or 0.0):.2f}"})
    except Exception:
        pass

    # Sort priorities by (impact desc, effort asc)
    impact_rank = {"high": 3, "medium": 2, "low": 1}
    effort_rank = {"low": 1, "medium": 2, "high": 3}
    priorities.sort(key=lambda r: (-impact_rank.get(r.get("impact"), 1), effort_rank.get(r.get("effort"), 3)))
    top_priority = priorities[0] if priorities else {
        "title": "Maintain baseline",
        "reason": "No major red flags detected in current metrics.",
        "impact": "low",
        "effort": "low",
        "recommended_action": "Keep monitoring key funnels and run one small experiment.",
    }

    # Next actions: derive from top priorities (max 3)
    for pr in priorities[:3]:
        next_actions.append({"area": pr.get("area"), "action": pr.get("recommended_action")})

    return {
        "period": p,
        "health_score": int(health_score),
        "top_priority": {
            "title": str(top_priority.get("title") or ""),
            "reason": str(top_priority.get("reason") or ""),
            "impact": str(top_priority.get("impact") or ""),
            "effort": str(top_priority.get("effort") or ""),
            "recommended_action": str(top_priority.get("recommended_action") or ""),
        },
        "priorities": priorities,
        "wins": wins,
        "risks": risks,
        "next_actions": next_actions,
    }


@router.get("/cto/roadmap")
def admin_cto_roadmap(
    period: str = "today",
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    p, _since = _period_since(period)

    sysd = system_doctor(admin_actor=admin_actor, db=db)
    aiq = ai_quality(admin_actor=admin_actor, db=db)
    conv = admin_conversation_quality_overview(period=p, admin_actor=admin_actor, db=db)
    l10n = localization_quality(admin_actor=admin_actor)
    prem = admin_premium_overview(admin_actor=admin_actor, db=db)
    growth = admin_growth_overview(period=p, admin_actor=admin_actor, db=db)
    mq = admin_match_quality_overview(admin_actor=admin_actor, db=db)
    pm = admin_product_manager_daily_brief(period=p, admin_actor=admin_actor, db=db)

    api_errors_24h = int((sysd or {}).get("api_errors_24h") or 0)
    fallback_24h = int((sysd or {}).get("ai_fallback_count_24h") or 0)
    gemini_status = str((sysd or {}).get("gemini_status") or "")
    db_status = str((sysd or {}).get("database_status") or "")
    redis_status = str((sysd or {}).get("redis_status") or "")

    # AI quality signals
    try:
        ai_summary = (aiq or {}).get("summary") or {}
    except Exception:
        ai_summary = {}
    selection_rate = float(ai_summary.get("selection_rate") or 0.0)
    edited_rate = float(ai_summary.get("edited_rate") or 0.0)
    partner_reply_rate = float(((conv or {}).get("summary") or {}).get("partner_reply_rate") or 0.0)

    # Localization issues count only
    l10n_issues = 0
    try:
        if isinstance(l10n, dict):
            l10n_issues = int(len(l10n.get("issues") or [])) if isinstance(l10n.get("issues"), list) else int(l10n.get("issues_count") or 0)
    except Exception:
        l10n_issues = 0

    # Monetization / payments signal (conversion)
    paywall_views = int((growth or {}).get("monetization", {}).get("paywall_views") or 0)
    premium_conv = float((growth or {}).get("monetization", {}).get("premium_conversion_rate") or 0.0)

    # Match/chat infra-ish signals (dead chats implies UX but can require backend changes)
    dead_chats = int((mq or {}).get("dead_chats_count") or 0)

    # Technical health score (0..100): penalize stability/infra issues first.
    score = 100.0
    score -= min(30.0, float(api_errors_24h) * 0.6)
    score -= 20.0 if db_status != "ok" else 0.0
    score -= 10.0 if redis_status in {"error"} else 0.0
    score -= min(25.0, float(fallback_24h) * 1.2)
    if gemini_status in {"disabled", "not_active"}:
        score -= 10.0
    score -= min(10.0, max(0.0, (edited_rate - 0.45) * 50.0))
    score -= min(10.0, max(0.0, (0.20 - selection_rate) * 50.0))
    score -= min(10.0, max(0.0, (0.25 - partner_reply_rate) * 60.0))
    score -= 10.0 if l10n_issues > 20 else 0.0
    score -= 8.0 if (paywall_views >= 50 and premium_conv < 0.05) else 0.0
    technical_health_score = _clamp_score(score)

    priorities: list[dict] = []
    technical_debt: list[dict] = []
    risks: list[dict] = []
    next_actions: list[dict] = []

    def add(area: str, title: str, reason: str, impact: str, risk: str, recommended_action: str, signal: str) -> None:
        priorities.append(
            {
                "area": area,
                "title": title,
                "reason": reason,
                "impact": impact,
                "risk": risk,
                "recommended_action": recommended_action,
                "signal": signal,
            }
        )

    if fallback_24h > 10 or api_errors_24h > 10:
        add(
            "ai",
            "AI reliability & fallback reduction",
            "High fallback/errors create unstable UX and degrade trust.",
            "high",
            "high",
            "Investigate provider failures, add caching/retries, and harden prompt JSON parsing.",
            f"ai_fallback_count_24h={fallback_24h}, api_errors_24h={api_errors_24h}",
        )
        risks.append({"title": "AI reliability risk", "detail": f"fallback_24h={fallback_24h}"})

    if db_status != "ok":
        add(
            "database",
            "Database stability check",
            "DB health is not OK; risk of outages and data loss.",
            "high",
            "high",
            "Run DB health checks, review migrations, and fix failing queries.",
            f"database_status={db_status}",
        )
        risks.append({"title": "DB risk", "detail": f"database_status={db_status}"})

    if api_errors_24h > 20:
        add(
            "backend",
            "Reduce API error rate",
            "Elevated API errors can impact all product surfaces.",
            "high",
            "high",
            "Inspect last errors buffer, fix top exceptions, and add guardrails.",
            f"api_errors_24h={api_errors_24h}",
        )

    if edited_rate > 0.45 or partner_reply_rate < 0.25:
        add(
            "ai",
            "Improve AI prompt quality & evaluation",
            "Users edit AI replies often or partner replies are low — indicates quality gap.",
            "medium",
            "medium",
            "Add prompt regression tests, tune style prompts, and track reply outcomes per style.",
            f"edited_rate={edited_rate:.2f}, partner_reply_rate={partner_reply_rate:.2f}",
        )
        technical_debt.append({"title": "Add AI regression/eval harness", "detail": "Create deterministic fixtures + scoring for prompt changes."})

    if l10n_issues > 20:
        add(
            "localization",
            "Localization backlog reduction",
            "High localization issue count slows international growth and increases support load.",
            "medium",
            "low",
            "Run localization scan, fix high-confidence issues, and add CI check for missing keys.",
            f"localization_issues={l10n_issues}",
        )
        technical_debt.append({"title": "Localization CI guard", "detail": "Fail builds on missing/unused keys and malformed locale JSON."})

    if paywall_views >= 50 and premium_conv < 0.05:
        add(
            "payments",
            "Instrument & iterate paywall conversion",
            "High views with low conversion suggests offer/flow issues.",
            "medium",
            "medium",
            "Add more granular paywall source tracking and run offer experiments.",
            f"paywall_views={paywall_views}, premium_conversion_rate={premium_conv:.2f}",
        )

    if dead_chats > 50:
        add(
            "backend",
            "Chat engagement instrumentation",
            "Many dead chats; need better signals to improve revive/timing logic safely.",
            "medium",
            "low",
            "Add aggregate chat lifecycle metrics (no message content) and track revive outcomes.",
            f"dead_chats_count={dead_chats}",
        )

    # Testing priority (best-effort: leverage PM health score as proxy for confidence)
    pm_health = int((pm or {}).get("health_score") or 0)
    if pm_health < 50:
        add(
            "testing",
            "Increase test coverage for critical funnels",
            "Low overall product health implies changes should be safer and more measurable.",
            "medium",
            "low",
            "Add targeted tests around onboarding, AI events, and admin dashboards to prevent regressions.",
            f"pm_health_score={pm_health}",
        )

    # Sort priorities: impact desc, risk desc
    rank = {"high": 3, "medium": 2, "low": 1}
    priorities.sort(key=lambda r: (-rank.get(r.get("impact"), 1), -rank.get(r.get("risk"), 1)))
    top_engineering_priority = priorities[0] if priorities else {
        "title": "Maintain stability",
        "reason": "No major technical red flags detected.",
        "impact": "low",
        "risk": "low",
        "recommended_action": "Keep monitoring and ship small improvements.",
    }

    for pr in priorities[:3]:
        next_actions.append({"area": pr.get("area"), "action": pr.get("recommended_action")})

    return {
        "period": p,
        "technical_health_score": int(technical_health_score),
        "top_engineering_priority": {
            "title": str(top_engineering_priority.get("title") or ""),
            "reason": str(top_engineering_priority.get("reason") or ""),
            "impact": str(top_engineering_priority.get("impact") or ""),
            "risk": str(top_engineering_priority.get("risk") or ""),
            "recommended_action": str(top_engineering_priority.get("recommended_action") or ""),
        },
        "priorities": priorities,
        "technical_debt": technical_debt,
        "risks": risks,
        "next_actions": next_actions,
    }


@router.get("/telegram-menu-qa/scan")
def admin_telegram_menu_qa_scan(admin_actor: User | dict = Depends(get_admin_actor)):
    """
    Read-only QA scan of backend/scripts/telegram_admin_bot.py menu/callback system.
    Does NOT call Telegram API.
    """
    import sys as _sys
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader

    here = Path(__file__).resolve()
    candidates: list[Path] = []
    for parent in list(here.parents)[:12]:
        candidates.append((parent / "scripts" / "telegram_admin_bot.py").resolve())
        candidates.append((parent / "backend" / "scripts" / "telegram_admin_bot.py").resolve())
    script = next((p for p in candidates if p.exists()), None)
    if script is None:
        raise HTTPException(status_code=404, detail={"error": "telegram_admin_bot_not_found", "candidates": [str(x) for x in candidates[:12]]})

    loader = SourceFileLoader("telegram_admin_bot_scan", str(script))
    spec = spec_from_loader("telegram_admin_bot_scan", loader)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail={"error": "import_failed"})
    bot = module_from_spec(spec)
    _sys.modules["telegram_admin_bot_scan"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    # Ensure we never hit network: stub tg_call and backend.request if present.
    try:
        setattr(bot, "tg_call", lambda *a, **k: {"ok": True, "result": {}})
        setattr(bot, "backend", type("B", (), {"request": lambda *a, **k: {}})())
    except Exception:
        pass

    return scan_telegram_bot_module(bot)


@router.get("/e2e-qa/scan")
def admin_e2e_qa_scan(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """Read-only end-to-end QA scan of critical flows (aggregate-only)."""
    return run_e2e_qa_scan(db)


@router.post("/qa-agent/run")
def admin_qa_agent_run(body: dict, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """
    QA Agent runner.
    English UX QA should be run first; Localization QA only after localization agent.
    """
    kind = str((body or {}).get("kind") or "").strip().lower()
    if kind not in {"full_product", "quick_product", "deep_product", "english_ux", "localization", "chat", "menu", "bot2bot"}:
        kind = "full_product"
    return run_qa(db, kind=kind)  # type: ignore[arg-type]


@router.get("/qa-agent/last")
def admin_qa_agent_last(mode: str = "deep", admin_actor: User | dict = Depends(get_admin_actor)):
    """Load last QA report from reports/qa_latest.json (repo-root)."""
    rep = load_latest_report()
    if not rep:
        return {"ok": False, "error": "QA_REPORT_NOT_FOUND"}
    m = str(mode or "deep").strip().lower()
    if m not in {"summary", "fixes", "deep", "prompts", "prompts_top"}:
        m = "deep"
    return {**rep, "mode": m, "formatted_html": format_report(rep, mode=m)}  # type: ignore[arg-type]


class AdminAiHelpRequest(BaseModel):
    """Body for POST /ai-help — section id only; no user content or secrets."""

    section: str = ""
    lang: str = "en"


def _admin_ai_help_analysis_from_legacy(out: dict, lang: str) -> dict[str, Any]:
    """Map legacy help dict to Telegram-friendly analysis (explanation / issues / suggestions)."""
    lg = str(lang or "en").strip().lower()
    if lg not in {"uk", "en"}:
        lg = "en"

    def tr(en: str, uk: str) -> str:
        return uk if lg == "uk" else en

    lines: list[str] = []
    for x in (out.get("what_to_watch") or [])[:10]:
        if isinstance(x, dict) and "metric" in x:
            lines.append(f"{x.get('metric')}: {x.get('value')}")
        elif isinstance(x, dict):
            lines.append(str(x.get("title") or x)[:200])
        else:
            lines.append(str(x)[:200])
    summary = str(out.get("summary") or "").strip()
    explanation = summary
    if lines:
        hdr = tr("Key signals:", "Ключові сигнали:")
        explanation = summary + "\n\n" + hdr + "\n" + "\n".join(f"• {ln}" for ln in lines)

    issues: list[str] = []
    for r in out.get("risk_notes") or []:
        if isinstance(r, dict):
            issues.append(str(r.get("title") or r.get("text") or r)[:600])
        else:
            issues.append(str(r)[:600])

    suggestions: list[str] = []
    for a in out.get("recommended_actions") or []:
        if isinstance(a, str):
            suggestions.append(a)
        elif isinstance(a, dict):
            suggestions.append(str(a.get("title") or a.get("action") or a.get("recommended_action") or a)[:600])
        else:
            suggestions.append(str(a)[:600])
    nba = out.get("next_best_action")
    if nba:
        suggestions.append(str(nba))
    return {"explanation": explanation.strip(), "issues": issues, "suggestions": suggestions}


def build_admin_ai_help(*, admin_actor: User | dict, db: Session, section: str, lang: str = "en") -> dict[str, Any]:
    """
    Deterministic, rule-based contextual help for Telegram Admin Control Center menus.
    - No Gemini required
    - Aggregate-only (no private chats, no secrets)
    """
    sec = str(section or "").strip().lower()
    lg = str(lang or "en").strip().lower()
    if lg not in {"uk", "en"}:
        lg = "en"

    def tr(en: str, uk: str) -> str:
        return uk if lg == "uk" else en

    title_map = {
        "command_center": tr("🧠 Command Center", "🧠 Command Center"),
        "statistics": tr("📊 Statistics", "📊 Статистика"),
        "users": tr("👥 Users", "👥 Користувачі"),
        "safety": tr("🛡 Safety", "🛡 Безпека"),
        "premium": tr("💎 Premium", "💎 Premium"),
        "match_quality": tr("❤️ Match Quality", "❤️ Якість матчів"),
        "conversation_quality": tr("💬 Conversation Quality", "💬 Якість розмов"),
        "growth": tr("📈 Growth", "📈 Зростання"),
        "product_manager": tr("🧭 Product Manager", "🧭 Product Manager"),
        "cto": tr("🧑‍💻 AI CTO", "🧑‍💻 AI CTO"),
        "autopilot": tr("🤖 Autopilot", "🤖 Автопілот"),
        "founder": tr("👑 Founder Mode", "👑 Founder Mode"),
        "alerts": tr("🚨 Alerts", "🚨 Alerts"),
        "system": tr("⚙️ System Doctor", "⚙️ System Doctor"),
        "backup": tr("🗄 Backup Center", "🗄 Backup Center"),
        "audit": tr("🧾 Audit Log", "🧾 Audit Log"),
        "release": tr("🚀 Release Manager", "🚀 Release Manager"),
        "menu_qa": tr("🧪 Menu QA", "🧪 Menu QA"),
        "e2e_qa": tr("🧪 E2E QA", "🧪 E2E QA"),
        "localization": tr("🌍 Localization / Geo", "🌍 Localization / Geo"),
        "full_analysis": tr("🧠 Full System Analysis", "🧠 Повний аналіз системи"),
        "ai_quality": tr("🧠 AI Quality", "🧠 Якість AI"),
        "more_menu": tr("More tools", "Додаткові інструменти"),
        "engagement": tr("💬 Engagement", "💬 Залучення"),
    }

    # Default generic response
    out = {
        "section": sec or "unknown",
        "title": title_map.get(sec, tr("NEYRA Control Center", "NEYRA Control Center")),
        "summary": tr(
            "This section is part of the NEYRA Control Center. Use it to monitor and manage this area safely.",
            "Цей розділ — частина NEYRA Control Center. Використовуйте його для безпечного моніторингу та керування цією зоною.",
        ),
        "what_to_watch": [],
        "recommended_actions": [],
        "risk_notes": [],
        "next_best_action": tr("Open overview and monitor key metrics.", "Відкрий overview і стеж за ключовими метриками."),
    }

    try:
        now = datetime.now(UTC)
        if sec == "system":
            sysd = system_doctor(admin_actor=admin_actor, db=db)
            api_errors = int((sysd or {}).get("api_errors_24h") or 0)
            fallback = int((sysd or {}).get("ai_fallback_count_24h") or 0)
            db_status = str((sysd or {}).get("database_status") or "")
            redis_status = str((sysd or {}).get("redis_status") or "")
            out["summary"] = tr(
                "System health snapshot: API/DB/Redis/AI status and recent error pressure.",
                "Стан системи: API/DB/Redis/AI та тиск помилок за останню добу.",
            )
            out["what_to_watch"] = [
                {"metric": "api_errors_24h", "value": api_errors},
                {"metric": "ai_fallback_count_24h", "value": fallback},
                {"metric": "database_status", "value": db_status},
                {"metric": "redis_status", "value": redis_status},
            ]
            if api_errors > 20 or db_status != "ok":
                out["risk_notes"] = [tr("Elevated stability risk. Prioritize fixes before shipping new features.", "Підвищений ризик стабільності. Спершу фікси, потім фічі.")]
                out["next_best_action"] = tr("Open System Doctor and check last errors.", "Відкрий System Doctor і переглянь останні помилки.")
            else:
                out["next_best_action"] = tr("Keep an eye on fallback/errors; ship one small improvement today.", "Стеж за fallback/помилками; заплануй 1 невелике покращення сьогодні.")

        elif sec == "command_center":
            st = admin_stats_overview(period="today", admin_actor=admin_actor, db=db)
            nu = int(((st or {}).get("users") or {}).get("new") or 0)
            chats = int(((st or {}).get("dating") or {}).get("active_chats") or 0)
            out["summary"] = tr(
                "Your main hub: open stats, safety, growth, AI quality, and operations. Start with today's pulse, then drill down.",
                "Головний хаб: статистика, безпека, зростання, якість AI та операції. Почни з пульсу за сьогодні, потім провалюйся глибше.",
            )
            out["what_to_watch"] = [
                {"metric": "new_users_today", "value": nu},
                {"metric": "active_chats_today", "value": chats},
            ]
            out["recommended_actions"] = [
                tr("Check Alerts and System Doctor once per day.", "Щодня перевіряй Alerts і System Doctor."),
                tr("If metrics look off: open Statistics (7d) and compare periods.", "Якщо метрики дивні: відкрий Statistics (7d) і порівняй періоди."),
            ]
            out["next_best_action"] = tr("Open Full System Analysis for a one-screen health snapshot.", "Відкрий Full System Analysis для знімка здоров'я на одному екрані.")

        elif sec == "statistics":
            st = admin_stats_overview(period="7d", admin_actor=admin_actor, db=db)
            out["summary"] = tr(
                "High-level product health (users, dating, AI, premium, safety) by period.",
                "Загальний стан продукту (users, dating, AI, premium, safety) за період.",
            )
            out["what_to_watch"] = [
                {"metric": "new_users_7d", "value": int(((st or {}).get("users") or {}).get("new") or 0)},
                {"metric": "matches_7d", "value": int(((st or {}).get("dating") or {}).get("matches") or 0)},
                {"metric": "dead_chats_7d", "value": int(((st or {}).get("dating") or {}).get("dead_chats") or 0)},
                {"metric": "premium_conversion", "value": float(((st or {}).get("premium") or {}).get("conversion_rate") or 0.0)},
                {"metric": "open_reports", "value": int(((st or {}).get("safety") or {}).get("open_reports") or 0)},
            ]
            out["recommended_actions"] = [
                tr("If dead chats are high: improve first-message prompts / revive nudges.", "Якщо dead chats високі: покращ перше повідомлення / revive nudges."),
                tr("If conversion is low: iterate paywall offer and trial timing.", "Якщо конверсія низька: покращ оффер paywall та таймінг trial."),
            ]
            out["next_best_action"] = tr("Compare Today vs 7d vs 30d and identify the biggest drop.", "Порівняй Today vs 7d vs 30d і знайди найбільший провал.")

        elif sec == "premium":
            po = admin_premium_overview(admin_actor=admin_actor, db=db)
            out["summary"] = tr(
                "Premium health: trials, premium users, expirations, conversion and paywall sources.",
                "Стан Premium: trials, premium users, закінчення, конверсія та джерела paywall.",
            )
            out["what_to_watch"] = [
                {"metric": "trial_users", "value": int(po.get("trial_users") or 0)},
                {"metric": "premium_users", "value": int(po.get("premium_users") or 0)},
                {"metric": "expiring_trials_3d", "value": int(po.get("expiring_trials_3d") or 0)},
                {"metric": "conversion_rate", "value": float(po.get("conversion_rate") or 0.0)},
            ]
            out["recommended_actions"] = [
                tr("If many trials expire: add value reminders and upgrade prompts before expiry.", "Якщо багато trial закінчується: додай нагадування цінності та upgrade промпти."),
                tr("Review top paywall sources and fix the weakest surface first.", "Перевір top paywall sources і виправ найслабшу поверхню першою."),
            ]
            out["next_best_action"] = tr("Open Premium → Overview, then check Expiring trials.", "Відкрий Premium → Overview, потім Expiring trials.")

        elif sec == "safety":
            st = admin_stats_overview(period="7d", admin_actor=admin_actor, db=db)
            open_reports = int(((st or {}).get("safety") or {}).get("open_reports") or 0)
            out["summary"] = tr(
                "Safety signals and moderation workload (reports, bans).",
                "Сигнали безпеки та навантаження модерації (репорти, бани).",
            )
            out["what_to_watch"] = [{"metric": "open_reports", "value": open_reports}]
            out["recommended_actions"] = [tr("Triage open reports daily; resolve/ban where clear.", "Щодня розбирай open reports; resolve/ban коли очевидно.")]
            out["next_best_action"] = tr("Open Safety → Open reports.", "Відкрий Safety → Open reports.")

        elif sec == "match_quality":
            mq = admin_match_quality_overview(admin_actor=admin_actor, db=db)
            out["summary"] = tr(
                "Match quality: weak matches, dead chats, reply rate, AI coverage.",
                "Якість матчів: слабкі матчі, dead chats, reply rate, AI coverage.",
            )
            out["what_to_watch"] = [
                {"metric": "dead_chats_count", "value": int(mq.get("dead_chats_count") or 0)},
                {"metric": "reply_rate", "value": float(mq.get("reply_rate") or 0.0)},
                {"metric": "ai_match_coverage_rate", "value": float(mq.get("ai_match_coverage_rate") or 0.0)},
            ]
            out["recommended_actions"] = [tr("Investigate weak/dead chats; improve first-message UX and revive prompts.", "Перевір weak/dead chats; покращ UX першого повідомлення та revive.")]
            out["next_best_action"] = tr("Open Weak matches and Dead chats lists.", "Відкрий списки Weak matches і Dead chats.")

        elif sec == "engagement":
            ev = engagement_overview(db)
            tg = engagement_targets(db, max_each=12)
            fm = float(ev.get("first_message_rate") or 0.0)
            rr = float(ev.get("reply_rate") or 0.0)
            n_no = int(ev.get("chats_no_first_message_count") or 0)
            n_stale = int(ev.get("stale_chats_sample_count") or 0)
            out["summary"] = tr(
                "Why this happens: after a match, users often stall because starting feels high-stakes, timing is unclear, or the value of chatting isn’t obvious. Long silence usually isn’t malice — it’s friction. Reply-rate pressure often reflects one-sided momentum, weak prompts, or mismatched expectations — not something you fix by exposing private chats.",
                "Чому так буває: після матчу люди часто завмирають, бо перше повідомлення здається «відповідальним», незрозумілий таймінг, або вигода від чату неочевидна. Довга тиша рідко про злі наміри — це фрикція. Низька взаємна відповідь часто про односторонній імпульс, слабкі підказки чи очікування — не про перегляд приватних чатів.",
            )
            out["what_to_watch"] = [
                {"metric": "first_message_rate", "value": fm},
                {"metric": "reply_rate", "value": rr},
                {"metric": "dead_chats_3d_no_messages", "value": int(ev.get("dead_chats_count") or 0)},
                {"metric": "chats_no_first_message", "value": n_no},
                {"metric": "targets_no_first_message_listed", "value": int((tg.get("counts") or {}).get("no_first_message") or 0)},
                {"metric": "targets_stale_chats_listed", "value": int((tg.get("counts") or {}).get("dead_stale") or 0)},
            ]
            out["risk_notes"] = []
            if n_no >= 5 or fm < 0.35:
                out["risk_notes"].append(
                    tr(
                        "Many matches never start: you likely need clearer post-match guidance and lower-friction first prompts.",
                        "Багато матчів не стартують: ймовірно потрібні чітші підказки після матчу та простіший вхід у перше повідомлення.",
                    )
                )
            if n_stale >= 3 or rr < 0.2:
                out["risk_notes"].append(
                    tr(
                        "Low mutual reply or stale threads: add respectful revive patterns and reduce generic openers in product copy.",
                        "Низька взаємна відповідь або застій: додай культуру revive без токсичності й прибери шаблонні openers у продукті.",
                    )
                )
            out["recommended_actions"] = [
                tr(
                    "Open First message boost → pick a pair → Generate opener; paste ideas only into product experiments after moderation.",
                    "Відкрий First message boost → обери пару → Згенеруй opener; ідеї в продукт лише після модерації.",
                ),
                tr(
                    "Open Revive chats → check last activity (timestamp only) → Regenerate drafts until tone fits your brand.",
                    "Відкрий Revive chats → перевір останню активність (лише час) → Регенеруй текст, поки тон не збігається з брендом.",
                ),
                tr(
                    "Ship one product change: timed nudge after match + 3 suggested starters (light/flirty/deep) inside the client.",
                    "Запусти одну зміну в продукті: нагадування після матчу + 3 стартові лінії (light/flirty/deep) у клієнті.",
                ),
            ]
            out["next_best_action"] = tr(
                "Use Engagement → AI suggestions for tone packs per match; nothing auto-sends from NEYRA admin APIs.",
                "Використовуй Engagement → AI suggestions для наборів тонів на матч; з адмін-API NEYRA нічого не відправляється автоматично.",
            )

        elif sec == "conversation_quality":
            cq = admin_conversation_quality_overview(period="7d", admin_actor=admin_actor, db=db)
            summ = (cq or {}).get("summary") or {}
            out["summary"] = tr(
                "AI assistant effectiveness: selection, edits, partner reply outcomes by style.",
                "Ефективність AI: вибір, редагування, відповіді партнера по стилях.",
            )
            out["what_to_watch"] = [
                {"metric": "selection_rate", "value": float(summ.get("selection_rate") or 0.0)},
                {"metric": "edited_rate", "value": float(summ.get("edited_rate") or 0.0)},
                {"metric": "partner_reply_rate", "value": float(summ.get("partner_reply_rate") or 0.0)},
            ]
            out["recommended_actions"] = [
                tr("If edits are high: adjust prompts and style constraints.", "Якщо edits високі: підкрути промпти та обмеження стилю."),
                tr("If partner reply is low: iterate openers and reduce generic phrasing.", "Якщо reply low: покращ openers і прибери загальні фрази."),
            ]
            out["next_best_action"] = tr("Open Issues and fix the top driver first.", "Відкрий Issues і виправ головний драйвер.")

        elif sec == "growth":
            go = admin_growth_overview(period="7d", admin_actor=admin_actor, db=db)
            act = (go or {}).get("activation") or {}
            mon = (go or {}).get("monetization") or {}
            ref = (go or {}).get("referrals") or {}
            out["summary"] = tr(
                "Growth funnel: acquisition → activation → retention → monetization with practical recommendations.",
                "Воронка росту: acquisition → activation → retention → monetization + рекомендації.",
            )
            out["what_to_watch"] = [
                {"metric": "new_users", "value": int((go.get("acquisition") or {}).get("new_users") or 0)},
                {"metric": "profile_completed_rate", "value": float(act.get("profile_completed_rate") or 0.0)},
                {"metric": "first_message_rate", "value": float(act.get("first_message_rate") or 0.0)},
                {"metric": "premium_conversion_rate", "value": float(mon.get("premium_conversion_rate") or 0.0)},
                {"metric": "referral_signups_7d", "value": int(ref.get("referred_signups") or 0)},
                {"metric": "invite_actions_7d", "value": int(ref.get("invite_link_copied") or 0) + int(ref.get("invite_native_share_clicked") or 0)},
                {"metric": "referral_conversion_rate_7d", "value": float(ref.get("invite_conversion_rate") or 0.0)},
                {
                    "metric": "referral_premium_grants_7d",
                    "value": int(((ref.get("referral_rewards") or {}) if isinstance(ref, dict) else {}).get("premium_grants_in_period") or 0),
                },
                {
                    "metric": "referral_abuse_flags_7d",
                    "value": int(len(((ref.get("referral_rewards") or {}) if isinstance(ref, dict) else {}).get("abuse_flags") or [])),
                },
            ]
            out["recommended_actions"] = (go or {}).get("recommendations") or []
            out["next_best_action"] = tr("Run 7d overview and execute the top recommendation.", "Запусти 7d overview і виконай топ-рекомендацію.")

        elif sec == "product_manager":
            pm = admin_product_manager_daily_brief(period="7d", admin_actor=admin_actor, db=db)
            out["summary"] = tr(
                "Daily prioritized product plan generated from current metrics.",
                "Щоденний пріоритизований продукт-план на основі метрик.",
            )
            out["what_to_watch"] = [{"metric": "health_score", "value": int(pm.get("health_score") or 0)}]
            out["recommended_actions"] = pm.get("priorities")[:3] if isinstance(pm.get("priorities"), list) else []
            out["risk_notes"] = pm.get("risks") or []
            out["next_best_action"] = tr("Implement the top priority with a measurable KPI.", "Виконай топ-пріоритет з вимірюваним KPI.")

        elif sec == "cto":
            cr = admin_cto_roadmap(period="7d", admin_actor=admin_actor, db=db)
            out["summary"] = tr(
                "Engineering roadmap: stability, AI infra, DB/devops, testing and technical risks.",
                "Інженерний roadmap: стабільність, AI infra, DB/devops, тести та ризики.",
            )
            out["what_to_watch"] = [{"metric": "technical_health_score", "value": int(cr.get("technical_health_score") or 0)}]
            out["recommended_actions"] = cr.get("priorities")[:3] if isinstance(cr.get("priorities"), list) else []
            out["risk_notes"] = cr.get("risks") or []
            out["next_best_action"] = tr("Fix the highest risk item before starting new work.", "Спочатку закрий найвищий ризик, потім нові задачі.")

        elif sec == "menu_qa":
            qa = admin_telegram_menu_qa_scan(admin_actor=admin_actor)
            summ = qa.get("summary") if isinstance(qa, dict) else {}
            out["summary"] = tr("Automated QA of the Telegram admin menu system.", "Автоматична QA перевірка меню Telegram адмін-бота.")
            out["what_to_watch"] = [
                {"metric": "missing_handlers", "value": int((summ or {}).get("missing_handlers") or 0)},
                {"metric": "missing_translations", "value": int((summ or {}).get("missing_translations") or 0)},
                {"metric": "unsafe_actions", "value": int((summ or {}).get("unsafe_actions") or 0)},
            ]
            out["recommended_actions"] = [tr("Fix critical issues first, then warnings.", "Спершу виправ critical, потім warnings.")]
            out["next_best_action"] = tr("Run scan and resolve all critical items.", "Запусти скан і закрий всі critical.")

        elif sec == "e2e_qa":
            qa = run_e2e_qa_scan(db)
            summ = qa.get("summary") if isinstance(qa, dict) else {}
            out["summary"] = tr("Automated E2E QA of critical user flows (safe, no private data).", "Автоматична E2E QA критичних user flows (без приватних даних).")
            out["what_to_watch"] = [
                {"metric": "failed", "value": int((summ or {}).get("failed") or 0)},
                {"metric": "warnings", "value": int((summ or {}).get("warnings") or 0)},
            ]
            out["recommended_actions"] = [tr("If any failures: fix before release.", "Якщо є fail: фікс перед релізом.")]
            out["next_best_action"] = tr("Run scan and address the top failure first.", "Запусти скан і закрий перший fail.")

        elif sec == "full_analysis":
            go_fa = admin_growth_overview(period="7d", admin_actor=admin_actor, db=db)
            ref_fa = (go_fa or {}).get("referrals") or {}
            out["summary"] = tr(
                "One-screen aggregate for the owner: Command Center, System Doctor, alerts, growth, safety, AI, localization, menu/E2E QA, backups, audit, and release readiness. No private chats or secrets.",
                "Агрегат для власника: Command Center, System Doctor, алерти, зростання, безпека, AI, локалізація, Menu/E2E QA, бекапи, аудит і готовність релізу. Без приватних чатів і секретів.",
            )
            rr_fa = (ref_fa.get("referral_rewards") or {}) if isinstance(ref_fa, dict) else {}
            out["what_to_watch"] = [
                {"metric": "score", "value": tr("0–100 (rules)", "0–100 (правила)")},
                {"metric": "status", "value": tr("healthy / warning / critical", "healthy / warning / critical")},
                {"metric": "referral_signups_7d", "value": int(ref_fa.get("referred_signups") or 0)},
                {"metric": "invite_conversion_7d", "value": float(ref_fa.get("invite_conversion_rate") or 0.0)},
                {"metric": "referral_premium_grants_7d", "value": int(rr_fa.get("premium_grants_in_period") or 0)},
                {"metric": "referral_abuse_flags_7d", "value": int(len(rr_fa.get("abuse_flags") or []))},
            ]
            out["recommended_actions"] = [
                tr("Refresh after changes; open the linked section for detail.", "Оновлюй після змін; деталі — у відповідному розділі."),
                tr("Triage top issues before Autopilot actions.", "Спочатку top issues, потім дії Autopilot."),
                tr(
                    "Growth → referrals: compare invite actions to referred signups; top referrers are user_id + code only.",
                    "Growth → referrals: порівняй invite actions і referred signups; топ реферери лише user_id + code.",
                ),
            ]
            out["risk_notes"] = [
                tr("Aggregate-only; not a substitute for logs in incidents.", "Лише агрегати; при інцидентах дивись логи."),
            ]
            out["next_best_action"] = tr("Use Top issues → Database/API → Release.", "Top issues → Database/API → Release.")

        elif sec == "localization":
            rep = localization_quality(admin_actor=admin_actor)
            cnt = 0
            try:
                if isinstance(rep, dict):
                    cnt = int(len(rep.get("issues") or [])) if isinstance(rep.get("issues"), list) else int(rep.get("issues_count") or 0)
            except Exception:
                cnt = 0
            out["summary"] = tr("Localization and geo UX quality diagnostics.", "Діагностика якості локалізації та geo UX.")
            out["what_to_watch"] = [{"metric": "localization_issues", "value": cnt}]
            out["recommended_actions"] = [tr("Fix high-confidence issues first; ensure key UI strings are localized.", "Спершу high-confidence фікси; перевір ключові UI тексти.")]
            out["next_best_action"] = tr("Open Localization report and address the top recurring issue.", "Відкрий звіт і виправ найчастішу проблему.")

        elif sec == "ai_quality":
            aiq = ai_quality(admin_actor=admin_actor, db=db)
            summ = (aiq or {}).get("summary") if isinstance(aiq, dict) else {}
            flags = (aiq or {}).get("quality_flags") if isinstance(aiq, dict) else []
            out["summary"] = tr(
                "AI Copilot quality: selection, edit, and reply rates plus rule-based quality flags (aggregate only).",
                "Якість AI Copilot: вибір, редагування та відповіді плюс прапорці якості (лише агрегати).",
            )
            out["what_to_watch"] = [
                {"metric": "selection_rate", "value": float((summ or {}).get("selection_rate") or 0.0)},
                {"metric": "edited_rate", "value": float((summ or {}).get("edited_rate") or 0.0)},
                {"metric": "partner_reply_rate", "value": float((summ or {}).get("partner_reply_rate") or 0.0)},
            ]
            risk_msgs: list[str] = []
            for f in flags[:6]:
                if not isinstance(f, dict):
                    continue
                ft = str(f.get("type") or "").strip().lower()
                if ft == "high_edit_rate":
                    risk_msgs.append(tr("High edit rate: users often change AI suggestions.", "Високий рівень редагувань: користувачі часто змінюють підказки AI."))
                elif ft == "low_selection_rate":
                    risk_msgs.append(tr("Low selection rate: suggestions may feel irrelevant.", "Низький вибір варіантів: підказки можуть здаватися нерелевантними."))
                else:
                    msg = str(f.get("message") or "").strip()
                    if msg and len(msg) < 400:
                        risk_msgs.append(msg)
            if risk_msgs:
                out["risk_notes"] = risk_msgs
            out["recommended_actions"] = [
                tr("If edits are high: tighten style constraints and shorten options.", "Якщо багато редагувань: звузь стиль і скороти варіанти."),
                tr("If replies are low: improve openers and reduce generic phrasing.", "Якщо мало відповідей: покращ відкривальні речення."),
            ]
            out["next_best_action"] = tr("Compare style breakdowns and fix the weakest surface first.", "Порівняй стилі та виправ найслабшу поверхню першою.")

        elif sec == "alerts":
            poll = admin_alerts_poll(admin_actor=admin_actor, db=db)
            alerts_list = poll.get("alerts") if isinstance(poll, dict) else []
            n = len(alerts_list) if isinstance(alerts_list, list) else 0
            crit = sum(1 for a in (alerts_list or []) if isinstance(a, dict) and str(a.get("level") or "").lower() == "critical")
            out["summary"] = tr(
                "Operational alerts derived from system metrics (no private message content).",
                "Операційні алерти з метрик системи (без приватного вмісту повідомлень).",
            )
            out["what_to_watch"] = [{"metric": "active_alerts", "value": n}, {"metric": "critical_alerts", "value": crit}]
            if crit > 0:
                out["risk_notes"] = [tr("Critical alerts need attention before routine work.", "Критичні алерти потребують уваги перед рутиною.")]
            out["recommended_actions"] = [tr("Mute only after triage; open linked sections from each alert.", "Вимикай сповіщення лише після triage; відкривай розділи з алерту.")]
            out["next_best_action"] = tr("Review Active alerts and resolve top severity first.", "Переглянь активні алерти й закрий спершу найвищий пріоритет.")

        elif sec == "users":
            out["summary"] = tr(
                "Search users and open moderation cards (structured fields only; not a message dump).",
                "Пошук користувачів і картки модерації (структуровані поля; не експорт переписок).",
            )
            out["recommended_actions"] = [
                tr("Search by numeric ID when possible; verify before bans.", "За можливості шукай за числовим ID; перевіряй перед баном."),
            ]
            out["next_best_action"] = tr("Use Safety → reports when behavior needs context beyond the card.", "Для контексту поведінки використовуй Safety → reports.")

        elif sec == "founder":
            fd = admin_founder_daily(admin_actor=admin_actor, db=db)
            ns = (fd or {}).get("north_star") if isinstance(fd, dict) else {}
            ref_fd = (fd or {}).get("referrals") if isinstance(fd, dict) else {}
            out["summary"] = tr(
                "Founder view: north-star metric and cross-team priorities (sanitized summaries).",
                "Звіт для засновника: north-star та пріоритети команд (узагальнено).",
            )
            out["what_to_watch"] = [
                {"metric": str((ns or {}).get("metric") or "north_star"), "value": (ns or {}).get("value")},
                {"metric": "trend", "value": str((ns or {}).get("trend") or "—")},
                {"metric": "referral_signups_today", "value": int((ref_fd or {}).get("referred_signups") or 0)},
                {"metric": "invite_actions_today", "value": int((ref_fd or {}).get("invite_link_copied") or 0) + int((ref_fd or {}).get("invite_native_share_clicked") or 0)},
            ]
            out["recommended_actions"] = [tr("Pick one bet with a measurable KPI for the week.", "Обери одну ставку з вимірюваним KPI на тиждень.")]
            out["next_best_action"] = tr("Read Daily and Focus; align PM + CTO top items.", "Прочитай Daily і Focus; вирівняй топ-задачі PM і CTO.")

        elif sec == "autopilot":
            sug = admin_autopilot_suggestions(admin_actor=admin_actor, db=db)
            items = sug.get("suggestions") if isinstance(sug, dict) else []
            n = len(items) if isinstance(items, list) else 0
            out["summary"] = tr(
                "Autopilot proposes low-risk maintenance actions from aggregate signals; always confirm.",
                "Автопілот пропонує обережні технічні дії за агрегатами; завжди підтверджуй.",
            )
            out["what_to_watch"] = [{"metric": "open_suggestions", "value": n}]
            out["risk_notes"] = [
                tr("Some actions may be blocked in production; read the confirmation screen.", "У production частина дій може бути заблокована; читай екран підтвердження."),
            ]
            out["recommended_actions"] = [tr("Review suggestions and execute only what you understand.", "Переглянь підказки й виконуй лише те, що розумієш.")]
            out["next_best_action"] = tr("Start with clear_cache or localization_scan when signals point there.", "Почни з clear_cache або localization_scan, якщо сигнали вказують туди.")

        elif sec == "backup":
            out["summary"] = tr(
                "Create, list, and restore encrypted backups using explicit confirmation phrases.",
                "Створення, список і відновлення зашифрованих копій з явними фразами підтвердження.",
            )
            out["risk_notes"] = [
                tr("Restore can overwrite live data — use only in controlled maintenance windows.", "Restore може перезаписати робочі дані — лише в керованих вікнах обслуговування."),
            ]
            out["recommended_actions"] = [tr("Take a backup before migrations or risky changes.", "Зроби копію перед міграціями або ризикованими змінами.")]
            out["next_best_action"] = tr("Verify backup files on disk after create.", "Після створення перевір файли резервних копій на диску.")

        elif sec == "audit":
            out["summary"] = tr(
                "Audit trail for premium, user, system, and safety events (metadata; no secrets).",
                "Журнал аудиту premium/user/system/safety (метадані; без секретів).",
            )
            out["recommended_actions"] = [tr("Use filters to narrow time ranges when investigating.", "Використовуй фільтри, щоб звузити час при розслідуванні.")]
            out["next_best_action"] = tr("Correlate spikes with deploys and System Doctor errors.", "Зіставляй сплески з деплоями та помилками System Doctor.")

        elif sec == "release":
            out["summary"] = tr(
                "Release readiness: blockers, warnings, and checklist-style signals before shipping.",
                "Готовність релізу: блокери, попередження та сигнали чекліста перед релізом.",
            )
            out["recommended_actions"] = [tr("Resolve blockers before warnings; re-run readiness after fixes.", "Спочатку блокери, потім warnings; після фіксів знову перевір готовність.")]
            out["next_best_action"] = tr("Open blockers and verify owners + ETA.", "Відкрий blockers і перевір відповідальних та ETA.")

        elif sec == "more_menu":
            out["summary"] = tr(
                "Secondary entry points: backups, audit, release, full analysis, and language.",
                "Додаткові входи: бекапи, аудит, реліз, повний аналіз та мова.",
            )
            out["recommended_actions"] = [
                tr("Use Full System Analysis for a single owner snapshot.", "Для знімка для власника використай Full System Analysis."),
            ]
            out["next_best_action"] = tr("Pick one operational area (backup, audit, or release) per session.", "За сесію обери одну операційну зону: backup, audit або release.")

    except Exception:
        # Fall back to generic help; do not leak stack traces
        pass

    return out


@router.get("/ai-help/{section}")
def admin_ai_help(
    section: str,
    lang: str = "en",
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    """Same payload as POST /ai-help plus legacy fields for compatibility."""
    lg = str(lang or "en").strip().lower()
    if lg not in {"uk", "en"}:
        lg = "en"
    out = build_admin_ai_help(admin_actor=admin_actor, db=db, section=section, lang=lg)
    analysis = _admin_ai_help_analysis_from_legacy(out, lg)
    out.update(analysis)
    return out


@router.post("/ai-help")
def admin_ai_help_post(
    body: AdminAiHelpRequest,
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    """Telegram-friendly analysis: explanation, issues, suggestions (aggregate-only)."""
    lg = str(body.lang or "en").strip().lower()
    if lg not in {"uk", "en"}:
        lg = "en"
    out = build_admin_ai_help(admin_actor=admin_actor, db=db, section=str(body.section or ""), lang=lg)
    analysis = _admin_ai_help_analysis_from_legacy(out, lg)
    return {**analysis, "section": out.get("section"), "title": out.get("title")}


_FOUNDER_SENSITIVE_TEXT_MARKERS = (
    "api_key",
    "authorization",
    "bearer ",
    "credential",
    "email",
    "password",
    "phone",
    "private",
    "private_key",
    "secret",
    "token",
)


def _founder_clean_text(value: Any, max_len: int = 220) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return ""
    low = text_value.lower()
    if any(marker in low for marker in _FOUNDER_SENSITIVE_TEXT_MARKERS):
        return "[redacted]"
    text_value = text_value.replace("raw_messages", "conversation metrics")
    text_value = text_value.replace("messages_count", "conversation_count")
    text_value = text_value.replace("messages", "conversations")
    if len(text_value) > max_len:
        text_value = text_value[: max_len - 3].rstrip() + "..."
    return text_value


def _founder_impact_score(value: Any) -> int:
    return {"high": 30, "medium": 20, "low": 10}.get(str(value or "").strip().lower(), 10)


def _founder_effort_score(value: Any) -> int:
    return {"low": 6, "medium": 3, "high": 0}.get(str(value or "").strip().lower(), 2)


def _founder_risk_score(value: Any) -> int:
    return {"critical": 12, "high": 8, "medium": 4, "low": 1}.get(str(value or "").strip().lower(), 0)


def _founder_trend(today_value: int, seven_day_value: int) -> str:
    baseline = float(seven_day_value or 0) / 7.0
    if today_value <= 0 and baseline <= 0:
        return "flat"
    if float(today_value) > baseline * 1.05:
        return "up"
    if float(today_value) < baseline * 0.95:
        return "down"
    return "flat"


def _founder_add_candidate(
    candidates: list[dict],
    *,
    title: Any,
    reason: Any,
    expected_impact: Any,
    action: Any,
    impact: Any = "medium",
    effort: Any = "medium",
    risk: Any = "low",
    source: str = "",
) -> None:
    title_s = _founder_clean_text(title, 90)
    if not title_s or title_s == "[redacted]":
        return
    candidates.append(
        {
            "title": title_s,
            "reason": _founder_clean_text(reason, 180),
            "expected_impact": _founder_clean_text(expected_impact or impact, 140),
            "action": _founder_clean_text(action, 180),
            "_score": _founder_impact_score(impact) + _founder_effort_score(effort) + _founder_risk_score(risk),
            "_source": source,
        }
    )


def _founder_alert(level: str, message: Any, suggested_fix: Any) -> dict:
    lvl = str(level or "warning").strip().lower()
    if lvl not in {"critical", "warning"}:
        lvl = "warning"
    return {
        "level": lvl,
        "message": _founder_clean_text(message, 160),
        "suggested_fix": _founder_clean_text(suggested_fix, 180),
    }


def _founder_focus(today_plan: list[dict], alerts: list[dict]) -> str:
    haystack = " ".join([str((p or {}).get("title") or "") for p in today_plan[:2]] + [str((a or {}).get("message") or "") for a in alerts[:2]]).lower()
    if "ai" in haystack or "reply" in haystack or "conversation" in haystack or "chat" in haystack:
        return "Improve conversation quality"
    if "localization" in haystack or "language" in haystack or "locale" in haystack:
        return "Fix localization quality"
    if "onboarding" in haystack or "profile" in haystack:
        return "Increase profile completion"
    if "premium" in haystack or "paywall" in haystack or "conversion" in haystack:
        return "Improve premium conversion"
    if "database" in haystack or "api" in haystack or "stability" in haystack:
        return "Stabilize core systems"
    return "Grow daily active conversations"


@router.get("/founder/daily")
def admin_founder_daily(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    today = datetime.now(UTC).date().isoformat()

    stats_today = admin_stats_overview("today", admin_actor, db)
    stats_7d = admin_stats_overview("7d", admin_actor, db)
    pm = admin_product_manager_daily_brief("today", admin_actor, db)
    growth = admin_growth_overview("today", admin_actor, db)
    conv = admin_conversation_quality_overview("today", admin_actor, db)
    mq = admin_match_quality_overview(admin_actor, db)
    premium = admin_premium_overview(admin_actor, db)
    sysd = system_doctor(admin_actor, db)
    cto = admin_cto_roadmap("today", admin_actor, db)
    autopilot = admin_autopilot_suggestions(admin_actor, db)

    today_chats = _safe_int(((stats_today or {}).get("dating") or {}).get("active_chats"))
    seven_day_chats = _safe_int(((stats_7d or {}).get("dating") or {}).get("active_chats"))
    north_star = {
        "metric": "Daily active conversations",
        "value": int(today_chats),
        "trend": _founder_trend(today_chats, seven_day_chats),
    }

    candidates: list[dict] = []
    top_pm = (pm or {}).get("top_priority") if isinstance(pm, dict) else {}
    if isinstance(top_pm, dict):
        _founder_add_candidate(
            candidates,
            title=top_pm.get("title"),
            reason=top_pm.get("reason"),
            expected_impact=top_pm.get("impact"),
            action=top_pm.get("recommended_action"),
            impact=top_pm.get("impact"),
            effort=top_pm.get("effort"),
            source="product_manager",
        )

    for row in (((pm or {}).get("priorities") or [])[:8] if isinstance(pm, dict) else []):
        if isinstance(row, dict):
            _founder_add_candidate(
                candidates,
                title=row.get("title"),
                reason=row.get("reason"),
                expected_impact=row.get("impact"),
                action=row.get("recommended_action"),
                impact=row.get("impact"),
                effort=row.get("effort"),
                source="product_manager",
            )

    top_cto = (cto or {}).get("top_engineering_priority") if isinstance(cto, dict) else {}
    if isinstance(top_cto, dict):
        _founder_add_candidate(
            candidates,
            title=top_cto.get("title"),
            reason=top_cto.get("reason"),
            expected_impact=top_cto.get("impact"),
            action=top_cto.get("recommended_action"),
            impact=top_cto.get("impact"),
            risk=top_cto.get("risk"),
            source="cto",
        )

    for row in (((cto or {}).get("priorities") or [])[:8] if isinstance(cto, dict) else []):
        if isinstance(row, dict):
            _founder_add_candidate(
                candidates,
                title=row.get("title"),
                reason=row.get("reason"),
                expected_impact=row.get("impact"),
                action=row.get("recommended_action"),
                impact=row.get("impact"),
                risk=row.get("risk"),
                source="cto",
            )

    for row in (((growth or {}).get("recommendations") or [])[:5] if isinstance(growth, dict) else []):
        if isinstance(row, dict):
            _founder_add_candidate(
                candidates,
                title=row.get("title"),
                reason=row.get("reason"),
                expected_impact=row.get("priority"),
                action=row.get("action"),
                impact=row.get("priority"),
                effort="low",
                source="growth",
            )

    for row in (((autopilot or {}).get("suggestions") or [])[:5] if isinstance(autopilot, dict) else []):
        if isinstance(row, dict):
            _founder_add_candidate(
                candidates,
                title=row.get("title"),
                reason=row.get("reason"),
                expected_impact=row.get("impact"),
                action=f"Review and confirm Autopilot action: {row.get('action_endpoint')}",
                impact=row.get("impact"),
                risk=row.get("risk"),
                effort="low",
                source="autopilot",
            )

    candidates.sort(key=lambda row: int(row.get("_score") or 0), reverse=True)
    today_plan: list[dict] = []
    seen_titles: set[str] = set()
    for row in candidates:
        key = str(row.get("title") or "").strip().lower()
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        today_plan.append(
            {
                "priority": len(today_plan) + 1,
                "title": row.get("title") or "",
                "reason": row.get("reason") or "",
                "expected_impact": row.get("expected_impact") or "",
                "action": row.get("action") or "",
            }
        )
        if len(today_plan) >= 5:
            break

    if not today_plan:
        today_plan.append(
            {
                "priority": 1,
                "title": "Grow daily active conversations",
                "reason": "No critical issues detected in aggregate diagnostics.",
                "expected_impact": "medium",
                "action": "Run one small activation or conversation-quality experiment today.",
            }
        )

    alerts: list[dict] = []
    db_status = str((sysd or {}).get("database_status") or "")
    api_errors_24h = _safe_int((sysd or {}).get("api_errors_24h"))
    fallback_24h = _safe_int((sysd or {}).get("ai_fallback_count_24h"))
    gemini_status = str((sysd or {}).get("gemini_status") or "")
    dead_chats = _safe_int((mq or {}).get("dead_chats_count"))
    weak_matches = _safe_int((mq or {}).get("weak_matches_count"))
    conv_issues = (conv or {}).get("issues") if isinstance(conv, dict) else []
    premium_expiring = _safe_int((premium or {}).get("expiring_trials_24h"))

    if db_status and db_status != "ok":
        alerts.append(_founder_alert("critical", "Database health is not OK", "Run DB health checks and review recent migrations."))
    if api_errors_24h > 20:
        alerts.append(_founder_alert("critical", f"API errors rising ({api_errors_24h} in 24h)", "Inspect last errors and fix top backend exceptions."))
    elif api_errors_24h > 0:
        alerts.append(_founder_alert("warning", f"API errors detected ({api_errors_24h} in 24h)", "Review error buffer and add targeted guardrails."))
    if fallback_24h > 10:
        alerts.append(_founder_alert("warning", f"AI fallback elevated ({fallback_24h} in 24h)", "Check provider reliability, cache behavior, and prompt failure paths."))
    if gemini_status in {"disabled", "not_active", "error"}:
        alerts.append(_founder_alert("warning", f"Gemini status is {gemini_status}", "Confirm provider config or keep mock/fallback mode intentional."))
    if dead_chats > 0:
        alerts.append(_founder_alert("warning", f"Dead chats growing ({dead_chats})", "Improve revive prompts and match-to-conversation nudges."))
    if weak_matches > 0:
        alerts.append(_founder_alert("warning", f"Weak matches detected ({weak_matches})", "Recompute match quality and tune discovery ranking."))
    if isinstance(conv_issues, list):
        for issue in conv_issues[:2]:
            if isinstance(issue, dict):
                severity = str(issue.get("severity") or "warning").lower()
                alerts.append(
                    _founder_alert(
                        "critical" if severity == "high" else "warning",
                        issue.get("message") or issue.get("type") or "Conversation quality issue",
                        "Tune AI reply prompts and monitor aggregate reply outcomes.",
                    )
                )
    if premium_expiring > 0:
        alerts.append(_founder_alert("warning", f"Trials expiring soon ({premium_expiring} in 24h)", "Send value-focused reminders and check paywall timing."))

    wins: list[dict] = []
    for row in (((pm or {}).get("wins") or [])[:3] if isinstance(pm, dict) else []):
        if isinstance(row, dict):
            title = _founder_clean_text(row.get("title"), 120)
            if title and title != "[redacted]":
                wins.append({"title": title, "metric": _founder_clean_text(row.get("metric"), 120)})
    if north_star["trend"] == "up":
        wins.insert(0, {"title": "Daily active conversations are trending up", "metric": f"value={today_chats}"})
    wins = wins[:5]

    brief = {
        "date": today,
        "north_star": north_star,
        "today_plan": today_plan[:5],
        "alerts": alerts[:8],
        "wins": wins,
        "focus": _founder_focus(today_plan, alerts),
        "referrals": (growth or {}).get("referrals") or {},
    }
    return _sanitize_autopilot_result(brief)


def _command_center_top_recommendation(founder: dict, cto: dict, autopilot: dict) -> dict:
    plan = (founder or {}).get("today_plan") if isinstance(founder, dict) else []
    if isinstance(plan, list) and plan:
        first = plan[0] if isinstance(plan[0], dict) else {}
        return {
            "title": _founder_clean_text(first.get("title"), 120) or "Review today's founder plan",
            "reason": _founder_clean_text(first.get("reason"), 180) or "Founder Mode selected this as the highest-impact priority.",
            "action": _founder_clean_text(first.get("action"), 180) or "Open Founder Mode daily plan.",
        }

    top_cto = (cto or {}).get("top_engineering_priority") if isinstance(cto, dict) else {}
    if isinstance(top_cto, dict) and top_cto.get("title"):
        return {
            "title": _founder_clean_text(top_cto.get("title"), 120),
            "reason": _founder_clean_text(top_cto.get("reason"), 180),
            "action": _founder_clean_text(top_cto.get("recommended_action"), 180) or "Open AI CTO roadmap.",
        }

    suggestions = (autopilot or {}).get("suggestions") if isinstance(autopilot, dict) else []
    if isinstance(suggestions, list) and suggestions:
        first_suggestion = suggestions[0] if isinstance(suggestions[0], dict) else {}
        return {
            "title": _founder_clean_text(first_suggestion.get("title"), 120) or "Review Autopilot suggestion",
            "reason": _founder_clean_text(first_suggestion.get("reason"), 180) or "Autopilot found an operational opportunity.",
            "action": _founder_clean_text(f"Review and confirm: {first_suggestion.get('action_endpoint')}", 180),
        }

    return {
        "title": "Grow daily active conversations",
        "reason": "No critical aggregate issues detected.",
        "action": "Run one focused improvement for activation or conversation quality today.",
    }


def _command_center_status(founder: dict, sysd: dict, cto: dict, autopilot: dict, stats: dict) -> str:
    alerts = (founder or {}).get("alerts") if isinstance(founder, dict) else []
    critical_alert = any(str((row or {}).get("level") or "").lower() == "critical" for row in alerts if isinstance(row, dict))
    db_status = str((sysd or {}).get("database_status") or "ok").lower() if isinstance(sysd, dict) else "ok"
    api_status = str((sysd or {}).get("api_status") or "ok").lower() if isinstance(sysd, dict) else "ok"
    redis_status = str((sysd or {}).get("redis_status") or "").lower() if isinstance(sysd, dict) else ""
    api_errors_24h = _safe_int((sysd or {}).get("api_errors_24h") if isinstance(sysd, dict) else 0)
    fallback_24h = _safe_int((sysd or {}).get("ai_fallback_count_24h") if isinstance(sysd, dict) else 0)
    technical_health = _safe_int((cto or {}).get("technical_health_score", 100) if isinstance(cto, dict) else 100)
    open_reports = _safe_int((((stats or {}).get("safety") or {}).get("open_reports")) if isinstance(stats, dict) else 0)
    suggestions = (autopilot or {}).get("suggestions") if isinstance(autopilot, dict) else []

    if critical_alert or db_status not in {"ok", ""} or api_status not in {"ok", ""} or api_errors_24h > 20 or technical_health < 40:
        return "critical"
    if (
        bool(alerts)
        or bool(suggestions)
        or api_errors_24h > 0
        or fallback_24h > 10
        or redis_status == "error"
        or technical_health < 70
        or open_reports > 0
    ):
        return "warning"
    return "healthy"


def _command_center_critical_alerts(founder: dict, sysd: dict, cto: dict) -> list[dict]:
    alerts: list[dict] = []
    for row in ((founder or {}).get("alerts") or []) if isinstance(founder, dict) else []:
        if not isinstance(row, dict):
            continue
        if str(row.get("level") or "").lower() != "critical":
            continue
        alerts.append(
            {
                "level": "critical",
                "message": _founder_clean_text(row.get("message"), 160),
                "suggested_fix": _founder_clean_text(row.get("suggested_fix"), 180),
            }
        )

    if isinstance(sysd, dict):
        db_status = str(sysd.get("database_status") or "").lower()
        api_errors_24h = _safe_int(sysd.get("api_errors_24h"))
        if db_status and db_status != "ok":
            alerts.append(_founder_alert("critical", "Database health is not OK", "Run DB health checks and review recent migrations."))
        if api_errors_24h > 20:
            alerts.append(_founder_alert("critical", f"API errors rising ({api_errors_24h} in 24h)", "Inspect last errors and fix top backend exceptions."))

    if isinstance(cto, dict) and "technical_health_score" in cto and _safe_int(cto.get("technical_health_score")) < 40:
        alerts.append(_founder_alert("critical", "Technical health score is critical", "Open AI CTO roadmap and fix the top engineering priority."))

    out: list[dict] = []
    seen: set[str] = set()
    for row in alerts:
        key = str(row.get("message") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= 5:
            break
    return out


def _command_center_headline(status: str, critical_alerts: list[dict], top_recommendation: dict) -> str:
    if status == "critical" and critical_alerts:
        return _founder_clean_text(f"Critical attention needed: {critical_alerts[0].get('message')}", 180)
    if status == "warning":
        return _founder_clean_text(f"Watch today: {top_recommendation.get('title')}", 180)
    return "Healthy. Focus on growth and conversation quality."


@router.get("/command-center/home")
def admin_command_center_home(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    stats = admin_stats_overview("today", admin_actor, db)
    sysd = system_doctor(admin_actor, db)
    premium = admin_premium_overview(admin_actor, db)
    cto = admin_cto_roadmap("today", admin_actor, db)
    autopilot = admin_autopilot_suggestions(admin_actor, db)
    founder = admin_founder_daily(admin_actor, db)

    users = (stats or {}).get("users") if isinstance(stats, dict) else {}
    dating = (stats or {}).get("dating") if isinstance(stats, dict) else {}
    ai = (stats or {}).get("ai") if isinstance(stats, dict) else {}
    stats_premium = (stats or {}).get("premium") if isinstance(stats, dict) else {}
    safety = (stats or {}).get("safety") if isinstance(stats, dict) else {}
    today = {
        "new_users": _safe_int((users or {}).get("new")),
        "active_users": _safe_int((users or {}).get("active")),
        "matches": _safe_int((dating or {}).get("matches")),
        "messages": _safe_int((dating or {}).get("messages")),
        "ai_calls": _safe_int((ai or {}).get("ai_calls")),
        "premium_users": _safe_int((stats_premium or {}).get("premium_users") or (premium or {}).get("premium_users")),
        "open_reports": _safe_int((safety or {}).get("open_reports")),
    }

    critical_alerts = _command_center_critical_alerts(founder, sysd, cto)
    top_recommendation = _command_center_top_recommendation(founder, cto, autopilot)
    status = _command_center_status(founder, sysd, cto, autopilot, stats)
    home = {
        "status": status,
        "headline": _command_center_headline(status, critical_alerts, top_recommendation),
        "today": today,
        "critical_alerts": critical_alerts,
        "top_recommendation": top_recommendation,
        "quick_actions": [
            {"id": "stats", "label": "Stats", "risk": "none"},
            {"id": "founder", "label": "Founder Mode", "risk": "none"},
            {"id": "system_doctor", "label": "System Doctor", "risk": "none"},
            {"id": "autopilot", "label": "Autopilot", "risk": "low"},
            {"id": "users", "label": "Users", "risk": "none"},
            {"id": "safety", "label": "Safety", "risk": "none"},
            {"id": "language", "label": "Language", "risk": "none"},
            {"id": "more", "label": "More", "risk": "none"},
        ],
    }
    return _sanitize_autopilot_result(home)


def _admin_alert(
    *,
    alert_id: str,
    level: str,
    title: Any,
    message: Any,
    source: str,
    dedupe_key: str,
    action_label: str,
    action_callback: str,
    created_at: str,
) -> dict:
    lvl = str(level or "info").strip().lower()
    if lvl not in {"critical", "warning", "info"}:
        lvl = "info"
    src = str(source or "system").strip().lower()
    if src not in {"system", "ai", "safety", "premium", "growth", "matches"}:
        src = "system"
    return {
        "id": str(alert_id or dedupe_key).strip()[:80],
        "level": lvl,
        "title": _founder_clean_text(title, 100),
        "message": _founder_clean_text(message, 220),
        "source": src,
        "created_at": created_at,
        "dedupe_key": _founder_clean_text(dedupe_key, 120),
        "action": {
            "label": _founder_clean_text(action_label, 80),
            "callback": str(action_callback or "m:home").strip()[:64],
        },
    }


def _append_admin_alert(alerts: list[dict], seen: set[str], **kwargs: Any) -> None:
    key = str(kwargs.get("dedupe_key") or kwargs.get("alert_id") or "").strip()
    if not key or key in seen:
        return
    alert = _admin_alert(**kwargs)
    if not alert.get("title") or alert.get("title") == "[redacted]":
        return
    seen.add(key)
    alerts.append(alert)


@router.get("/alerts/poll")
def admin_alerts_poll(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    created_at = datetime.now(UTC).isoformat()
    alerts: list[dict] = []
    seen: set[str] = set()

    sysd = system_doctor(admin_actor, db)
    stats_today = admin_stats_overview("today", admin_actor, db)
    mq = admin_match_quality_overview(admin_actor, db)
    premium = admin_premium_overview(admin_actor, db)
    growth = admin_growth_overview("today", admin_actor, db)
    l10n = localization_quality(admin_actor)

    db_status = str((sysd or {}).get("database_status") or "").lower()
    redis_status = str((sysd or {}).get("redis_status") or "").lower()
    api_errors_24h = _safe_int((sysd or {}).get("api_errors_24h"))
    fallback_24h = _safe_int((sysd or {}).get("ai_fallback_count_24h"))
    gemini_status = str((sysd or {}).get("gemini_status") or "").lower()
    has_gemini_error = bool((sysd or {}).get("last_gemini_error"))
    ai_op = str((sysd or {}).get("ai_operational_status") or "").strip().lower()
    ai_fb = bool((sysd or {}).get("ai_fallback_active"))
    gem_err_class = str((sysd or {}).get("gemini_error_classification") or "").strip()

    system_action = {"action_label": "Open System Doctor", "action_callback": "m:system"}
    if db_status and db_status != "ok":
        _append_admin_alert(
            alerts,
            seen,
            alert_id="database_unhealthy",
            level="critical",
            title="Database health is not OK",
            message=f"System Doctor reports database_status={db_status}. Review migrations and DB connectivity.",
            source="system",
            dedupe_key="system:database_unhealthy",
            created_at=created_at,
            **system_action,
        )
    if redis_status == "error":
        _append_admin_alert(
            alerts,
            seen,
            alert_id="redis_unhealthy",
            level="warning",
            title="Redis is unhealthy",
            message="System Doctor reports Redis errors. Cache and rate-limit behavior may be degraded.",
            source="system",
            dedupe_key="system:redis_unhealthy",
            created_at=created_at,
            **system_action,
        )
    if api_errors_24h > 0:
        _append_admin_alert(
            alerts,
            seen,
            alert_id="api_errors_high" if api_errors_24h > 20 else "api_errors_detected",
            level="critical" if api_errors_24h > 20 else "warning",
            title="API errors are rising" if api_errors_24h > 20 else "API errors detected",
            message=f"{api_errors_24h} API errors were recorded in the last 24h.",
            source="system",
            dedupe_key="system:api_errors_high" if api_errors_24h > 20 else "system:api_errors_detected",
            created_at=created_at,
            **system_action,
        )

    gem_alert_bucket = f"{ai_op}|fb:{int(ai_fb)}|cls:{gem_err_class}|err:{int(has_gemini_error)}|gs:{gemini_status}"
    if ai_op == "fail" or (has_gemini_error and not ai_fb and gem_err_class in {"api_key_missing", "api_key_invalid"}):
        if gemini_alert_bucket_should_emit(f"critical:{gem_alert_bucket}"):
            _append_admin_alert(
                alerts,
                seen,
                alert_id="gemini_provider_critical",
                level="critical",
                title="Gemini provider failure — users may be impacted",
                message="Gemini errors detected without a healthy fallback signal. Investigate keys, quotas, and AI routing.",
                source="ai",
                dedupe_key="ai:gemini_provider_critical",
                created_at=created_at,
                **system_action,
            )
    elif ai_op == "degraded" or has_gemini_error or gemini_status == "error":
        if gemini_alert_bucket_should_emit(f"warn:{gem_alert_bucket}"):
            _append_admin_alert(
                alerts,
                seen,
                alert_id="gemini_provider_degraded",
                level="warning",
                title="Gemini free-tier/provider errors detected",
                message="Gemini free-tier/provider errors detected. Fallback is active. Upgrade Google AI billing or wait for quota reset.",
                source="ai",
                dedupe_key="ai:gemini_provider_degraded",
                created_at=created_at,
                **system_action,
            )
    elif gemini_status in {"disabled", "not_active"}:
        _append_admin_alert(
            alerts,
            seen,
            alert_id="gemini_not_active",
            level="info",
            title="Gemini is not active",
            message=f"AI provider status is {gemini_status}. Confirm this is intentional.",
            source="ai",
            dedupe_key="ai:gemini_not_active",
            created_at=created_at,
            **system_action,
        )
    if fallback_24h > 10:
        fb_lvl = "warning"
        if fallback_24h > 30 and ai_op != "degraded":
            fb_lvl = "critical"
        elif fallback_24h > 30 and ai_op == "degraded":
            fb_lvl = "warning"
        _append_admin_alert(
            alerts,
            seen,
            alert_id="ai_fallback_high",
            level=fb_lvl,
            title="AI fallback is elevated",
            message=f"{fallback_24h} AI fallback events were recorded in the last 24h."
            + (" Deterministic fallback is protecting users while Gemini recovers." if ai_op == "degraded" else ""),
            source="ai",
            dedupe_key="ai:fallback_high",
            created_at=created_at,
            **system_action,
        )

    safety = (stats_today or {}).get("safety") if isinstance(stats_today, dict) else {}
    open_reports = _safe_int((safety or {}).get("open_reports"))
    new_reports = _safe_int((safety or {}).get("new_reports"))
    banned_users = _safe_int((safety or {}).get("banned_users"))
    if open_reports > 5:
        _append_admin_alert(
            alerts,
            seen,
            alert_id="open_reports_high",
            level="critical" if open_reports > 20 else "warning",
            title="Open reports need moderation",
            message=f"{open_reports} reports are open. Triage the safety queue.",
            source="safety",
            dedupe_key="safety:open_reports_high",
            action_label="Open Safety",
            action_callback="m:safety",
            created_at=created_at,
        )
    if banned_users >= 10 and new_reports > 0:
        _append_admin_alert(
            alerts,
            seen,
            alert_id="banned_users_spike",
            level="warning",
            title="Banned users spike detected",
            message=f"{banned_users} users are currently banned and {new_reports} new reports arrived today.",
            source="safety",
            dedupe_key="safety:banned_users_spike",
            action_label="Open Safety",
            action_callback="m:safety",
            created_at=created_at,
        )

    dead_chats = _safe_int((mq or {}).get("dead_chats_count"))
    weak_matches = _safe_int((mq or {}).get("weak_matches_count"))
    if dead_chats > 20:
        _append_admin_alert(
            alerts,
            seen,
            alert_id="dead_chats_increasing",
            level="critical" if dead_chats > 200 else "warning",
            title="Dead chats are increasing",
            message=f"{dead_chats} matches appear stalled or inactive.",
            source="matches",
            dedupe_key="matches:dead_chats_increasing",
            action_label="Open Match Quality",
            action_callback="m:match_quality",
            created_at=created_at,
        )
    if weak_matches > 25:
        _append_admin_alert(
            alerts,
            seen,
            alert_id="weak_matches_increasing",
            level="critical" if weak_matches > 100 else "warning",
            title="Weak matches are increasing",
            message=f"{weak_matches} weak match signals were detected.",
            source="matches",
            dedupe_key="matches:weak_matches_increasing",
            action_label="Open Match Quality",
            action_callback="m:match_quality",
            created_at=created_at,
        )

    expiring_trials_24h = _safe_int((premium or {}).get("expiring_trials_24h"))
    if expiring_trials_24h > 0:
        _append_admin_alert(
            alerts,
            seen,
            alert_id="premium_trials_expiring_24h",
            level="warning" if expiring_trials_24h >= 5 else "info",
            title="Premium trials expiring soon",
            message=f"{expiring_trials_24h} premium trials expire in the next 24h.",
            source="premium",
            dedupe_key="premium:trials_expiring_24h",
            action_label="Open Premium",
            action_callback="m:premium",
            created_at=created_at,
        )

    monetization = (growth or {}).get("monetization") if isinstance(growth, dict) else {}
    paywall_views = _safe_int((monetization or {}).get("paywall_views"))
    premium_conversion_rate = _safe_float((monetization or {}).get("premium_conversion_rate"))
    if paywall_views >= 50 and premium_conversion_rate < 0.05:
        _append_admin_alert(
            alerts,
            seen,
            alert_id="paywall_conversion_low",
            level="warning",
            title="Paywall conversion is low",
            message=f"{paywall_views} paywall views with {premium_conversion_rate:.1%} premium conversion.",
            source="growth",
            dedupe_key="growth:paywall_conversion_low",
            action_label="Open Growth",
            action_callback="m:growth",
            created_at=created_at,
        )

    l10n_issues = _localization_issue_count(l10n if isinstance(l10n, dict) else {})
    if l10n_issues > 20:
        _append_admin_alert(
            alerts,
            seen,
            alert_id="localization_issues_high",
            level="critical" if l10n_issues > 50 else "warning",
            title="Localization issues are high",
            message=f"{l10n_issues} localization quality issues were detected.",
            source="growth",
            dedupe_key="growth:localization_issues_high",
            action_label="Open Localization",
            action_callback="m:l10n",
            created_at=created_at,
        )

    level_rank = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda row: (level_rank.get(str(row.get("level") or "info"), 3), str(row.get("source") or ""), str(row.get("id") or "")))
    return _sanitize_autopilot_result({"alerts": alerts[:20]})


def _release_check(check_id: str, title: str, status: str, details: Any, blocking: bool) -> dict:
    st = str(status or "warning").strip().lower()
    if st not in {"pass", "warning", "fail"}:
        st = "warning"
    return {
        "id": check_id,
        "title": title,
        "status": st,
        "details": _founder_clean_text(details, 220),
        "blocking": bool(blocking),
    }


def _release_backup_recent(hours: int = 24) -> tuple[bool, str]:
    base = _backup_dir()
    if not base.exists():
        return False, "No backup directory found"
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    latest: Path | None = None
    for path in base.iterdir():
        if not path.is_file():
            continue
        try:
            _validate_backup_filename(path.name)
        except HTTPException:
            continue
        if latest is None or path.stat().st_mtime > latest.stat().st_mtime:
            latest = path
    if latest is None:
        return False, "No backups found"
    latest_dt = datetime.fromtimestamp(float(latest.stat().st_mtime), UTC)
    if latest_dt >= cutoff:
        return True, f"Latest backup {latest.name} at {latest_dt.isoformat()}"
    return False, f"Latest backup {latest.name} is older than {hours}h"


def _release_tests_check() -> dict:
    cache = _repo_root() / ".pytest_cache" / "v" / "cache" / "lastfailed"
    if not cache.exists():
        return _release_check(
            "tests",
            "Backend tests",
            "pass",
            "No local pytest lastfailed cache (optional); rely on CI or run pytest locally before release.",
            False,
        )
    try:
        data = json.loads(cache.read_text(encoding="utf-8") or "{}")
    except Exception:
        return _release_check("tests", "Backend tests", "warning", "Cached test status unreadable; run backend tests before release.", False)
    if isinstance(data, dict) and not data:
        return _release_check("tests", "Backend tests", "pass", "No cached failing tests detected.", True)
    failed = len(data) if isinstance(data, dict) else 1
    env = str(getattr(settings, "ENV", "") or "development").strip().lower()
    if env in {"production", "prod"}:
        return _release_check("tests", "Backend tests", "fail", f"{failed} cached failing tests detected.", True)
    return _release_check(
        "tests",
        "Backend tests",
        "warning",
        f"{failed} cached failing tests detected locally (dev: non-blocking; clear .pytest_cache or fix tests).",
        False,
    )


def _release_score(checks: list[dict]) -> int:
    """Weighted score: optional gaps are warnings, not score wipeouts. Core stack healthy ⇒ floor 50."""
    if not checks:
        return 100
    core_ids = frozenset({"api_health", "db_health", "redis_health", "alembic", "gemini"})
    core_rows = [row for row in checks if row.get("id") in core_ids]
    core_all_pass = bool(core_rows) and all(str(row.get("status") or "") == "pass" for row in core_rows)

    pts = 0.0
    mx = 0.0
    for row in checks:
        w = 1.0 + (0.55 if row.get("blocking") else 0.0)
        mx += w
        st = str(row.get("status") or "")
        if st == "pass":
            pts += w
        elif st == "warning":
            pts += w * 0.85
        else:
            pts += w * (0.42 if row.get("blocking") else 0.68)
    if mx <= 0:
        return 100
    raw = int(round(100.0 * pts / mx))
    if core_all_pass:
        raw = max(50, raw)
    return max(1, min(100, raw))


def _release_recommended_actions(checks: list[dict]) -> list[str]:
    actions: list[str] = []
    for row in checks:
        status = str(row.get("status") or "")
        if status == "pass":
            continue
        check_id = str(row.get("id") or "")
        title = str(row.get("title") or "")
        if check_id == "api_health":
            actions.append("Open System Doctor and restore API health.")
        elif check_id == "db_health":
            actions.append("Fix database connectivity and verify migrations.")
        elif check_id == "redis_health":
            actions.append("Verify Redis availability or confirm disabled cache mode is intentional.")
        elif check_id == "alembic":
            actions.append("Run or verify Alembic migrations before release.")
        elif check_id == "gemini":
            actions.append("Confirm Gemini provider configuration and clear recent AI failures.")
        elif check_id == "critical_alerts":
            actions.append("Resolve critical admin alerts before release.")
        elif check_id == "backup_recent":
            actions.append("Create a fresh database backup before release.")
        elif check_id == "open_reports":
            actions.append("Triage open safety reports.")
        elif check_id == "api_errors":
            actions.append("Inspect error buffer and fix top API exceptions.")
        elif check_id == "localization":
            actions.append("Run localization scan/fix and review critical locale issues.")
        elif check_id == "billing":
            actions.append("Verify premium and billing provider configuration.")
        elif check_id == "tests":
            actions.append("Run backend tests and resolve failures.")
        elif check_id == "telegram_menu_qa":
            actions.append("Open Menu QA, fix missing handlers or render errors; review any unsafe heuristics.")
        elif check_id == "localization_coverage":
            actions.append("Improve locale JSON coverage (including core-ui-translations overlays).")
        else:
            actions.append(f"Review release check: {title}")
        if len(actions) >= 8:
            break
    return actions


@router.get("/release/readiness")
def admin_release_readiness(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    env = str(getattr(settings, "ENV", "") or "development").strip().lower() or "development"
    production = env in {"production", "prod"}
    checks: list[dict] = []

    sysd = system_doctor(admin_actor, db)
    stats = admin_stats_overview("today", admin_actor, db)
    alerts = admin_alerts_poll(admin_actor, db)
    l10n = localization_quality(admin_actor)

    api_status = str((sysd or {}).get("api_status") or "").lower()
    checks.append(_release_check("api_health", "API healthy", "pass" if api_status == "ok" else "fail", f"api_status={api_status or 'unknown'}", True))

    db_status = str((sysd or {}).get("database_status") or "").lower()
    checks.append(_release_check("db_health", "DB healthy", "pass" if db_status == "ok" else "fail", f"database_status={db_status or 'unknown'}", True))

    redis_status = str((sysd or {}).get("redis_status") or "").lower()
    if redis_status == "ok":
        redis_check = _release_check("redis_health", "Redis healthy", "pass", "redis_status=ok", True)
    elif redis_status == "error" or production:
        redis_check = _release_check("redis_health", "Redis healthy", "fail", f"redis_status={redis_status or 'unknown'}", production)
    else:
        redis_check = _release_check("redis_health", "Redis healthy", "warning", f"redis_status={redis_status or 'unknown'}", False)
    checks.append(redis_check)

    alembic_revision = (sysd or {}).get("alembic_revision")
    checks.append(
        _release_check(
            "alembic",
            "Alembic revision current",
            "pass" if alembic_revision else ("fail" if production else "warning"),
            f"alembic_revision={alembic_revision or 'unavailable'}",
            production,
        )
    )

    gemini_status = str((sysd or {}).get("gemini_status") or "").lower()
    last_gemini_error = bool((sysd or {}).get("last_gemini_error"))
    ai_op_status = str((sysd or {}).get("ai_operational_status") or "").lower()
    if ai_op_status == "ok" and not last_gemini_error:
        gemini_check = _release_check("gemini", "Gemini configured and stable", "pass", "Gemini status OK", True)
    elif ai_op_status == "degraded":
        gemini_check = _release_check(
            "gemini",
            "Gemini configured and stable",
            "warning",
            "AI operational status DEGRADED — fallback active; monitor quotas/keys.",
            production,
        )
    elif gemini_status == "error" or last_gemini_error or ai_op_status == "fail":
        gemini_check = _release_check("gemini", "Gemini configured and stable", "fail", "Gemini provider error or AI operational FAIL.", production)
    else:
        gemini_check = _release_check("gemini", "Gemini configured and stable", "warning", f"gemini_status={gemini_status or 'unknown'}", production)
    checks.append(gemini_check)

    critical_alerts = [row for row in ((alerts or {}).get("alerts") or []) if isinstance(row, dict) and str(row.get("level") or "") == "critical"]
    checks.append(
        _release_check(
            "critical_alerts",
            "No critical alerts",
            "pass" if not critical_alerts else "fail",
            "No critical alerts" if not critical_alerts else f"{len(critical_alerts)} critical alerts active",
            True,
        )
    )

    backup_ok, backup_details = _release_backup_recent(24)
    if production:
        checks.append(_release_check("backup_recent", "Backup exists in last 24h", "pass" if backup_ok else "fail", backup_details, True))
    else:
        checks.append(
            _release_check(
                "backup_recent",
                "Backup exists (recommended)",
                "pass" if backup_ok else "warning",
                backup_details,
                False,
            )
        )

    try:
        tqa = admin_telegram_menu_qa_scan(admin_actor)
        tqas = (tqa or {}).get("summary") if isinstance(tqa, dict) else {}
        mh = _safe_int((tqas or {}).get("missing_handlers"))
        rerr = _safe_int((tqas or {}).get("render_errors"))
        unsafe_h = _safe_int((tqas or {}).get("unsafe_actions"))
        tq_st = str((tqa or {}).get("status") or "")
        if mh > 0:
            checks.append(
                _release_check(
                    "telegram_menu_qa",
                    "Telegram Menu QA",
                    "warning",
                    f"missing_handlers={mh}, render_errors={rerr} (Menu QA is warning-only).",
                    False,
                )
            )
        elif rerr > 0 or tq_st == "warning" or unsafe_h > 0:
            checks.append(
                _release_check(
                    "telegram_menu_qa",
                    "Telegram Menu QA",
                    "warning",
                    f"status={tq_st}, render_errors={rerr}, unsafe_heuristic={unsafe_h}",
                    False,
                )
            )
        else:
            checks.append(_release_check("telegram_menu_qa", "Telegram Menu QA", "pass", f"status={tq_st}", False))
    except Exception as e:
        checks.append(
            _release_check("telegram_menu_qa", "Telegram Menu QA", "warning", f"scan_unavailable={type(e).__name__}", False)
        )

    try:
        cov = compute_localization_coverage()
        locrows = [x for x in (cov.get("locales") or []) if isinstance(x, dict) and str(x.get("code") or "") != "en"]
        summ = cov.get("summary") if isinstance(cov.get("summary"), dict) else {}
        miss_tot = _safe_int(summ.get("missing_keys_total"))
        raw_tot = _safe_int(summ.get("raw_value_leaks_total"))
        fb_tot = _safe_int(summ.get("en_fallback_keys_total"))
        if not locrows:
            avg_unique = 0.0
            avg_present = 0.0
        else:
            avg_unique = float(sum(_safe_int(x.get("coverage")) for x in locrows)) / float(len(locrows))
            avg_present = float(
                sum(_safe_int(x.get("coverage_present_pct", x.get("coverage"))) for x in locrows)
            ) / float(len(locrows))
        # Intentional EN fallback should not read as a release failure; block only on structural gaps / raw leaks.
        cov_st = "warning" if miss_tot > 0 or raw_tot > 0 else "pass"
        checks.append(
            _release_check(
                "localization_coverage",
                "Localization JSON coverage",
                cov_st,
                f"missing={miss_tot}, raw={raw_tot}, fallback_used={fb_tot}, "
                f"avg_unique_pct={int(round(avg_unique))}, avg_present_pct={int(round(avg_present))}",
                False,
            )
        )
    except Exception as e:
        checks.append(
            _release_check(
                "localization_coverage",
                "Localization JSON coverage",
                "warning",
                f"unavailable={type(e).__name__}",
                False,
            )
        )

    safety = (stats or {}).get("safety") if isinstance(stats, dict) else {}
    open_reports = _safe_int((safety or {}).get("open_reports"))
    checks.append(
        _release_check(
            "open_reports",
            "Open reports not too high",
            "fail" if open_reports > 20 else ("warning" if open_reports > 5 else "pass"),
            f"open_reports={open_reports}",
            open_reports > 20,
        )
    )

    api_errors = _safe_int((sysd or {}).get("api_errors_24h"))
    checks.append(
        _release_check(
            "api_errors",
            "API errors last 24h acceptable",
            "fail" if api_errors > 20 else ("warning" if api_errors > 0 else "pass"),
            f"api_errors_24h={api_errors}",
            api_errors > 20,
        )
    )

    l10n_issues = _localization_issue_count(l10n if isinstance(l10n, dict) else {})
    checks.append(
        _release_check(
            "localization",
            "Localization critical issues absent",
            "fail" if l10n_issues > 50 else ("warning" if l10n_issues > 20 else "pass"),
            f"localization_issues={l10n_issues}",
            l10n_issues > 50,
        )
    )

    premium_enabled = bool(getattr(settings, "ENABLE_PREMIUM_FEATURES", True))
    provider = str(getattr(settings, "PAYMENTS_PROVIDER", "") or "mock").strip().lower()
    stripe_ready = bool(str(getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip()) and bool(str(getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or "").strip())
    if not premium_enabled:
        billing_check = _release_check("billing", "Premium/billing config valid", "warning", "Premium features disabled.", False)
    elif production and provider == "stripe" and not stripe_ready:
        billing_check = _release_check("billing", "Premium/billing config valid", "fail", "Stripe provider selected but billing secrets are not fully configured.", True)
    elif production and provider == "mock":
        billing_check = _release_check("billing", "Premium/billing config valid", "fail", "Mock payments provider is not release-ready for production.", True)
    else:
        billing_check = _release_check("billing", "Premium/billing config valid", "pass", f"payments_provider={provider}", False)
    checks.append(billing_check)

    checks.append(_release_tests_check())

    blockers = [row.get("title") for row in checks if row.get("status") == "fail" and bool(row.get("blocking"))]
    warnings = [row.get("title") for row in checks if row.get("status") == "warning" or (row.get("status") == "fail" and not bool(row.get("blocking")))]
    score = _release_score(checks)
    return _sanitize_autopilot_result(
        {
            "ready": not blockers,
            "score": score,
            "environment": "production" if env == "prod" else env,
            "checks": checks,
            "blockers": blockers,
            "warnings": warnings,
            "recommended_actions": _release_recommended_actions(checks),
        }
    )


@router.post("/release/mark")
def admin_release_mark(
    payload: dict = Body(default_factory=dict),
    admin_actor: User | dict = Depends(get_admin_actor),
    db: Session = Depends(get_db),
):
    _require_confirm(payload)
    version = _founder_clean_text(payload.get("version"), 64)
    if not version or version == "[redacted]":
        raise HTTPException(status_code=400, detail={"error": "invalid_version"})
    notes = _founder_clean_text(payload.get("notes"), 500)
    marker = {
        "action": "release_mark",
        "version": version,
        "notes": notes,
        "environment": str(getattr(settings, "ENV", "") or ""),
        "status": "success",
    }
    track_event(db, "admin_action", user_id=_actor_user_id(admin_actor), payload={**marker, **_actor_meta(admin_actor)})
    return {"ok": True, "version": version, "environment": marker["environment"], "marked_at": datetime.now(UTC).isoformat()}


@router.post("/profile/verification/approve")
def approve_profile_verification(user_id: int, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == int(user_id)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.verification_status = "verified"
    profile.verification_level = "photo"
    profile.verification_type = "selfie"
    profile.verification_updated_at = datetime.now(UTC)
    profile.verified = True
    profile.verified_at = datetime.now(UTC)
    db.add(profile)
    db.commit()
    track_event(db, "verification_badge_seen", user_id=int(user_id), payload={"source": "admin_approved"})
    return {"ok": True, "verification_status": "verified"}


@router.post("/profile/verification/reject")
def reject_profile_verification(user_id: int, admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == int(user_id)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.verification_status = "none"
    profile.verification_level = "none"
    profile.verification_type = "selfie"
    profile.verification_updated_at = datetime.now(UTC)
    profile.verified = False
    profile.verified_at = None
    db.add(profile)
    db.commit()
    track_event(db, "verification_badge_seen", user_id=int(user_id), payload={"source": "admin_rejected"})
    return {"ok": True, "verification_status": "none"}


@router.get("/ai-debug")
def ai_debug(admin_actor: User | dict = Depends(get_admin_actor)):
    provider = str(getattr(settings, "AI_PROVIDER", "") or "").strip() or "mock"
    return {
        "ai_provider": provider,
        "ai_model": str(getattr(settings, "AI_MODEL", "") or "").strip(),
        "gemini_model": str(getattr(settings, "GEMINI_MODEL", "") or "").strip(),
        "has_gemini_key": bool(str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()),
        "last_provider_used": get_last_provider_used() or ("gemini" if provider == "gemini" else "fallback"),
        "last_gemini_error": get_last_gemini_error(),
        "last_quota_error": get_last_gemini_quota_error(),
        "fallback_count_last_24h": int(get_fallback_count_24h() or 0),
        "gemini_calls_today": int(get_gemini_calls_today() or 0),
        "gemini_calls_this_minute": int(get_gemini_calls_minute() or 0),
        "gemini_cache": get_gemini_cache_stats_today(),
    }


class _GeminiTestOut(BaseModel):
    text: str


@router.post("/ai-debug/test-gemini")
async def ai_debug_test_gemini(admin_actor: User | dict = Depends(get_admin_actor)):
    """
    Makes a tiny Gemini request to verify connectivity and model config.
    Never returns API key.
    """
    client = GeminiClient()
    try:
        raw = await client.generate_json(
            system_prompt="Respond ONLY in Ukrainian. Output ONLY JSON: {\"text\":\"...\"}",
            user_prompt="Скажи ОК українською",
            out_model=None,
            timeout_s=10.0,
            max_retries=0,
            temperature=0.2,
            max_output_tokens=64,
            surface="admin-debug",
        )
        set_last_provider_used("gemini")
        return {"success": True, "provider": "gemini", "model": GeminiClient.model_name(), "raw": raw, "error": None}
    except GeminiError as e:
        set_last_provider_used("fallback")
        set_last_gemini_error(f"{e.code}: {e.message}")
        incr_fallback_24h()
        log_ai_fallback_triggered(
            endpoint="admin/ai-debug/test-gemini",
            locale=None,
            reason=str(e.code),
            error_message=str(e.message or e.code),
            provider="gemini",
        )
        return {
            "success": False,
            "provider": "gemini",
            "model": str(e.model or GeminiClient.model_name()),
            "response": None,
            "raw": None,
            "error": str(e.message or e.code),
            "status": e.status_code,
            "response_body": (e.response_body or "")[:4000] if e.response_body else None,
            "code": e.code,
        }
    except Exception as e:
        set_last_provider_used("fallback")
        set_last_gemini_error(str(e))
        incr_fallback_24h()
        log_ai_fallback_triggered(
            endpoint="admin/ai-debug/test-gemini",
            locale=None,
            reason=type(e).__name__,
            error_message=str(e),
            provider="gemini",
        )
        return {"success": False, "provider": "gemini", "model": GeminiClient.model_name(), "response": None, "raw": None, "error": str(e)}


@router.post("/dev/grant-premium-all")
def dev_grant_premium_all(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """
    DEV/STAGING ONLY.
    Extends users.premium_until by setting it to now + 90 days for all users whose premium_until is null or expired.
    Does not touch payments/subscriptions tables.
    """
    _ensure_not_production()
    now = datetime.now(UTC)
    new_until = now + timedelta(days=90)
    updated = (
        db.query(User)
        .filter((User.premium_until.is_(None)) | (User.premium_until < now))
        .update({User.premium_until: new_until}, synchronize_session=False)
    )
    db.commit()
    print(f"DEV: granted premium to {int(updated or 0)} users at {now.isoformat()}")
    return {"ok": True, "updated_users": int(updated or 0), "premium_until": new_until.isoformat(), "timestamp": now.isoformat()}


@router.post("/dev/revoke-premium-all")
def dev_revoke_premium_all(admin_actor: User | dict = Depends(get_admin_actor), db: Session = Depends(get_db)):
    """
    DEV/STAGING ONLY.
    Reverses the dev grant by setting users.premium_until to NULL for all users.
    Does not touch payments/subscriptions tables.
    """
    _ensure_not_production()
    now = datetime.now(UTC)
    updated = db.query(User).update({User.premium_until: None}, synchronize_session=False)
    db.commit()
    print(f"DEV: revoked premium from {int(updated or 0)} users at {now.isoformat()}")
    return {"ok": True, "updated_users": int(updated or 0), "timestamp": now.isoformat()}
