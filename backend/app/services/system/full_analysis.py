"""
Owner-facing full system analysis: aggregates existing admin diagnostics (no paid AI).
Partial failures become section warnings; response is sanitized for secrets and private content.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

_TypeFetch = tuple[Any | None, str | None]


def _safe_int(x: Any) -> int:
    try:
        return int(x or 0)
    except Exception:
        return 0


def _dedupe_str_list(seq: list[str], n: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in seq:
        k = str(item or "").strip()
        if not k or k.lower() in seen:
            continue
        seen.add(k.lower())
        out.append(k)
        if len(out) >= n:
            break
    return out


def _clamp_score(x: float) -> int:
    try:
        return int(max(0, min(100, round(float(x)))))
    except Exception:
        return 0


def _merge_status(*statuses: str) -> str:
    if any(str(s or "").lower() == "critical" for s in statuses):
        return "critical"
    if any(str(s or "").lower() == "warning" for s in statuses):
        return "warning"
    return "healthy"


def _status_points(st: str) -> float:
    s = str(st or "").lower()
    if s == "critical":
        return 45.0
    if s == "warning":
        return 72.0
    return 100.0


def _fetch(label: str, fn: Callable[[], Any]) -> _TypeFetch:
    try:
        return fn(), None
    except Exception as e:
        return None, f"{label} ({type(e).__name__})"


def _trim_system_doctor(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out = {k: v for k, v in raw.items() if k != "last_10_errors"}
    le = raw.get("last_10_errors")
    out["logged_error_events_recent"] = len(le) if isinstance(le, list) else 0
    return out


def _docker_hint() -> str:
    try:
        if Path("/.dockerenv").exists():
            return "Runtime: container detected (.dockerenv)."
    except Exception:
        pass
    return ""


def _avg_coverage_pct(cov: Any) -> int | None:
    if not isinstance(cov, dict):
        return None
    locs = cov.get("locales")
    if not isinstance(locs, list) or not locs:
        return None
    pcts: list[int] = []
    for row in locs:
        if isinstance(row, dict) and row.get("code") != "en":
            tk = _safe_int(row.get("total_keys"))
            if tk <= 0:
                continue
            pcts.append(_safe_int(row.get("coverage")))
    if not pcts:
        return None
    return int(round(sum(pcts) / len(pcts)))


def _avg_present_pct(cov: Any) -> int | None:
    """Average % of keys with a non-empty value (includes intentional English fallback)."""
    if not isinstance(cov, dict):
        return None
    locs = cov.get("locales")
    if not isinstance(locs, list) or not locs:
        return None
    pcts: list[int] = []
    for row in locs:
        if isinstance(row, dict) and row.get("code") != "en":
            tk = _safe_int(row.get("total_keys"))
            if tk <= 0:
                continue
            pcts.append(_safe_int(row.get("coverage_present_pct", row.get("coverage"))))
    if not pcts:
        return None
    return int(round(sum(pcts) / len(pcts)))


def _e2e_warning_details(e2e: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    if not isinstance(e2e, dict):
        return out

    def _push(row: dict[str, Any]) -> None:
        key = (row.get("flow_id"), row.get("step"), str(row.get("message") or "")[:120])
        if key in seen:
            return
        seen.add(key)
        out.append(row)

    for it in e2e.get("issues") or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("severity") or "").lower() not in {"warning", "critical"}:
            continue
        _push(
            {
                "flow_id": it.get("flow"),
                "flow_title": it.get("flow_title") or it.get("flow"),
                "step": it.get("step"),
                "message": it.get("message"),
                "suggested_fix": it.get("suggested_fix"),
            }
        )
    for f in e2e.get("flows") or []:
        if not isinstance(f, dict) or str(f.get("status") or "").lower() != "warning":
            continue
        fid = f.get("id")
        ftitle = f.get("title") or fid
        for it in f.get("issues") or []:
            if not isinstance(it, dict):
                continue
            _push(
                {
                    "flow_id": fid,
                    "flow_title": ftitle,
                    "step": it.get("step"),
                    "message": it.get("message"),
                    "suggested_fix": it.get("suggested_fix"),
                    "kind": it.get("kind"),
                }
            )
    return out[:30]


def _localization_locale_showcase(growth: Any, l10_cov: Any) -> list[dict[str, Any]]:
    """Top 5 locales: prioritize signups in window, then fill by coverage gap."""
    rows = [x for x in (l10_cov or {}).get("locales") or [] if isinstance(x, dict) and str(x.get("code") or "") != "en"]
    if not rows:
        return []
    by_code = {str(r.get("code") or ""): r for r in rows}
    acq = (growth or {}).get("acquisition") if isinstance(growth, dict) else {}
    signups = (acq or {}).get("signups_by_locale") if isinstance(acq, dict) else {}
    ranked_codes: list[str] = []
    if isinstance(signups, dict) and signups:
        for code, _n in sorted(signups.items(), key=lambda kv: -_safe_int(kv[1])):
            c = str(code or "").strip().lower()[:16]
            if c and c != "unknown" and c in by_code and c not in ranked_codes:
                ranked_codes.append(c)
            if len(ranked_codes) >= 5:
                break
    out: list[dict[str, Any]] = []
    for c in ranked_codes:
        out.append(by_code[c])
    if len(out) < 5:
        rest = sorted(
            (r for r in rows if str(r.get("code") or "") not in {str(x.get("code") or "") for x in out}),
            key=lambda r: (_safe_int(r.get("coverage")), str(r.get("code") or "")),
        )
        for r in rest:
            out.append(r)
            if len(out) >= 5:
                break
    return out[:5]


def build_full_system_analysis(admin_actor: Any, db: Any) -> dict[str, Any]:
    from app.api.v1.endpoints import admin as adm
    from app.services.localization.coverage import compute_localization_coverage
    from app.services.localization.runtime_agent import run_localization_agent_scan

    partial: list[str] = []

    cc, e = _fetch("command_center", lambda: adm.admin_command_center_home(admin_actor, db))
    if e:
        partial.append(e)

    sysd_raw, e = _fetch("system_doctor", lambda: adm.system_doctor(admin_actor, db))
    if e:
        partial.append(e)
    sysd = _trim_system_doctor(sysd_raw)

    alerts, e = _fetch("alerts", lambda: adm.admin_alerts_poll(admin_actor, db))
    if e:
        partial.append(e)

    stats_today, e1 = _fetch("stats_today", lambda: adm.admin_stats_overview("today", admin_actor, db))
    stats_7d, e2 = _fetch("stats_7d", lambda: adm.admin_stats_overview("7d", admin_actor, db))
    stats_30d, e3 = _fetch("stats_30d", lambda: adm.admin_stats_overview("30d", admin_actor, db))
    for err in (e1, e2, e3):
        if err:
            partial.append(err)

    growth, e = _fetch("growth", lambda: adm.admin_growth_overview("7d", admin_actor, db))
    if e:
        partial.append(e)

    premium, e = _fetch("premium", lambda: adm.admin_premium_overview(admin_actor, db))
    if e:
        partial.append(e)

    mq, e = _fetch("match_quality", lambda: adm.admin_match_quality_overview(admin_actor, db))
    if e:
        partial.append(e)

    cq, e = _fetch("conversation_quality", lambda: adm.admin_conversation_quality_overview("7d", admin_actor, db))
    if e:
        partial.append(e)

    founder, e = _fetch("founder", lambda: adm.admin_founder_daily(admin_actor, db))
    if e:
        partial.append(e)

    autopilot, e = _fetch("autopilot", lambda: adm.admin_autopilot_suggestions(admin_actor, db))
    if e:
        partial.append(e)

    pm, e = _fetch("product_manager", lambda: adm.admin_product_manager_daily_brief("7d", admin_actor, db))
    if e:
        partial.append(e)

    cto, e = _fetch("cto", lambda: adm.admin_cto_roadmap("7d", admin_actor, db))
    if e:
        partial.append(e)

    release, e = _fetch("release", lambda: adm.admin_release_readiness(admin_actor, db))
    if e:
        partial.append(e)

    l10_report, e = _fetch("localization_report", lambda: adm.localization_quality(admin_actor))
    if e:
        partial.append(e)

    l10_scan, e = _fetch("localization_agent", lambda: run_localization_agent_scan())
    if e:
        partial.append(e)

    l10_cov, e = _fetch("localization_coverage", lambda: compute_localization_coverage())
    if e:
        partial.append(e)

    menu_qa, e = _fetch("menu_qa", lambda: adm.admin_telegram_menu_qa_scan(admin_actor))
    if e:
        partial.append(e)

    e2e, e = _fetch("e2e_qa", lambda: adm.admin_e2e_qa_scan(admin_actor, db))
    if e:
        partial.append(e)

    backups, e = _fetch("backups", lambda: adm.admin_backups_list(admin_actor, db))
    if e:
        partial.append(e)

    audit, e = _fetch("audit", lambda: adm.admin_audit_log(1, 0, None, admin_actor, db))
    if e:
        partial.append(e)

    aiq, e = _fetch("ai_quality", lambda: adm.ai_quality(admin_actor, db))
    if e:
        partial.append(e)

    sections: list[dict[str, Any]] = []
    all_issues: list[str] = []
    all_recs: list[str] = []
    all_actions: list[str] = []

    # --- 1. System / Runtime ---
    cc_status = str((cc or {}).get("status") or "warning").lower() if isinstance(cc, dict) else "warning"
    if not cc:
        cc_status = "warning"
    api_ok = str(sysd.get("api_status") or "").lower() in {"", "ok"}
    api_err = _safe_int(sysd.get("api_errors_24h"))
    up = _safe_int(sysd.get("uptime_seconds"))
    env = str(sysd.get("environment") or "")
    dh = _docker_hint()
    crit_alerts_n = len((cc or {}).get("critical_alerts") or []) if isinstance(cc, dict) else 0
    poll_crit = 0
    if isinstance(alerts, dict):
        for row in (alerts.get("alerts") or []):
            if isinstance(row, dict) and str(row.get("level") or "").lower() == "critical":
                poll_crit += 1

    def _partial_subsystems(pl: list[str]) -> tuple[bool, list[str]]:
        labels: list[str] = []
        for p in pl:
            s = str(p or "").strip()
            if not s:
                continue
            labels.append(s.split(" (", 1)[0].strip() if " (" in s else s)
        core = {"command_center", "system_doctor"}
        core_hit = any(lbl in core for lbl in labels)
        return core_hit, labels

    partial_core, _partial_labels = _partial_subsystems(partial)

    s1_issues: list[str] = []
    s1_recs: list[str] = []
    if not api_ok:
        s1_issues.append("API status is not reported as healthy.")
    if api_err > 20:
        s1_issues.append(f"Elevated API errors in the last 24h ({api_err}).")
    elif api_err > 0:
        s1_issues.append(f"Some API errors in the last 24h ({api_err}).")
    if crit_alerts_n or poll_crit:
        s1_issues.append(f"Critical signals: {crit_alerts_n + poll_crit} aggregate alert(s) need attention.")
    if partial and partial_core:
        s1_issues.append("Core diagnostics could not be loaded; see section notes.")
    s1_status = "critical" if (not api_ok or api_err > 20 or cc_status == "critical") else ("warning" if (api_err > 0 or cc_status == "warning" or s1_issues) else "healthy")
    headline = str((cc or {}).get("headline") or "Command Center snapshot unavailable.") if isinstance(cc, dict) else "Command Center snapshot unavailable."
    s1_summary = headline
    if isinstance(cc, dict) and (cc or {}).get("today"):
        t0 = (cc or {}).get("today") if isinstance((cc or {}).get("today"), dict) else {}
        s1_summary = (
            f"{headline} Today: {_safe_int(t0.get('active_users'))} active users, "
            f"{_safe_int(t0.get('matches'))} matches, {_safe_int(t0.get('messages'))} messages."
        )
    s1_details = [
        f"Uptime ~{up // 3600}h, environment: {env or 'unknown'}.",
        f"Logged error events (recent buffer): {sysd.get('logged_error_events_recent', 0)}.",
    ]
    if dh:
        s1_details.append(dh)
    if poll_crit:
        s1_details.append(f"Active alert poll: {poll_crit} critical, {len((alerts or {}).get('alerts') or []) if isinstance(alerts, dict) else 0} total.")
    if api_err > 0:
        s1_recs.append("Open System Doctor and review recent API error trends.")
    if poll_crit:
        s1_recs.append("Open Alerts and mute only after triage.")
    if api_err > 0:
        s1_details.append("Action: System Doctor → last errors / API pressure (no private content).")
    if crit_alerts_n or poll_crit:
        s1_details.append("Action: Command Center alerts → triage critical items before feature work.")
    sections.append(
        {
            "id": "system",
            "title": "System / Runtime",
            "status": s1_status,
            "summary": s1_summary[:500],
            "details": s1_details,
            "issues": s1_issues,
            "recommended_actions": s1_recs,
        }
    )
    all_issues.extend(s1_issues)
    all_recs.extend(s1_recs)

    # --- 2. Database / Redis / Alembic ---
    db_s = str(sysd.get("database_status") or "unknown").lower()
    redis_s = str(sysd.get("redis_status") or "unknown").lower()
    alembic_rev = sysd.get("alembic_revision")
    s2_issues: list[str] = []
    if db_s not in {"", "ok"}:
        s2_issues.append(f"Database status: {db_s}.")
    if redis_s == "error":
        s2_issues.append("Redis returned an error state.")
    elif redis_s == "disabled":
        s2_issues.append("Redis is disabled (caching/queues may be limited).")
    if not alembic_rev:
        s2_issues.append("Alembic revision not reported (migrations may need attention).")
    s2_status = "critical" if db_s not in {"", "ok"} else ("warning" if s2_issues else "healthy")
    s2_summary = (
        f"Database: {db_s or 'unknown'}, Redis: {redis_s}, Alembic: {alembic_rev or 'not available'}. "
        f"Rows (approx): users {sysd.get('users_count', '?')}, matches {sysd.get('matches_count', '?')}."
    )
    s2_details = [
        f"Profiles: {_safe_int(sysd.get('profiles_count'))}, messages (all-time count): {_safe_int(sysd.get('messages_count'))}.",
    ]
    s2_recs: list[str] = []
    if db_s not in {"", "ok"}:
        s2_recs.append("Check database connectivity, disk, and recent migrations.")
    if not alembic_rev:
        s2_recs.append("Verify alembic_version and run migrations if needed (non-production tooling).")
    sections.append(
        {
            "id": "database",
            "title": "Database / Redis / Alembic",
            "status": s2_status,
            "summary": s2_summary,
            "details": s2_details,
            "issues": s2_issues,
            "recommended_actions": s2_recs,
        }
    )
    all_issues.extend(s2_issues)
    all_recs.extend(s2_recs)

    # --- 3. Telegram Admin / Menu QA ---
    mq_summ = (menu_qa or {}).get("summary") if isinstance(menu_qa, dict) else {}
    mq_status = str((menu_qa or {}).get("status") or "unknown").lower() if isinstance(menu_qa, dict) else "unknown"
    miss_h = _safe_int((mq_summ or {}).get("missing_handlers"))
    miss_tr = _safe_int((mq_summ or {}).get("missing_translations"))
    unsafe_n = _safe_int((mq_summ or {}).get("unsafe_actions"))
    rend_err = _safe_int((mq_summ or {}).get("render_errors"))
    unsafe_detail = (mq_summ or {}).get("unsafe_callbacks") if isinstance(mq_summ, dict) else []
    unsafe_list = unsafe_detail if isinstance(unsafe_detail, list) else []
    s3_issues: list[str] = []
    if miss_h:
        s3_issues.append(f"Menu QA: {miss_h} missing handler(s).")
    if miss_tr:
        s3_issues.append(f"Menu QA: {miss_tr} missing translation(s).")
    if unsafe_n:
        s3_issues.append(
            f"Menu QA: {unsafe_n} heuristic unsafe flag(s) (scan looks for matching x:* confirm steps; not proof of missing confirm at runtime)."
        )
    if rend_err:
        s3_issues.append(f"Menu QA: {rend_err} render error(s) while scanning menus.")
    if mq_status == "warning" and (miss_h or rend_err):
        s3_issues.append("Telegram menu QA: routing or render warnings present.")
    elif mq_status == "warning" and not (miss_h or rend_err):
        s3_issues.append("Telegram menu QA: review issues (often heuristics or i18n parity).")
    # Critical only for real routing/render gaps; unsafe_* is warning-only noise.
    s3_hard = bool(miss_h or rend_err)
    s3_status = "critical" if s3_hard else ("warning" if (miss_tr or unsafe_n or mq_status == "warning" or s3_issues) else "healthy")
    if not menu_qa:
        s3_status = "warning"
        s3_issues.append("Telegram menu QA data unavailable.")
    s3_summary = (
        f"Admin menu scan: status {mq_status}. Handlers missing: {miss_h}, "
        f"missing translations: {miss_tr}, unsafe heuristics: {unsafe_n}, render errors: {rend_err}."
    )
    s3_recs: list[str] = []
    if miss_h:
        s3_recs.append("Menu QA → add route_callback branches or fix callback_data for each missing handler.")
    if rend_err:
        s3_recs.append("Fix render_* functions that throw during scan (empty-state safe).")
    if unsafe_n:
        s3_recs.append("For each unsafe heuristic: open scan details; verify c:* → x:* confirm exists, then dismiss or fix.")
    s3_details = [
        f"Menus checked: {_safe_int((mq_summ or {}).get('menus_checked'))}, "
        f"buttons: {_safe_int((mq_summ or {}).get('buttons_checked'))}, callbacks: {_safe_int((mq_summ or {}).get('callbacks_checked'))}.",
        "Unsafe flags require a matching confirm keyboard token (e.g. x:clear_cache_yes) collected from the same bot module.",
    ]
    for row in unsafe_list[:12]:
        if not isinstance(row, dict):
            continue
        cb = str(row.get("callback") or "")
        if not cb:
            continue
        risk = str(row.get("risk") or "").strip()
        exp = str(row.get("expected_confirm") or "").strip()
        src = row.get("source_menus") if isinstance(row.get("source_menus"), list) else []
        src_s = ", ".join(str(x) for x in src[:4]) if src else "routing / unknown menu"
        bit = f"Unsafe: <code>{cb}</code> — {risk or 'elevated action'}"
        if exp:
            bit += f" — expect confirm like <code>{exp}</code>"
        bit += f" — sources: {src_s}"
        s3_details.append(bit)
    sections.append(
        {
            "id": "telegram_menu",
            "title": "Telegram Admin Bot / Menu QA",
            "status": s3_status,
            "summary": s3_summary,
            "details": s3_details,
            "issues": s3_issues,
            "recommended_actions": s3_recs,
        }
    )
    all_issues.extend(s3_issues)
    all_recs.extend(s3_recs)

    # --- 4. AI / Gemini ---
    gem = str(sysd.get("gemini_status") or "").lower()
    gem_err = bool(sysd.get("last_gemini_error"))
    fb = _safe_int(sysd.get("ai_fallback_count_24h"))
    aiq_summ = (aiq or {}).get("summary") if isinstance(aiq, dict) else {}
    s4_issues: list[str] = []
    if gem in {"error", "disabled", "not_active"}:
        s4_issues.append(f"Gemini/provider status: {gem}.")
    if gem_err:
        s4_issues.append("A recent Gemini error was recorded in diagnostics.")
    if fb > 10:
        s4_issues.append(f"AI fallback volume is elevated ({fb} / 24h).")
    elif fb > 0:
        s4_issues.append(f"Some AI fallbacks in the last 24h ({fb}).")
    s4_status = "critical" if gem == "error" else ("warning" if (s4_issues or gem_err) else "healthy")
    if not aiq:
        s4_status = _merge_status(s4_status, "warning")
        s4_issues.append("AI quality aggregate unavailable.")
    sel = float((aiq_summ or {}).get("selection_rate") or 0.0) if isinstance(aiq_summ, dict) else 0.0
    edit_r = float((aiq_summ or {}).get("edited_rate") or 0.0) if isinstance(aiq_summ, dict) else 0.0
    s4_summary = (
        f"Gemini: {gem or 'unknown'}, model: {sysd.get('gemini_model') or 'n/a'}. "
        f"Quality (7d-style aggregates where available): selection ~{sel:.0%}, edits ~{edit_r:.0%}."
    )
    s4_recs = ["If fallbacks rise: verify provider quota, keys, and model configuration (without exposing secrets)."]
    sections.append(
        {
            "id": "ai",
            "title": "AI / Gemini",
            "status": s4_status,
            "summary": s4_summary,
            "details": [f"Fallback events (24h): {fb}."],
            "issues": s4_issues,
            "recommended_actions": s4_recs if s4_issues else [],
        }
    )
    all_issues.extend(s4_issues)

    # --- 5. Users / Growth ---
    u_t = (stats_today or {}).get("users") if isinstance(stats_today, dict) else {}
    u7 = (stats_7d or {}).get("users") if isinstance(stats_7d, dict) else {}
    u30 = (stats_30d or {}).get("users") if isinstance(stats_30d, dict) else {}
    acq = (growth or {}).get("acquisition") if isinstance(growth, dict) else {}
    s5_issues: list[str] = []
    if not stats_7d:
        s5_issues.append("Extended user statistics partially unavailable.")
    s5_status = "warning" if s5_issues else "healthy"
    s5_summary = (
        f"Users — today new {_safe_int((u_t or {}).get('new'))}, active {_safe_int((u_t or {}).get('active'))}; "
        f"7d new {_safe_int((u7 or {}).get('new'))}; 30d new {_safe_int((u30 or {}).get('new'))}. "
        f"Growth (7d) new users: {_safe_int((acq or {}).get('new_users'))}."
    )
    growth_recs = (growth or {}).get("recommendations") if isinstance(growth, dict) else []
    grec_texts: list[str] = []
    if isinstance(growth_recs, list):
        for row in growth_recs[:3]:
            if isinstance(row, dict) and row.get("title"):
                grec_texts.append(str(row.get("title")))
            elif isinstance(row, str):
                grec_texts.append(row)
    s5_recs = grec_texts[:3]
    s5_details: list[str] = []
    onb = (growth or {}).get("onboarding") if isinstance(growth, dict) else {}
    if isinstance(onb, dict):
        b = onb.get("bottlenecks") if isinstance(onb.get("bottlenecks"), dict) else {}
        rt = onb.get("rates") if isinstance(onb.get("rates"), dict) else {}
        s5_details.append(
            "Onboarding bottlenecks (window cohort): "
            f"missing/empty photos ~{_safe_int(b.get('missing_photo_count'))}, thin bios ~{_safe_int(b.get('thin_bio_count'))}, "
            f"verification pending ~{_safe_int(b.get('verification_pending_count'))}, "
            f"verified none after complete ~{_safe_int(b.get('verification_none_after_complete_count'))}."
        )
        s5_details.append(
            f"Onboarding rates: photo added ~{float(rt.get('photo_added_rate') or 0.0):.0%}, thin bio ~{float(rt.get('thin_bio_rate') or 0.0):.0%}."
        )
    sections.append(
        {
            "id": "users_growth",
            "title": "Users / Growth",
            "status": s5_status,
            "summary": s5_summary,
            "details": s5_details,
            "issues": s5_issues,
            "recommended_actions": s5_recs,
        }
    )
    all_issues.extend(s5_issues)
    all_recs.extend(s5_recs)

    # --- 6. Matches / Chats ---
    s6_issues: list[str] = []
    dead = _safe_int((mq or {}).get("dead_chats_count"))
    weak = _safe_int((mq or {}).get("weak_matches_count"))
    if dead:
        s6_issues.append(f"Dead chats (no messages 3d+): {dead}.")
    if weak:
        s6_issues.append(f"Weak / low-compatibility matches (approx): {weak}.")
    cq_summ = (cq or {}).get("summary") if isinstance(cq, dict) else {}
    pr = float((cq_summ or {}).get("partner_reply_rate") or 0.0) if isinstance(cq_summ, dict) else 0.0
    if not mq or not cq:
        s6_issues.append("Match or conversation quality overview incomplete.")
    s6_status = "warning" if (dead or weak or s6_issues) else "healthy"
    s6_summary = (
        f"Matches: reply rate ~{float((mq or {}).get('reply_rate') or 0.0):.0%}, "
        f"avg compatibility ~{float((mq or {}).get('average_compatibility_score') or 0.0):.1f}. "
        f"Conversation partner reply ~{pr:.0%} (7d window)."
    )
    s6_recs: list[str] = []
    if dead:
        s6_recs.append("Revive dead chats: nudge matches with no messages 3+ days (push, email, or in-app reopen).")
    cq_recs = (cq or {}).get("recommendations") if isinstance(cq, dict) else []
    if isinstance(cq_recs, list):
        for row in cq_recs:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            act = str(row.get("action") or "").strip()
            if title and act:
                s6_recs.append(f"{title}: {act[:220]}")
            elif title:
                s6_recs.append(title)
    sections.append(
        {
            "id": "matches_chats",
            "title": "Matches / Chats",
            "status": s6_status,
            "summary": s6_summary,
            "details": [],
            "issues": s6_issues,
            "recommended_actions": _dedupe_str_list(s6_recs, 6),
        }
    )
    all_issues.extend(s6_issues)
    all_recs.extend(s6_recs)

    # --- 7. Premium ---
    s7_issues: list[str] = []
    conv_r = float((premium or {}).get("conversion_rate") or 0.0) if isinstance(premium, dict) else 0.0
    exp3 = _safe_int((premium or {}).get("expiring_trials_3d")) if isinstance(premium, dict) else 0
    if exp3 > 10:
        s7_issues.append(f"Many trials expiring soon ({exp3} in ~3d).")
    elif exp3 > 0:
        s7_issues.append(f"Some trials expiring soon ({exp3}).")
    s7_status = "warning" if s7_issues else "healthy"
    if not premium:
        s7_status = "warning"
        s7_issues.append("Premium overview unavailable.")
    s7_summary = (
        f"Premium users: {_safe_int((premium or {}).get('premium_users'))}, trials: {_safe_int((premium or {}).get('trial_users'))}, "
        f"conversion ~{conv_r:.1%}."
    )
    s7_recs = ["Review paywall surfaces if conversion is below target."] if conv_r < 0.03 and premium else []
    sections.append(
        {
            "id": "premium",
            "title": "Premium / Monetization",
            "status": s7_status,
            "summary": s7_summary,
            "details": [],
            "issues": s7_issues,
            "recommended_actions": s7_recs,
        }
    )
    all_issues.extend(s7_issues)

    # --- 8. Safety ---
    saf_t = (stats_today or {}).get("safety") if isinstance(stats_today, dict) else {}
    open_rep = _safe_int((saf_t or {}).get("open_reports"))
    new_rep = _safe_int((saf_t or {}).get("new_reports"))
    s8_issues: list[str] = []
    if open_rep > 20:
        s8_issues.append(f"Open reports are very high ({open_rep}).")
        s8_status = "critical"
    elif open_rep > 5:
        s8_issues.append(f"Open reports elevated ({open_rep}).")
        s8_status = "warning"
    elif open_rep > 0:
        s8_issues.append(f"Open reports: {open_rep}.")
        s8_status = "warning"
    else:
        s8_status = "healthy"
    s8_summary = f"Safety: {open_rep} open reports, {new_rep} new (today window)."
    s8_recs = ["Triage open reports regularly."] if open_rep else []
    s8_details: list[str] = []
    if open_rep:
        s8_details.append("Action: Safety → open reports queue; resolve or escalate without exposing private messages in admin notes.")
    sections.append(
        {
            "id": "safety",
            "title": "Safety / Reports",
            "status": s8_status,
            "summary": s8_summary,
            "details": s8_details,
            "issues": s8_issues,
            "recommended_actions": s8_recs,
        }
    )
    all_issues.extend(s8_issues)

    # --- 9. Localization ---
    l10_issues_n = adm._localization_issue_count(l10_report if isinstance(l10_report, dict) else {})
    scan_summ = (l10_scan or {}).get("summary") if isinstance(l10_scan, dict) else {}
    avg_cov = _avg_coverage_pct(l10_cov)
    avg_present = _avg_present_pct(l10_cov)
    cov_summ = l10_cov.get("summary") if isinstance(l10_cov, dict) else {}
    miss_tot = _safe_int((cov_summ or {}).get("missing_keys_total")) if isinstance(cov_summ, dict) else 0
    raw_tot = _safe_int((cov_summ or {}).get("raw_value_leaks_total")) if isinstance(cov_summ, dict) else 0
    fb_tot = _safe_int((cov_summ or {}).get("en_fallback_keys_total")) if isinstance(cov_summ, dict) else 0
    acq_g = (growth or {}).get("acquisition") if isinstance(growth, dict) else {}
    low_traffic_l10 = _safe_int((acq_g or {}).get("new_users")) < 5
    loc_showcase = _localization_locale_showcase(growth, l10_cov)
    s9_issues: list[str] = []
    if l10_issues_n > 50:
        s9_issues.append(f"Localization report shows many issues (~{l10_issues_n}).")
    elif l10_issues_n > 20:
        s9_issues.append(f"Localization report issues: ~{l10_issues_n}.")
    if avg_cov is not None and avg_cov < 70 and not low_traffic_l10:
        if miss_tot > 0 or raw_tot > 0:
            s9_issues.append(
                f"Locale catalog needs attention: missing_keys={miss_tot}, raw_key_like_values={raw_tot} "
                f"(unique_translation ~{avg_cov}%, present ~{avg_present if avg_present is not None else '?'}%)."
            )
        # Low unique % with missing=0 is usually intentional English fallback — not a regression signal.
    elif avg_cov is not None and avg_cov < 70 and low_traffic_l10:
        pass  # informational only; see details (not enough signups to treat as regression)
    s9_status = "critical" if l10_issues_n > 50 else ("warning" if (l10_issues_n > 20 or s9_issues) else "healthy")
    if not l10_report and not l10_scan:
        s9_status = "warning"
        s9_issues.append("Localization diagnostics partially unavailable.")
    s9_summary = (
        f"Localization agent: missing keys {_safe_int((scan_summ or {}).get('missing_keys'))}, "
        f"raw-key-like strings {_safe_int((scan_summ or {}).get('raw_keys_visible'))}, "
        f"mixed-language {_safe_int((scan_summ or {}).get('mixed_language_strings'))}. "
        f"Static report issue estimate: {l10_issues_n}. "
        f"JSON catalog: missing={miss_tot}, raw={raw_tot}, EN_fallback={fb_tot}; "
        f"avg unique ~{avg_cov if avg_cov is not None else 'n/a'}%, avg present ~{avg_present if avg_present is not None else 'n/a'}%."
    )
    s9_recs = ["Fix missing locale keys and high-confidence hardcoded UI strings."]
    s9_details: list[str] = [
        "Coverage merges locales/*.json with frontend/scripts/core-ui-translations.json per locale (patch wins).",
    ]
    if low_traffic_l10 and avg_cov is not None and avg_cov < 70:
        s9_details.append(
            "Average non-EN coverage looks low, but new-user volume in the growth window is small — classify as not enough data before prioritizing translation sprints."
        )
    if isinstance(cov_summ, dict):
        s9_details.append(
            f"Catalog totals (non-EN): missing={miss_tot}, raw_like={raw_tot}, EN_fallback_keys={fb_tot}, "
            f"avg_unique~{avg_cov if avg_cov is not None else 'n/a'}%, avg_present~{avg_present if avg_present is not None else 'n/a'}%."
        )
    for row in loc_showcase:
        code = str(row.get("code") or "")
        covp = _safe_int(row.get("coverage"))
        presp = _safe_int(row.get("coverage_present_pct", row.get("coverage")))
        tk = _safe_int(row.get("translated_keys"))
        tot = _safe_int(row.get("total_keys"))
        core_n = _safe_int(row.get("core_overlay_keys"))
        top_u = row.get("top_untranslated_keys") if isinstance(row.get("top_untranslated_keys"), list) else []
        keys_preview = ", ".join(
            str((u or {}).get("key") or "") for u in top_u[:5] if isinstance(u, dict) and (u or {}).get("key")
        )
        line = (
            f"{code.upper()}: unique {covp}% · present {presp}% ({tk}/{tot} keys differ from EN; "
            f"core-ui overlay keys: {core_n})."
        )
        if keys_preview:
            line += f" Sample gaps: {keys_preview}."
        s9_details.append(line)
    if isinstance(l10_cov, dict):
        locrows = [x for x in (l10_cov.get("locales") or []) if isinstance(x, dict) and str(x.get("code") or "") != "en"]
        locrows.sort(key=lambda r: str(r.get("code") or ""))
        for row in locrows[:12]:
            code = str(row.get("code") or "")
            if any(str(x.get("code") or "") == code for x in loc_showcase):
                continue
            covp = _safe_int(row.get("coverage"))
            presp = _safe_int(row.get("coverage_present_pct", row.get("coverage")))
            tk = _safe_int(row.get("translated_keys"))
            tot = _safe_int(row.get("total_keys"))
            core_n = _safe_int(row.get("core_overlay_keys"))
            s9_details.append(
                f"{code.upper()}: unique {covp}% · present {presp}% ({tk}/{tot} keys differ from EN; core-ui patch keys: {core_n})."
            )
    sections.append(
        {
            "id": "localization",
            "title": "Localization / Languages",
            "status": s9_status,
            "summary": s9_summary,
            "details": s9_details,
            "issues": s9_issues,
            "recommended_actions": s9_recs if s9_issues else [],
        }
    )
    all_issues.extend(s9_issues)

    # --- 10. Backups / Audit / Release ---
    blist = backups if isinstance(backups, list) else []
    bcount = len(blist)
    latest = str((blist[0] or {}).get("created_at") or "") if blist and isinstance(blist[0], dict) else ""
    backup_recent_ok = False
    backup_recent_msg = ""
    try:
        backup_recent_ok, backup_recent_msg = adm._release_backup_recent(24)
    except Exception:
        backup_recent_ok, backup_recent_msg = False, "Backup recency check unavailable."
    atotal = _safe_int((audit or {}).get("total")) if isinstance(audit, dict) else 0
    rel_score = _safe_int((release or {}).get("score")) if isinstance(release, dict) else 0
    rel_ready = bool((release or {}).get("ready")) if isinstance(release, dict) else False
    blockers = (release or {}).get("blockers") if isinstance(release, dict) else []
    bn = len(blockers) if isinstance(blockers, list) else 0
    s10_issues: list[str] = []
    if not backup_recent_ok:
        s10_issues.append(str(backup_recent_msg or "No database backup within the last 24h (recommended)."))
    if bn:
        s10_issues.append(f"Release readiness: {bn} blocker(s).")
    elif isinstance(release, dict) and not rel_ready:
        s10_issues.append("Release readiness: not marked ready.")
    if bn:
        s10_status = "critical"
    elif not s10_issues:
        s10_status = "healthy"
    else:
        s10_status = "warning"
    s10_summary = (
        f"Backups on disk: {bcount} (latest {latest or 'n/a'}; last 24h: {'yes' if backup_recent_ok else 'no'}). "
        f"Audit events logged: {atotal}. Release score {rel_score}/100, ready={rel_ready}."
    )
    rel_actions = (release or {}).get("recommended_actions") if isinstance(release, dict) else []
    s10_recs: list[str] = []
    if isinstance(rel_actions, list):
        for x in rel_actions[:4]:
            if isinstance(x, str) and x.strip():
                s10_recs.append(x.strip())
    if not backup_recent_ok:
        s10_recs.append("Create a backup before meaningful schema or data changes (Telegram: Backup Center or quick action).")
    s10_details: list[str] = [
        "Action: Release Manager → Readiness for weighted score, backups, Menu QA, tests, and locale coverage.",
    ]
    if not backup_recent_ok:
        s10_details.append("Action: use “Create backup now” below or Backup Center → Create backup (confirm step required).")
    if bn:
        s10_details.append("Action: clear each release blocker in order (DB/API/alerts/tests).")
    sections.append(
        {
            "id": "backups_audit_release",
            "title": "Backups / Audit / Release",
            "status": s10_status,
            "summary": s10_summary,
            "details": s10_details,
            "issues": s10_issues,
            "recommended_actions": s10_recs,
        }
    )
    all_issues.extend(s10_issues)
    all_recs.extend(s10_recs)

    # --- 11. Autopilot / Founder / CTO / E2E ---
    sug = (autopilot or {}).get("suggestions") if isinstance(autopilot, dict) else []
    nsug = len(sug) if isinstance(sug, list) else 0
    ns = (founder or {}).get("north_star") if isinstance(founder, dict) else {}
    focus = str((founder or {}).get("focus") or "") if isinstance(founder, dict) else ""
    plan = (founder or {}).get("today_plan") if isinstance(founder, dict) else []
    plan_titles: list[str] = []
    if isinstance(plan, list):
        for row in plan[:3]:
            if isinstance(row, dict) and row.get("title"):
                plan_titles.append(str(row.get("title")))
    th = _safe_int((cto or {}).get("technical_health_score"))
    hs = _safe_int((pm or {}).get("health_score"))
    flows_e2e = (e2e or {}).get("flows") if isinstance(e2e, dict) else []
    failed = sum(1 for f in flows_e2e if isinstance(f, dict) and str(f.get("status") or "") == "fail")
    warn_e2e = sum(1 for f in flows_e2e if isinstance(f, dict) and str(f.get("status") or "") == "warning")
    e2e_summ = (e2e or {}).get("summary") if isinstance(e2e, dict) else {}
    e2e_no_data = _safe_int((e2e_summ or {}).get("no_data"))
    e2e_skipped = _safe_int((e2e_summ or {}).get("skipped"))
    e2e_warn_rows = _e2e_warning_details(e2e)
    s11_issues: list[str] = []
    if th and th < 40:
        s11_issues.append(f"Technical health score is critical ({th}).")
    elif th and th < 70:
        s11_issues.append(f"Technical health could be stronger ({th}).")
    if failed:
        s11_issues.append(f"E2E QA: {failed} failed flow(s).")
    if warn_e2e:
        s11_issues.append(f"E2E QA: {warn_e2e} flow(s) with warnings (details below and in e2e_warning_details).")
    if not founder:
        s11_issues.append("Founder daily brief unavailable.")
    # Only failed E2E flows are treated as hard-stop here; CTO health stays warning-level guidance.
    s11_status = "critical" if failed else ("warning" if s11_issues else "healthy")
    s11_summary = (
        f"Founder focus: {focus or 'n/a'}. North-star metric: {str((ns or {}).get('metric') or '')} = {_safe_int((ns or {}).get('value'))}. "
        f"Autopilot suggestions: {nsug}. PM health {hs}, CTO technical health {th}. "
        f"E2E: failed {failed}, warnings {warn_e2e}, not_enough_data {e2e_no_data}, skipped {e2e_skipped}."
    )
    s11_details: list[str] = []
    if plan_titles:
        s11_details.append("Top plan themes: " + "; ".join(plan_titles))
    for row in e2e_warn_rows[:15]:
        if not isinstance(row, dict):
            continue
        ft = row.get("flow_title") or row.get("flow_id") or "flow"
        step = row.get("step") or "?"
        msg = str(row.get("message") or "")[:260]
        fix = str(row.get("suggested_fix") or "").strip()[:220]
        line = f"E2E — {ft} · step {step}: {msg}"
        if fix:
            line += f"\nSuggested fix: {fix}"
        s11_details.append(line)
    s11_recs: list[str] = []
    if nsug:
        s11_recs.append("Review Autopilot suggestions before running any destructive action.")
    if isinstance(sug, list):
        for row in sug[:2]:
            if isinstance(row, dict) and row.get("title"):
                s11_recs.append(str(row.get("title")))
    sections.append(
        {
            "id": "strategy_engineering",
            "title": "Autopilot / Founder / CTO recommendations",
            "status": s11_status,
            "summary": s11_summary,
            "details": s11_details,
            "issues": s11_issues,
            "recommended_actions": s11_recs,
        }
    )
    all_issues.extend(s11_issues)
    all_recs.extend(s11_recs)

    # Top lists (dedupe, cap)
    def _dedupe(seq: list[str], n: int) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in seq:
            k = str(item or "").strip()
            if not k or k.lower() in seen:
                continue
            seen.add(k.lower())
            out.append(k)
            if len(out) >= n:
                break
        return out

    top_issues = _dedupe(all_issues, 5)
    top_recommendations = _dedupe(all_recs, 5)

    tr_top = (cc or {}).get("top_recommendation") if isinstance(cc, dict) else {}
    if isinstance(tr_top, dict) and tr_top.get("title"):
        all_actions.append(str(tr_top.get("action") or tr_top.get("title")))
    if isinstance(rel_actions, list):
        for x in rel_actions:
            if isinstance(x, str) and x.strip():
                all_actions.append(x.strip())
    if isinstance(growth_recs, list):
        for row in growth_recs:
            if isinstance(row, dict) and row.get("action"):
                all_actions.append(str(row.get("action")))
            elif isinstance(row, str):
                all_actions.append(row)
    for row in plan_titles:
        all_actions.append(f"Founder plan: {row}")
    next_best_actions = _dedupe(all_actions, 5)

    sec_points = [_status_points(str(s.get("status"))) for s in sections]
    score = _clamp_score(sum(sec_points) / max(1, len(sec_points)))

    if any(str(s.get("status") or "") == "critical" for s in sections):
        glob = "critical"
    elif partial or any(str(s.get("status") or "") == "warning" for s in sections):
        glob = "warning"
    else:
        glob = "healthy"

    owner_summary = headline if isinstance(cc, dict) else "Aggregate diagnostics summarized for the owner."
    owner_summary += f" Overall score {score}/100."
    if isinstance(release, dict) and blockers:
        owner_summary += f" Release blocked on {bn} item(s)."
    elif isinstance(release, dict) and rel_ready:
        owner_summary += " Release checklist looks clear of blockers."
    if partial and partial_core:
        owner_summary += " Core feeds were skipped; open individual sections for full detail."
    elif partial:
        owner_summary += " Optional feeds were skipped; open individual sections for full detail."

    quick_actions: list[dict[str, Any]] = [
        {
            "id": "create_backup",
            "title": "Create backup now",
            "callback_data": "c:backup_create",
        },
        {
            "id": "recompute_matches",
            "title": "Recompute match compatibility",
            "callback_data": "m:match_quality_recompute",
        },
    ]

    out: dict[str, Any] = {
        "status": glob,
        "score": score,
        "generated_at": datetime.now(UTC).isoformat(),
        "sections": sections,
        "top_issues": top_issues,
        "top_recommendations": top_recommendations,
        "next_best_actions": next_best_actions,
        "owner_summary": owner_summary[:900],
        "quick_actions": quick_actions,
        "e2e_warning_details": e2e_warn_rows,
        "localization_top_locales": loc_showcase,
    }
    return adm._sanitize_autopilot_result(out)
