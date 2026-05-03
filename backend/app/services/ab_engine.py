from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.analytics_event import AnalyticsEvent
from app.models.app_setting import AppSetting
from app.models.user_ai_memory import UserAiMemory
from app.services.analytics import track_event
from app.services.ai.safe_ai import log_ai_fallback_triggered

log = logging.getLogger("neyra.ab_engine")

AB_ENGINE_STATE_KEY = "ab_engine_state"
AB_MEMORY_TYPE = "ab_variant"

# Experiment keys (logical; map to UI surfaces in frontend).
EXPERIMENT_KEYS = frozenset(
    {
        "chat.opener.nudge",
        "paywall.message",
        "onboarding.cta",
        "paywall.modal.copy",
        "growth.trial.duration",
        "ai.limit.copy",
        "subscription.pricing.copy",
    }
)

DEFAULT_BASELINES: dict[str, str] = {
    "chat.opener.nudge": "Say hi — it takes 2 seconds.",
    "paywall.message": "Want better chances? Unlock smart replies",
    "onboarding.cta": "Continue",
    "paywall.modal.copy": "Unlock unlimited AI, likes insights, and smarter replies.",
    "growth.trial.duration": "Start your 5-day Premium trial",
    "ai.limit.copy": "You’ve hit today’s free AI limit — upgrade for unlimited suggestions.",
    "subscription.pricing.copy": "Show savings and highlighted yearly plan",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _sha256_mod(s: str, mod: int) -> int:
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:12], 16) % max(1, mod)


def _load_state(db: Session) -> dict[str, Any]:
    row = db.query(AppSetting).filter(AppSetting.key == AB_ENGINE_STATE_KEY).first()
    if not row or not (row.value_json or "").strip():
        return _default_state()
    try:
        data = json.loads(row.value_json)
        if not isinstance(data, dict):
            return _default_state()
        return _merge_defaults_into_state(data)
    except Exception:
        return _default_state()


def _save_state(db: Session, state: dict[str, Any]) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == AB_ENGINE_STATE_KEY).first()
    payload = json.dumps(state, ensure_ascii=False)
    if not row:
        row = AppSetting(key=AB_ENGINE_STATE_KEY, value_json=payload)
        db.add(row)
    else:
        row.value_json = payload
    db.commit()


def _default_state() -> dict[str, Any]:
    experiments: dict[str, Any] = {}
    for key in sorted(EXPERIMENT_KEYS):
        base = DEFAULT_BASELINES.get(key, "")
        experiments[key] = {
            "status": "running",
            "round": 1,
            "champion_id": "v0",
            "min_impressions_per_variant": 60,
            "min_relative_lift_vs_median": 0.06,
            "evaluation_window_days": 7,
            "variants": _seed_variants(key, base),
        }
    return {"version": 1, "updated_at": _utcnow().isoformat(), "experiments": experiments}


def _merge_defaults_into_state(data: dict[str, Any]) -> dict[str, Any]:
    experiments = data.get("experiments")
    if not isinstance(experiments, dict):
        experiments = {}
    for key in EXPERIMENT_KEYS:
        if key not in experiments or not isinstance(experiments[key], dict):
            base = DEFAULT_BASELINES.get(key, "")
            experiments[key] = {
                "status": "running",
                "round": 1,
                "champion_id": "v0",
                "min_impressions_per_variant": 60,
                "min_relative_lift_vs_median": 0.06,
                "evaluation_window_days": 7,
                "variants": _seed_variants(key, base),
            }
    data["experiments"] = experiments
    return data


