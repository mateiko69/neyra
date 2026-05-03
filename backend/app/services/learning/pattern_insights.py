"""
Privacy-safe Pattern Insights: aggregate dating/chat behavior into supportive, actionable insights.
Never persists raw message text — only buckets, counts, and rates.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import math
from typing import Any

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.models.message import Message
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.user_ai_memory import UserAiMemory
from app.models.user_ignore import UserIgnore
from app.services.learning.message_learning import _tone
from app.services.trust.profile_quality import compute_profile_quality

MIN_TOTAL_MESSAGES = 12
MIN_BUCKET = 6
MIN_OPENERS_PER_TONE = 6
MIN_LIKED_QUALITY_BUCKET = 5
MIN_SHARED_BUCKET = 5
MIN_STOP_DENOM = 8
EFFECT_DELTA = 0.12

_PATTERN_INSIGHTS_GLOBAL_KEY = "learning:pattern_insights_global_v1"


def _rate(replied: int, ignored: int) -> float:
    d = max(1, int(replied) + int(ignored))
    return float(replied) / float(d)


def _confidence_from_n(n: int, spread: float) -> float:
    """Higher with more samples and larger effect (spread in [0,1])."""
    n = max(0, int(n))
    spread = max(0.0, min(1.0, float(spread)))
    return round(min(0.92, 0.35 + 0.35 * min(1.0, n / 40.0) + 0.25 * spread), 4)


def _interest_tokens(profile: Profile | None) -> set[str]:
    if not profile:
        return set()
    raw = (getattr(profile, "interests", "") or "") + "," + (getattr(profile, "lifestyle_tags", "") or "")
    out: set[str] = set()
    for part in raw.split(","):
        t = part.strip().lower()
        if len(t) >= 2:
            out.add(t)
    return out


def _shared_interest_count(viewer: Profile | None, partner: Profile | None) -> int:
    if not viewer or not partner:
        return 0
    a = _interest_tokens(viewer)
    b = _interest_tokens(partner)
    if not a or not b:
        return 0
    return len(a & b)


def _same_city(viewer: Profile | None, partner: Profile | None) -> bool:
    if not viewer or not partner:
        return False
    c1 = (getattr(viewer, "city", "") or "").strip().lower()
    c2 = (getattr(partner, "city", "") or "").strip().lower()
    return bool(c1 and c2 and c1 == c2)


def _replied_within_hours(db: Session, *, partner_id: int, user_id: int, after: datetime, hours: int) -> bool:
    horizon = after + timedelta(hours=int(hours))
    q = (
        db.query(Message.id)
        .filter(
            Message.sender_id == int(partner_id),
            Message.receiver_id == int(user_id),
            Message.created_at > after,
            Message.created_at <= horizon,
            Message.is_demo_simulation.is_(False),
        )
        .first()
    )
    return q is not None


def _default_actions(insight_id: str) -> list[dict[str, str]]:
    base = [
        {"id": "try_7_days", "label": "Try this for 7 days"},
    ]
    if insight_id == "prefer_responsive_matches":
        base.append({"id": "show_fewer_low_response", "label": "Show fewer low-response profiles"})
    if insight_id == "playful_openers_win":
        base.append({"id": "show_more_like_this", "label": "Show more like this"})
    if insight_id == "shared_interests_help":
        base.append({"id": "show_more_like_this", "label": "Show more like this"})
    if insight_id == "follow_up_after_reply":
        base.append({"id": "show_more_like_this", "label": "Get nudges to follow up"})
    return base


def generate_insights_from_aggregates(agg: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Deterministic rules only — no LLM, no raw text.
    """
    insights: list[dict[str, Any]] = []
    total = int(agg.get("outgoing_messages_sampled") or 0)
    if total < MIN_TOTAL_MESSAGES:
        return insights

    # 1) Playful vs serious (openers / first messages)
    ot = agg.get("opener_by_tone") or {}
    playful = ot.get("playful") or {}
    serious = ot.get("serious") or {}
    pr, pi = int(playful.get("replied") or 0), int(playful.get("ignored") or 0)
    sr, si = int(serious.get("replied") or 0), int(serious.get("ignored") or 0)
    if pr + pi >= MIN_OPENERS_PER_TONE and sr + si >= MIN_OPENERS_PER_TONE:
        rp = _rate(pr, pi)
        rs = _rate(sr, si)
        if rp >= rs + EFFECT_DELTA:
            spread = min(1.0, (rp - rs) * 2)
            insights.append(
                {
                    "id": "playful_openers_win",
                    "title": "Your tone matters",
                    "body": "Your more playful openers tend to get more replies than serious ones. Want to lean into that style a bit more?",
                    "confidence": _confidence_from_n(pr + pi + sr + si, spread),
                    "evidence": {
                        "sample_window_days": int(agg.get("window_days") or 14),
                        "opener_playful_reply_rate": round(rp, 4),
                        "opener_serious_reply_rate": round(rs, 4),
                        "opener_playful_n": pr + pi,
                        "opener_serious_n": sr + si,
                    },
                    "actions": _default_actions("playful_openers_win"),
                }
            )

    # 2) Liked profiles — low profile-quality bucket vs ok (proxy for “harder” matches)
    lq = agg.get("liked_messages_by_partner_quality") or {}
    low = lq.get("low_quality") or {}
    ok = lq.get("ok") or {}
    lr, li = int(low.get("replied") or 0), int(low.get("ignored") or 0)
    orr, oi = int(ok.get("replied") or 0), int(ok.get("ignored") or 0)
    if lr + li >= MIN_LIKED_QUALITY_BUCKET and orr + oi >= MIN_LIKED_QUALITY_BUCKET:
        r_low = _rate(lr, li)
        r_ok = _rate(orr, oi)
        if r_ok >= r_low + EFFECT_DELTA:
            spread = min(1.0, (r_ok - r_low) * 2)
            insights.append(
                {
                    "id": "prefer_responsive_matches",
                    "title": "A small pattern in who you like",
                    "body": "Some profiles you like tend to reply less often (often when the profile is still pretty light). Want to try people who look a bit more responsive for a week?",
                    "confidence": _confidence_from_n(lr + li + orr + oi, spread),
                    "evidence": {
                        "sample_window_days": int(agg.get("window_days") or 14),
                        "liked_low_quality_reply_rate": round(r_low, 4),
                        "liked_ok_reply_rate": round(r_ok, 4),
                        "liked_low_quality_n": lr + li,
                        "liked_ok_n": orr + oi,
                    },
                    "actions": _default_actions("prefer_responsive_matches"),
                }
            )

    # 3) Shared interests
    si = agg.get("by_shared_interests") or {}
    none_b = si.get("none") or {}
    some_b = si.get("some") or {}
    nr, ni = int(none_b.get("replied") or 0), int(none_b.get("ignored") or 0)
    sr2, si2 = int(some_b.get("replied") or 0), int(some_b.get("ignored") or 0)
    if nr + ni >= MIN_SHARED_BUCKET and sr2 + si2 >= MIN_SHARED_BUCKET:
        r_none = _rate(nr, ni)
        r_some = _rate(sr2, si2)
        if r_some >= r_none + EFFECT_DELTA:
            spread = min(1.0, (r_some - r_none) * 2)
            insights.append(
                {
                    "id": "shared_interests_help",
                    "title": "Shared interests",
                    "body": "When you have overlapping interests with someone, replies tend to come back more often. Want to prioritize those a bit more?",
                    "confidence": _confidence_from_n(nr + ni + sr2 + si2, spread),
                    "evidence": {
                        "sample_window_days": int(agg.get("window_days") or 14),
                        "shared_none_reply_rate": round(r_none, 4),
                        "shared_some_reply_rate": round(r_some, 4),
                        "shared_none_n": nr + ni,
                        "shared_some_n": sr2 + si2,
                    },
                    "actions": _default_actions("shared_interests_help"),
                }
            )

    # 4) Stop after first partner reply
    stop = agg.get("stop_after_first_reply") or {}
    stop_d = int(stop.get("denominator") or 0)
    stop_n = int(stop.get("numerator") or 0)
    if stop_d >= MIN_STOP_DENOM:
        ratio = float(stop_n) / float(stop_d)
        if ratio >= 0.45:
            spread = min(1.0, (ratio - 0.45) * 2)
            insights.append(
                {
                    "id": "follow_up_after_reply",
                    "title": "Keeping momentum",
                    "body": "Sometimes the chat cools off after the first reply. Want gentle reminders to send a quick follow-up?",
                    "confidence": _confidence_from_n(stop_d, spread),
                    "evidence": {
                        "sample_window_days": int(agg.get("window_days") or 14),
                        "stop_after_first_reply_ratio": round(ratio, 4),
                        "stop_after_first_reply_n": stop_d,
                    },
                    "actions": _default_actions("follow_up_after_reply"),
                }
            )

    # 5) High ignore rate — supportive, not shaming
    ign = int(agg.get("ignored_24h") or 0)
    rep = int(agg.get("replied_24h") or 0)
    if rep + ign >= MIN_TOTAL_MESSAGES:
        ri = _rate(rep, ign)
        if ign >= rep and ign >= MIN_BUCKET:
            insights.append(
                {
                    "id": "conversation_momentum",
                    "title": "Small tweaks, big difference",
                    "body": "A fair number of chats pause after your first message. That happens to everyone — want tips to restart in a low-pressure way?",
                    "confidence": _confidence_from_n(rep + ign, min(1.0, (ign / max(1, rep + ign)) - 0.4)),
                    "evidence": {
                        "sample_window_days": int(agg.get("window_days") or 14),
                        "reply_rate_24h": round(ri, 4),
                        "replied_n": rep,
                        "ignored_n": ign,
                    },
                    "actions": [
                        {"id": "try_7_days", "label": "Try this for 7 days"},
                        {"id": "show_more_like_this", "label": "Show revive suggestions more"},
                    ],
                }
            )

    # Cap at 6, sort by confidence
    insights.sort(key=lambda x: float(x.get("confidence") or 0), reverse=True)
    return insights[:6]


