"""
Living demo mode: delayed, probabilistic demo user messages (chat-brain powered).
Does not run for real users. Never sends from real accounts.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.user import User
from app.services.ai.orchestrator import AIOrchestrator
from app.services.analytics import track_event
from app.services.app_language import normalize_app_language, resolve_recipient_language
from app.services.demo_bot_script import demo_outbound_step, scripted_demo_message
from app.services.demo_message_templates import get_demo_template_message
from app.services.demo_mode import (
    ensure_demo_personality_json,
    get_demo_live_settings,
    is_demo_live_enabled,
    is_demo_user_id,
    set_demo_last_error,
)
from app.services.chat_manager import schedule_ws_send_to_user
from app.services.events import publish_event
from app.services.match_partner import users_are_matched
from app.services.safety import is_blocked
from app.utils.media_urls import normalize_media_url

try:
    from app.services.ai.cache import get_redis
except Exception:  # pragma: no cover
    get_redis = None  # type: ignore[misc, assignment]

log = logging.getLogger("neyra.demo_behavior")


def _sanitize_demo_bot_reply_text(text: str) -> str:
    """Strip canned demo disclaimers from outbound lines — disclaimer belongs in profile/UI."""
    t = (text or "").strip()
    if not t:
        return ""
    noise = (
        "Demo profile — not a real person.",
        "AI demo profile — not a real person.",
        "demo profile — not a real person",
        "(demo simulation)",
        "— not a real person",
    )
    for n in noise:
        t = t.replace(n, "").strip()
    return t.strip()


def _demo_outbound_min_gap_seconds() -> float:
    return float(max(2, int(getattr(settings, "DEMO_BOT_OUTBOUND_MIN_INTERVAL_SECONDS", 4) or 4)))


def _throttle_or_defer_demo_outbound(
    db: Session, profile: Profile, *, demo_uid: int, partner_id: int, mode: str, trigger_message_id: int | None
) -> bool:
    """If the same pair just received a bot line, defer delivery slightly (prevents double-fire)."""
    if get_redis is None:
        return True
    try:
        r = get_redis()
        key = f"demo:bot:ts:{int(demo_uid)}:{int(partner_id)}"
        now = time.time()
        gap = _demo_outbound_min_gap_seconds()
        raw = r.get(key)
        if raw:
            try:
                if now - float(raw) < gap:
                    defer = min(5.0, max(1.5, gap - (now - float(raw))))
                    _set_pending(profile, int(partner_id), str(mode), _utcnow() + timedelta(seconds=defer), trigger_message_id=trigger_message_id)
                    db.add(profile)
                    db.commit()
                    return False
            except Exception:
                pass
        r.setex(key, 180, str(now))
        return True
    except Exception:
        return True


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware_utc(dt: datetime) -> datetime:
    """SQLite may return naive datetimes; normalize for comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


_FIRST_HOOK_SECONDS = 10 * 60


def _real_user_in_first_hook_window(db: Session, real_user_id: int) -> bool:
    u = db.query(User).filter(User.id == int(real_user_id)).first()
    if not u:
        return False
    c = getattr(u, "created_at", None)
    if not c:
        return False
    if c.tzinfo is None:
        c = c.replace(tzinfo=UTC)
    return (_utcnow() - c).total_seconds() <= _FIRST_HOOK_SECONDS


def schedule_demo_activity() -> None:
    """Alias for a single scheduler tick (background worker calls `run_demo_behavior_tick`)."""
    run_demo_behavior_tick()


def _engine_personality(pers: dict[str, Any]) -> str:
    """Map bot profile labels to chat-brain / template styling tags."""
    raw = str(pers.get("style") or pers.get("personality") or "warm").strip().lower()
    alias = {
        "playful": "flirty",
        "flirty": "flirty",
        "warm": "curious",
        "calm": "curious",
        "deep": "curious",
        "curious": "curious",
        "sarcastic": "dry",
        "dry": "dry",
        "cold": "dry",
        "confident": "flirty",
    }
    v = alias.get(raw, raw)
    return v if v in ("flirty", "dry", "curious", "cold") else "curious"


def _load_personality(profile: Profile) -> dict[str, Any]:
    try:
        d = json.loads(profile.demo_personality_json or "{}")
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("personality", "warm")
    d.setdefault("style", "warm")
    d.setdefault("response_speed", "normal")
    d.setdefault("reply_speed", str(d.get("response_speed") or "normal"))
    d.setdefault("engagement_level", 0.6)
    d.setdefault("humor_style", "warm")
    d.setdefault("humor", "light")
    d.setdefault("reply_delay_min", 5)
    d.setdefault("reply_delay_max", 25)
    d.setdefault("flirt_level", 1)
    d.setdefault("flirt_level_label", "low")
    if not d.get("interests") and isinstance(d.get("preferred_topics"), list):
        d["interests"] = list(d["preferred_topics"])
    if not isinstance(d.get("interests"), list):
        d["interests"] = ["coffee", "music"]
    st = str(d.get("style") or "").strip().lower()
    if st not in {"warm", "playful", "calm", "bold"}:
        d["style"] = "warm"
    hm = str(d.get("humor") or "").strip().lower()
    if hm not in {"light", "dry", "soft_tease"}:
        d["humor"] = "light"
    rs = str(d.get("reply_speed") or d.get("response_speed") or "normal").strip().lower()
    if rs not in {"fast", "normal", "slow"}:
        rs = "normal"
    d["reply_speed"] = rs
    d["response_speed"] = rs
    fl_raw = str(d.get("flirt_level_label") or "").strip().lower()
    if fl_raw not in {"low", "medium", "high"}:
        try:
            fv = int(d.get("flirt_level") or 1)
        except Exception:
            fv = 1
        fl_raw = "low" if fv <= 1 else "medium" if fv == 2 else "high"
    d["flirt_level_label"] = fl_raw
    return d


