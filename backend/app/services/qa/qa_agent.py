from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any, Literal, TypedDict
import subprocess

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.localization.report import load_localization_report
from app.services.e2e_qa import run_e2e_qa_scan
from app.services.telegram_menu_qa import scan_telegram_bot_module
from app.models.user import User
from app.models.match import Match
from app.services.ai.locale import is_text_locale
from app.services.ai.chat_brain_suggestions import ChatBrainRequest, run_chat_brain_suggestions
from app.core.security import get_password_hash, create_access_token
from app.models.profile import Profile


QaKind = Literal[
    "english_ux",
    "localization",
    "chat",
    "menu",
    "bot2bot",
    # QA tiers:
    "quick_product",  # fast API smoke
    "deep_product",  # Playwright UI flows
    # Back-compat:
    "full_product",
]
QaMode = Literal["summary", "fixes", "deep", "prompts", "prompts_top"]


def _enabled() -> bool:
    v = str(os.getenv("QA_AGENT_ENABLED", "false") or "false").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def _demo_only() -> bool:
    v = str(os.getenv("QA_AGENT_DEMO_ONLY", "true") or "true").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def _repo_root() -> Path:
    # backend/app/services/qa/qa_agent.py -> repo root
    return Path(__file__).resolve().parents[4]


def _latest_path() -> Path:
    reports = _repo_root() / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    return reports / "qa_latest.json"


def save_latest_report(payload: dict[str, Any]) -> Path:
    path = _latest_path()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_latest_report() -> dict[str, Any] | None:
    path = _latest_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        return data if isinstance(data, dict) else None
    except Exception:
        return None


@dataclass
class _Issue:
    # critical|high|medium|low
    severity: str
    impact: str  # crash|ux|conversion|localization|ai|data
    category: str  # api_error|ui_ux|ai_behavior|localization|data_inconsistency
    title: str
    message: str
    endpoint_or_route: str
    status: int | None = None
    error_message: str = ""
    stack_trace: str = ""
    probable_locations: list[str] | None = None
    cause: str = ""
    fix_steps: list[str] | None = None
    cursor_fix_prompt: str = ""
    priority_score: int = 0
    fingerprint: str = ""
    recurring: bool = False


class QaReport(TypedDict, total=False):
    title: str
    kind: str
    score: int
    runtime_s: float
    checks: dict[str, Any]
    issues: list[dict[str, Any]]
    top_issues: list[dict[str, Any]]
    suggested_fixes: list[str]
    summary: dict[str, Any]
    sections: dict[str, Any]
    product_intelligence: dict[str, Any]


def _score_from_issues(issues: list[_Issue]) -> int:
    score = 100
    for it in issues:
        sev = str(it.severity or "").strip().lower()
        if sev == "critical":
            score -= 16
        elif sev == "high":
            score -= 11
        elif sev == "medium":
            score -= 6
        else:  # low/info
            score -= 3
    return max(0, min(100, score))


_CYRILLIC_RE = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
_RAW_KEY_RE = re.compile(r"\b(chat|matches|onboarding|profile|premium|errors|navigation)\.[a-z0-9_.-]+\b", re.IGNORECASE)

_STACK_HINT_RE = re.compile(r"(Traceback \(most recent call last\):[\s\S]{0,6000})", re.IGNORECASE)
_NEXT_ERROR_RE = re.compile(r"(Error:\s.*?)(?:\n|</pre>|</h1>|</title>)", re.IGNORECASE)


def _norm_severity(value: str) -> str:
    v = str(value or "").strip().lower()
    if v in {"critical", "high", "medium", "low"}:
        return v
    if v in {"warning"}:
        return "medium"
    if v in {"info"}:
        return "low"
    return "medium"


def _priority_score(severity: str, impact: str) -> int:
    sev_w = {"critical": 40, "high": 28, "medium": 16, "low": 6}
    imp_w = {"crash": 30, "conversion": 22, "ux": 16, "localization": 14, "ai": 12, "data": 10}
    return int(sev_w.get(_norm_severity(severity), 16) + imp_w.get(str(impact or "ux").strip().lower(), 16))


def _classify(endpoint_or_route: str, message: str) -> tuple[str, str]:
    p = str(endpoint_or_route or "")
    m = str(message or "").lower()
    if p.startswith("/api/") or p.startswith("/api/v1/"):
        return "api_error", "crash"
    if "localization" in m or "translation" in m or "i18n" in m or "raw i18n" in m:
        return "localization", "localization"
    if "ai" in m or "suggestion" in m or "assistant" in m:
        return "ai_behavior", "ai"
    if "failed to load" in m or "500" in m:
        return "ui_ux", "crash"
    return "ui_ux", "ux"


def _probable_locations(endpoint_or_route: str, message: str) -> list[str]:
    p = str(endpoint_or_route or "")
    m = str(message or "").lower()
    out: list[str] = []
    # Backend routing heuristics
    if p.startswith("/api/v1/messages") or "/messages" in p:
        out.append("backend/app/api/v1/endpoints/messages.py")
    if p.startswith("/api/v1/ai") or "/ai/" in p or "ai suggestions" in m:
        out.append("backend/app/services/ai/")
        out.append("backend/app/api/v1/endpoints/ai.py")
    if "/matches" in p or "matches" in m:
        out.append("frontend/app/matches/page.tsx")
        out.append("frontend/app/components/likes/LikesYouPanel.tsx")
    if "/chat" in p or "chat" in m:
        out.append("frontend/app/components/chat/ChatThreadPage.tsx")
        out.append("frontend/app/components/chat/ChatMessageList.tsx")
        out.append("frontend/app/components/chat/ChatAiBrainPanel.tsx")
    if "raw i18n" in m or "translation" in m or "locale" in m:
        out.append("frontend/public/locales/*.json")
        out.append("frontend/lib/i18n/")
    if "onboarding" in p or "onboarding" in m:
        out.append("frontend/app/onboarding/")
    if "/subscription" in p or "premium" in m:
        out.append("frontend/app/subscription/")
    # De-dupe while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        deduped.append(x)
    return deduped


def _issue_fingerprint(kind: str, endpoint_or_route: str, title: str, message: str) -> str:
    base = f"{kind}|{endpoint_or_route}|{title}|{message}"
    base = re.sub(r"\s+", " ", base.strip().lower())
    return base[:240]


def _extract_error_details(body: str) -> tuple[str, str]:
    """Best-effort (frontend HTML/JSON). Returns (error_message, stack_trace)."""
    text = str(body or "")
    stack = ""
    err = ""
    m = _STACK_HINT_RE.search(text)
    if m:
        stack = m.group(1).strip()
    m2 = _NEXT_ERROR_RE.search(text)
    if m2:
        err = m2.group(1).strip()
    # Fallback: short snippet
    if not err:
        snippet = re.sub(r"\s+", " ", text)[:240].strip()
        err = snippet
    return err[:800], stack[:6000]


def _to_public_issue_dict(issue: _Issue) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "impact": issue.impact,
        "category": issue.category,
        "priority_score": issue.priority_score,
        "title": issue.title,
        "message": issue.message,
        "endpoint_or_route": issue.endpoint_or_route,
        "status": issue.status,
        "error_message": issue.error_message,
        "stack_trace": issue.stack_trace,
        "probable_locations": issue.probable_locations or [],
        "cause": issue.cause,
        "fix_steps": issue.fix_steps or [],
        "cursor_fix_prompt": issue.cursor_fix_prompt,
        "fingerprint": issue.fingerprint,
        "recurring": bool(issue.recurring),
    }


def _html_has(html: str, needle: str) -> bool:
    return needle in (html or "")


def _count_substrings(html: str, needle: str) -> int:
    return (html or "").count(needle)


def _extract_primary_cta_labels(html: str) -> list[str]:
    """
    Ultra-light heuristic: Next.js markup includes our CSS classes.
    We look for button/anchor class tokens; we don't parse DOM here (safe + dependency-free).
    """
    h = html or ""
    labels: list[str] = []
    # Common CTAs we care about, by intent.
    for token in ("Say hi", "Open chat", "Unlock", "Continue", "Upgrade", "Start", "Next", "Send"):
        if token in h:
            labels.append(token)
    return labels[:6]