def _upsert_pattern_memory(
    db: Session,
    *,
    user_id: int,
    key: str,
    value_json: dict[str, Any],
    confidence: float,
    source: str,
) -> None:
    now = datetime.now(UTC)
    row = (
        db.query(UserAiMemory)
        .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == "pattern_insights", UserAiMemory.key == str(key)[:64])
        .first()
    )
    if not row:
        row = UserAiMemory(
            user_id=int(user_id),
            memory_type="pattern_insights",
            key=str(key)[:64],
            value_json=value_json or {},
            confidence_score=max(0.0, min(1.0, float(confidence))),
            source=str(source or "pattern_insights")[:64],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.value_json = value_json or {}
        row.confidence_score = max(0.0, min(1.0, float(confidence)))
        row.source = str(source or row.source or "pattern_insights")[:64]
        row.updated_at = now


def _compute_user_aggregates(db: Session, *, user_id: int, since: datetime, lookback_days: int) -> dict[str, Any]:
    uid = int(user_id)
    msgs = (
        db.query(Message)
        .filter(
            Message.sender_id == uid,
            Message.created_at >= since,
            Message.is_demo_simulation.is_(False),
        )
        .order_by(Message.created_at.desc())
        .limit(450)
        .all()
    )
    if not msgs:
        return {"window_days": lookback_days, "outgoing_messages_sampled": 0}

    partner_ids = {int(m.receiver_id) for m in msgs}
    prof_by_uid: dict[int, Profile] = {}
    if partner_ids:
        for p in db.query(Profile).filter(Profile.user_id.in_(partner_ids)).all():
            prof_by_uid[int(p.user_id)] = p
    viewer_prof = db.query(Profile).filter(Profile.user_id == uid).first()

    liked_rows = (
        db.query(Swipe.target_user_id)
        .filter(Swipe.swiper_id == uid, Swipe.liked.is_(True), Swipe.created_at >= since)
        .all()
    )
    liked_set = {int(r[0]) for r in liked_rows if r and r[0]}

    # Incoming messages from partners (for ordering / first reply)
    incoming_by_partner: dict[int, list[Message]] = defaultdict(list)
    if partner_ids:
        in_rows = (
            db.query(Message)
            .filter(
                Message.receiver_id == uid,
                Message.sender_id.in_(partner_ids),
                Message.created_at >= since,
                Message.is_demo_simulation.is_(False),
            )
            .order_by(Message.created_at.asc())
            .limit(2000)
            .all()
        )
        for im in in_rows:
            incoming_by_partner[int(im.sender_id)].append(im)

    totals = {"replied": 0, "ignored": 0}
    by_tone: dict[str, dict[str, int]] = {"playful": {"replied": 0, "ignored": 0}, "serious": {"replied": 0, "ignored": 0}}
    by_shared: dict[str, dict[str, int]] = {"none": {"replied": 0, "ignored": 0}, "some": {"replied": 0, "ignored": 0}}
    liked_by_quality: dict[str, dict[str, int]] = {
        "low_quality": {"replied": 0, "ignored": 0},
        "ok": {"replied": 0, "ignored": 0},
    }
    by_city: dict[str, dict[str, int]] = {"same": {"replied": 0, "ignored": 0}, "diff": {"replied": 0, "ignored": 0}}

    opener_by_tone: dict[str, dict[str, int]] = {"playful": {"replied": 0, "ignored": 0}, "serious": {"replied": 0, "ignored": 0}}
    earliest_out: dict[int, Message] = {}

    stall_short_partner_msgs = 0
    stall_threads = 0

    for m in msgs:
        rid = int(m.receiver_id)
        if m.voice_url or not (m.content or "").strip():
            continue
        rep = _replied_within_hours(db, partner_id=rid, user_id=uid, after=m.created_at, hours=24)
        key = "replied" if rep else "ignored"
        totals[key] += 1

        tone = _tone(m.content)
        by_tone.setdefault(tone, {"replied": 0, "ignored": 0})
        by_tone[tone][key] += 1

        pp = prof_by_uid.get(rid)
        sc = _shared_interest_count(viewer_prof, pp)
        sb = "none" if sc == 0 else "some"
        by_shared[sb][key] += 1

        if rid in liked_set and pp:
            pq = compute_profile_quality(pp).quality_flag
            qk = "low_quality" if pq == "low_quality" else "ok"
            liked_by_quality[qk][key] += 1

        if _same_city(viewer_prof, pp):
            by_city["same"][key] += 1
        else:
            by_city["diff"][key] += 1

        cur_e = earliest_out.get(rid)
        if cur_e is None or m.created_at < cur_e.created_at:
            earliest_out[rid] = m

    for rid, om in earliest_out.items():
        if om.voice_url or not (om.content or "").strip():
            continue
        rep_o = _replied_within_hours(db, partner_id=rid, user_id=uid, after=om.created_at, hours=24)
        key_o = "replied" if rep_o else "ignored"
        ot = "playful" if _tone(om.content) == "playful" else "serious"
        opener_by_tone[ot][key_o] += 1

    # Stop after first reply heuristic
    stop_num = 0
    stop_den = 0
    outgoing_by_partner: dict[int, list[Message]] = defaultdict(list)
    for m in msgs:
        if m.voice_url:
            continue
        outgoing_by_partner[int(m.receiver_id)].append(m)
    for rid, outs in outgoing_by_partner.items():
        outs_sorted = sorted(outs, key=lambda x: x.created_at)
        if not outs_sorted:
            continue
        first_u = outs_sorted[0]
        ins_list = incoming_by_partner.get(rid, [])
        first_p = None
        for im in ins_list:
            if im.created_at > first_u.created_at:
                first_p = im
                break
        if first_p is None:
            continue
        stop_den += 1
        horizon_end = first_p.created_at + timedelta(hours=48)
        follow = None
        for om in outs_sorted:
            if om.created_at > first_p.created_at and om.created_at <= horizon_end:
                follow = om
                break
        if follow is None:
            stop_num += 1

        # Stall: partner messages short (ephemeral scan)
        thread_msgs = sorted(
            [x for x in outs_sorted + ins_list if x.created_at >= first_u.created_at],
            key=lambda x: x.created_at,
        )[:40]
        if len(thread_msgs) >= 4:
            stall_threads += 1
            short_p = 0
            ptot = 0
            for tm in thread_msgs:
                if int(tm.sender_id) == rid and (tm.content or "").strip():
                    ptot += 1
                    if len((tm.content or "").strip()) < 20:
                        short_p += 1
            if ptot >= 2 and short_p >= max(1, int(math.ceil(ptot * 0.5))):
                stall_short_partner_msgs += 1

    ignored_threads = int(
        db.query(UserIgnore)
        .filter(UserIgnore.user_id == uid, UserIgnore.created_at >= since)
        .count()
    )

    return {
        "window_days": int(lookback_days),
        "outgoing_messages_sampled": int(sum(totals.values())),
        "replied_24h": int(totals["replied"]),
        "ignored_24h": int(totals["ignored"]),
        "reply_rate_24h": round(_rate(totals["replied"], totals["ignored"]), 4),
        "by_tone": {k: {**v, "reply_rate": round(_rate(v["replied"], v["ignored"]), 4)} for k, v in by_tone.items()},
        "by_shared_interests": {
            k: {**v, "reply_rate": round(_rate(v["replied"], v["ignored"]), 4)} for k, v in by_shared.items()
        },
        "liked_messages_by_partner_quality": {
            k: {**v, "reply_rate": round(_rate(v["replied"], v["ignored"]), 4)} for k, v in liked_by_quality.items()
        },
        "by_city_match": {
            k: {**v, "reply_rate": round(_rate(v["replied"], v["ignored"]), 4)} for k, v in by_city.items()
        },
        "opener_by_tone": {
            k: {**v, "reply_rate": round(_rate(v["replied"], v["ignored"]), 4)} for k, v in opener_by_tone.items()
        },
        "stop_after_first_reply": {"numerator": stop_num, "denominator": stop_den},
        "stall_heuristic": {
            "threads_sampled": stall_threads,
            "threads_many_short_partner_msgs": stall_short_partner_msgs,
        },
        "ignored_conversations_count": ignored_threads,
    }


@dataclass(frozen=True)
class PatternInsightsStats:
    users_updated: int


def run_pattern_insights_tick(db: Session, *, lookback_days: int = 14, max_users: int = 600) -> PatternInsightsStats:
    since = datetime.now(UTC) - timedelta(days=int(lookback_days or 14))
    sender_rows = (
        db.query(Message.sender_id)
        .filter(Message.created_at >= since, Message.is_demo_simulation.is_(False))
        .group_by(Message.sender_id)
        .limit(int(max_users or 600))
        .all()
    )
    sender_ids = [int(r[0]) for r in sender_rows if r and r[0]]
    users_updated = 0
    global_reply = {"replied": 0, "ignored": 0}

    for uid in sender_ids:
        agg = _compute_user_aggregates(db, user_id=uid, since=since, lookback_days=int(lookback_days or 14))
        global_reply["replied"] += int(agg.get("replied_24h") or 0)
        global_reply["ignored"] += int(agg.get("ignored_24h") or 0)
        insights = generate_insights_from_aggregates(agg)
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "aggregates": agg,
            "insights": insights,
        }
        conf = 0.55
        if int(agg.get("outgoing_messages_sampled") or 0) >= MIN_TOTAL_MESSAGES:
            conf = min(0.9, 0.5 + 0.01 * min(40, int(agg.get("outgoing_messages_sampled") or 0)))
        _upsert_pattern_memory(db, user_id=uid, key="weekly", value_json=payload, confidence=conf, source="learning:pattern_insights")
        users_updated += 1

    g_denom = max(1, global_reply["replied"] + global_reply["ignored"])
    g_payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "window_days": int(lookback_days or 14),
        "reply_rate_24h": round(global_reply["replied"] / float(g_denom), 4),
        "totals": global_reply,
    }
    row = db.query(AppSetting).filter(AppSetting.key == _PATTERN_INSIGHTS_GLOBAL_KEY).first()
    if not row:
        row = AppSetting(key=_PATTERN_INSIGHTS_GLOBAL_KEY, value_json=json.dumps(g_payload, ensure_ascii=False))
        db.add(row)
    else:
        row.value_json = json.dumps(g_payload, ensure_ascii=False)

    db.commit()
    return PatternInsightsStats(users_updated=int(users_updated))