def _recent_demo_outbound_texts(db: Session, demo_uid: int, partner_id: int, limit: int = 10) -> list[str]:
    rows = (
        db.query(Message.content)
        .filter(
            Message.sender_id == int(demo_uid),
            Message.receiver_id == int(partner_id),
            Message.is_demo_simulation == True,  # noqa: E712
        )
        .order_by(Message.created_at.desc())
        .limit(int(limit))
        .all()
    )
    out: list[str] = []
    for (txt,) in rows:
        s = str(txt or "").strip().lower()
        if s:
            out.append(s)
    return out


def _line_too_similar(candidate: str, recent: list[str], *, ratio: float = 0.88) -> bool:
    c = (candidate or "").strip().lower()
    if len(c) < 12:
        return False
    for r in recent:
        if not r:
            continue
        if c == r or (len(r) > 15 and (c in r or r in c)):
            return True
        if len(c) > 24 and len(r) > 24 and SequenceMatcher(None, c, r).ratio() >= ratio:
            return True
    return False


def _real_match_partners(db: Session, demo_uid: int) -> list[int]:
    demo_uid = int(demo_uid)
    out: list[int] = []
    for m in db.query(Match).filter(or_(Match.user_a_id == demo_uid, Match.user_b_id == demo_uid)).all():
        other = int(m.user_b_id if m.user_a_id == demo_uid else m.user_a_id)
        u = db.query(User).filter(User.id == other).first()
        if u and not u.is_demo and not u.is_deleted and not u.is_banned:
            out.append(other)
    return out


def _compatibility_score(db: Session, demo_uid: int, real_uid: int) -> float:
    a = db.query(Profile).filter(Profile.user_id == int(demo_uid)).first()
    b = db.query(Profile).filter(Profile.user_id == int(real_uid)).first()
    if not a or not b:
        return 0.5
    ca = (a.city or "").strip().lower()
    cb = (b.city or "").strip().lower()
    if ca and cb and ca == cb:
        return 0.82
    if ca and cb and (ca in cb or cb in ca):
        return 0.72
    return 0.48


def _real_user_has_active_real_chat(db: Session, real_uid: int) -> bool:
    """
    Stop auto-demo when the user already engages in real (non-demo) conversations.
    """
    real_uid = int(real_uid)
    real_matches = db.query(Match).filter(or_(Match.user_a_id == real_uid, Match.user_b_id == real_uid)).all()
    for m in real_matches:
        other = int(m.user_b_id if int(m.user_a_id) == real_uid else m.user_a_id)
        ou = db.query(User).filter(User.id == other).first()
        if not ou or bool(getattr(ou, "is_demo", False)):
            continue
        has_msgs = (
            db.query(Message.id)
            .filter(
                or_(
                    and_(Message.sender_id == real_uid, Message.receiver_id == other),
                    and_(Message.sender_id == other, Message.receiver_id == real_uid),
                )
            )
            .first()
        )
        if has_msgs:
            return True
    return False


def _waiting_for_user_response(db: Session, demo_uid: int, real_uid: int) -> bool:
    last = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == int(demo_uid), Message.receiver_id == int(real_uid)),
                and_(Message.sender_id == int(real_uid), Message.receiver_id == int(demo_uid)),
            )
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if not last:
        return False
    return int(getattr(last, "sender_id", 0) or 0) == int(demo_uid)


def _real_user_onboarding_completed(db: Session, real_uid: int) -> bool:
    p = db.query(Profile).filter(Profile.user_id == int(real_uid)).first()
    return bool(p and getattr(p, "onboarding_completed", False))


def _pair_auto_demo_allowed(db: Session, demo_uid: int, real_uid: int) -> bool:
    if not _real_user_onboarding_completed(db, int(real_uid)):
        return False
    if not users_are_matched(db, int(demo_uid), int(real_uid)):
        return False
    if is_blocked(db, int(demo_uid), int(real_uid)):
        return False
    # If the real user has passed/disliked this demo profile after scheduling, stop.
    latest_real_swipe = (
        db.query(Swipe)
        .filter(Swipe.swiper_id == int(real_uid), Swipe.target_user_id == int(demo_uid))
        .order_by(Swipe.created_at.desc())
        .first()
    )
    if latest_real_swipe is not None and not bool(getattr(latest_real_swipe, "liked", False)):
        return False
    return True


def _trailing_real_streak(db: Session, demo_uid: int, real_uid: int) -> int:
    rows = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == demo_uid, Message.receiver_id == real_uid),
                and_(Message.sender_id == real_uid, Message.receiver_id == demo_uid),
            )
        )
        .order_by(Message.created_at.desc())
        .limit(24)
        .all()
    )
    n = 0
    for m in rows:
        if int(m.sender_id) == int(real_uid):
            n += 1
        else:
            break
    return n