def _seed_variants(experiment_key: str, baseline: str) -> list[dict[str, Any]]:
    """2–4 local variants without AI (AI can replace later)."""
    base = (baseline or "").strip() or "Tap to continue"
    seeds = {
        "chat.opener.nudge": [
            base,
            "Say hello — it’s quick and starts the vibe.",
            "Break the ice with a tiny hello.",
            "Two seconds for a hi can change the chat.",
        ],
        "paywall.message": [
            base,
            "Want an edge? Unlock smarter replies.",
            "Boost your odds — smart replies are one tap away.",
            "Level up your messages — unlock AI that fits you.",
        ],
        "onboarding.cta": [
            base,
            "Keep going — you’re almost there.",
            "Next step — let’s finish your profile.",
            "Almost done — continue to Discover.",
        ],
        "paywall.modal.copy": [
            base,
            "Get noticed faster — Premium unlocks the full AI wingman.",
            "More replies, better timing — upgrade to unlock everything.",
            "Don’t leave chemistry on read — unlock Premium tools.",
        ],
        "growth.trial.duration": [
            base,
            "Start your 7-day Premium trial",
            "Try Premium free for 3 days",
            "5 days of Premium on us — see the difference",
        ],
        "ai.limit.copy": [
            base,
            "Daily AI cap reached — go Premium for unlimited chat help.",
            "You’re out of free AI for today — Premium keeps you in flow.",
            "Smart replies pause until tomorrow — or unlock Premium now.",
        ],
        "subscription.pricing.copy": [
            base,
            "Emphasize yearly savings vs monthly",
            "Minimal pricing — fewer badges",
            "Trust-first copy — same prices, calmer layout",
        ],
    }
    texts = seeds.get(experiment_key) or [base, base + " ✨", base + " →", base + " ·"]
    out: list[dict[str, Any]] = []
    for i, t in enumerate(texts[:4]):
        out.append({"id": f"v{i}", "text": str(t).strip(), "source": "seed"})
    return out


def _variant_by_index(experiment: dict[str, Any], index: int) -> dict[str, Any]:
    variants = experiment.get("variants") or []
    if not variants:
        return {"id": "v0", "text": DEFAULT_BASELINES.get("chat.opener.nudge", ""), "source": "fallback"}
    idx = max(0, min(len(variants) - 1, index))
    v = variants[idx]
    if isinstance(v, dict) and v.get("text"):
        return v
    return {"id": f"v{idx}", "text": str(v), "source": "raw"}