def compute_live_pattern_insights(db: Session, *, user_id: int, lookback_days: int = 14) -> dict[str, Any]:
    """Compute aggregates + insights for one user (no DB write). Used when weekly snapshot is empty."""
    since = datetime.now(UTC) - timedelta(days=int(lookback_days or 14))
    agg = _compute_user_aggregates(db, user_id=int(user_id), since=since, lookback_days=int(lookback_days or 14))
    insights = generate_insights_from_aggregates(agg)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "aggregates": agg,
        "insights": insights,
        "on_demand": True,
    }


def get_pattern_insights_weekly(db: Session, *, user_id: int) -> dict[str, Any] | None:
    row = (
        db.query(UserAiMemory)
        .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == "pattern_insights", UserAiMemory.key == "weekly")
        .first()
    )
    if not row or not row.value_json:
        return None
    return dict(row.value_json)


def get_pattern_actions_state(db: Session, *, user_id: int) -> dict[str, Any]:
    row = (
        db.query(UserAiMemory)
        .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == "pattern_insights", UserAiMemory.key == "actions_state")
        .first()
    )
    if not row or not row.value_json:
        return {"experiments": [], "preferences": {}}
    return dict(row.value_json)


def upsert_pattern_actions_state(db: Session, *, user_id: int, state: dict[str, Any]) -> None:
    _upsert_pattern_memory(db, user_id=user_id, key="actions_state", value_json=state, confidence=0.99, source="user:pattern_insights_action")
    db.commit()