def _is_cold_personality(pers: dict[str, Any]) -> bool:
    raw = str(pers.get("personality") or "").strip().lower()
    if raw in {"cold", "sarcastic"}:
        return True
    return _engine_personality(pers) == "cold"


def _should_ignore(
    db: Session,
    demo_uid: int,
    real_uid: int,
    settings: dict[str, Any],
    pers: dict[str, Any],
) -> bool:
    base = float(settings.get("ignore_rate") or 0.3)
    streak = _trailing_real_streak(db, demo_uid, real_uid)
    if streak >= 2:
        base += 0.20
    comp = _compatibility_score(db, demo_uid, real_uid)
    if comp < 0.55:
        base += 0.20
    if _is_cold_personality(pers):
        base += 0.25
    base = max(0.05, min(0.95, base))
    base = min(base, 0.3)
    return random.random() < base


def _delay_seconds(response_speed: str, global_speed: str) -> int:
    rs = (response_speed or "normal").strip().lower()
    gs = (global_speed or "normal").strip().lower()
    eff = rs
    if gs == "fast" and rs == "slow":
        eff = "normal"
    elif gs == "slow" and rs == "fast":
        eff = "normal"
    elif gs == "fast":
        eff = "fast" if rs != "slow" else "normal"
    elif gs == "slow":
        eff = "slow" if rs != "fast" else "normal"
    if eff == "fast":
        return random.randint(5, 25)
    if eff == "slow":
        return random.randint(180, 900)
    return random.randint(12, 38)


def _set_pending(profile: Profile, partner_id: int, mode: str, when: datetime, trigger_message_id: int | None = None) -> None:
    profile.demo_pending_json = json.dumps(
        {
            "partner_user_id": int(partner_id),
            "mode": str(mode),
            "planned_at": when.isoformat(),
            "trigger_message_id": int(trigger_message_id) if trigger_message_id is not None else None,
        }
    )
    profile.demo_reply_scheduled_at = when


def _clear_pending(profile: Profile) -> None:
    profile.demo_pending_json = "{}"
    profile.demo_reply_scheduled_at = None


def _pick_single_variant(result: dict[str, Any], personality: str, lang: str = "en") -> str:
    variants = result.get("variants") or {}
    rec = result.get("recommended_variant")
    line = ""
    if rec and variants.get(rec):
        line = str(variants[rec]).strip()
    if not line:
        order = {
            "flirty": ["flirty", "light", "deep"],
            "dry": ["light", "deep", "flirty"],
            "curious": ["deep", "light", "flirty"],
            "cold": ["light", "flirty", "deep"],
        }.get(personality, ["light", "flirty", "deep"])
        for k in order:
            v = str(variants.get(k) or "").strip()
            if v:
                line = v
                break
    if not line:
        for k in ("light", "flirty", "deep"):
            v = str(variants.get(k) or "").strip()
            if v:
                line = v
                break
    return _style_line(line, personality, None, lang)


def _style_line(line: str, personality: str, gender: str | None = None, lang: str = "en", *, demo_human: bool = False) -> str:
    line = (line or "").strip()
    if not line:
        return ""
    g = (gender or "").strip().lower()
    max_len = 220 if demo_human else 500
    if personality == "dry" and g in ("man", "male") and not demo_human:
        max_len = 220
    if personality == "dry" and len(line) > 118 and not demo_human:
        line = line[:115].rsplit(" ", 1)[0] + "…"
    if demo_human and len(line) > 215:
        line = line[:212].rsplit(" ", 1)[0] + "…"
    if personality == "flirty" and not any(x in line for x in ("😊", "😉", "✨")):
        line = line.rstrip(".!") + " 😊"
    if personality == "curious" and "?" not in line and "？" not in line:
        code = normalize_app_language(lang)
        if code == "uk":
            line = line.rstrip(".!") + " А ти?"
        elif code == "en":
            line = line.rstrip(".!") + " And you?"
        else:
            line = line.rstrip(".!") + "?"
    return line[:max_len]