def _ux_screen_eval(screen: str, html: str) -> dict[str, Any]:
    """
    Product UX Intelligence (heuristic, no browser automation).
    Returns structured ratings + improvement suggestions.
    """
    h = html or ""
    # Clarity signals
    primary_cta_present = _html_has(h, 'class="btn btn-primary') or _html_has(h, "btn btn-primary")
    primary_cta_count = _count_substrings(h, "btn btn-primary")
    empty_state_present = "EmptyState" in h or "empty" in h.lower() and ("no matches" in h.lower() or "empty" in h.lower())
    raw_keys_present = bool(_RAW_KEY_RE.search(h))
    cyrillic_present = bool(_CYRILLIC_RE.search(h))
    labels = _extract_primary_cta_labels(h)

    clarity = 2
    if primary_cta_present and primary_cta_count >= 1:
        clarity = 4 if primary_cta_count >= 2 else 3
    if empty_state_present and not primary_cta_present:
        clarity = 1

    friction = 2
    if empty_state_present:
        friction += 1
    if raw_keys_present:
        friction += 2
    friction = max(0, min(5, friction))

    emotion = 2
    if _html_has(h, "match-row") or _html_has(h, "discover-card") or _html_has(h, "chat-brain-panel"):
        emotion = 3
    if _html_has(h, "skeleton") or _html_has(h, "neyraShimmer"):
        emotion = max(emotion, 3)
    if empty_state_present and primary_cta_count == 0:
        emotion = 1

    conversion = 2
    if screen in {"discover"}:
        conversion = 4  # swipe-like flow by definition (heuristic)
    if screen in {"matches", "chat"} and primary_cta_present:
        conversion = 4
    if screen in {"premium"} and primary_cta_present:
        conversion = 3

    suggestions: list[dict[str, Any]] = []

    def add(title: str, why: str, suggestion: list[str], impact: str, effort: str, quick_win: bool) -> None:
        suggestions.append(
            {
                "title": title,
                "why_it_matters": why,
                "suggestion": suggestion,
                "impact": impact,
                "effort": effort,
                "quick_win": bool(quick_win),
            }
        )

    # Global UX hygiene
    if not primary_cta_present:
        add(
            f"No clear primary action on {screen}",
            "Users hesitate → lower activation / lower message rate.",
            ["Add a single, obvious primary CTA above the fold.", "Make secondary actions visually secondary."],
            impact="high",
            effort="low",
            quick_win=True,
        )
    if raw_keys_present:
        add(
            f"Raw i18n keys visible on {screen}",
            "Looks broken/unpolished → trust + conversion hit.",
            ["Fix missing translation keys; ensure UI never renders token strings.", "Run `npm run check-i18n` and fix offenders."],
            impact="high",
            effort="medium",
            quick_win=False,
        )
    if cyrillic_present and screen != "localization":
        add(
            f"Language leak in English UX ({screen})",
            "Mixed language breaks clarity and premium feel.",
            ["Ensure locale=en renders English only.", "Remove hardcoded UA/RU strings from shared components."],
            impact="medium",
            effort="medium",
            quick_win=False,
        )

    # Screen-specific product suggestions (Tinder/Bumble-style heuristics)
    if screen == "matches":
        add(
            "Weak Matches CTA clarity",
            "If users don't instantly see 'what to do', first-message rate drops.",
            [
                "Primary button: “💬 Say hi” on each match (opens chat + focuses input).",
                "Secondary: “✨ AI opener” for frictionless first message.",
                "Highlight 1 best/recently-active match with a subtle glow.",
            ],
            impact="high",
            effort="low",
            quick_win=True,
        )
        add(
            "Make Likes feel valuable before paywall",
            "Showing real partial info builds curiosity → higher upgrade conversion without feeling pushy.",
            ["Show 2–3 partial-like cards (age/city/match%)", "Use copy like “Someone already likes you 👀” before “Unlock more”."],
            impact="high",
            effort="low",
            quick_win=True,
        )
    if screen == "chat":
        add(
            "Conversation momentum nudges",
            "Small, timely nudges increase replies and reduce dead chats.",
            [
                "Keep AI as suggestion-only; never as participant.",
                "When draft is empty and partner just replied, surface 1–3 reply options near composer.",
                "Default to short, playful options (not assistant-like).",
            ],
            impact="high",
            effort="medium",
            quick_win=False,
        )
    if screen == "discover":
        add(
            "Make Discover feel 'alive'",
            "Tinder/Bumble optimize for fast swipe momentum; empty/slow cards kill intent.",
            ["Ensure skeletons load instantly on slow networks.", "Add 1-line reasons (why this match) without blocking swipe."],
            impact="medium",
            effort="medium",
            quick_win=False,
        )
    if screen == "onboarding":
        add(
            "Reduce onboarding friction",
            "Shorter onboarding improves completion and time-to-first-swipe.",
            ["Keep steps minimal; avoid long text blocks.", "Ensure language step is clear + early."],
            impact="high",
            effort="medium",
            quick_win=False,
        )
    if screen == "premium":
        add(
            "Value-first paywall",
            "Aggressive copy hurts trust; value-first increases conversion over time.",
            ["Show concrete benefits (openers, better replies) before price.", "Avoid guilt/pressure language; keep tone confident."],
            impact="medium",
            effort="low",
            quick_win=True,
        )

    # Sort by high impact + low effort first
    impact_rank = {"high": 3, "medium": 2, "low": 1}
    effort_rank = {"low": 3, "medium": 2, "high": 1}
    suggestions.sort(key=lambda s: (impact_rank.get(str(s.get("impact")), 1), effort_rank.get(str(s.get("effort")), 1)), reverse=True)

    return {
        "screen": screen,
        "metrics": {
            "clarity_0_5": clarity,
            "friction_0_5": friction,
            "conversion_0_5": conversion,
            "emotion_0_5": emotion,
            "primary_cta_count": primary_cta_count,
            "primary_cta_labels": labels,
            "empty_state_present": bool(empty_state_present),
        },
        "product_suggestions": suggestions,
    }


def _benchmark_insights() -> list[dict[str, Any]]:
    """
    Static benchmark heuristics (senior PM tone).
    We keep them concrete + actionable, not fluff.
    """
    return [
        {
            "title": "Tinder: immediate action loop (swipe) → NEYRA: keep actions above the fold",
            "insight": "Top-tier apps minimize hesitation: one primary action per screen.",
            "recommendation": ["Matches: emphasize “Say hi” as the obvious primary CTA.", "Chat: keep composer + suggestions visible, avoid extra blocks."],
            "impact": "high",
            "effort": "low",
        },
        {
            "title": "Bumble: empowers first message → NEYRA: reduce first-message anxiety",
            "insight": "First message is the biggest friction point; remove blank-state paralysis.",
            "recommendation": ["Offer 2–3 strong openers (suggestion-only) and focus input immediately.", "Prefer short, playful options over assistant tone."],
            "impact": "high",
            "effort": "medium",
        },
        {
            "title": "Hinge: prompts create depth → NEYRA: add lightweight hooks, not essays",
            "insight": "Depth increases replies, but only if it stays easy.",
            "recommendation": ["Use one-line hooks/questions; avoid long 'coach' paragraphs.", "Keep deep suggestions gated until there is momentum."],
            "impact": "medium",
            "effort": "medium",
        },
    ]


def _run_telegram_menu_qa_scan() -> dict[str, Any] | None:
    """
    Run the existing Telegram Menu QA scan (read-only), without calling Telegram API.
    Mirrors admin endpoint logic but keeps it local to QA Agent.
    """
    try:
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
            return None

        loader = SourceFileLoader("telegram_admin_bot_scan_qa_agent", str(script))
        spec = spec_from_loader("telegram_admin_bot_scan_qa_agent", loader)
        if spec is None or spec.loader is None:
            return None
        bot = module_from_spec(spec)
        _sys.modules["telegram_admin_bot_scan_qa_agent"] = bot
        spec.loader.exec_module(bot)  # type: ignore

        # Ensure we never hit network: stub tg_call and backend.request if present.
        try:
            setattr(bot, "tg_call", lambda *a, **k: {"ok": True, "result": {}})
            setattr(bot, "backend", type("B", (), {"request": lambda *a, **k: {}})())
        except Exception:
            pass

        out = scan_telegram_bot_module(bot)
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def _pick_demo_match_pair(db: Session) -> tuple[int, int] | None:
    """
    Safety: demo users only. Prefer demo<->demo matches so we never touch real users.
    Returns (user_id, partner_id) or None.
    """
    try:
        # find any match where both sides are demo
        rows = (
            db.query(Match)
            .join(User, User.id == Match.user_a_id)
            .filter(User.is_demo == True)  # noqa: E712
            .limit(40)
            .all()
        )
        for m in rows:
            a = int(getattr(m, "user_a_id"))
            b = int(getattr(m, "user_b_id"))
            ua = db.query(User).filter(User.id == a).first()
            ub = db.query(User).filter(User.id == b).first()
            if not ua or not ub:
                continue
            if bool(getattr(ua, "is_demo", False)) and bool(getattr(ub, "is_demo", False)):
                return a, b
    except Exception:
        return None
    return None