def _get_or_assign_variant_index(db: Session, user_id: int, experiment_key: str, experiment: dict[str, Any]) -> int:
    variants = experiment.get("variants") or []
    n = len(variants)
    if n < 1:
        return 0

    row = (
        db.query(UserAiMemory)
        .filter(
            UserAiMemory.user_id == int(user_id),
            UserAiMemory.memory_type == AB_MEMORY_TYPE,
            UserAiMemory.key == str(experiment_key)[:64],
        )
        .first()
    )

    now = _utcnow()
    if row and isinstance(row.value_json, dict):
        idx = row.value_json.get("variant_index")
        round_id = row.value_json.get("round")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = -1
        cur_round = int(experiment.get("round") or 1)
        if round_id == cur_round and 0 <= idx < n:
            return idx

    idx = _sha256_mod(f"{experiment_key}:{user_id}:{experiment.get('round')}", n)
    val = {
        "variant_index": idx,
        "round": int(experiment.get("round") or 1),
        "assigned_at": now.isoformat(),
        "exposure_logged": False,
    }
    if not row:
        row = UserAiMemory(
            user_id=int(user_id),
            memory_type=AB_MEMORY_TYPE,
            key=str(experiment_key)[:64],
            value_json=val,
            confidence_score=0.5,
            source="ab_engine",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.value_json = val
        row.updated_at = now
        row.source = "ab_engine"
    db.commit()
    return idx


def resolve_copy(
    db: Session,
    *,
    user_id: int,
    keys: list[str],
    record_exposure: bool = True,
) -> dict[str, Any]:
    """Return variant text per experiment key; optionally log first exposure per assignment."""
    state = _load_state(db)
    experiments = state.get("experiments") or {}
    out: dict[str, Any] = {}

    for raw_key in keys:
        key = str(raw_key or "").strip()
        if key not in EXPERIMENT_KEYS:
            continue
        exp = experiments.get(key) or {}
        variants = exp.get("variants") or []
        idx = _get_or_assign_variant_index(db, user_id, key, exp)
        v = _variant_by_index(exp, idx)
        vid = str(v.get("id") or f"v{idx}")
        text = str(v.get("text") or "").strip() or DEFAULT_BASELINES.get(key, "")

        out[key] = {"variant_id": vid, "variant_index": idx, "text": text}

        if record_exposure:
            mem = (
                db.query(UserAiMemory)
                .filter(
                    UserAiMemory.user_id == int(user_id),
                    UserAiMemory.memory_type == AB_MEMORY_TYPE,
                    UserAiMemory.key == key[:64],
                )
                .first()
            )
            already = False
            if mem and isinstance(mem.value_json, dict):
                already = bool(mem.value_json.get("exposure_logged"))
            if not already:
                try:
                    track_event(
                        db,
                        "ab_exposure",
                        user_id=int(user_id),
                        payload={"experiment_key": key, "variant_id": vid, "round": int(exp.get("round") or 1)},
                    )
                except Exception:
                    pass
                if mem and isinstance(mem.value_json, dict):
                    nv = dict(mem.value_json)
                    nv["exposure_logged"] = True
                    mem.value_json = nv
                    mem.updated_at = _utcnow()
                    db.commit()

    return {"copy": out, "updated_at": state.get("updated_at")}


# Aligns with seeded variants for `growth.trial.duration` (v0..v3).
TRIAL_DAYS_BY_VARIANT_INDEX: tuple[int, ...] = (5, 7, 3, 5)


def trial_days_for_user(db: Session, user_id: int) -> int:
    """Resolve Premium trial length from the user's assigned `growth.trial.duration` variant."""
    key = "growth.trial.duration"
    state = _load_state(db)
    experiments = state.get("experiments") or {}
    exp = experiments.get(key) or {}
    idx = _get_or_assign_variant_index(db, int(user_id), key, exp)
    if 0 <= idx < len(TRIAL_DAYS_BY_VARIANT_INDEX):
        return int(TRIAL_DAYS_BY_VARIANT_INDEX[idx])
    return 5


def record_metric(
    db: Session,
    *,
    user_id: int,
    experiment_key: str,
    variant_id: str,
    metric: str,
    extra: dict[str, Any] | None = None,
) -> None:
    key = str(experiment_key or "").strip()
    if key not in EXPERIMENT_KEYS:
        return
    m = str(metric or "").strip().lower()
    allowed = {"click", "message_sent", "reply", "premium"}
    if m not in allowed:
        return
    name = {
        "click": "ab_click",
        "message_sent": "ab_message_sent",
        "reply": "ab_reply",
        "premium": "ab_premium",
    }[m]
    payload = {"experiment_key": key, "variant_id": str(variant_id or "").strip(), **(extra or {})}
    try:
        state = _load_state(db)
        exp = (state.get("experiments") or {}).get(key) or {}
        payload["round"] = int(exp.get("round") or 1)
    except Exception:
        pass
    try:
        track_event(db, name, user_id=int(user_id), payload=payload)
    except Exception:
        pass


def _count_events(
    db: Session,
    *,
    since: datetime,
    name: str,
    experiment_key: str,
    variant_id: str,
) -> int:
    rows = (
        db.query(AnalyticsEvent)
        .filter(
            AnalyticsEvent.name == name,
            AnalyticsEvent.created_at >= since,
        )
        .all()
    )
    n = 0
    for r in rows:
        try:
            p = json.loads(r.payload_json or "{}")
        except Exception:
            continue
        if str(p.get("experiment_key") or "") != experiment_key:
            continue
        if str(p.get("variant_id") or "") != variant_id:
            continue
        n += 1
    return n


def _composite_score(impressions: int, clicks: int, sent: int, replies: int, prem: int) -> float:
    if impressions <= 0:
        return 0.0
    cr = clicks / impressions
    sr = sent / impressions
    rr = replies / impressions
    pr = prem / impressions
    return 0.15 * cr + 0.35 * sr + 0.35 * rr + 0.15 * pr


def evaluate_experiments(db: Session) -> dict[str, Any]:
    """Pick winners when enough data; champion + new challenger pool for next round."""
    state = _load_state(db)
    experiments = state.get("experiments") or {}
    now = _utcnow()
    summary: dict[str, Any] = {}

    for key, exp in list(experiments.items()):
        if key not in EXPERIMENT_KEYS or not isinstance(exp, dict):
            continue
        days = int(exp.get("evaluation_window_days") or 7)
        since = now - timedelta(days=days)
        variants = exp.get("variants") or []
        if not variants:
            continue
        min_imp = int(exp.get("min_impressions_per_variant") or 60)
        min_lift = float(exp.get("min_relative_lift_vs_median") or 0.06)

        stats: list[dict[str, Any]] = []
        for v in variants:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id") or "")
            imp = _count_events(db, since=since, name="ab_exposure", experiment_key=key, variant_id=vid)
            clicks = _count_events(db, since=since, name="ab_click", experiment_key=key, variant_id=vid)
            sent = _count_events(db, since=since, name="ab_message_sent", experiment_key=key, variant_id=vid)
            replies = _count_events(db, since=since, name="ab_reply", experiment_key=key, variant_id=vid)
            prem = _count_events(db, since=since, name="ab_premium", experiment_key=key, variant_id=vid)
            score = _composite_score(imp, clicks, sent, replies, prem)
            stats.append(
                {
                    "variant_id": vid,
                    "impressions": imp,
                    "click_rate": (clicks / imp) if imp else 0.0,
                    "message_rate": (sent / imp) if imp else 0.0,
                    "reply_rate": (replies / imp) if imp else 0.0,
                    "premium_rate": (prem / imp) if imp else 0.0,
                    "score": score,
                }
            )

        stats.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
        summary[key] = {"stats": stats, "promoted": False}

        if len(stats) < 2:
            continue
        if stats[0]["impressions"] < min_imp:
            continue
        best_score = float(stats[0].get("score") or 0.0)
        second_score = float(stats[1].get("score") or 0.0) if len(stats) > 1 else 0.0
        if best_score <= 0 and second_score <= 0:
            continue
        if second_score > 0 and best_score < second_score * (1.0 + min_lift):
            continue
        if second_score <= 0 and best_score < 0.04:
            continue

        winner_vid = str(stats[0]["variant_id"])
        winner_text = ""
        for v in variants:
            if isinstance(v, dict) and str(v.get("id")) == winner_vid:
                winner_text = str(v.get("text") or "").strip()
                break
        if not winner_text:
            winner_text = DEFAULT_BASELINES.get(key, "")

        exp["champion_id"] = winner_vid
        exp["round"] = int(exp.get("round") or 1) + 1
        exp["variants"] = [
            {"id": "v0", "text": winner_text, "source": "champion"},
            {"id": "v1", "text": winner_text, "source": "champion_dup"},
            {"id": "v2", "text": _mutate_placeholder(winner_text), "source": "mutate"},
            {"id": "v3", "text": _mutate_placeholder(winner_text, seed=1), "source": "mutate"},
        ]
        exp["last_promoted_at"] = now.isoformat()
        summary[key]["promoted"] = True
        summary[key]["winner_variant_id"] = winner_vid

        try:
            track_event(
                db,
                "ab_winner_promoted",
                user_id=None,
                payload={"experiment_key": key, "winner_variant_id": winner_vid, "round": exp["round"]},
            )
        except Exception:
            pass

    state["updated_at"] = now.isoformat()
    _save_state(db, state)
    return {"evaluated_at": now.isoformat(), "summary": summary}


def _mutate_placeholder(text: str, seed: int = 0) -> str:
    """Cheap local paraphrase until AI refresh runs."""
    t = (text or "").strip()
    if not t:
        return t
    suffixes = [" ✨", " →", " ·", "!"]
    return (t + suffixes[seed % len(suffixes)]).strip()


async def generate_variants_with_ai(*, experiment_key: str, base_message: str, locale: str = "en") -> list[str]:
    """
    AI: 'Write 3 short versions of this message for a dating app that increase engagement.'
    Returns 3 strings (caller merges with champion).
    """
    system = (
        "You write UI microcopy for a premium dating app.\n"
        "Rules:\n"
        "- Short (under 90 characters each).\n"
        "- Warm, human, confident — not cringe.\n"
        "- No quotes in output.\n"
        "Return STRICT JSON: {\"variants\": [\"...\", \"...\", \"...\"]}\n"
        "Exactly 3 items."
    )
    user = (
        "Write 3 short versions of this message for a dating app that increase engagement.\n\n"
        f"BASE_MESSAGE:\n{base_message}\n\n"
        f"LOCALE_HINT:{locale}\n"
    )

    if not getattr(settings, "ENABLE_AI_SUGGESTIONS", True):
        return []

    try:
        from app.services.ai.gemini_client import GeminiClient, GeminiError

        if not GeminiClient.enabled():
            return _fallback_ai_variants(base_message)

        client = GeminiClient()
        from pydantic import BaseModel, Field

        class VariantsOut(BaseModel):
            variants: list[str] = Field(default_factory=list)

        out = await client.generate_json(
            system_prompt=system,
            user_prompt=user,
            out_model=VariantsOut,
            temperature=0.85,
            max_output_tokens=220,
            timeout_s=12.0,
        )
        rows = list(getattr(out, "variants", None) or [])
        if not isinstance(rows, list):
            return _fallback_ai_variants(base_message)
        cleaned = [str(x).strip() for x in rows if str(x).strip()][:3]
        return cleaned if len(cleaned) == 3 else _fallback_ai_variants(base_message)
    except Exception as e:
        log_ai_fallback_triggered(
            endpoint="ab_engine/variants",
            locale=locale,
            reason=type(e).__name__,
            error_message=str(e),
            provider="gemini",
        )
        return _fallback_ai_variants(base_message)


def _fallback_ai_variants(base_message: str) -> list[str]:
    b = (base_message or "").strip() or "Continue"
    return [b, b + " ✨", (b + " — you got this.").strip()[:90]]


async def refresh_challengers_with_ai(db: Session, experiment_key: str, *, locale: str = "en") -> dict[str, Any]:
    """Regenerate challenger slots from champion using AI (await from async route)."""
    key = str(experiment_key or "").strip()
    if key not in EXPERIMENT_KEYS:
        return {"ok": False, "error": "unknown_experiment"}

    state = _load_state(db)
    exp = (state.get("experiments") or {}).get(key) or {}
    variants = list(exp.get("variants") or [])
    if not variants:
        return {"ok": False, "error": "no_variants"}

    champion = variants[0]
    if not isinstance(champion, dict):
        return {"ok": False, "error": "bad_champion"}
    champion_text = str(champion.get("text") or "").strip() or DEFAULT_BASELINES.get(key, "")

    new_three = await generate_variants_with_ai(experiment_key=key, base_message=champion_text, locale=locale)
    if len(new_three) < 3:
        new_three = _fallback_ai_variants(champion_text)

    exp["variants"] = [
        {"id": "v0", "text": champion_text, "source": "champion"},
        {"id": "v1", "text": new_three[0], "source": "ai"},
        {"id": "v2", "text": new_three[1], "source": "ai"},
        {"id": "v3", "text": new_three[2], "source": "ai"},
    ]
    exp["last_ai_refresh_at"] = _utcnow().isoformat()
    state.setdefault("experiments", {})[key] = exp
    state["updated_at"] = _utcnow().isoformat()
    _save_state(db, state)

    try:
        track_event(db, "ab_variants_refreshed", user_id=None, payload={"experiment_key": key, "source": "ai"})
    except Exception:
        pass

    return {"ok": True, "experiment_key": key, "variant_count": len(exp["variants"])}