def _append_human_followup_if_needed(text: str, lang: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if "?" in t or "？" in t:
        return t
    code = normalize_app_language(lang)
    if code == "uk":
        return t.rstrip(".!") + " А в тебе як із цим?"
    if code == "ru":
        return t.rstrip(".!") + " А у тебя как с этим?"
    return t.rstrip(".!") + " How about you?"


def _is_generic_first_line(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    bad_exact = {
        "hi",
        "hello",
        "hello!",
        "hello :)",
        "hello 🙂",
        "how are you",
        "tell me more about yourself",
        "as an ai",
    }
    if t in bad_exact:
        return True
    return t.startswith("hey, how are")


def _contextual_first_hook(demo_profile: Profile | None, partner_profile: Profile | None, lang: str) -> str:
    d_city = str(getattr(demo_profile, "city", "") or "").strip()
    p_city = str(getattr(partner_profile, "city", "") or "").strip()
    d_int = str(getattr(demo_profile, "interests", "") or "").strip()
    p_int = str(getattr(partner_profile, "interests", "") or "").strip()
    code = normalize_app_language(lang)
    if d_int and p_int:
        if code == "uk":
            return "Бачу, у нас є перетин по інтересах 🙂 Ти більше за спонтанні плани чи любиш усе продумати?"
        if code == "ru":
            return "Похоже, у нас пересекаются интересы 🙂 Ты больше за спонтанность или любишь всё планировать?"
        return "Looks like we have overlap in interests 🙂 Are you more into spontaneous plans or planning ahead?"
    if d_city and p_city and d_city.lower() == p_city.lower():
        if code == "uk":
            return f"Привіт 🙂 Класно бачити людину з {p_city}. У тебе є улюблене місце для кави там?"
        if code == "ru":
            return f"Привет 🙂 Классно видеть человека из {p_city}. Есть любимое место на кофе?"
        return f"Hey 🙂 Nice to see someone from {p_city}. Got a favorite coffee spot there?"
    if code == "uk":
        return "Твій профіль виглядає цікаво 🙂 Що тебе останнім часом реально заряджає?"
    if code == "ru":
        return "Твой профиль выглядит интересно 🙂 Что тебя в последнее время реально заряжает?"
    return "Your profile looks interesting 🙂 What's been energizing you lately?"


def _pick_example_line(pers: dict[str, Any], mode: str, lang: str) -> str:
    mode_l = (mode or "reply").strip().lower()
    key = {
        "opener": "opener_examples",
        "reply": "reply_examples",
        "revive": "revive_examples",
    }.get(mode_l, "reply_examples")
    ex = pers.get(key)
    code = normalize_app_language(lang)
    candidates: list[str] = []

    if isinstance(ex, dict):
        lines = ex.get(code)
        if lines is None and "-" in code:
            lines = ex.get(code.replace("-", ""))
        if not lines and code != "en":
            lines = ex.get("en")
        if isinstance(lines, list):
            candidates = [str(x).strip() for x in lines if str(x).strip()]
        elif isinstance(lines, str) and lines.strip():
            candidates = [lines.strip()]
    elif isinstance(ex, list):
        candidates = [str(x).strip() for x in ex if str(x).strip()]
    elif isinstance(ex, str) and ex.strip():
        candidates = [ex.strip()]

    if not candidates:
        return ""
    return random.choice(candidates)


def _demo_conversation_mode_for_turn(db: Session, demo_uid: int, partner_id: int) -> str:
    prior_demo = int(
        db.query(Message)
        .filter(Message.sender_id == int(demo_uid), Message.receiver_id == int(partner_id))
        .count()
    )
    cycle = ("easy", "playful", "deep", "confident", "flirty", "easy", "romantic")
    return cycle[min(max(prior_demo, 0), len(cycle) - 1)]


def _generate_demo_text(
    db: Session,
    demo_uid: int,
    partner_id: int,
    mode: str,
    personality: str,
    target_lang: str,
) -> str:
    """Demo text via orchestrator-backed chat-brain/opener pipeline."""
    lang = normalize_app_language(target_lang)
    demo_profile = db.query(Profile).filter(Profile.user_id == int(demo_uid)).first()
    partner_profile = db.query(Profile).filter(Profile.user_id == int(partner_id)).first()
    if not demo_profile or not partner_profile:
        return ""
    try:
        pers = _load_personality(demo_profile)
    except Exception:
        pers = {"style": "warm", "flirt_level_label": "low", "humor": "light"}
    stage_mode = "first_match" if str(mode).strip().lower() in {"first_match", "opener"} else "reply"
    try:
        result = AIOrchestrator.generate_demo_opener(
            db=db,
            demo_user_id=int(demo_uid),
            partner_user_id=int(partner_id),
            ui_locale=lang,
            style=str(pers.get("style") or "warm"),
            flirt_level=str(pers.get("flirt_level_label") or "low"),
            humor=str(pers.get("humor") or "light"),
            relationship_goal=str(getattr(partner_profile, "relationship_goal", "") or ""),
        )
    except Exception as e:
        log.warning("demo_orchestrator_open_error %s", e)
        result = ""
    text = str(result or "").strip()
    if not text:
        # Fallback to direct-answer pipeline for continuity in reply mode.
        if stage_mode != "first_match":
            try:
                text = (
                    AIOrchestrator.generate_demo_reply(
                        speaker_profile=demo_profile,
                        partner_profile=partner_profile,
                        user_message="",
                        ui_locale=lang,
                    )
                    or ""
                ).strip()
            except Exception:
                text = ""
    if not text:
        return ""
    return text.strip() if text.strip() else ""


def _display_name(db: Session, uid: int) -> str:
    p = db.query(Profile).filter(Profile.user_id == int(uid)).first()
    return str(getattr(p, "display_name", "") or "").strip() or "friend"


def _demo_message_ws_body(msg: Message) -> dict:
    demo_flag = bool(getattr(msg, "is_demo_simulation", False))
    return {
        "id": msg.id,
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "content": msg.content,
        "reply_to_message_id": getattr(msg, "reply_to_message_id", None),
        "voice_url": normalize_media_url(getattr(msg, "voice_url", None)),
        "voice_mime": getattr(msg, "voice_mime", None),
        "voice_duration_ms": getattr(msg, "voice_duration_ms", None),
        "is_demo_simulation": demo_flag,
        "is_demo": demo_flag,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "reactions": {},
        "my_reactions": [],
    }


def _deliver_pending(db: Session, profile: Profile, demo_user: User) -> None:
    db.refresh(profile)
    now = _utcnow()
    sched = profile.demo_reply_scheduled_at
    if sched is None or _aware_utc(sched) > now:
        return
    pending_raw = profile.demo_pending_json or "{}"
    try:
        pending = json.loads(pending_raw)
    except Exception:
        pending = {}
    partner_id = int(pending.get("partner_user_id") or 0)
    mode = str(pending.get("mode") or "reply").strip().lower()
    trigger_message_id = int(pending.get("trigger_message_id") or 0) or None
    if not partner_id or not _pair_auto_demo_allowed(db, int(demo_user.id), partner_id):
        _clear_pending(profile)
        db.add(profile)
        db.commit()
        return
    if bool(getattr(settings, "DEMO_PAUSE_AUTO_DEMO_IF_REAL_CHAT", False)) and _real_user_has_active_real_chat(db, int(partner_id)):
        _clear_pending(profile)
        db.add(profile)
        db.commit()
        return
    # Never send another auto-demo message while waiting for user response.
    if mode != "first_match" and _waiting_for_user_response(db, int(demo_user.id), int(partner_id)):
        _clear_pending(profile)
        db.add(profile)
        db.commit()
        return
    if not _throttle_or_defer_demo_outbound(
        db,
        profile,
        demo_uid=int(demo_user.id),
        partner_id=int(partner_id),
        mode=mode,
        trigger_message_id=trigger_message_id,
    ):
        return
    # If user already wrote before first opener fired, cancel scheduled opener.
    if mode == "first_match":
        user_already_sent = (
            db.query(Message.id)
            .filter(Message.sender_id == int(partner_id), Message.receiver_id == int(demo_user.id))
            .first()
            is not None
        )
        if user_already_sent:
            _clear_pending(profile)
            db.add(profile)
            db.commit()
            return
    pers = _load_personality(profile)
    personality = _engine_personality(pers)
    gender_pf = str(getattr(profile, "gender", "") or "").strip().lower()
    target_lang = resolve_recipient_language(db, partner_id)
    partner_profile = db.query(Profile).filter(Profile.user_id == int(partner_id)).first()
    pname = _display_name(db, partner_id)
    n_out = demo_outbound_step(db, int(demo_user.id), partner_id)
    recent_lines = _recent_demo_outbound_texts(db, int(demo_user.id), partner_id, limit=10)

    # Direct-question intent first, via AIOrchestrator pipeline.
    try:
        last_inbound = None
        if trigger_message_id:
            m = db.query(Message).filter(Message.id == int(trigger_message_id)).first()
            if m and int(getattr(m, "sender_id", 0) or 0) == int(partner_id):
                last_inbound = str(getattr(m, "content", "") or "").strip()
        if not last_inbound:
            m2 = (
                db.query(Message)
                .filter(Message.sender_id == int(partner_id), Message.receiver_id == int(demo_user.id))
                .order_by(Message.created_at.desc())
                .first()
            )
            last_inbound = str(getattr(m2, "content", "") or "").strip() if m2 else ""
        direct = AIOrchestrator.generate_demo_reply(
            speaker_profile=profile,
            partner_profile=partner_profile,
            user_message=last_inbound or "",
            ui_locale=target_lang,
        )
        if direct:
            content = _append_human_followup_if_needed(str(direct), target_lang)
            source = "direct_answer"
            # Skip the rest of generation logic and proceed to the shared styling + send path.
            goto_send = True
        else:
            goto_send = False
    except Exception:
        goto_send = False

    # Scripted arc is only for the first post-match opener-like nudge.
    # Replies should prefer example catalog / Chat Brain so language + tone adapt per recipient.
    if mode == "first_match":
        script_step = 0
    else:
        script_step = -1

    if not goto_send:
        content = ""
        source = "script"
    if not goto_send and 0 <= script_step <= 4:
        for attempt in range(3):
            candidate = scripted_demo_message(step=script_step, pers=pers, lang=target_lang, partner_name=pname)
            if candidate and not _line_too_similar(candidate, recent_lines):
                content = candidate
                break
        if not content:
            candidate = scripted_demo_message(step=script_step, pers=pers, lang=target_lang, partner_name=pname)
            content = candidate or ""

    if not goto_send and not (content or "").strip():
        source = "example"
        content = _pick_example_line(pers, mode, target_lang)
        if not content:
            content = _generate_demo_text(db, int(demo_user.id), partner_id, mode, personality, target_lang)
            source = "chat_brain"
        if not (content or "").strip():
            content = get_demo_template_message(mode, personality, target_lang, pname)
            source = "template"
    if not goto_send and content and _line_too_similar(content, recent_lines):
        alt = _generate_demo_text(db, int(demo_user.id), partner_id, mode, personality, target_lang)
        if (alt or "").strip() and not _line_too_similar(alt, recent_lines):
            content = alt
            source = "chat_brain"
    if source == "chat_brain":
        content = _style_line(content, personality, gender_pf, target_lang, demo_human=True)
    elif source == "script":
        content = _style_line(content, personality, gender_pf, target_lang, demo_human=True)
    else:
        # Example/template lines should still be human-styled (question mark, emoji, length).
        content = _style_line(content, personality, gender_pf, target_lang, demo_human=True)
    if mode in {"first_match", "opener"} and (_is_generic_first_line(content) or len((content or "").strip()) < 14):
        content = _contextual_first_hook(profile, partner_profile, target_lang)
        source = "context_fallback"
    content = _sanitize_demo_bot_reply_text(str(content or ""))[:4000]
    if not content.strip():
        _clear_pending(profile)
        db.add(profile)
        db.commit()
        return

    recent_dup = (
        db.query(Message)
        .filter(
            Message.sender_id == int(demo_user.id),
            Message.receiver_id == int(partner_id),
            Message.is_demo_simulation == True,  # noqa: E712
            Message.content == content[:4000],
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if trigger_message_id:
        linked_dup = (
            db.query(Message)
            .filter(
                Message.sender_id == int(demo_user.id),
                Message.receiver_id == int(partner_id),
                Message.is_demo_simulation == True,  # noqa: E712
                Message.reply_to_message_id == int(trigger_message_id),
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        if linked_dup:
            log.info("demo_bot_reply_skipped_duplicate demo=%s partner=%s trigger=%s", int(demo_user.id), int(partner_id), int(trigger_message_id))
            _clear_pending(profile)
            db.add(profile)
            db.commit()
            return
    if recent_dup and recent_dup.created_at:
        ra = recent_dup.created_at
        if ra.tzinfo is None:
            ra = ra.replace(tzinfo=UTC)
        if (now - ra).total_seconds() < 8:
            log.debug("demo_deliver_skip_duplicate demo=%s partner=%s", demo_user.id, partner_id)
            _clear_pending(profile)
            db.add(profile)
            db.commit()
            return

    msg = Message(
        sender_id=int(demo_user.id),
        receiver_id=int(partner_id),
        content=content[:4000],
        is_demo_simulation=True,
        reply_to_message_id=trigger_message_id,
    )
    db.add(msg)
    now_after_send = _utcnow()
    profile.demo_last_auto_message_at = now_after_send
    if mode in {"opener", "first_match"} and profile.demo_first_message_sent_at is None:
        profile.demo_first_message_sent_at = now_after_send
    _clear_pending(profile)
    db.add(profile)
    db.commit()
    db.refresh(msg)
    publish_event("message_sent", {"sender_id": int(demo_user.id), "receiver_id": int(partner_id), "message_id": int(msg.id)})
    payload = {
        "receiver_id": int(partner_id),
        "mode": mode,
        "personality": personality,
        "source": source,
        "language": target_lang,
    }
    if mode in {"opener", "first_match"}:
        track_event(db, "demo_first_message_sent", user_id=int(demo_user.id), payload=payload)
        log.info("demo_bot_first_message_created demo=%s partner=%s source=%s lang=%s", int(demo_user.id), int(partner_id), source, target_lang)
    elif mode == "revive":
        track_event(db, "demo_revive_sent", user_id=int(demo_user.id), payload=payload)
    else:
        track_event(db, "demo_reply_sent", user_id=int(demo_user.id), payload=payload)
        if source == "chat_brain":
            track_event(db, "bot_reply_sent", user_id=int(demo_user.id), payload={**payload, "channel": "demo_sim"})
        log.info("demo_bot_reply_created demo=%s partner=%s source=%s lang=%s", int(demo_user.id), int(partner_id), source, target_lang)
    schedule_ws_send_to_user(int(partner_id), {"type": "message", **_demo_message_ws_body(msg)})


def _process_due(db: Session) -> int:
    now = _utcnow()
    n = 0
    rows = (
        db.query(Profile, User)
        .join(User, User.id == Profile.user_id)
        .filter(
            User.is_demo == True,  # noqa: E712
            Profile.is_demo_profile == True,  # noqa: E712
            Profile.demo_reply_scheduled_at.isnot(None),
        )
        .all()
    )
    for profile, demo_user in rows:
        scheduled_at = _aware_utc(profile.demo_reply_scheduled_at)
        if scheduled_at is None:
            continue
        if scheduled_at > now:
            continue
        try:
            _deliver_pending(db, profile, demo_user)
            n += 1
        except Exception as e:
            log.warning("demo_deliver_failed uid=%s err=%s", demo_user.id, e)
            try:
                set_demo_last_error(db, f"deliver_failed uid={int(demo_user.id)} err={type(e).__name__}")
            except Exception:
                pass
            try:
                _clear_pending(profile)
                db.add(profile)
                db.commit()
            except Exception:
                db.rollback()
    return n


def note_real_user_message_to_demo(db: Session, demo_user_id: int, real_user_id: int, *, trigger_message_id: int | None = None) -> None:
    """Call when a real user sends a text/voice message to a demo profile (living mode)."""
    if not bool(getattr(settings, "DEMO_BOT_CHAT_ENABLED", True)):
        log.info("demo_bot_disabled action=reply_schedule")
        return
    demo_user_id = int(demo_user_id)
    real_user_id = int(real_user_id)
    if not _real_user_onboarding_completed(db, int(real_user_id)):
        return
    prof = db.query(Profile).filter(Profile.user_id == demo_user_id).first()
    demo_u = db.query(User).filter(User.id == demo_user_id).first()
    if not prof or not demo_u or not prof.is_demo_profile:
        return
    if bool(getattr(settings, "DEMO_PAUSE_AUTO_DEMO_IF_REAL_CHAT", False)) and _real_user_has_active_real_chat(db, int(real_user_id)):
        return
    ensure_demo_personality_json(prof)
    now = _utcnow()
    # Always reschedule so rapid messages collapse into one reply tied to the latest trigger id.
    pers = _load_personality(prof)
    rd_lo = int(pers.get("reply_delay_min", 5))
    rd_hi = int(pers.get("reply_delay_max", 25))
    rd_lo = max(3, min(60, rd_lo))
    rd_hi = max(rd_lo, min(120, rd_hi))
    forced_delay = int(getattr(settings, "DEMO_BOT_REPLY_DELAY_SECONDS", 0) or 0)
    # DEMO_BOT_REPLY_DELAY_SECONDS == 0 with live off => instant (tests). With live on, use human 5–25s
    # unless forcing instant via negative sentinel (tests only).
    instant_override = forced_delay < 0
    if is_demo_live_enabled(db) and not instant_override:
        # Human pacing: 5–25s (per profile), slower when thread has gone cold.
        last = (
            db.query(Message)
            .filter(
                or_(
                    and_(Message.sender_id == demo_user_id, Message.receiver_id == real_user_id),
                    and_(Message.sender_id == real_user_id, Message.receiver_id == demo_user_id),
                )
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        staleness_s = 0.0
        if last and last.created_at:
            staleness_s = max(0.0, (now - _aware_utc(last.created_at)).total_seconds())
        if staleness_s > 6 * 3600:
            delay = random.randint(max(rd_lo, 12), min(rd_hi + 20, 55))
        elif staleness_s > 3600:
            delay = random.randint(max(rd_lo, 8), min(rd_hi + 10, 40))
        else:
            delay = random.randint(rd_lo, rd_hi)
        if forced_delay > 0:
            delay = max(delay, forced_delay)
        if _real_user_in_first_hook_window(db, real_user_id):
            delay = min(delay, random.randint(2, 8))
    else:
        # Tests / demo live off: instant unless a positive floor is configured.
        delay = max(0, forced_delay)
    _set_pending(prof, real_user_id, "reply", now + timedelta(seconds=delay), trigger_message_id=trigger_message_id)
    log.info("demo_bot_reply_scheduled demo=%s partner=%s delay=%s trigger=%s", int(demo_user_id), int(real_user_id), int(delay), int(trigger_message_id or 0))
    db.add(prof)
    db.commit()


def schedule_demo_first_message_maybe(db: Session, demo_user_id: int, real_user_id: int) -> None:
    """After a demo match, maybe schedule an opener from the demo side."""
    if not bool(getattr(settings, "DEMO_BOT_CHAT_ENABLED", True)):
        log.info("demo_bot_disabled action=first_message_schedule")
        return
    if not bool(getattr(settings, "DEMO_BOT_FIRST_MESSAGE_ENABLED", True)):
        log.info("demo_bot_disabled action=first_message_flag")
        return
    demo_user_id = int(demo_user_id)
    real_user_id = int(real_user_id)
    if not _real_user_onboarding_completed(db, int(real_user_id)):
        return
    prof = db.query(Profile).filter(Profile.user_id == demo_user_id).first()
    if not prof or not prof.is_demo_profile:
        return
    if not users_are_matched(db, int(demo_user_id), int(real_user_id)):
        return
    if bool(getattr(settings, "DEMO_PAUSE_AUTO_DEMO_IF_REAL_CHAT", False)) and _real_user_has_active_real_chat(db, int(real_user_id)):
        return
    ensure_demo_personality_json(prof)
    if prof.demo_reply_scheduled_at and _aware_utc(prof.demo_reply_scheduled_at) > _utcnow():
        return
    # Cooldown per demo/real pair (prevents re-trigger spam).
    if prof.demo_last_auto_message_at is not None:
        last_auto = _aware_utc(prof.demo_last_auto_message_at)
        if (_utcnow() - last_auto).total_seconds() < 10 * 60:
            return
    n = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == demo_user_id, Message.receiver_id == real_user_id),
                and_(Message.sender_id == real_user_id, Message.receiver_id == demo_user_id),
            )
        )
        .count()
    )
    if int(n or 0) > 0:
        return
    # Product requirement: human opener delay 45..150 seconds after like/match.
    delay = random.randint(45, 150)
    _set_pending(prof, real_user_id, "first_match", _utcnow() + timedelta(seconds=delay))
    log.info("demo_bot_reply_scheduled demo=%s partner=%s delay=%s trigger=0", int(demo_user_id), int(real_user_id), int(delay))
    db.add(prof)
    db.commit()


def _maybe_revive_thread(db: Session, profile: Profile, demo_uid: int, real_uid: int) -> None:
    if not _pair_auto_demo_allowed(db, int(demo_uid), int(real_uid)):
        return
    if bool(getattr(settings, "DEMO_PAUSE_AUTO_DEMO_IF_REAL_CHAT", False)) and _real_user_has_active_real_chat(db, int(real_uid)):
        return
    if _waiting_for_user_response(db, int(demo_uid), int(real_uid)):
        return
    if profile.demo_reply_scheduled_at and _aware_utc(profile.demo_reply_scheduled_at) > _utcnow():
        return
    last = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == demo_uid, Message.receiver_id == real_uid),
                and_(Message.sender_id == real_uid, Message.receiver_id == demo_uid),
            )
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if not last or not last.created_at:
        return
    idle_s = (_utcnow() - last.created_at).total_seconds()
    if idle_s < 600 or idle_s > 3600:
        return
    if random.random() > 0.25:
        return
    ensure_demo_personality_json(profile)
    pers = _load_personality(profile)
    settings = get_demo_live_settings(db)
    if _should_ignore(db, demo_uid, real_uid, settings, pers):
        track_event(
            db,
            "demo_reply_ignored",
            user_id=demo_uid,
            payload={"real_user_id": real_uid, "context": "revive"},
        )
        return
    delay = _delay_seconds(str(pers.get("response_speed") or "normal"), str(settings.get("speed") or "normal"))
    _set_pending(profile, real_uid, "revive", _utcnow() + timedelta(seconds=delay))
    db.add(profile)
    db.commit()


def _random_planned_action(db: Session, profile: Profile, demo_uid: int) -> None:
    if profile.demo_reply_scheduled_at and _aware_utc(profile.demo_reply_scheduled_at) > _utcnow():
        return
    partners = _real_match_partners(db, demo_uid)
    if not partners:
        return
    r = random.random()
    if r < 0.4:
        return
    real_uid = random.choice(partners)
    if not _pair_auto_demo_allowed(db, int(demo_uid), int(real_uid)):
        return
    if bool(getattr(settings, "DEMO_PAUSE_AUTO_DEMO_IF_REAL_CHAT", False)) and _real_user_has_active_real_chat(db, int(real_uid)):
        return
    if _waiting_for_user_response(db, int(demo_uid), int(real_uid)):
        return
    ensure_demo_personality_json(profile)
    pers = _load_personality(profile)
    settings = get_demo_live_settings(db)
    if r < 0.7:
        if _should_ignore(db, demo_uid, real_uid, settings, pers):
            track_event(
                db,
                "demo_reply_ignored",
                user_id=demo_uid,
                payload={"real_user_id": real_uid, "context": "tick_reply"},
            )
            return
        mode = "reply"
    elif r < 0.9:
        n = (
            db.query(Message)
            .filter(
                or_(
                    and_(Message.sender_id == demo_uid, Message.receiver_id == real_uid),
                    and_(Message.sender_id == real_uid, Message.receiver_id == demo_uid),
                )
            )
            .count()
        )
        if int(n or 0) > 0:
            return
        mode = "opener"
    else:
        mode = "reply"
        if _should_ignore(db, demo_uid, real_uid, settings, pers):
            return
    delay = _delay_seconds(str(pers.get("response_speed") or "normal"), str(settings.get("speed") or "normal"))
    if r >= 0.9:
        delay = int(delay * random.uniform(1.2, 2.0))
    _set_pending(profile, real_uid, mode, _utcnow() + timedelta(seconds=delay))
    db.add(profile)
    db.commit()


def run_demo_behavior_tick(db: Session) -> dict[str, int]:
    """Single background pass: deliver due messages, light revive + random planning."""
    out = {"delivered": 0, "revives": 0, "planned": 0}
    if not bool(getattr(settings, "DEMO_BOT_CHAT_ENABLED", True)):
        log.info("demo_bot_disabled action=tick")
        return out
    out["delivered"] = int(_process_due(db))
    if not is_demo_live_enabled(db):
        return out
    demo_profiles = (
        db.query(Profile, User)
        .join(User, User.id == Profile.user_id)
        .filter(User.is_demo == True, Profile.is_demo_profile == True)  # noqa: E712
        .all()
    )
    for profile, user in demo_profiles:
        db.refresh(profile)
        if profile.demo_reply_scheduled_at and _aware_utc(profile.demo_reply_scheduled_at) > _utcnow():
            continue
        partners = _real_match_partners(db, int(user.id))
        if not partners or random.random() > 0.12:
            continue
        rid = random.choice(partners)
        try:
            before = profile.demo_reply_scheduled_at
            _maybe_revive_thread(db, profile, int(user.id), rid)
            db.refresh(profile)
            if profile.demo_reply_scheduled_at != before:
                out["revives"] += 1
        except Exception as e:
            log.warning("revive_failed %s", e)
            try:
                set_demo_last_error(db, f"revive_failed uid={int(user.id)} err={type(e).__name__}")
            except Exception:
                pass
    if random.random() < 0.35:
        candidates = [
            (p, u)
            for p, u in demo_profiles
            if not (p.demo_reply_scheduled_at and _aware_utc(p.demo_reply_scheduled_at) > _utcnow())
        ]
        if candidates:
            profile, user = random.choice(candidates)
            try:
                _random_planned_action(db, profile, int(user.id))
                out["planned"] += 1
            except Exception as e:
                log.warning("plan_failed %s", e)
                try:
                    set_demo_last_error(db, f"plan_failed uid={int(user.id)} err={type(e).__name__}")
                except Exception:
                    pass
    return out


def regenerate_demo_personalities(db: Session) -> int:
    n = 0
    q = (
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(User.is_demo == True, Profile.is_demo_profile == True)  # noqa: E712
    )
    for profile in q.all():
        profile.demo_personality_json = "{}"
        ensure_demo_personality_json(profile)
        db.add(profile)
        n += 1
    db.commit()
    return n