def _ensure_qa_demo_seed(db: Session) -> tuple[int, int] | None:
    """
    Creates/ensures two demo users + profiles + a match between them.
    Safe: demo users only, deterministic emails.
    """
    try:
        a_email = "qa_demo_a@neyra.local"
        b_email = "qa_demo_b@neyra.local"
        pwd = "qa-demo-only"

        def ensure_user(email: str, display_name: str) -> int:
            u = db.query(User).filter(User.email == email).first()
            if not u:
                u = User(email=email, hashed_password=get_password_hash(pwd), is_active=True, is_demo=True)
                db.add(u)
                db.flush()
            else:
                u.is_demo = True
                if not u.hashed_password:
                    u.hashed_password = get_password_hash(pwd)
            p = db.query(Profile).filter(Profile.user_id == int(u.id)).first()
            if not p:
                p = Profile(user_id=int(u.id), display_name=display_name, is_demo_profile=True, preferred_language="en")
                db.add(p)
            else:
                p.is_demo_profile = True
                if not (p.display_name or "").strip():
                    p.display_name = display_name
            return int(u.id)

        a_id = ensure_user(a_email, "QA Demo A")
        b_id = ensure_user(b_email, "QA Demo B")

        # ensure match exists (unique constraint handles duplicates)
        pair = (min(a_id, b_id), max(a_id, b_id))
        existing = db.query(Match).filter(Match.user_a_id == pair[0], Match.user_b_id == pair[1]).first()
        if not existing:
            db.add(Match(user_a_id=pair[0], user_b_id=pair[1]))
        db.commit()
        return a_id, b_id
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _ai_chat_qa(db: Session) -> list[_Issue]:
    """
    AI Chat QA (server-side): opener/reply/revive packs for demo users.
    Verifies: 3 suggestions, no duplicates, correct language, no hard failures (429/500).
    """
    pair = _pick_demo_match_pair(db) or _ensure_qa_demo_seed(db)
    if not pair:
        it = _Issue(
            severity="high",
            impact="conversion",
            category="data_inconsistency",
            title="AI Chat QA skipped: no demo match pair available",
            message="Could not find a demo↔demo match to safely run AI suggestion generation.",
            endpoint_or_route="db:matches",
            probable_locations=["backend/app/services/demo_mode.py", "backend/app/services/demo_behavior.py", "backend/app/models/match.py"],
            cause="Demo seed data missing matches between demo users.",
            fix_steps=["Seed at least one demo↔demo match (two demo users matched).", "Rerun Full Product QA."],
            cursor_fix_prompt="Seed demo data: ensure there is at least one Match between two demo users (User.is_demo=True) so AI Chat QA can run safely.",
        )
        it.fingerprint = _issue_fingerprint("ai_chat_qa", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        return [it]

    me, partner = pair
    out: list[_Issue] = []

    def check_mode(mode: str, lang: str = "en") -> None:
        body = ChatBrainRequest(partner_user_id=int(partner), mode=str(mode), language=str(lang))
        try:
            res = run_chat_brain_suggestions(db, user_id=int(me), body=body)
        except Exception as e:
            res = {"ok": False, "error": type(e).__name__}
        if not isinstance(res, dict) or not res.get("ok"):
            it = _Issue(
                severity="critical",
                impact="ai",
                category="ai_behavior",
                title=f"AI suggestions failed ({mode})",
                message=f"Chat brain suggestions failed for mode={mode}.",
                endpoint_or_route="/api/v1/ai/chat-brain/suggestions",
                probable_locations=["backend/app/services/ai/chat_brain_suggestions.py", "backend/app/api/v1/endpoints/ai.py"],
                cause=f"AI provider error/rate limit or prompt/parse failure (mode={mode}).",
                fix_steps=["Check server logs for gemini/provider errors.", "Verify AI provider keys and rate limits.", "Rerun Full Product QA."],
                cursor_fix_prompt=f"Fix chat-brain suggestions failing for mode={mode} by tracing errors in chat_brain_suggestions.py and ai.py endpoint; handle provider errors and ensure ok=True response.",
            )
            it.fingerprint = _issue_fingerprint("ai_chat_qa", it.endpoint_or_route, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            out.append(it)
            return

        variants = res.get("variants") if isinstance(res.get("variants"), dict) else {}
        texts = [str(variants.get(k) or "").strip() for k in ("light", "flirty", "deep")]
        non_empty = [t for t in texts if t]
        if len(non_empty) < 3:
            it = _Issue(
                severity="high",
                impact="conversion",
                category="ai_behavior",
                title=f"AI pack incomplete ({mode})",
                message=f"Expected 3 suggestions (light/flirty/deep) but got {len(non_empty)} non-empty.",
                endpoint_or_route="/api/v1/ai/chat-brain/suggestions",
                probable_locations=["backend/app/services/ai/chat_brain_suggestions.py"],
                cause="Language enforcement or safety filter dropped variants; refill/regeneration insufficient.",
                fix_steps=["Ensure pack refills empty variants with safe fallbacks.", "Add guardrails to always return 3 short suggestions."],
                cursor_fix_prompt=f"Ensure run_chat_brain_suggestions always returns 3 non-empty variants for mode={mode}, refilling any filtered variant with fallback generation.",
            )
            it.fingerprint = _issue_fingerprint("ai_chat_qa", it.endpoint_or_route, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            out.append(it)

        # Duplicates
        norm = [re.sub(r"\s+", " ", t.lower()).strip() for t in non_empty]
        if len(set(norm)) != len(norm) and len(norm) >= 2:
            it = _Issue(
                severity="high",
                impact="ux",
                category="ai_behavior",
                title=f"Duplicate AI suggestions ({mode})",
                message="At least two variants are identical/near-identical.",
                endpoint_or_route="/api/v1/ai/chat-brain/suggestions",
                probable_locations=["backend/app/services/ai/chat_brain_suggestions.py"],
                cause="Variation repair/regeneration did not trigger or threshold too lenient.",
                fix_steps=["Tighten similarity threshold and force regen of duplicates.", "Add deterministic de-duplication before returning."],
                cursor_fix_prompt=f"Prevent duplicate variants in chat-brain suggestions for mode={mode}: detect similarity and regenerate the weaker variant until all 3 differ meaningfully.",
            )
            it.fingerprint = _issue_fingerprint("ai_chat_qa", it.endpoint_or_route, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            out.append(it)

        # Language correctness
        bad_lang = [t for t in non_empty if not is_text_locale(t, lang)]
        if bad_lang:
            it = _Issue(
                severity="high",
                impact="localization",
                category="localization",
                title=f"Wrong-language AI suggestions ({mode})",
                message=f"Some variants are not in requested language={lang}.",
                endpoint_or_route="/api/v1/ai/chat-brain/suggestions",
                probable_locations=["backend/app/services/ai/chat_brain_suggestions.py", "frontend/lib/chat/aiLanguageTone.ts"],
                cause="Request language not enforced end-to-end; model drift or fallback copy leaks.",
                fix_steps=["Enforce request.language as the single source of truth.", "Drop+refill variants that violate locale."],
                cursor_fix_prompt=f"Enforce chat-brain language lock: if requested language={lang}, ensure all 3 variants satisfy is_text_locale() or regenerate/refill until they do.",
            )
            it.fingerprint = _issue_fingerprint("ai_chat_qa", it.endpoint_or_route, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            out.append(it)

    for m in ("opener", "reply", "revive"):
        check_mode(m, "en")
    return out


def _as_issue_from_menu_qa(row: dict[str, Any]) -> _Issue | None:
    if not isinstance(row, dict):
        return None
    sev0 = str(row.get("severity") or "").strip().lower()
    sev = "critical" if sev0 == "critical" else ("high" if sev0 in {"warning", "warn"} else "low")
    cb = str(row.get("callback") or "").strip()
    msg = str(row.get("message") or "").strip()
    sug = str(row.get("suggested_fix") or "").strip()
    ttl = str(row.get("type") or "menu_qa_issue").replace("_", " ").strip().title()
    it = _Issue(
        severity=sev,
        impact="ux" if sev != "low" else "data",
        category="ui_ux",
        title=f"Telegram menu QA: {ttl}",
        message=(msg or cb)[:500],
        endpoint_or_route=f"telegram:{cb}" if cb else "telegram:menu",
        probable_locations=["backend/scripts/telegram_admin_bot.py", "backend/app/services/telegram_menu_qa.py"],
        cause="Telegram admin menu routing/translation/confirm flow issue (static scan).",
        fix_steps=[sug] if sug else [],
        cursor_fix_prompt=f"Fix Telegram admin bot menu issue ({cb}): {msg}. Update handlers/keys and rerun Menu QA scan.",
    )
    it.fingerprint = _issue_fingerprint("menu_qa", it.endpoint_or_route, it.title, it.message)
    it.priority_score = _priority_score(it.severity, it.impact)
    return it


def _as_issue_from_e2e(row: dict[str, Any]) -> _Issue | None:
    if not isinstance(row, dict):
        return None
    sev0 = str(row.get("severity") or "").strip().lower()
    sev = "critical" if sev0 == "critical" else ("high" if sev0 in {"high", "warning", "warn"} else "medium")
    flow = str(row.get("flow") or "").strip()
    step = str(row.get("step") or "").strip()
    msg = str(row.get("message") or "").strip()
    fix = str(row.get("suggested_fix") or "").strip()
    endpoint = f"e2e:{flow}:{step}" if flow or step else "e2e:issue"
    locs = _probable_locations("/api", msg)
    locs = ["backend/app/services/e2e_qa.py", *locs]
    it = _Issue(
        severity=sev,
        impact="crash" if sev == "critical" else "conversion",
        category="api_error" if "config" in step or "db" in step else "ui_ux",
        title=f"E2E QA: {flow or 'flow'}",
        message=f"{step}: {msg}"[:700],
        endpoint_or_route=endpoint,
        probable_locations=locs,
        cause="Critical flow/config/DB health regression detected by E2E scan.",
        fix_steps=[fix] if fix else [],
        cursor_fix_prompt=f"Fix E2E QA issue in {flow}/{step}: {msg}. Apply suggested fix and rerun E2E QA scan.",
    )
    it.fingerprint = _issue_fingerprint("e2e", it.endpoint_or_route, it.title, it.message)
    it.priority_score = _priority_score(it.severity, it.impact)
    return it


def _full_product_qa(db: Session) -> dict[str, Any]:
    started = time.time()
    issues: list[_Issue] = []

    # 1) Core UX + product intelligence (screens + copy hygiene)
    en = _english_ux_qa(db)
    for it in (en.get("issues") or [])[:60]:
        # Rehydrate into _Issue-like dicts (we keep public dicts, but for scoring unify)
        if isinstance(it, dict):
            sev = _norm_severity(str(it.get("severity") or "medium"))
            imp = str(it.get("impact") or "ux")
            ps = int(it.get("priority_score") or _priority_score(sev, imp))
            issues.append(
                _Issue(
                    severity=sev,
                    impact=imp,
                    category=str(it.get("category") or "ui_ux"),
                    title=str(it.get("title") or "Issue"),
                    message=str(it.get("message") or "")[:900],
                    endpoint_or_route=str(it.get("endpoint_or_route") or ""),
                    status=int(it.get("status")) if it.get("status") is not None else None,
                    error_message=str(it.get("error_message") or ""),
                    stack_trace=str(it.get("stack_trace") or ""),
                    probable_locations=list(it.get("probable_locations") or []),
                    cause=str(it.get("cause") or ""),
                    fix_steps=list(it.get("fix_steps") or []),
                    cursor_fix_prompt=str(it.get("cursor_fix_prompt") or ""),
                    priority_score=ps,
                    fingerprint=str(it.get("fingerprint") or ""),
                    recurring=bool(it.get("recurring")),
                )
            )

    # 2) E2E QA (API/config/data health) — already read-only
    try:
        e2e = run_e2e_qa_scan(db)
        for row in (e2e.get("issues") or [])[:40]:
            if isinstance(row, dict):
                it = _as_issue_from_e2e(row)
                if it:
                    issues.append(it)
    except Exception:
        pass

    # 3) Telegram menu QA (admin UX safety + completeness)
    menu = _run_telegram_menu_qa_scan() or {}
    for row in (menu.get("issues") or [])[:60]:
        if isinstance(row, dict):
            it = _as_issue_from_menu_qa(row)
            if it:
                issues.append(it)

    # 4) Localization (basic): only summary-level from localization_report.json
    try:
        l10n = _localization_qa(db)
        for it in (l10n.get("issues") or [])[:30]:
            if isinstance(it, dict):
                sev = _norm_severity(str(it.get("severity") or "medium"))
                imp = str(it.get("impact") or "localization")
                ps = int(it.get("priority_score") or _priority_score(sev, imp))
                issues.append(
                    _Issue(
                        severity=sev,
                        impact=imp,
                        category=str(it.get("category") or "localization"),
                        title=str(it.get("title") or "Localization issue"),
                        message=str(it.get("message") or "")[:900],
                        endpoint_or_route=str(it.get("endpoint_or_route") or "reports/localization_report.json"),
                        probable_locations=list(it.get("probable_locations") or []),
                        cause=str(it.get("cause") or ""),
                        fix_steps=list(it.get("fix_steps") or []),
                        cursor_fix_prompt=str(it.get("cursor_fix_prompt") or ""),
                        priority_score=ps,
                        fingerprint=str(it.get("fingerprint") or ""),
                        recurring=bool(it.get("recurring")),
                    )
                )
    except Exception:
        pass

    # 5) AI Chat QA (opener/reply/revive packs) — demo only
    try:
        issues.extend(_ai_chat_qa(db))
    except Exception:
        pass

    # Deduplicate by fingerprint/title/message
    seen: set[str] = set()
    deduped: list[_Issue] = []
    for it in sorted(issues, key=lambda x: int(x.priority_score or 0), reverse=True):
        fp = it.fingerprint or _issue_fingerprint("quick_product", it.endpoint_or_route, it.title, it.message)
        if fp in seen:
            continue
        seen.add(fp)
        deduped.append(it)

    # Keep it short: 10–12 key points, grouped by severity.
    deduped.sort(key=lambda x: int(x.priority_score or 0), reverse=True)
    top = deduped[:12]

    score = _score_from_issues(top)
    runtime_s = round(time.time() - started, 2)

    # Product Intelligence summary comes from English UX report (already contains it)
    pi = en.get("product_intelligence") if isinstance(en.get("product_intelligence"), dict) else {}
    quick = pi.get("quick_wins") if isinstance(pi.get("quick_wins"), list) else []

    top_priority = _to_public_issue_dict(top[0]) if top else {}
    report: QaReport = {
        "title": "🧪 NEYRA QA Report",
        "kind": "quick_product",
        "score": score,
        "runtime_s": runtime_s,
        "issues": [_to_public_issue_dict(i) for i in top],
        "top_issues": [_to_public_issue_dict(i) for i in top[:5]],
        "summary": {
            "critical": len([i for i in top if i.severity == "critical"]),
            "important": len([i for i in top if i.severity in {"high", "medium"}]),
            "minor": len([i for i in top if i.severity == "low"]),
        },
        "product_intelligence": {
            "product_insights": [
                *(pi.get("ux_issues") or [])[:3],
                *(pi.get("conversion_blockers") or [])[:3],
                *(pi.get("engagement_gaps") or [])[:3],
            ],
            "quick_wins": quick[:8] if isinstance(quick, list) else [],
            "benchmark_insights": (pi.get("benchmark_insights") or _benchmark_insights())[:3],
            "top_priority_fix": top_priority,
        },
    }
    return report  # type: ignore[return-value]


def _deep_product_qa(db: Session) -> dict[str, Any]:
    """
    Deep product QA: real UI flows via Playwright (frontend).
    This must never claim "deep QA" unless Playwright actually ran.
    """
    started = time.time()
    repo = _repo_root()
    # Do not hardcode /frontend. Prefer env FRONTEND_DIR inside Docker.
    env_frontend_dir = str(os.getenv("FRONTEND_DIR", "") or "").strip()
    candidates: list[Path] = []
    if env_frontend_dir:
        candidates.append(Path(env_frontend_dir).resolve())
    candidates.extend(
        [
            Path("/app/frontend"),
            Path("/frontend"),
            (repo / "frontend"),
            (repo / "../frontend"),
            Path("./frontend"),
            Path("../frontend"),
        ]
    )
    frontend_dir = next((p.resolve() for p in candidates if p and p.exists()), None)
    metrics_path = (repo / "reports" / "deep_qa_metrics.json").resolve()

    # Ensure demo user exists (for login).
    _ensure_qa_demo_seed(db)
    demo_email = "qa_demo_a@neyra.local"
    demo_password = "qa-demo-only"

    # Frontend URL for Deep QA runs inside Docker must use service DNS name, not localhost.
    configured_url = str(getattr(settings, "INTERNAL_FRONTEND_URL", "") or getattr(settings, "FRONTEND_URL", "") or "").strip()
    url_candidates = [
        configured_url.rstrip("/") if configured_url else "",
        "http://neyra-web:3000",
        "http://localhost:3000",
    ]
    url_candidates = [u for u in url_candidates if u]
    base_url = url_candidates[0].rstrip("/") if url_candidates else "http://localhost:3000"
    frontend_url_used = ""
    qa_runner_url = str(os.getenv("QA_RUNNER_URL", "") or "http://qa-runner:3999").strip().rstrip("/")

    def unavailable(msg: str) -> dict[str, Any]:
        runtime_s = round(time.time() - started, 2)
        it = _Issue(
            severity="critical",
            impact="ux",
            category="ui_ux",
            title="Deep QA unavailable",
            message=msg,
            endpoint_or_route="playwright:runner",
            probable_locations=["backend/app/services/qa/qa_agent.py", "frontend/playwright.config.ts"],
            cause="Playwright not installed or cannot be executed in this environment.",
            fix_steps=[
                "Install frontend deps (npm ci) including @playwright/test.",
                "Ensure browsers are installed (npx playwright install).",
                "Rerun Deep QA.",
            ],
            cursor_fix_prompt="Make Deep QA runnable in backend container: ensure node + @playwright/test + browsers exist, and allow running `npx playwright test` from backend QA agent.",
        )
        it.fingerprint = _issue_fingerprint("deep_product", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        frontend_dir_str = str(frontend_dir) if frontend_dir is not None else ""
        return {
            "title": "🧪 NEYRA Deep QA Report",
            "kind": "deep_product",
            "score": 0,
            "runtime_s": runtime_s,
            "checks": {
                "browser_used": False,
                "auth_used": False,
                "frontend_url": base_url,
                "frontend_url_used": frontend_url_used or base_url,
                "frontend_dir": frontend_dir_str,
            },
            "summary": {"note": "Deep QA unavailable"},
            "issues": [_to_public_issue_dict(it)],
        }

    # Deep QA must run where Node + Playwright exist. In Docker, that is the qa-runner service.
    # Backend triggers it over HTTP; if missing, do not fake a score.
    ok_url = ""
    last_err = ""
    for u in url_candidates:
        try:
            r = requests.get(u.rstrip("/") + "/", timeout=4)
            if int(getattr(r, "status_code", 0) or 0) >= 500:
                last_err = f"frontend returned {r.status_code} at {u}/"
                continue
            ok_url = u.rstrip("/")
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
    if not ok_url:
        return unavailable(f"Deep QA unavailable: frontend not reachable (tried: {', '.join(url_candidates[:3])}). Last error: {last_err}")
    base_url = ok_url
    frontend_url_used = ok_url

    try:
        health = requests.get(f"{qa_runner_url}/health", timeout=3)
        if int(getattr(health, "status_code", 0) or 0) >= 400:
            return unavailable("Deep QA unavailable: qa-runner service not configured")
    except Exception:
        return unavailable("Deep QA unavailable: qa-runner service not configured")

    runtime_s = round(time.time() - started, 2)
    runner_payload = {"frontend_url": base_url, "email": demo_email, "password": demo_password}
    try:
        runner_res = requests.post(f"{qa_runner_url}/run", json=runner_payload, timeout=260)
        runner_text = runner_res.text if runner_res is not None else ""
        try:
            runner_json = json.loads(runner_text or "{}")
        except Exception:
            runner_json = None
    except Exception as e:
        return unavailable(f"Deep QA failed: qa-runner unreachable ({type(e).__name__}: {e})")

    if not isinstance(runner_json, dict):
        snippet = (runner_text or "")[:1000].strip()
        it = _Issue(
            severity="critical",
            impact="ux",
            category="ui_ux",
            title="qa-runner invalid JSON response",
            message=f"Deep QA runner returned invalid JSON. First bytes:\n{snippet}",
            endpoint_or_route=f"{qa_runner_url}/run",
            probable_locations=["frontend/scripts/deep-qa-runner.mjs", "backend/app/services/qa/qa_agent.py"],
            cause="qa-runner returned logs/text instead of JSON.",
            fix_steps=["Ensure qa-runner always responds with strict JSON.", "Send logs to stderr, not response body."],
            cursor_fix_prompt="Fix qa-runner contract: ensure /run returns valid JSON always; backend should parse runner_res.text safely and include snippets on parse failure.",
        )
        it.fingerprint = _issue_fingerprint("deep_product", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        report = {
            "title": "🧪 NEYRA Deep QA Report",
            "kind": "deep_product",
            "score": 0,
            "runtime_s": round(time.time() - started, 2),
            "checks": {
                "browser_used": False,
                "auth_used": False,
                "frontend_url": base_url,
                "frontend_url_used": frontend_url_used or base_url,
                "frontend_dir": "",
            },
            "issues": [_to_public_issue_dict(it)],
            "summary": {"note": "qa-runner invalid JSON response"},
        }
        return report  # type: ignore[return-value]

    runtime_s = float(runner_json.get("runtime_seconds") or runtime_s)
    pages_visited = int(runner_json.get("pages_visited") or 0)
    buttons_clicked = int(runner_json.get("buttons_clicked") or 0)
    interactions_count = int(runner_json.get("interactions_count") or 0)
    flows_completed = runner_json.get("flows_completed") if isinstance(runner_json.get("flows_completed"), list) else []
    flows_completed = [str(x) for x in flows_completed if x]
    flow_failures = runner_json.get("flow_failures") if isinstance(runner_json.get("flow_failures"), dict) else {}
    flow_failures = {str(k): str(v) for k, v in (flow_failures or {}).items()}
    flow_report_raw = runner_json.get("flow_report") if isinstance(runner_json.get("flow_report"), dict) else {}
    flow_report = {str(k): str(v) for k, v in (flow_report_raw or {}).items()}
    flow_skip_reasons_raw = runner_json.get("flow_skip_reasons") if isinstance(runner_json.get("flow_skip_reasons"), dict) else {}
    flow_skip_reasons = {str(k): str(v) for k, v in (flow_skip_reasons_raw or {}).items()}
    frontend_reachable = bool(runner_json.get("frontend_reachable", True))
    first_failed_test = str(runner_json.get("first_failed_test") or "")[:220]
    failed_selector = str(runner_json.get("failed_selector") or "")[:220]
    first_trace = str(runner_json.get("first_trace") or "")[:220]
    screenshots = runner_json.get("screenshots") if isinstance(runner_json.get("screenshots"), list) else []
    screenshots = [str(x) for x in screenshots if x]
    screenshots_count = int(runner_json.get("screenshots_count") or len(screenshots))
    # Source of truth: Playwright exit code from qa-runner.
    # Fall back to ok flag only if exit_code missing.
    if runner_json.get("exit_code") is None:
        ok = bool(runner_json.get("ok") is True)
        exit_code = 0 if ok else 1
    else:
        exit_code = int(runner_json.get("exit_code") or 0)
        ok = exit_code == 0
    auth_status = str(runner_json.get("auth_status") or ("ok" if ok else "unknown"))[:40]
    rep_json: dict[str, Any] = {}

    issues: list[_Issue] = []
    # runner issues (structured)
    runner_issues = runner_json.get("issues") if isinstance(runner_json.get("issues"), list) else []
    for ri in runner_issues[:8]:
        if not isinstance(ri, dict):
            continue
        sev = _norm_severity(str(ri.get("severity") or "high"))
        ttl = str(ri.get("title") or "Deep QA issue").strip()[:120]
        det = str(ri.get("details") or "").strip()[:900]
        loc = str(ri.get("location") or "").strip()[:180]
        fix = str(ri.get("fix") or "").strip()[:320]
        it = _Issue(
            severity=sev,
            impact="ux",
            category="ui_ux",
            title=ttl,
            message=det or ttl,
            endpoint_or_route="playwright:test",
            probable_locations=[loc] if loc else ["frontend/tests/ui/deep-product.spec.ts"],
            cause="Deep QA detected a UI flow regression.",
            fix_steps=[fix] if fix else [],
            cursor_fix_prompt="Fix the failing Deep QA flow and rerun Deep Product QA.",
        )
        it.fingerprint = _issue_fingerprint("deep_product", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        issues.append(it)

    if ok and buttons_clicked < 6 and pages_visited < 4:
        # Passing run but low interaction coverage should be a warning, not a failure.
        it = _Issue(
            severity="low",
            impact="ux",
            category="ui_ux",
            title="Low interaction coverage",
            message="Low interaction coverage",
            endpoint_or_route="playwright:coverage",
            probable_locations=["frontend/tests/ui/deep-product.spec.ts"],
            cause="Deep QA spec is too shallow or environment limited interactions.",
            fix_steps=["Increase button clicks and page interactions in deep-product.spec.ts.", "Rerun Deep Product QA."],
            cursor_fix_prompt="Improve Deep QA coverage: extend `frontend/tests/ui/deep-product.spec.ts` to click more actions (discover like/pass, open first match/chat, open AI suggestions, open verification modal).",
        )
        it.fingerprint = _issue_fingerprint("deep_product", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        issues.append(it)

    if not ok:
        if not issues:
            msg = "Deep QA failed: at least one UI flow test failed."
            stderr_tail = str(runner_json.get("stderr_tail") or "").strip()
            stdout_tail = str(runner_json.get("stdout_tail") or "").strip()
            if stderr_tail:
                msg += f" Stderr: {stderr_tail[:700]}"
            elif stdout_tail:
                msg += f" Output: {stdout_tail[:700]}"
            it = _Issue(
                severity="critical",
                impact="ux",
                category="ui_ux",
                title="Deep QA failed (Playwright)",
                message=msg[:1200],
                endpoint_or_route="playwright:test",
                probable_locations=["frontend/tests/ui/deep-product.spec.ts", "frontend/app/"],
                cause="UI regression or environment issue detected by browser automation.",
                fix_steps=["Open the screenshot artifacts and Playwright output.", "Fix failing UI flow and rerun Deep QA."],
                cursor_fix_prompt="Fix failing Deep QA Playwright flow in `frontend/tests/ui/deep-product.spec.ts` and the referenced page/component. Re-run Deep QA.",
            )
            it.fingerprint = _issue_fingerprint("deep_product", it.endpoint_or_route, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            issues.append(it)

    score = int(runner_json.get("score") or (90 if ok else 0))
    return {
        "title": "🧪 NEYRA Deep QA Report",
        "kind": "deep_product",
        "score": score,
        "runtime_s": runtime_s,
        "checks": {
            "browser_used": bool(runner_json.get("browser_used", True)),
            "auth_used": bool(runner_json.get("auth_used", True)),
            "frontend_reachable": frontend_reachable,
            "auth_status": auth_status,
            "frontend_url": base_url,
            "frontend_url_used": frontend_url_used or base_url,
            "frontend_dir": "",
            "pages_visited": pages_visited,
            "buttons_clicked": buttons_clicked,
            "interactions_count": interactions_count,
            "flows_completed": flows_completed[:20],
            "flow_failures": dict(list(flow_failures.items())[:12]),
            "flow_skip_reasons": dict(list(flow_skip_reasons.items())[:16]),
            "flow_report": flow_report,
            "screenshots": screenshots[:12],
            "playwright_exit_code": exit_code,
            "first_failed_test": first_failed_test,
            "failed_selector": failed_selector,
            "first_trace": first_trace,
        },
        "issues": [_to_public_issue_dict(i) for i in issues],
        "summary": {
            "pages_visited": pages_visited,
            "buttons_clicked": buttons_clicked,
            "interactions_count": interactions_count,
            "flows_completed": flows_completed[:20],
            "flow_failures": dict(list(flow_failures.items())[:12]),
            "flow_skip_reasons": dict(list(flow_skip_reasons.items())[:16]),
            "flow_report": flow_report,
            "screenshots_count": screenshots_count,
            "browser_used": bool(runner_json.get("browser_used", True)),
            "auth_used": bool(runner_json.get("auth_used", True)),
            "frontend_reachable": frontend_reachable,
            "auth_status": auth_status,
        },
        "sections": {"playwright_report": rep_json if isinstance(rep_json, dict) else {}},
    }

def format_report(payload: dict[str, Any] | None, *, mode: QaMode = "deep") -> str:
    if not payload or payload.get("ok") is not True:
        return "No QA report found yet."
    rep = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    title = str(rep.get("title") or "🧪 QA Engineer Report").strip()
    score = rep.get("score")
    runtime_s = rep.get("runtime_s")
    issues = rep.get("issues") if isinstance(rep.get("issues"), list) else []

    # Count buckets
    crit = [i for i in issues if isinstance(i, dict) and str(i.get("severity") or "").lower() == "critical"]
    high = [i for i in issues if isinstance(i, dict) and str(i.get("severity") or "").lower() == "high"]
    med = [i for i in issues if isinstance(i, dict) and str(i.get("severity") or "").lower() == "medium"]
    low = [i for i in issues if isinstance(i, dict) and str(i.get("severity") or "").lower() == "low"]

    lines: list[str] = []
    lines.append(f"<b>{title}</b>")
    meta: list[str] = []
    if score is not None:
        meta.append(f"Score: <b>{score}</b>/100")
    if runtime_s is not None:
        meta.append(f"Runtime: <code>{runtime_s}s</code>")
    if meta:
        lines.append("\n" + " · ".join(meta))
    lines.append("")
    lines.append(f"❌ Critical issues ({len(crit)})")
    lines.append(f"⚠️ High/Medium issues ({len(high) + len(med)})")
    lines.append(f"ℹ️ Minor issues ({len(low)})")

    # Sort by priority_score desc if present
    def keyfn(x: dict) -> tuple[int, int]:
        ps = int(x.get("priority_score") or 0)
        sev = str(x.get("severity") or "").lower()
        sev_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(sev, 1)
        return (ps, sev_rank)

    sorted_issues = sorted([i for i in issues if isinstance(i, dict)], key=keyfn, reverse=True)
    top = sorted_issues[:6] if mode != "summary" else sorted_issues[:3]
    if mode == "prompts":
        top = sorted_issues[:10]
    if mode == "prompts_top":
        top = sorted_issues[:6]

    if not top:
        lines.append("\n✅ No issues detected by QA heuristics.")
        return "\n".join(lines).strip()

    if mode in {"prompts", "prompts_top"}:
        # For prompts_top we prefer: critical issues + top fix (single most important).
        picks: list[dict[str, Any]] = []
        if mode == "prompts_top":
            crits = [i for i in sorted_issues if str(i.get("severity") or "").lower() == "critical"]
            picks.extend(crits[:3])
            if sorted_issues:
                picks.append(sorted_issues[0])
            # de-dupe
            seenp: set[str] = set()
            uniq: list[dict[str, Any]] = []
            for it in picks:
                fp = str(it.get("fingerprint") or "") or _issue_fingerprint("prompts_top", str(it.get("endpoint_or_route") or ""), str(it.get("title") or ""), str(it.get("message") or ""))
                if fp in seenp:
                    continue
                seenp.add(fp)
                uniq.append(it)
            picks = uniq[:3]
        else:
            picks = top

        lines.append("\n<b>🔧 Fix Prompts (Cursor-ready)</b>")
        for idx, it in enumerate(picks, start=1):
            ttl = str(it.get("title") or it.get("message") or "").strip()
            prompt = str(it.get("cursor_fix_prompt") or "").strip()
            if not prompt:
                continue
            lines.append(f"\n{idx}. <b>{escape(ttl[:90])}</b>")
            lines.append(f"<code>{escape(prompt[:520])}</code>")
        return "\n".join(lines).strip()

    kind0 = str(rep.get("kind") or "").strip().lower()

    # Deep QA: add runtime + browser metrics (must be Playwright-backed)
    if kind0 == "deep_product":
        lines = []
        lines.append(f"<b>{escape(title)}</b>")
        if score is not None:
            lines.append(f"\nScore: <b>{escape(str(score))}</b>/100")
        if runtime_s is not None:
            lines.append(f"Runtime: <code>{escape(str(runtime_s))}s</code>")
        checks = rep.get("checks") if isinstance(rep.get("checks"), dict) else {}
        pv = checks.get("pages_visited")
        bc = checks.get("buttons_clicked")
        ss = checks.get("screenshots") if isinstance(checks.get("screenshots"), list) else []
        lines.append("")
        lines.append("<b>🧭 UI run</b>")
        lines.append(f"browser_used: <b>{escape(str(bool(checks.get('browser_used'))).lower())}</b>")
        lines.append(f"auth_used: <b>{escape(str(bool(checks.get('auth_used'))).lower())}</b>")
        fe = checks.get("frontend_reachable")
        if fe is not None:
            lines.append(f"frontend_reachable: <b>{escape(str(bool(fe)).lower())}</b>")
        ast = checks.get("auth_status")
        if ast:
            lines.append(f"auth_status: <b>{escape(str(ast))}</b>")
        fft = checks.get("first_failed_test")
        if fft:
            lines.append(f"first_failed_test: <code>{escape(str(fft)[:200])}</code>")
        fs = checks.get("failed_selector")
        if fs:
            lines.append(f"failed_selector: <code>{escape(str(fs)[:200])}</code>")
        if pv is not None:
            lines.append(f"pages_visited: <b>{escape(str(pv))}</b>")
        if bc is not None:
            lines.append(f"buttons_clicked: <b>{escape(str(bc))}</b>")
        fr = checks.get("flow_report") if isinstance(checks.get("flow_report"), dict) else {}
        fsr = checks.get("flow_skip_reasons") if isinstance(checks.get("flow_skip_reasons"), dict) else {}
        if fr:
            lines.append("")
            lines.append("<b>Flow report</b>")
            for k in (
                "landing_flow",
                "discover_flow",
                "matches_flow",
                "chat_ai_flow",
                "profile_verification_flow",
                "premium_flow",
            ):
                if k in fr:
                    reason = str(fsr.get(k) or "").strip()
                    line = f"{escape(k)}: <b>{escape(str(fr[k]))}</b>"
                    if reason:
                        line += f" — <code>{escape(reason[:180])}</code>"
                    lines.append(line)
        if ss:
            lines.append("")
            lines.append("<b>📸 Screenshots (on failures)</b>")
            for p in ss[:8]:
                lines.append(f"• <code>{escape(str(p))}</code>")

        if sorted_issues:
            lines.append("")
            lines.append("<b>🧩 Top issues</b>")
            for it in sorted_issues[:6]:
                ttl2 = str(it.get("title") or it.get("message") or "").strip()
                msg2 = str(it.get("message") or "").strip()
                sev = str(it.get("severity") or "medium").lower()
                lines.append(f"\n<b>[{escape(sev.upper())}] {escape(ttl2[:90])}</b>")
                if msg2:
                    lines.append(escape(msg2[:400]))
        else:
            lines.append("\n✅ No UI flow failures detected by Deep QA.")
        return "\n".join(lines).strip()

    # Special compact layout for Quick Product report (API smoke)
    if kind0 in {"full_product", "quick_product"}:
        lines = []
        lines.append(f"<b>{escape(title)}</b>")
        if score is not None:
            lines.append(f"\nScore: <b>{escape(str(score))}</b>/100")
        if runtime_s is not None:
            lines.append(f"Runtime: <code>{escape(str(runtime_s))}s</code>")

        crit_items = [i for i in sorted_issues if str(i.get("severity") or "").lower() == "critical"][:3]
        imp_items = [i for i in sorted_issues if str(i.get("severity") or "").lower() in {"high", "medium"}][:5]

        def fmt_one(it: dict[str, Any]) -> str:
            ttl2 = str(it.get("title") or it.get("message") or "").strip()
            locs2 = it.get("probable_locations") if isinstance(it.get("probable_locations"), list) else []
            loc2 = str(locs2[0]) if locs2 else (str(it.get("endpoint_or_route") or "")[:120])
            steps2 = it.get("fix_steps") if isinstance(it.get("fix_steps"), list) else []
            fix2 = str(steps2[0]) if steps2 else ""
            out2 = f"- <b>{escape(ttl2[:120])}</b>\n  Location: <code>{escape(loc2[:140])}</code>"
            if fix2:
                out2 += f"\n  Fix: {escape(fix2[:180])}"
            return out2

        lines.append("\n<b>🔥 Critical (must fix now)</b>")
        if crit_items:
            for it in crit_items:
                lines.append(fmt_one(it))
        else:
            lines.append("- None")

        lines.append("\n<b>⚠️ Important</b>")
        if imp_items:
            for it in imp_items:
                lines.append(fmt_one(it))
        else:
            lines.append("- None")

        pi2 = rep.get("product_intelligence") if isinstance(rep.get("product_intelligence"), dict) else {}
        insights = pi2.get("product_insights") if isinstance(pi2.get("product_insights"), list) else []
        if insights:
            lines.append("\n<b>🧠 Product Insights</b>")
            for s in insights[:5]:
                lines.append(f"- {escape(str(s)[:190])}")
        qw2 = pi2.get("quick_wins") if isinstance(pi2.get("quick_wins"), list) else []
        if qw2:
            lines.append("\n<b>⚡ Quick Wins</b>")
            for s in qw2[:5]:
                if isinstance(s, dict) and s.get("title"):
                    lines.append(f"- {escape(str(s.get('title'))[:160])} ({escape(str(s.get('impact') or ''))}/{escape(str(s.get('effort') or ''))})")

        tpf2 = pi2.get("top_priority_fix") if isinstance(pi2.get("top_priority_fix"), dict) else {}
        if tpf2:
            ttl3 = str(tpf2.get("title") or tpf2.get("message") or "").strip()
            locs3 = tpf2.get("probable_locations") if isinstance(tpf2.get("probable_locations"), list) else []
            loc3 = str(locs3[0] if locs3 else "unknown_location")
            lines.append("\n<b>📍 Top Fix</b>")
            lines.append(f"- <b>{escape(ttl3[:140])}</b>")
            if loc3:
                lines.append(f"  Location: <code>{escape(loc3[:160])}</code>")

        return "\n".join(lines).strip()

    lines.append("\n<b>Top issues</b>")
    for idx, it in enumerate(top, start=1):
        sev = str(it.get("severity") or "").strip()
        ttl = str(it.get("title") or it.get("message") or "").strip()
        locs = it.get("probable_locations") if isinstance(it.get("probable_locations"), list) else []
        loc = str(locs[0] if locs else "unknown_location")
        lines.append(f"\n{idx}. <code>{sev}</code> {ttl}")
        if loc:
            lines.append(f"Location: <code>{loc}</code>")
        if mode in {"deep"}:
            cause = str(it.get("cause") or "").strip()
            if cause:
                lines.append(f"Cause: {cause}")
            msg = str(it.get("error_message") or "").strip()
            if msg and msg != ttl:
                lines.append(f"Error: <code>{msg[:220]}</code>")
        if mode in {"fixes", "deep"}:
            steps = it.get("fix_steps") if isinstance(it.get("fix_steps"), list) else []
            if steps:
                lines.append("Fix:")
                for s in steps[:6]:
                    lines.append(f"- {s}")
            prompt = str(it.get("cursor_fix_prompt") or "").strip()
            if prompt and mode == "deep":
                lines.append(f'Fix prompt for Cursor: <code>{prompt[:280]}</code>')

    # Product Intelligence (only in deep mode; summary gets quick wins line)
    pi = rep.get("product_intelligence") if isinstance(rep.get("product_intelligence"), dict) else {}
    quick = pi.get("quick_wins") if isinstance(pi.get("quick_wins"), list) else []
    if mode == "summary" and quick:
        lines.append("\n⚡ Quick wins")
        for s in quick[:5]:
            if isinstance(s, dict) and s.get("title"):
                lines.append(f"- {str(s.get('title'))}")

    if mode == "deep" and pi:
        lines.append("\n<b>🧠 Product Intelligence</b>")
        tpf = pi.get("top_priority_fix") if isinstance(pi.get("top_priority_fix"), dict) else {}
        if tpf:
            lines.append("\n<b>📍 Top Priority Fix</b>")
            ttl = str(tpf.get("title") or tpf.get("message") or "").strip()
            locs = tpf.get("probable_locations") if isinstance(tpf.get("probable_locations"), list) else []
            loc = str(locs[0] if locs else "unknown_location")
            lines.append(f"- <b>{escape(ttl[:140])}</b>")
            if loc:
                lines.append(f"  Location: <code>{escape(loc)}</code>")
        gaps = pi.get("engagement_gaps") if isinstance(pi.get("engagement_gaps"), list) else []
        if gaps:
            lines.append("\n<b>Engagement gaps</b>")
            for g in gaps[:4]:
                if isinstance(g, str):
                    lines.append(f"- {escape(g[:180])}")
        qw = pi.get("quick_wins") if isinstance(pi.get("quick_wins"), list) else []
        if qw:
            lines.append("\n<b>⚡ Quick wins (<1 day)</b>")
            for s in qw[:6]:
                if not isinstance(s, dict):
                    continue
                lines.append(f"- <b>{escape(str(s.get('title') or ''))}</b> ({escape(str(s.get('impact') or ''))} impact / {escape(str(s.get('effort') or ''))} effort)")
        bench = pi.get("benchmark_insights") if isinstance(pi.get("benchmark_insights"), list) else []
        if bench:
            lines.append("\n<b>🔥 Benchmark insights</b>")
            for b in bench[:3]:
                if not isinstance(b, dict):
                    continue
                lines.append(f"- {escape(str(b.get('title') or ''))}")

    return "\n".join(lines).strip()


def _fetch_html(url: str, *, timeout_s: float = 18.0) -> tuple[int | None, str, dict[str, Any]]:
    try:
        # Don't follow redirects: redirect-to-login is not a "screen crash".
        res = requests.get(url, timeout=timeout_s, headers={"User-Agent": "neyra-qa-engineer/1.0"}, allow_redirects=False)
        details: dict[str, Any] = {"headers": dict(res.headers), "final_url": str(res.url)}
        return int(res.status_code), str(res.text or ""), details
    except Exception:
        return None, "", {}


def _english_ux_qa(db: Session) -> dict[str, Any]:
    started = time.time()
    issues: list[_Issue] = []
    # Never throw for missing optional keys; the runner wraps failures defensively.
    # NOTE: We intentionally do NOT treat frontend page fetches as a primary health signal.
    # Protected pages often redirect to /login without a session, which is healthy behavior.
    # Instead we validate core product health via authenticated API checks.

    def fetch_api(path: str, *, token: str | None) -> tuple[int | None, str, Any]:
        base_api = str(getattr(settings, "PUBLIC_BACKEND_URL", "") or "http://localhost:8000").rstrip("/")
        url = f"{base_api}{path}"
        headers = {"User-Agent": "neyra-qa-engineer/1.0"}
        auth_used = False
        if token:
            headers["Authorization"] = f"Bearer {token}"
            auth_used = True
        try:
            res = requests.get(url, timeout=18.0, headers=headers, allow_redirects=False)
            text = str(res.text or "")
            try:
                data = res.json()
            except Exception:
                data = None
            return int(res.status_code), ("auth_used=true" if auth_used else "auth_used=false") + " " + text[:400], data
        except Exception as e:
            return None, f"exception={type(e).__name__}", None

    # Ensure QA demo seed exists (demo-only safety) and mint a QA token.
    pair = _ensure_qa_demo_seed(db)
    qa_token = create_access_token(str(pair[0])) if pair else None

    api_checks: list[tuple[str, bool]] = [
        ("/health/ready", False),
        ("/api/v1/auth/me", True),
        ("/api/v1/discover/feed", True),
        ("/api/v1/matches", True),
        ("/api/v1/messages/conversations", True),
    ]

    checks_out: list[dict[str, Any]] = []
    for path, needs_auth in api_checks:
        st, snippet, data = fetch_api(path, token=qa_token if needs_auth else None)
        auth_used = bool(needs_auth and qa_token)
        checks_out.append(
            {
                "endpoint": path,
                "status": st,
                "auth_used": auth_used,
                "error_snippet": snippet[:240],
            }
        )
        # classify outcomes
        if st is None:
            it = _Issue(
                severity="critical",
                impact="crash",
                category="api_error",
                title=f"API check failed (exception): {path}",
                message="Exception while requesting endpoint.",
                endpoint_or_route=path,
                status=None,
                error_message=snippet[:800],
                probable_locations=_probable_locations(path, snippet),
                cause="Backend not reachable or request handler crashed before response.",
                fix_steps=["Check backend container logs.", "Verify server is up and PUBLIC_BACKEND_URL is correct."],
                cursor_fix_prompt=f"Fix API exception for {path} by reproducing request and resolving the server-side error.",
            )
            it.fingerprint = _issue_fingerprint("api_health", path, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            issues.append(it)
            continue

        if st >= 500:
            it = _Issue(
                severity="critical",
                impact="crash",
                category="api_error",
                title=f"API 5xx: {path}",
                message=f"Endpoint returned {st}.",
                endpoint_or_route=path,
                status=st,
                error_message=snippet[:800],
                probable_locations=_probable_locations(path, snippet),
                cause="Backend endpoint crashed or misconfigured.",
                fix_steps=["Open server logs for stack trace.", "Fix exception and add regression test."],
                cursor_fix_prompt=f"Fix {path} returning {st} by tracing the exception in the endpoint and adding safe guards.",
            )
            it.fingerprint = _issue_fingerprint("api_health", path, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            issues.append(it)
            continue

        if needs_auth and st in {401, 403}:
            it = _Issue(
                severity="low",
                impact="ux",
                category="ui_ux",
                title=f"QA setup warning: auth failed for {path}",
                message=f"Endpoint requires auth; QA token missing/invalid (status={st}).",
                endpoint_or_route=path,
                status=st,
                error_message=snippet[:800],
                probable_locations=["backend/app/api/deps.py", "backend/app/api/v1/endpoints/auth.py"],
                cause="QA demo token not created or auth middleware rejected it.",
                fix_steps=["Ensure QA demo user seed runs and token is minted.", "Verify SECRET_KEY consistency across containers."],
                cursor_fix_prompt=f"Fix QA auth for {path}: ensure QA demo seed + create_access_token works and Authorization header is accepted.",
            )
            it.fingerprint = _issue_fingerprint("qa_setup", path, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            issues.append(it)
            continue

        # Basic schema sanity where it matters
        if path.endswith("/discover/feed") and st < 400 and not (isinstance(data, list) or data is None):
            it = _Issue(
                severity="high",
                impact="conversion",
                category="data_inconsistency",
                title="Invalid schema: discover feed is not a list",
                message=f"/discover/feed returned {type(data).__name__}, expected list.",
                endpoint_or_route=path,
                status=st,
                error_message=snippet[:800],
                probable_locations=["backend/app/api/v1/endpoints/discover.py", "backend/app/services/discover/"],
                cause="Endpoint response shape changed or error wrapper leaked into 200 response.",
                fix_steps=["Return a list consistently or raise proper HTTP error.", "Add contract test."],
                cursor_fix_prompt="Fix /api/v1/discover/feed contract: ensure success response is a JSON list of cards.",
            )
            it.fingerprint = _issue_fingerprint("api_schema", path, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            issues.append(it)

        # Product Intelligence inputs: keep minimal (do not fail score if protected).
        routes = ["/onboarding", "/discover", "/matches", "/chat", "/profile", "/subscription"]
        base = str(getattr(settings, "FRONTEND_URL", "") or "http://localhost:3000").rstrip("/")
        screens: list[dict[str, Any]] = []
        screen_html: dict[str, str] = {}
        for route in routes:
            screen = {
                "route": route,
                "ok": True,
                "status": 200,
                "error": None,
                "auth_used": False,
            }
            try:
                url = f"{base}{route}"
                st, html, _details = _fetch_html(url)
                screen["status"] = st
                # informational only: treat only 5xx / no-status as not-ok
                screen["ok"] = bool(st is not None and int(st) < 500)
                if not screen["ok"]:
                    err_msg, _stack = _extract_error_details(html)
                    screen["error"] = (err_msg or "")[:240] or None
                screen_html[route] = html or ""
            except Exception as e:
                screen["ok"] = False
                screen["status"] = None
                screen["error"] = f"{type(e).__name__}: {e}"[:240]
                screen_html[route] = ""
            screens.append(screen)

    # Product UX Intelligence (heuristic, Tinder/Bumble/Hinge-style)
    screen_map: dict[str, str] = {
        "/onboarding": "onboarding",
        "/discover": "discover",
        "/matches": "matches",
        "/chat": "chat",
        "/profile": "profile",
        "/subscription": "premium",
    }
    screen_evals: list[dict[str, Any]] = []
    all_suggestions: list[dict[str, Any]] = []
    for path, screen in screen_map.items():
        ev = _ux_screen_eval(screen, screen_html.get(path, ""))
        screen_evals.append(ev)
        for s in ev.get("product_suggestions") or []:
            if isinstance(s, dict):
                all_suggestions.append({**s, "screen": screen})

    impact_rank = {"high": 3, "medium": 2, "low": 1}
    effort_rank = {"low": 3, "medium": 2, "high": 1}
    all_suggestions.sort(
        key=lambda s: (impact_rank.get(str(s.get("impact")), 1), effort_rank.get(str(s.get("effort")), 1)),
        reverse=True,
    )
    quick_wins = [s for s in all_suggestions if bool(s.get("quick_win"))][:10]

    ux_issues: list[str] = []
    conversion_blockers: list[str] = []
    engagement_gaps: list[str] = []
    for ev in screen_evals:
        m = ev.get("metrics") if isinstance(ev.get("metrics"), dict) else {}
        sc = str(ev.get("screen") or "")
        clarity = int(m.get("clarity_0_5") or 0)
        conversion = int(m.get("conversion_0_5") or 0)
        emotion = int(m.get("emotion_0_5") or 0)
        ctas = int(m.get("primary_cta_count") or 0)
        if clarity <= 2:
            ux_issues.append(f"{sc}: clarity looks weak (primary CTA count={ctas}).")
        if conversion <= 2 or ctas == 0:
            conversion_blockers.append(f"{sc}: conversion loop not obvious (primary CTA missing or weak).")
        if emotion <= 2:
            engagement_gaps.append(f"{sc}: feels low-energy (empty/sparse UI risk) → add alive signals (activity, microcopy, skeletons).")

    product_intelligence = {
        "screens": screen_evals,
        "suggested_improvements": all_suggestions[:18],
        "ux_issues": ux_issues[:10],
        "conversion_blockers": conversion_blockers[:10],
        "engagement_gaps": engagement_gaps[:10],
        "quick_wins": quick_wins,
        "benchmark_insights": _benchmark_insights(),
    }

    # Repo static check: EN bundle should exist (any valid location) and not contain Cyrillic values.
    en_candidates = [
        _repo_root() / "frontend" / "public" / "locales" / "en.json",
        _repo_root() / "frontend" / "locales" / "en.json",
        _repo_root() / "frontend" / "messages" / "en.json",
    ]
    en_bundle = next((p for p in en_candidates if p.exists()), None)
    if en_bundle is not None and en_bundle.exists():
        try:
            txt = en_bundle.read_text(encoding="utf-8")
            if _CYRILLIC_RE.search(txt):
                locs = [str(en_bundle).replace(str(_repo_root()) + os.sep, "").replace("\\", "/")]
                it = _Issue(
                    severity="medium",
                    impact="localization",
                    category="localization",
                    title="Cyrillic characters found in en.json",
                    message="Cyrillic characters found in en.json.",
                    endpoint_or_route=locs[0] if locs else "en.json",
                    probable_locations=locs,
                    cause="Accidental copy-paste from UA/RU into EN bundle.",
                    fix_steps=[f"Remove Cyrillic values from `{locs[0] if locs else 'en.json'}` and rerun `npm run check-i18n`."],
                    cursor_fix_prompt="Audit en.json for accidental Cyrillic strings and replace with English copy.",
                )
                it.fingerprint = _issue_fingerprint("english_ux", it.endpoint_or_route, it.title, it.message)
                it.priority_score = _priority_score(it.severity, it.impact)
                issues.append(it)
        except Exception:
            it = _Issue(
                severity="low",
                impact="data",
                category="data_inconsistency",
                title="Failed reading en.json",
                message="Failed reading en.json from known locale locations.",
                endpoint_or_route=str(en_bundle),
                probable_locations=[str(en_bundle)],
                cause="File missing/corrupted or permissions issue.",
                fix_steps=["Verify the file exists and is readable; restore from git if needed."],
                cursor_fix_prompt="Fix locale bundle loading by ensuring en.json exists and is valid JSON.",
            )
            it.fingerprint = _issue_fingerprint("english_ux", it.endpoint_or_route, it.title, it.message)
            it.priority_score = _priority_score(it.severity, it.impact)
            issues.append(it)
    else:
        it = _Issue(
            severity="low",
            impact="localization",
            category="localization",
            title="Missing en.json",
            message="Missing en.json in any of the known locale locations.",
            endpoint_or_route="frontend/(public/locales|locales|messages)/en.json",
            probable_locations=[
                "frontend/public/locales/en.json",
                "frontend/locales/en.json",
                "frontend/messages/en.json",
            ],
            cause="Locale bundles missing from build inputs.",
            fix_steps=[
                "Ensure `frontend/public/locales/en.json` exists and is included in deploy image.",
                "Alternatively ensure `frontend/locales/en.json` exists (used as build-time English base).",
            ],
            cursor_fix_prompt="Restore missing en.json locale bundle and rerun i18n validation.",
        )
        it.fingerprint = _issue_fingerprint("english_ux", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        issues.append(it)

    # Chat / Matches: checklist-only but developer-ready (now with locations + fix hints).
    for area, route, title, fix in [
        (
            "chat_ux",
            "/chat/40",
            "Chat UX checklist (single AI panel, no AI in history, no duplicate suggestions)",
            [
                "Verify only one AI panel exists near composer.",
                "Ensure `ChatMessageList` filters assistant/aiGenerated/demo messages.",
                "Ensure suggestions only insert into composer (no auto-send).",
            ],
        ),
        (
            "matches_ux",
            "/matches",
            "Matches UX checklist (Your matches + People who liked you, clear CTAs, no empty cards)",
            [
                "Verify `frontend/app/matches/page.tsx` shows clear sections.",
                "Verify likes preview is limited and not fully blurred (embedded mode).",
                "Verify CTAs open chat and focus composer.",
            ],
        ),
    ]:
        locs = _probable_locations(route, title)
        it = _Issue(
            severity="low",
            impact="conversion",
            category="ui_ux",
            title=title,
            message="Manual validation required (automation planned).",
            endpoint_or_route=route,
            probable_locations=locs,
            cause="Not yet automated (Playwright not integrated).",
            fix_steps=fix,
            cursor_fix_prompt=f"Implement automated UI QA for {route} using Playwright to validate the checklist.",
        )
        it.fingerprint = _issue_fingerprint("english_ux", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        issues.append(it)

    # Recurrence learning: mark recurring if seen in previous report.
    prev = load_latest_report() or {}
    prev_rep = prev.get("report") if isinstance(prev.get("report"), dict) else {}
    prev_issues = prev_rep.get("issues") if isinstance(prev_rep.get("issues"), list) else []
    prev_fps = {str(i.get("fingerprint")) for i in prev_issues if isinstance(i, dict) and i.get("fingerprint")}
    for it in issues:
        if it.fingerprint and it.fingerprint in prev_fps:
            it.recurring = True

    # Sort by priority
    issues.sort(key=lambda x: int(x.priority_score or 0), reverse=True)

    score = _score_from_issues(issues)
    runtime_s = round(time.time() - started, 2)
    top5 = [_to_public_issue_dict(i) for i in issues[:5]]
    report: QaReport = {
        "title": "🇺🇸 English UX QA Report",
        "kind": "english_ux",
        "score": score,
        "runtime_s": runtime_s,
        "checks": {"screens": screens, "api_checks": checks_out},
        "product_intelligence": product_intelligence,
        "sections": {
            "Runtime": {
                "screens_checked": len(routes),
                "failures": [s for s in screens if not s.get("ok", False)],
            },
            "English Copy": {"notes": "Backend-first QA: API health drives score. UI pages are informational only."},
        },
        "top_issues": top5,
        "issues": [_to_public_issue_dict(i) for i in issues],
        "suggested_fixes": [s for i in issues[:10] for s in (i.fix_steps or [])[:2]],
    }
    return report  # type: ignore[return-value]


def _localization_qa(db: Session) -> dict[str, Any]:
    started = time.time()
    issues: list[_Issue] = []

    rep = None
    try:
        rep = load_localization_report()
    except Exception:
        rep = None

    if not rep:
        it = _Issue(
            severity="medium",
            impact="localization",
            category="localization",
            title="No localization report found",
            message="No localization report found. Run localization agent first.",
            endpoint_or_route="reports/localization_report.json",
            probable_locations=["backend/app/services/localization/report.py", "reports/localization_report.json"],
            cause="Localization agent has not produced a report yet (or path differs).",
            fix_steps=["Run localization agent to generate `reports/localization_report.json`.", "Then rerun 🌍 Localization QA."],
            cursor_fix_prompt="Generate localization_report.json via localization agent, then run localization QA to validate all locales.",
        )
        it.fingerprint = _issue_fingerprint("localization", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        issues.append(it)
        score = _score_from_issues(issues)
        return {
            "title": "🌍 Localization QA Report",
            "kind": "localization",
            "score": score,
            "runtime_s": round(time.time() - started, 2),
            "summary": {"total_locales_tested": 0, "locales_passed": 0, "locales_failed": 0},
            "issues": [_to_public_issue_dict(i) for i in issues],
        }

    # Best-effort summary over the existing report shape.
    locales = rep.get("locales") if isinstance(rep.get("locales"), list) else []
    total = len(locales)
    failed = 0
    missing_keys_total = int(rep.get("missing_keys_total") or rep.get("missing_keys") or 0) if isinstance(rep, dict) else 0
    english_fallback_total = int(rep.get("english_fallback_total") or 0) if isinstance(rep, dict) else 0
    mixed_language_total = int(rep.get("mixed_language_total") or 0) if isinstance(rep, dict) else 0
    for row in locales:
        if not isinstance(row, dict):
            continue
        st = str(row.get("status") or "").strip().lower()
        if st in {"fail", "failed", "error"}:
            failed += 1
    passed = max(0, total - failed)

    if missing_keys_total > 0:
        it = _Issue(
            severity="critical",
            impact="localization",
            category="localization",
            title="Missing translation keys",
            message=f"Missing translation keys detected: {missing_keys_total}",
            endpoint_or_route="reports/localization_report.json",
            probable_locations=["frontend/public/locales/*.json", "frontend/scripts/check-i18n.mjs", "backend/app/services/localization/"],
            cause="Locale bundles out of parity with en.json.",
            fix_steps=["Run `npm run check-i18n` to identify missing keys.", "Generate/fill missing keys across locales; rerun localization QA."],
            cursor_fix_prompt="Fix missing i18n keys by syncing locale bundles to en.json and rerun localization QA.",
        )
        it.fingerprint = _issue_fingerprint("localization", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        issues.append(it)
    if english_fallback_total > 0:
        it = _Issue(
            severity="high",
            impact="localization",
            category="localization",
            title="English fallback strings in non-EN locales",
            message=f"English fallback strings detected: {english_fallback_total}",
            endpoint_or_route="reports/localization_report.json",
            probable_locations=["frontend/public/locales/*.json"],
            cause="Locales still contain English mirror strings after localization (or intentionally allowed tokens exceeded).",
            fix_steps=["Fill localized values for the failing locales.", "Allow only tokens: NEYRA, AI, Premium, URLs, brand names."],
            cursor_fix_prompt="Reduce English fallback in non-EN locales by localizing mirrored strings and enforcing allowed tokens only.",
        )
        it.fingerprint = _issue_fingerprint("localization", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        issues.append(it)
    if mixed_language_total > 0:
        it = _Issue(
            severity="critical",
            impact="localization",
            category="localization",
            title="Mixed-language strings",
            message=f"Mixed-language strings detected: {mixed_language_total}",
            endpoint_or_route="reports/localization_report.json",
            probable_locations=["frontend/lib/i18n/", "frontend/lib/chat/aiLanguageTone.ts", "backend/app/services/ai/"],
            cause="Locale selection or AI language lock is inconsistent; multiple scripts in same string.",
            fix_steps=["Fix UI locale resolution (ensure request locale wins).", "Enforce AI language lock per request; rerun localization QA."],
            cursor_fix_prompt="Fix mixed-language output by enforcing UI locale as the single source of truth across UI and AI suggestions.",
        )
        it.fingerprint = _issue_fingerprint("localization", it.endpoint_or_route, it.title, it.message)
        it.priority_score = _priority_score(it.severity, it.impact)
        issues.append(it)

    issues.sort(key=lambda x: int(x.priority_score or 0), reverse=True)
    score = _score_from_issues(issues)
    return {
        "title": "🌍 Localization QA Report",
        "kind": "localization",
        "score": score,
        "runtime_s": round(time.time() - started, 2),
        "summary": {
            "total_locales_tested": total,
            "locales_passed": passed,
            "locales_failed": failed,
            "missing_keys": missing_keys_total,
            "english_fallback_count": english_fallback_total,
            "mixed_language_count": mixed_language_total,
        },
        "issues": [_to_public_issue_dict(i) for i in issues],
        "raw_report_hint": "Loaded from reports/localization_report.json (via localization.report.load_localization_report).",
    }


def run_qa(db: Session, *, kind: QaKind) -> dict[str, Any]:
    if not _enabled():
        return {"ok": False, "error": "QA_AGENT_DISABLED", "detail": "Set QA_AGENT_ENABLED=true to run QA Agent."}

    env = str(getattr(settings, "ENV", "") or "development").strip().lower()
    demo_only = _demo_only()

    started_at = datetime.now(UTC).isoformat()
    try:
        out: dict[str, Any]
        # Back-compat: "full_product" now means quick smoke QA.
        if kind == "full_product":
            out = _full_product_qa(db)
        elif kind == "quick_product":
            out = _full_product_qa(db)
        elif kind == "deep_product":
            out = _deep_product_qa(db)
        elif kind == "english_ux":
            out = _english_ux_qa(db)
        elif kind == "localization":
            out = _localization_qa(db)
        else:
            # Placeholders for future expansion (Chat QA, Menu QA, Bot-to-bot QA).
            out = {
                "title": "🧪 QA Agent Report",
                "kind": kind,
                "score": 0,
                "runtime_s": 0.0,
                "issues": [
                    {
                        "severity": "warning",
                        "area": "not_implemented",
                        "message": f"QA kind '{kind}' not implemented yet in backend agent.",
                        "suggested_fix": "Implement Playwright-based UI tests and demo-only synthetic flows.",
                    }
                ],
            }
    except Exception as e:
        out = {
            "title": "🧪 QA Agent Report",
            "kind": kind,
            "score": 50,
            "runtime_s": 0.0,
            "issues": [
                {
                    "severity": "low",
                    "impact": "ux",
                    "category": "ui_ux",
                    "title": "QA agent failure (runner)",
                    "message": "QA agent crashed while running. This is a QA checker bug, not an app failure.",
                    "endpoint_or_route": "qa_agent:run_qa",
                    "error_message": f"{type(e).__name__}: {e}",
                    "probable_locations": ["backend/app/services/qa/qa_agent.py"],
                    "fix_steps": ["Fix QA agent exception and rerun QA."],
                }
            ],
            "summary": {"note": "QA agent failure, not app failure"},
        }

    payload = {
        "ok": True,
        "started_at": started_at,
        "env": env,
        "demo_only": demo_only,
        "report": out,
    }
    save_latest_report(payload)
    return payload

