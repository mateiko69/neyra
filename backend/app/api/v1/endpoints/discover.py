from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import random
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.message import Message
from app.models.match import Match
from app.services.analytics import track_event
from app.services.monetization.access import MonetizationAccess
from app.services.premium import has_premium_access, is_user_premium_map
from app.services.trust.verification_state import is_verified_profile, should_show_verified_badge
from app.services.ai.ranking_engine.service import RankingEngineService
from app.services.trust.profile_risk_evaluator import ProfileRiskEvaluator
from app.core.config import settings
from app.services.ai.cache import bump_user_cache_version, cache_get, cache_set, cache_key, get_user_cache_version
from app.services.monetization.boosts import is_boost_active
from app.services.visual_embeddings import VisualEmbedding, cosine_similarity
from app.services.safety import blocked_user_ids, ignored_user_ids
from app.utils.media_urls import normalize_photo_url
from app.utils.datetime_utc import to_utc_aware
from app.services.trust.profile_quality import compute_profile_quality
from app.services.demo_mode import (
    DEMO_PROFILE_DISCLAIMER,
    DEMO_PROFILE_LABEL,
    ensure_demo_profiles,
    is_demo_mode_enabled,
    is_demo_premium_feed_enabled,
    is_demo_profile,
    repair_demo_profile_photos,
)
from app.utils.demo_catalog_paths import is_demo_catalog_primary_photo_url
from app.services.discover_visibility import internal_test_discover_match, internal_test_discover_match_loose

router = APIRouter()
logger = logging.getLogger("neyra.discover")

VERIFIED_DISCOVER_BOOST = 10.0  # subtle (+8..+12) per plan; tuneable
LOW_QUALITY_DISCOVER_PENALTY = 6.0  # subtle; never hard-hide
ACTIVE_USER_BOOST_MAX = 6.0
RESPONSE_PROXY_BOOST_MAX = 5.0  # recent reply messages → likelier responders in Discover
MUTUAL_INTEREST_BOOST = 9.0
HIGH_COMPAT_BOOST = 8.0
NEW_USER_BOOST = 5.0
BOOSTED_PROFILE_BOOST = 14.0
PREMIUM_PLUS_DISCOVER_BIAS = 4.0
HIGH_COMPAT_THRESHOLD = 75.0
NEW_USER_SWIPES_MAX = 50
ACTIVE_NOW_MINUTES = 6
# Swiped profiles are hidden temporarily, not forever.
SWIPE_HIDE_DAYS = 7
PASS_COOLDOWN_HOURS = 24
RELAX_AGE_YEARS = 5
# First ~10 minutes + low swipe count: surface stronger profiles + optional demo walkthrough first.
FIRST_HOOK_MINUTES = 10.0
FRESH_SESSION_SWIPE_CAP = 28
FIRST_HOOK_FOCUS_BOOST = 11.0
FIRST_HOOK_HIGH_COMPAT_EXTRA = 5.0
FIRST_HOOK_LOW_QUALITY_EXTRA_PENALTY = 7.0


@dataclass(frozen=True)
class _DiscoverFallbackSql:
    mutual_interest: bool
    relax_age_years: int


@dataclass(frozen=True)
class _DiscoverFallbackSoft:
    mutual_interest_pair: bool
    require_onboarding: bool
    require_photo: bool
    viewer_age_prefs: bool
    candidate_age_prefs: bool
    # When True, skip viewer↔candidate gender / mutual-interest pairing checks (still enforce blocks/match/age SQL elsewhere).
    pairing_loose: bool = False


# SQL + pairing softness expand until we surface real profiles (incoming likes always bypass soft pairing below).
_DISCOVER_FALLBACK_LADDER: tuple[tuple[str, _DiscoverFallbackSql, _DiscoverFallbackSoft], ...] = (
    ("strict", _DiscoverFallbackSql(True, 0), _DiscoverFallbackSoft(True, False, True, True, True, False)),
    ("age_expand", _DiscoverFallbackSql(True, RELAX_AGE_YEARS), _DiscoverFallbackSoft(True, False, True, True, True, False)),
    ("interest_relaxed", _DiscoverFallbackSql(False, RELAX_AGE_YEARS), _DiscoverFallbackSoft(False, False, True, True, True, False)),
    # Widest real tier: disable strict soft pairing (photo/age prefs/onboarding checks in pair reasons).
    ("wide_real", _DiscoverFallbackSql(False, 100), _DiscoverFallbackSoft(False, False, False, False, False, True)),
)

_INCOMING_LIKE_PAIRING_SOFT = _DiscoverFallbackSoft(False, False, False, False, False, False)


def _uniq_profiles_merge(*lists: list[Profile]) -> list[Profile]:
    seen: set[int] = set()
    out: list[Profile] = []
    for lst in lists:
        for p in lst or []:
            if not p or not getattr(p, "user_id", None):
                continue
            uid = int(p.user_id)
            if uid in seen:
                continue
            seen.add(uid)
            out.append(p)
    return out


def _incoming_like_profiles_for_discover(
    db: Session,
    *,
    viewer_id: int,
    blocked_ids: set[int],
    matched_partner_ids: set[int],
    recent_swiped_ids: set[int],
    demo_enabled: bool,
    premium_demo_feed: bool = False,
) -> list[Profile]:
    rows = (
        db.query(Swipe.swiper_id)
        .filter(Swipe.target_user_id == int(viewer_id))
        .filter(Swipe.liked == True)  # noqa: E712
        .distinct()
        .all()
    )
    swiper_ids: list[int] = []
    seen_sid: set[int] = set()
    for r in rows:
        if not r or r[0] is None:
            continue
        sid = int(r[0])
        if sid < 1 or sid in seen_sid:
            continue
        if blocked_ids and sid in blocked_ids:
            continue
        if matched_partner_ids and sid in matched_partner_ids:
            continue
        # Incoming likes must bypass swipe suppression so they can be resurfaced.
        seen_sid.add(sid)
        swiper_ids.append(sid)
    if not swiper_ids:
        return []
    q = (
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(Profile.user_id.in_(swiper_ids))
        .filter(User.is_deleted == False)  # noqa: E712
        .filter(User.is_banned == False)  # noqa: E712
    )
    if premium_demo_feed:
        q = q.filter(Profile.is_demo_profile == True).filter(User.is_demo == True)  # noqa: E712
    elif not demo_enabled:
        q = q.filter(Profile.is_demo_profile == False).filter(User.is_demo == False)  # noqa: E712
    try:
        admin_emails = set(settings.admin_emails_list())
        if admin_emails:
            q = q.filter(~User.email.in_(list(admin_emails)))
    except Exception:
        pass
    q = q.filter((Profile.display_name.is_(None)) | (Profile.display_name != "Admin"))
    q = _apply_internal_test_sql_filters(q)
    return q.all()


_FEMALE_TOKENS: tuple[str, ...] = ("woman", "female", "women", "girl", "f")
_MALE_TOKENS: tuple[str, ...] = ("man", "male", "men", "guy", "m")


def _normalize_gender_alias(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if v in _MALE_TOKENS:
        return "man"
    if v in _FEMALE_TOKENS:
        return "woman"
    return ""


def _normalize_interested_in_alias(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if v in ("everyone", "all", "any"):
        return "everyone"
    if v in _MALE_TOKENS:
        return "men"
    if v in _FEMALE_TOKENS:
        return "women"
    return ""

def _age_from_dob(dob) -> int | None:
    try:
        if not dob:
            return None
        if isinstance(dob, datetime):
            d = dob.date()
        else:
            d = dob
        now = datetime.now(UTC).date()
        years = now.year - int(getattr(d, "year", 0) or 0)
        if years <= 0:
            return None
        if (now.month, now.day) < (int(getattr(d, "month", 0) or 0), int(getattr(d, "day", 0) or 0)):
            years -= 1
        return int(years)
    except Exception:
        return None


def _viewer_gender_bucket(viewer_profile: Profile | None) -> str | None:
    """male | female | None (unknown / nonbinary-style → no auto filter)."""
    if not viewer_profile:
        return None
    g = _normalize_gender_alias(getattr(viewer_profile, "gender", None))
    if g == "man":
        return "male"
    if g == "woman":
        return "female"
    return None


def _candidate_must_want_viewer(viewer_profile: Profile | None) -> str | None:
    """Return 'women'|'men' to require candidate.interested_in to include that, or None to skip."""
    bucket = _viewer_gender_bucket(viewer_profile)
    if bucket == "male":
        return "men"
    if bucket == "female":
        return "women"
    return None


def _discover_gender_tokens(viewer_profile: Profile | None) -> list[str] | None:
    """Allowed lowercase `Profile.gender` values for candidates, or None to skip filtering."""
    if not viewer_profile:
        return None
    pref = _normalize_gender_alias(getattr(viewer_profile, "preferred_gender", None))
    if pref == "man":
        return list(_MALE_TOKENS)
    if pref == "woman":
        return list(_FEMALE_TOKENS)
    if _normalize_interested_in_alias(getattr(viewer_profile, "preferred_gender", None)) == "everyone":
        return None
    interest = _normalize_interested_in_alias(getattr(viewer_profile, "interested_in", None))
    if interest == "women":
        return list(_FEMALE_TOKENS)
    if interest == "men":
        return list(_MALE_TOKENS)
    if interest == "everyone":
        return None
    # Default hetero-style deck: female viewers see male profiles, male viewers see female.
    bucket = _viewer_gender_bucket(viewer_profile)
    if bucket == "male":
        return list(_FEMALE_TOKENS)
    if bucket == "female":
        return list(_MALE_TOKENS)
    return None


def _profile_has_valid_photo(profile: Profile | None) -> bool:
    if not profile:
        return False
    parts = [x.strip() for x in (getattr(profile, "photo_urls", "") or "").split(",") if x.strip()]
    for p in parts:
        if normalize_photo_url(p, demo_profile_gender=getattr(profile, "gender", None)):
            return True
    return False


def _profile_has_demo_folder_photo(profile: Profile | None) -> bool:
    """Strict: primary photo must be `/demo-profiles/(men|women)/…/main.jpg` (bundled catalog assets)."""
    if not profile:
        return False
    parts = [x.strip() for x in (getattr(profile, "photo_urls", "") or "").split(",") if x.strip()]
    if not parts:
        return False
    primary = normalize_photo_url(parts[0], demo_profile_gender=getattr(profile, "gender", None))
    return is_demo_catalog_primary_photo_url(primary)


def _get_profile_age(profile: Profile | None) -> int | None:
    if not profile:
        return None
    age = _age_from_dob(getattr(profile, "date_of_birth", None)) or getattr(profile, "age", None)
    try:
        return int(age) if age is not None else None
    except Exception:
        return None


def _discover_viewer_profile_ready(viewer_profile: Profile | None) -> tuple[bool, list[str]]:
    """Gender, interested-in, age (18+), and onboarding_completed required before full Discover."""
    missing: list[str] = []
    if not viewer_profile:
        return False, sorted({"profile", "gender", "interested_in", "age", "onboarding_completed"})
    if not bool(getattr(viewer_profile, "onboarding_completed", False)):
        missing.append("onboarding_completed")
    vg = _normalize_gender_alias(getattr(viewer_profile, "gender", None))
    if not vg:
        missing.append("gender")
    vi = _normalize_interested_in_alias(getattr(viewer_profile, "interested_in", None))
    if not vi:
        missing.append("interested_in")
    age = _get_profile_age(viewer_profile)
    if age is None or int(age) < 18:
        missing.append("age")
    return (len(missing) == 0), sorted(set(missing))


def _discover_pair_exclusion_reasons(
    *,
    viewer_user: User,
    viewer_profile: Profile | None,
    candidate_user: User,
    candidate_profile: Profile | None,
    recent_swiped_ids: set[int] | None,
    blocked_ids: set[int] | None,
    ignored_ids: set[int] | None,
    matched_ids: set[int] | None = None,
    require_mutual_interest_in_pairing: bool = True,
    require_candidate_onboarding: bool = True,
    require_candidate_photo: bool = True,
    apply_viewer_age_range: bool = True,
    apply_candidate_age_range: bool = True,
    pairing_loose: bool = False,
) -> list[str]:
    reasons: list[str] = []
    viewer_id = int(getattr(viewer_user, "id", 0) or 0)
    candidate_id = int(getattr(candidate_user, "id", 0) or 0)
    if candidate_id == viewer_id:
        reasons.append("self")
    if blocked_ids and candidate_id in blocked_ids:
        reasons.append("blocked")
    if ignored_ids and candidate_id in ignored_ids:
        reasons.append("ignored")
    if matched_ids and candidate_id in matched_ids:
        reasons.append("already_matched")
    if bool(getattr(candidate_user, "is_deleted", False)) or bool(getattr(candidate_user, "is_banned", False)):
        reasons.append("candidate_inactive")
    if internal_test_discover_match(user=candidate_user, profile=candidate_profile):
        reasons.append("internal_test_profile_hidden")

    if not pairing_loose:
        viewer_gender_tokens = _discover_gender_tokens(viewer_profile)
        candidate_gender = _normalize_gender_alias(getattr(candidate_profile, "gender", None))
        if viewer_gender_tokens and candidate_gender not in viewer_gender_tokens:
            reasons.append("viewer_not_interested_in_candidate_gender")

        viewer_wants = _candidate_must_want_viewer(viewer_profile)
        candidate_wants = _normalize_interested_in_alias(getattr(candidate_profile, "interested_in", None))
        if require_mutual_interest_in_pairing and viewer_wants and candidate_wants not in {viewer_wants, "everyone"}:
            reasons.append("candidate_not_interested_in_viewer_gender")

    viewer_age = _get_profile_age(viewer_profile)
    candidate_age = _get_profile_age(candidate_profile)
    try:
        vmn = int(getattr(viewer_profile, "min_preferred_age", None)) if viewer_profile and getattr(viewer_profile, "min_preferred_age", None) is not None else None
        vmx = int(getattr(viewer_profile, "max_preferred_age", None)) if viewer_profile and getattr(viewer_profile, "max_preferred_age", None) is not None else None
    except Exception:
        vmn, vmx = None, None
    if (
        apply_viewer_age_range
        and vmn is not None
        and vmx is not None
        and 18 <= vmn <= vmx <= 80
        and (candidate_age is None or not (vmn <= candidate_age <= vmx))
    ):
        reasons.append("candidate_age_not_in_viewer_range")

    try:
        cmn = int(getattr(candidate_profile, "min_preferred_age", None)) if candidate_profile and getattr(candidate_profile, "min_preferred_age", None) is not None else None
        cmx = int(getattr(candidate_profile, "max_preferred_age", None)) if candidate_profile and getattr(candidate_profile, "max_preferred_age", None) is not None else None
    except Exception:
        cmn, cmx = None, None
    if (
        apply_candidate_age_range
        and cmn is not None
        and cmx is not None
        and 18 <= cmn <= cmx <= 80
        and (viewer_age is None or not (cmn <= viewer_age <= cmx))
    ):
        reasons.append("viewer_age_not_in_candidate_range")

    # Never hard-exclude candidates who completed onboarding (only gate incomplete profiles).
    cand_onboarding_done = bool(candidate_profile is not None and getattr(candidate_profile, "onboarding_completed", False))
    if require_candidate_onboarding and not cand_onboarding_done:
        reasons.append("candidate_onboarding_incomplete")
    if not bool(getattr(viewer_profile, "onboarding_completed", False)):
        reasons.append("viewer_onboarding_incomplete")
    if require_candidate_photo and not _profile_has_valid_photo(candidate_profile):
        reasons.append("candidate_has_no_photo")
    return sorted(set(reasons))


def _primary_exclusion_for_log(reasons: list[str]) -> str:
    """Best single label for ops/logging when a candidate is excluded."""
    order = (
        "candidate_has_no_photo",
        "candidate_onboarding_incomplete",
        "candidate_age_not_in_viewer_range",
        "viewer_age_not_in_candidate_range",
        "candidate_not_interested_in_viewer_gender",
        "viewer_not_interested_in_candidate_gender",
        "already_matched",
        "blocked",
        "ignored",
        "candidate_inactive",
        "internal_test_profile_hidden",
        "self",
        "viewer_onboarding_incomplete",
    )
    s = set(reasons or [])
    for o in order:
        if o in s:
            return o
    return str(reasons[0]) if reasons else "unknown"


def _apply_discover_gender_filter(query, viewer_profile: Profile | None):
    tokens = _discover_gender_tokens(viewer_profile)
    if not tokens:
        return query
    lg = func.lower(func.trim(Profile.gender))
    return query.filter(lg.in_(tokens))


def _discover_gender_cache_sig(viewer_profile: Profile | None) -> str:
    tokens = _discover_gender_tokens(viewer_profile)
    return ",".join(tokens) if tokens else "all"


def _apply_internal_test_sql_filters(query):
    """Keep QA / probe / disposable accounts out of the candidate SQL window."""
    el = func.lower(func.trim(User.email))
    dn = func.lower(func.trim(func.coalesce(Profile.display_name, "")))
    return (
        query.filter(~el.like("qa_%"))
        .filter(~el.like("%localeprobe%"))
        .filter(~el.like("%disposable%"))
        .filter(~el.like("%+qa%"))
        .filter(~el.like("%@test.%"))
        .filter(~el.like("test_%"))
        .filter(~dn.like("qa %"))
        .filter(~dn.like("%localeprobe%"))
        .filter(~dn.like("%disposable%"))
    )


def _is_profile_verified_approved(profile: Profile | None) -> bool:
    """Verified for ranking (source: verification_status)."""
    return is_verified_profile(profile)


def discover_candidate_debug_breakdown(db: Session, *, viewer: User, candidate_user: User, candidate_profile: Profile) -> dict:
    """Shared Discover eligibility explanation for dev/debug endpoints."""
    viewer_profile = db.query(Profile).filter(Profile.user_id == int(viewer.id)).first()
    candidate_id = int(candidate_user.id)
    viewer_id = int(viewer.id)
    swiped = db.query(Swipe.id).filter(Swipe.swiper_id == viewer_id, Swipe.target_user_id == candidate_id).first() is not None
    blocked_ids = blocked_user_ids(db, viewer_id)
    ignored_ids = ignored_user_ids(db, viewer_id)
    blocked = candidate_id in blocked_ids
    ignored = candidate_id in ignored_ids

    reasons = _discover_pair_exclusion_reasons(
        viewer_user=viewer,
        viewer_profile=viewer_profile,
        candidate_user=candidate_user,
        candidate_profile=candidate_profile,
        recent_swiped_ids={candidate_id} if swiped else set(),
        blocked_ids=blocked_ids,
        ignored_ids=ignored_ids,
        matched_ids={
            int(m.user_b_id if int(m.user_a_id) == viewer_id else m.user_a_id)
            for m in db.query(Match).filter((Match.user_a_id == viewer_id) | (Match.user_b_id == viewer_id)).all()
        },
    )
    tokens = _discover_gender_tokens(viewer_profile)
    candidate_gender = _normalize_gender_alias(getattr(candidate_profile, "gender", ""))
    viewer_gender_ok = (not tokens) or candidate_gender in tokens
    viewer_interest_token = _candidate_must_want_viewer(viewer_profile)
    candidate_interest = _normalize_interested_in_alias(getattr(candidate_profile, "interested_in", ""))
    candidate_wants_viewer = (not viewer_interest_token) or candidate_interest in (viewer_interest_token, "everyone")
    gender_match = bool(viewer_gender_ok and candidate_wants_viewer)
    age_match = "candidate_age_not_in_viewer_range" not in reasons and "viewer_age_not_in_candidate_range" not in reasons
    candidate_age_pref_match = "viewer_age_not_in_candidate_range" not in reasons
    has_photo = _profile_has_valid_photo(candidate_profile)
    onboarding_completed = bool(getattr(candidate_profile, "onboarding_completed", False))
    is_demo = bool(is_demo_profile(candidate_profile)) or bool(getattr(candidate_user, "is_demo", False))
    inactive = bool(getattr(candidate_user, "is_deleted", False)) or bool(getattr(candidate_user, "is_banned", False))
    self_candidate = candidate_id == viewer_id

    if not gender_match:
        reasons.append("gender_match")
    if not age_match:
        reasons.append("age_match")
    if "candidate_onboarding_incomplete" in reasons:
        reasons.append("onboarding_completed")
    if "candidate_has_no_photo" in reasons:
        reasons.append("has_photo")
    try:
        admin_emails = set(settings.admin_emails_list())
        if admin_emails and str(getattr(candidate_user, "email", "") or "") in admin_emails:
            reasons.append("admin_hidden")
    except Exception:
        pass
    if str(getattr(candidate_profile, "display_name", "") or "").strip() == "Admin":
        reasons.append("admin_hidden")

    return {
        "user_id": candidate_id,
        "profile_id": int(getattr(candidate_profile, "id", 0) or 0) or None,
        "display_name": str(getattr(candidate_profile, "display_name", "") or ""),
        "candidate_name": str(getattr(candidate_profile, "display_name", "") or ""),
        "candidate_gender": _normalize_gender_alias(getattr(candidate_profile, "gender", None)),
        "candidate_interested_in": _normalize_interested_in_alias(getattr(candidate_profile, "interested_in", None)),
        "candidate_age": _get_profile_age(candidate_profile),
        "candidate_min_preferred_age": getattr(candidate_profile, "min_preferred_age", None),
        "candidate_max_preferred_age": getattr(candidate_profile, "max_preferred_age", None),
        "current_user_gender": _normalize_gender_alias(getattr(viewer_profile, "gender", None)),
        "current_user_interested_in": _normalize_interested_in_alias(getattr(viewer_profile, "interested_in", None)),
        "current_user_age": _get_profile_age(viewer_profile),
        "current_user_min_preferred_age": getattr(viewer_profile, "min_preferred_age", None) if viewer_profile else None,
        "current_user_max_preferred_age": getattr(viewer_profile, "max_preferred_age", None) if viewer_profile else None,
        "is_demo": bool(is_demo),
        "eligible": len(set(reasons)) == 0,
        "excluded_reasons": sorted(set(reasons)),
        "onboarding_completed": onboarding_completed,
        "gender_match": bool(gender_match),
        "age_match": bool(age_match),
        "has_photo": bool(has_photo),
        "already_swiped": bool(swiped),
        "blocked": bool(blocked),
        "ignored": bool(ignored),
        "candidate_wants_viewer": bool(candidate_wants_viewer),
        "viewer_gender_ok": bool(viewer_gender_ok),
        "candidate_age_pref_match": bool(candidate_age_pref_match),
    }


def _account_age_minutes(user: User | None, *, now: datetime) -> float | None:
    if not user:
        return None
    c = getattr(user, "created_at", None)
    if not c:
        return None
    if c.tzinfo is None:
        c = c.replace(tzinfo=UTC)
    return max(0.0, (now - c).total_seconds() / 60.0)


@router.get("/feed")
def discover_feed(
    limit: int = 20,
    offset: int = 0,
    verified_only: bool = False,
    include_debug: bool = Query(False, description="If true and DEV_TOOLS_ENABLED, returns {feed, debug} (no response caching)."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    now = datetime.now(UTC)
    pass_hide_since = now - timedelta(hours=PASS_COOLDOWN_HOURS)
    latest_swipe_by_target: dict[int, tuple[bool, datetime | None]] = {}
    recent_passed_ids: set[int] = set()
    liked_excluded_ids: set[int] = set()
    recycled_pass_ids: set[int] = set()
    try:
        rows_sw = (
            db.query(Swipe.target_user_id, Swipe.created_at, Swipe.liked)
            .filter(Swipe.swiper_id == int(current_user.id))
            .all()
        )
        for tid, created_at, liked in rows_sw:
            if not tid or created_at is None:
                continue
            target_id = int(tid)
            prev = latest_swipe_by_target.get(target_id)
            if prev is None:
                latest_swipe_by_target[target_id] = (bool(liked), created_at)
            else:
                _, prev_ts = prev
                try:
                    p = prev_ts
                    c = created_at
                    if p is not None and getattr(p, "tzinfo", None) is None:
                        p = p.replace(tzinfo=UTC)
                    if c is not None and getattr(c, "tzinfo", None) is None:
                        c = c.replace(tzinfo=UTC)
                    if p is None or (c is not None and c >= p):
                        latest_swipe_by_target[target_id] = (bool(liked), created_at)
                except Exception:
                    latest_swipe_by_target[target_id] = (bool(liked), created_at)
            ca = created_at
            try:
                if getattr(ca, "tzinfo", None) is None:
                    ca = ca.replace(tzinfo=UTC)
            except Exception:
                pass
            # Any swipe older than cooldown is recyclable.
            if bool(liked):
                try:
                    if ca >= pass_hide_since:
                        liked_excluded_ids.add(target_id)
                    else:
                        recycled_pass_ids.add(target_id)
                except Exception:
                    liked_excluded_ids.add(target_id)
                continue
            try:
                if ca >= pass_hide_since:
                    recent_passed_ids.add(target_id)
                else:
                    recycled_pass_ids.add(target_id)
            except Exception:
                # If compare fails in SQLite edge cases, be conservative: keep pass on cooldown.
                recent_passed_ids.add(target_id)
    except Exception:
        recent_passed_ids = set()
        liked_excluded_ids = set()
        recycled_pass_ids = set()
    # "already swiped" suppression applies only inside cooldown window.
    recent_swiped_ids: set[int] = set(recent_passed_ids | liked_excluded_ids)
    matched_partner_ids: set[int] = set()
    try:
        rows_m = db.query(Match).filter((Match.user_a_id == int(current_user.id)) | (Match.user_b_id == int(current_user.id))).all()
        for row in rows_m:
            uid = int(row.user_b_id) if int(row.user_a_id) == int(current_user.id) else int(row.user_a_id)
            if uid > 0:
                matched_partner_ids.add(uid)
    except Exception:
        matched_partner_ids = set()
    advanced = has_premium_access(db, current_user.id, "see_advanced_compatibility")
    can_see_who_liked_you = bool(
        MonetizationAccess().check_access(db, int(current_user.id), "see_who_liked_you").get("allowed")
    )
    ai_boost = has_premium_access(db, current_user.id, "ai_match_boost")
    demo_enabled = is_demo_mode_enabled(db)
    premium_demo_feed = is_demo_premium_feed_enabled()
    if premium_demo_feed:
        demo_enabled = True
    if demo_enabled:
        try:
            ensure_demo_profiles(db)
            if premium_demo_feed:
                repair_demo_profile_photos(db)
        except Exception:
            # Demo seeding must never break real discovery.
            pass
    my_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    viewer_ready, viewer_missing = _discover_viewer_profile_ready(my_profile)
    if not viewer_ready:
        try:
            track_event(
                db,
                "discover_blocked_viewer_onboarding_incomplete",
                user_id=int(current_user.id),
                payload={"missing_fields": viewer_missing},
            )
            logger.info(
                json.dumps(
                    {
                        "event": "discover_blocked_viewer_onboarding_incomplete",
                        "viewer_user_id": int(current_user.id),
                        "missing_fields": viewer_missing,
                    },
                    default=str,
                )
            )
        except Exception:
            pass
        if bool(include_debug and getattr(settings, "DEV_TOOLS_ENABLED", False)):
            return {
                "feed": [],
                "debug": {"blocked_reason": "viewer_profile_incomplete", "missing_fields": viewer_missing},
                "onboarding_required": True,
                "viewer_profile_incomplete": True,
                "missing_fields": viewer_missing,
                "reason": "viewer_profile_incomplete",
            }
        return {
            "onboarding_required": True,
            "viewer_profile_incomplete": True,
            "missing_fields": viewer_missing,
            "reason": "viewer_profile_incomplete",
            "feed": [],
        }

    viewer_age_min = _account_age_minutes(current_user, now=now)
    viewer_first_hook = viewer_age_min is not None and viewer_age_min <= FIRST_HOOK_MINUTES
    viewer_swipe_total = int(
        db.query(func.count(Swipe.id)).filter(Swipe.swiper_id == int(current_user.id)).scalar() or 0
    )
    viewer_fresh_session = bool(viewer_first_hook or viewer_swipe_total < FRESH_SESSION_SWIPE_CAP)
    gender_sig = _discover_gender_cache_sig(my_profile)
    day_sig = now.date().isoformat()
    first_session_sig = f"{int(bool(viewer_first_hook))}:{int(bool(viewer_fresh_session))}"
    v = get_user_cache_version("discover_feed", int(current_user.id))
    ck = cache_key(
        "feed",
        {
            "user_id": int(current_user.id),
            "limit": int(limit),
            "offset": int(offset),
            "verified_only": bool(verified_only),
            "advanced": bool(advanced),
            "ai_boost": bool(ai_boost),
            "demo": bool(demo_enabled),
            "premium_demo": bool(premium_demo_feed),
            "gender_sig": gender_sig,
            "day": day_sig,
            "session": first_session_sig,
            "v": int(v),
        },
    )
    debug_response = bool(include_debug and getattr(settings, "DEV_TOOLS_ENABLED", False))
    cached = None if debug_response else cache_get(ck)
    if cached and isinstance(cached, list):
        ids = [int(x.get("user_id")) for x in cached if isinstance(x, dict) and x.get("user_id")]
        if ids:
            deleted_ids: set[int] = set()
            try:
                deleted_ids = {
                    int(r[0])
                    for r in db.query(User.id)
                    .filter(User.id.in_(ids))
                    .filter(User.is_deleted == True)  # noqa: E712
                    .all()
                    if r and r[0]
                }
            except Exception:
                deleted_ids = set()
            blocked_ids = blocked_user_ids(db, current_user.id)
            ignored_ids = ignored_user_ids(db, current_user.id)
            # Never show admin/system profiles in Discover for normal users.
            admin_ids: set[int] = set()
            try:
                admin_emails = set(settings.admin_emails_list())
                if admin_emails:
                    rows = db.query(User.id).filter(User.id.in_(ids)).filter(User.email.in_(list(admin_emails))).all()
                    admin_ids = {int(r[0]) for r in rows if r and r[0]}
            except Exception:
                admin_ids = set()
            gender_tokens = _discover_gender_tokens(my_profile)
            banned_ids: set[int] = set()
            try:
                banned_ids = {
                    int(r[0])
                    for r in db.query(User.id)
                    .filter(User.id.in_(ids))
                    .filter(User.is_banned == True)  # noqa: E712
                    .all()
                    if r and r[0]
                }
            except Exception:
                banned_ids = set()
            email_by_id: dict[int, str] = {}
            try:
                rows_em = db.query(User.id, User.email).filter(User.id.in_(ids)).all()
                email_by_id = {int(r[0]): str(r[1] or "") for r in rows_em if r and r[0]}
            except Exception:
                email_by_id = {}
            filtered = []
            for card in cached:
                if not isinstance(card, dict):
                    continue
                try:
                    uid = int(card.get("user_id") or 0)
                except Exception:
                    continue
                if uid < 1:
                    continue
                if internal_test_discover_match_loose(
                    email=email_by_id.get(uid),
                    display_name=str(card.get("display_name") or ""),
                ):
                    continue
                if matched_partner_ids and uid in matched_partner_ids:
                    continue
                if deleted_ids and uid in deleted_ids:
                    continue
                if blocked_ids and uid in blocked_ids:
                    continue
                if ignored_ids and uid in ignored_ids:
                    continue
                if admin_ids and uid in admin_ids:
                    continue
                if banned_ids and uid in banned_ids:
                    continue
                if premium_demo_feed and not bool(card.get("is_demo_profile")):
                    continue
                if not demo_enabled and bool(card.get("is_demo_profile")):
                    continue
                if str(card.get("display_name") or "").strip() == "Admin":
                    continue
                if gender_tokens:
                    cg = str(card.get("gender") or "").strip().lower()
                    if cg not in gender_tokens:
                        continue
                # Incomplete onboarding is soft-ranked, not hard-filtered.
                if bool(card.get("discover_missing_photo")):
                    continue
                filtered.append(card)
            filtered.sort(key=lambda card: bool(card.get("is_demo_profile")) if isinstance(card, dict) else True)
            return filtered[:limit]
        return cached[:limit]
    blocked_ids = blocked_user_ids(db, current_user.id)
    ignored_ids = ignored_user_ids(db, current_user.id)
    candidate_window = max(200, min(limit * 20, 500))
    q_base = (
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(Profile.user_id != current_user.id)
        .filter(User.is_deleted == False)  # noqa: E712
        .filter(User.is_banned == False)  # noqa: E712
    )
    # Keep base query broad; apply matching + fallback ladder below.
    if premium_demo_feed:
        q_base = q_base.filter(Profile.is_demo_profile == True).filter(User.is_demo == True)  # noqa: E712
    elif not demo_enabled:
        q_base = q_base.filter(Profile.is_demo_profile == False).filter(User.is_demo == False)  # noqa: E712
    # Never show admin/system profiles in Discover for normal users.
    try:
        admin_emails = set(settings.admin_emails_list())
        if admin_emails:
            q_base = q_base.filter(~User.email.in_(list(admin_emails)))
    except Exception:
        pass
    q_base = q_base.filter((Profile.display_name.is_(None)) | (Profile.display_name != "Admin"))
    q_base = _apply_internal_test_sql_filters(q_base)
    if blocked_ids:
        q_base = q_base.filter(~Profile.user_id.in_(blocked_ids))
    if ignored_ids:
        q_base = q_base.filter(~Profile.user_id.in_(ignored_ids))
    # Attribute match-based suppression using the same strict window *before* excluding matched partners
    # (otherwise matched user_ids never appear in base_ids and filtered_by_match stays 0).
    try:
        mn0 = int(getattr(my_profile, "min_preferred_age", None)) if my_profile else None
        mx0 = int(getattr(my_profile, "max_preferred_age", None)) if my_profile else None
    except Exception:
        mn0, mx0 = None, None

    def _apply_strict_match_filters(query, *, mutual_interest: bool):
        qq = _apply_discover_gender_filter(query, my_profile)
        if mutual_interest:
            viewer_interest_token = _candidate_must_want_viewer(my_profile)
            if viewer_interest_token:
                ci = func.lower(func.trim(Profile.interested_in))
                qq = qq.filter(ci.in_([viewer_interest_token, "everyone"]))
        return qq

    def _apply_age_filter_debug(query, *, relax_years: int):
        # Keep SQL broad and apply authoritative age compatibility in pair checks.
        # Some profiles only have DOB and no denormalized `age`, and filtering here can
        # hide valid real candidates before strict pairing logic runs.
        return query

    candidate_window_dbg = max(200, min(limit * 20, 500))
    attrib_base_ids: list[int] = [
        int(p.user_id)
        for p in _apply_age_filter_debug(_apply_strict_match_filters(q_base, mutual_interest=True), relax_years=0)
        .offset(0)
        .limit(candidate_window_dbg)
        .all()
        if p and getattr(p, "user_id", None)
    ]
    if matched_partner_ids:
        q_base = q_base.filter(~Profile.user_id.in_(list(matched_partner_ids)))
    if verified_only:
        q_base = q_base.filter(Profile.verification_status == "verified")

    # Age-range preference filter (soft requirement: only when viewer provided a valid range).
    try:
        mn = int(getattr(my_profile, "min_preferred_age", None)) if my_profile else None
        mx = int(getattr(my_profile, "max_preferred_age", None)) if my_profile else None
    except Exception:
        mn, mx = None, None

    def _apply_swipe_filter(query, *, ignore_swipes: bool):
        # Swipe/pass are soft-ranked, not hard-excluded in SQL.
        return query

    def _apply_age_filter(query, *, relax_years: int):
        # Keep SQL broad and apply authoritative age compatibility in pair checks.
        # Some profiles only have DOB and no denormalized `age`, and filtering here can
        # hide valid real candidates before strict pairing logic runs.
        return query

    def _load_candidates(
        *,
        include_demo: bool,
        ignore_swipes: bool,
        relax_age: int,
        mutual_interest: bool,
        use_offset: bool,
    ) -> list[Profile]:
        qq = _apply_strict_match_filters(q_base, mutual_interest=mutual_interest)
        qq = _apply_swipe_filter(qq, ignore_swipes=ignore_swipes)
        qq = _apply_age_filter(qq, relax_years=relax_age)
        if not include_demo:
            qq = qq.filter(Profile.is_demo_profile == False)  # noqa: E712
        off = int(offset) if use_offset else 0
        return qq.offset(off).limit(candidate_window).all()

    sql_window_widened = False
    base_candidates = _apply_strict_match_filters(q_base, mutual_interest=True).offset(0).limit(candidate_window).all()
    if not base_candidates:
        sql_window_widened = True
        base_candidates = _apply_strict_match_filters(q_base, mutual_interest=False).offset(0).limit(candidate_window).all()
    if not base_candidates:
        sql_window_widened = True
        base_candidates = q_base.offset(0).limit(candidate_window).all()

    # Eligibility filters (real-first); expanded via _DISCOVER_FALLBACK_LADDER + always-merged incoming likes.
    viewer_age = _age_from_dob(getattr(my_profile, "date_of_birth", None)) or getattr(my_profile, "age", None)
    try:
        viewer_age = int(viewer_age) if viewer_age is not None else None
    except Exception:
        viewer_age = None

    incoming_profiles = _incoming_like_profiles_for_discover(
        db,
        viewer_id=int(current_user.id),
        blocked_ids=blocked_ids,
        matched_partner_ids=matched_partner_ids,
        recent_swiped_ids=recent_swiped_ids,
        demo_enabled=demo_enabled,
        premium_demo_feed=premium_demo_feed,
    )

    debug: dict[str, object] = {
        "user_id": int(current_user.id),
        "candidates_total": int(len(base_candidates)),
        "real_candidates": 0,
        "demo_candidates": 0,
        "soft_filtered_onboarding": 0,
        "filtered_by_gender": 0,
        "filtered_by_age": 0,
        "filtered_by_photo": 0,
        "filtered_by_swipe": 0,
        "filtered_by_match": 0,
        "filtered_by_pass": 0,
        "filtered_by_already_liked_by_current_user": 0,
        "recycled_candidates_count": 0,
        "pass_cooldown_active": bool(len(recent_passed_ids) > 0),
        "demo_filtered_by_gender": 0,
        "strict_real_ids": [],
        "fallback_demo_ids": [],
        "pass_penalty_applied": 0,
        "swipe_penalty_applied": 0,
        "incoming_like_candidates_included": 0,
        "incoming_like_candidates_excluded": 0,
        "fallback_used": False,
        "fallback_stage": "strict",
        "returned_ids": [],
        "filtered_by_internal_test_profile": 0,
        "sql_window_widened": False,
        "exclusion_block_counts": {},
        "strict_filters_disabled_fallback": False,
        "filtered_by_onboarding_exclusion": 0,
    }

    debug["sql_window_widened"] = bool(sql_window_widened)

    try:
        bt_ids = [int(p.user_id) for p in base_candidates if p and getattr(p, "user_id", None)]
        if bt_ids:
            bt_users = db.query(User).filter(User.id.in_(bt_ids)).all()
            bt_map = {int(u.id): u for u in bt_users if u}
            debug["filtered_by_internal_test_profile"] = int(
                sum(
                    1
                    for p in base_candidates
                    if p and internal_test_discover_match(user=bt_map.get(int(p.user_id)), profile=p)
                )
            )
    except Exception:
        pass

    # Approximate filter attribution on the sampled window (useful for diagnosis, not billing).
    try:
        base_ids = [int(p.user_id) for p in base_candidates if p and getattr(p, "user_id", None)]
        # Match suppression happens before base_candidates are loaded; attribute using pre-exclusion window.
        debug["filtered_by_match"] = int(sum(1 for i in attrib_base_ids if int(i) in matched_partner_ids))
        if base_ids:
            debug["filtered_by_swipe"] = int(sum(1 for i in base_ids if int(i) in recent_swiped_ids))
            sw_rows = (
                db.query(Swipe.target_user_id, Swipe.liked)
                .filter(Swipe.swiper_id == int(current_user.id))
                .filter(Swipe.target_user_id.in_(base_ids))
                .all()
            )
            liked_by_current_ids = {int(tid) for tid, liked in sw_rows if tid and bool(liked)}
            passed_by_current_ids = {int(tid) for tid, liked in sw_rows if tid and not bool(liked)}
            debug["filtered_by_already_liked_by_current_user"] = int(sum(1 for i in base_ids if int(i) in liked_by_current_ids))
            debug["filtered_by_pass"] = int(sum(1 for i in base_ids if int(i) in passed_by_current_ids))
            debug["recycled_candidates_count"] = int(sum(1 for i in base_ids if int(i) in recycled_pass_ids))
            incoming_rows = (
                db.query(Swipe.swiper_id)
                .filter(Swipe.target_user_id == int(current_user.id))
                .filter(Swipe.liked == True)  # noqa: E712
                .filter(Swipe.swiper_id.in_(base_ids))
                .all()
            )
            incoming_like_candidate_ids = {int(r[0]) for r in incoming_rows if r and r[0]}
            exclusion_allowed_ids = set(matched_partner_ids) | liked_by_current_ids | passed_by_current_ids
            debug["incoming_like_candidates_excluded"] = int(
                sum(1 for i in incoming_like_candidate_ids if int(i) in exclusion_allowed_ids)
            )
        tokens = _discover_gender_tokens(my_profile)
        if tokens:
            debug["filtered_by_gender"] = int(
                sum(
                    1
                    for p in base_candidates
                    if p
                    and getattr(p, "user_id", None)
                    and (getattr(p, "gender", "") or "").strip().lower() not in tokens
                )
            )
        if mn is not None and mx is not None and 18 <= mn <= mx <= 80:
            debug["filtered_by_age"] = int(
                sum(
                    1
                    for p in base_candidates
                    if p
                    and getattr(p, "user_id", None)
                    and (getattr(p, "age", None) is None or not (mn <= int(getattr(p, "age", 0) or 0) <= mx))
                )
            )
    except Exception:
        pass

    debug_real_seen_ids: set[int] = set()
    debug_demo_seen_ids: set[int] = set()

    def _eligible_profiles_batch(
        cands: list[Profile],
        *,
        soft: _DiscoverFallbackSoft,
        allow_demo: bool,
        advance_debug: bool = True,
    ) -> list[Profile]:
        out: list[Profile] = []
        for p in cands:
            if not p or not getattr(p, "user_id", None):
                continue
            cand_user = db.query(User).filter(User.id == int(p.user_id)).first()
            if not cand_user:
                continue
            candidate_uid = int(getattr(p, "user_id", 0) or 0)
            is_demo = bool(is_demo_profile(p))
            if is_demo:
                if advance_debug and candidate_uid > 0:
                    debug_demo_seen_ids.add(candidate_uid)
                    debug["demo_candidates"] = int(len(debug_demo_seen_ids))
                if allow_demo:
                    # Demo fallback still must respect viewer pairing basics, including
                    # viewer gender interest and hard exclusions like self/swiped/matched.
                    demo_reasons = _discover_pair_exclusion_reasons(
                        viewer_user=current_user,
                        viewer_profile=my_profile,
                        candidate_user=cand_user,
                        candidate_profile=p,
                        recent_swiped_ids=recent_swiped_ids,
                        blocked_ids=blocked_ids,
                        ignored_ids=ignored_ids,
                        matched_ids=matched_partner_ids,
                        require_mutual_interest_in_pairing=True,
                        require_candidate_onboarding=False,
                        require_candidate_photo=False,
                        apply_viewer_age_range=False,
                        apply_candidate_age_range=False,
                        pairing_loose=bool(soft.pairing_loose),
                    )
                    if not demo_reasons:
                        out.append(p)
                    elif advance_debug and (
                        "viewer_not_interested_in_candidate_gender" in demo_reasons
                        or "candidate_not_interested_in_viewer_gender" in demo_reasons
                    ):
                        debug["demo_filtered_by_gender"] += 1
                continue
            if advance_debug and candidate_uid > 0:
                debug_real_seen_ids.add(candidate_uid)
                debug["real_candidates"] = int(len(debug_real_seen_ids))
            reasons = _discover_pair_exclusion_reasons(
                viewer_user=current_user,
                viewer_profile=my_profile,
                candidate_user=cand_user,
                candidate_profile=p,
                recent_swiped_ids=recent_swiped_ids,
                blocked_ids=blocked_ids,
                ignored_ids=ignored_ids,
                matched_ids=matched_partner_ids,
                require_mutual_interest_in_pairing=bool(soft.mutual_interest_pair),
                require_candidate_onboarding=bool(soft.require_onboarding),
                require_candidate_photo=bool(soft.require_photo),
                apply_viewer_age_range=bool(soft.viewer_age_prefs),
                apply_candidate_age_range=bool(soft.candidate_age_prefs),
                pairing_loose=bool(soft.pairing_loose),
            )
            if reasons:
                if "viewer_onboarding_incomplete" in reasons:
                    # Viewer should be gated before candidate iteration; keep logs quiet if not.
                    pass
                else:
                    payload = {
                        "event": "discover_pair_excluded_real",
                        "candidate_user_id": int(getattr(p, "user_id", 0) or 0),
                        "candidate_name": str(getattr(p, "display_name", "") or ""),
                        "candidate_gender": _normalize_gender_alias(getattr(p, "gender", None)),
                        "candidate_interested_in": _normalize_interested_in_alias(getattr(p, "interested_in", None)),
                        "candidate_age": _get_profile_age(p),
                        "candidate_min_preferred_age": getattr(p, "min_preferred_age", None),
                        "candidate_max_preferred_age": getattr(p, "max_preferred_age", None),
                        "current_user_gender": _normalize_gender_alias(getattr(my_profile, "gender", None)),
                        "current_user_interested_in": _normalize_interested_in_alias(getattr(my_profile, "interested_in", None)),
                        "current_user_age": _get_profile_age(my_profile),
                        "current_user_min_preferred_age": getattr(my_profile, "min_preferred_age", None) if my_profile else None,
                        "current_user_max_preferred_age": getattr(my_profile, "max_preferred_age", None) if my_profile else None,
                        "has_photo": _profile_has_valid_photo(p),
                        "onboarding_completed": bool(getattr(p, "onboarding_completed", False)),
                        "already_swiped": int(getattr(p, "user_id", 0) or 0) in recent_swiped_ids,
                        "exclusion_reason": reasons,
                        "primary_exclusion": _primary_exclusion_for_log(list(reasons)),
                    }
                    try:
                        logger.info(json.dumps(payload, default=str))
                    except Exception:
                        pass
                if advance_debug:
                    if "candidate_has_no_photo" in reasons:
                        debug["filtered_by_photo"] += 1
                    if "candidate_age_not_in_viewer_range" in reasons or "viewer_age_not_in_candidate_range" in reasons:
                        debug["filtered_by_age"] += 1
                    if "candidate_onboarding_incomplete" in reasons:
                        debug["filtered_by_onboarding_exclusion"] = int(debug.get("filtered_by_onboarding_exclusion", 0) or 0) + 1
                    pk = _primary_exclusion_for_log(list(reasons))
                    bc = debug.setdefault("exclusion_block_counts", {})
                    if isinstance(bc, dict):
                        bc[pk] = int(bc.get(pk, 0) or 0) + 1
                continue
            raw_photos = (getattr(p, "photo_urls", "") or "").split(",")
            photos = [x.strip() for x in raw_photos if x.strip()]
            if soft.require_photo and not photos:
                if advance_debug:
                    debug["filtered_by_photo"] += 1
                    pk = "photo_requirement_soft"
                    bc = debug.setdefault("exclusion_block_counts", {})
                    if isinstance(bc, dict):
                        bc[pk] = int(bc.get(pk, 0) or 0) + 1
                    try:
                        logger.info(
                            json.dumps(
                                {
                                    "event": "discover_pair_excluded_real",
                                    "candidate_user_id": int(getattr(p, "user_id", 0) or 0),
                                    "primary_exclusion": pk,
                                    "exclusion_reason": [pk],
                                },
                                default=str,
                            )
                        )
                    except Exception:
                        pass
                continue
            if soft.viewer_age_prefs and viewer_age is not None:
                try:
                    cmn = int(getattr(p, "min_preferred_age", None)) if getattr(p, "min_preferred_age", None) is not None else None
                    cmx = int(getattr(p, "max_preferred_age", None)) if getattr(p, "max_preferred_age", None) is not None else None
                except Exception:
                    cmn, cmx = None, None
                if cmn is not None and cmx is not None and 18 <= cmn <= cmx <= 80:
                    if not (cmn <= int(viewer_age) <= cmx):
                        if advance_debug:
                            debug["filtered_by_age"] += 1
                        continue
            out.append(p)
        return out

    incoming_like_batch_eligible = _eligible_profiles_batch(
        incoming_profiles,
        soft=_INCOMING_LIKE_PAIRING_SOFT,
        allow_demo=False,
        advance_debug=True,
    )

    _, strict_sql_tier, strict_soft_tier = _DISCOVER_FALLBACK_LADDER[0]
    strict_preview_profiles = _load_candidates(
        include_demo=False,
        ignore_swipes=False,
        relax_age=int(strict_sql_tier.relax_age_years),
        mutual_interest=bool(strict_sql_tier.mutual_interest),
        use_offset=True,
    )
    if len(strict_preview_profiles) < min(10, limit) and offset > 0:
        strict_preview_profiles = _load_candidates(
            include_demo=False,
            ignore_swipes=False,
            relax_age=int(strict_sql_tier.relax_age_years),
            mutual_interest=bool(strict_sql_tier.mutual_interest),
            use_offset=False,
        )
    strict_count = len(
        _uniq_profiles_merge(
            _eligible_profiles_batch(
                incoming_profiles,
                soft=_INCOMING_LIKE_PAIRING_SOFT,
                allow_demo=False,
                advance_debug=False,
            ),
            _eligible_profiles_batch(
                strict_preview_profiles,
                soft=strict_soft_tier,
                allow_demo=False,
                advance_debug=False,
            ),
        )
    )
    strict_real_ids = [
        int(getattr(p, "user_id", 0) or 0)
        for p in _uniq_profiles_merge(
            _eligible_profiles_batch(
                incoming_profiles,
                soft=_INCOMING_LIKE_PAIRING_SOFT,
                allow_demo=False,
                advance_debug=False,
            ),
            _eligible_profiles_batch(
                strict_preview_profiles,
                soft=strict_soft_tier,
                allow_demo=False,
                advance_debug=False,
            ),
        )
        if p and int(getattr(p, "user_id", 0) or 0) > 0 and not bool(is_demo_profile(p))
    ]
    debug["strict_real_ids"] = strict_real_ids

    eligible: list[Profile] = []
    fallback_stage_final = "strict"
    fallback_used_final = False
    for stage_name, sql_tier, soft_tier in _DISCOVER_FALLBACK_LADDER:
        tier_profiles = _load_candidates(
            include_demo=False,
            ignore_swipes=False,
            relax_age=int(sql_tier.relax_age_years),
            mutual_interest=bool(sql_tier.mutual_interest),
            use_offset=True,
        )
        if len(tier_profiles) < min(10, limit) and offset > 0:
            tier_profiles = _load_candidates(
                include_demo=False,
                ignore_swipes=False,
                relax_age=int(sql_tier.relax_age_years),
                mutual_interest=bool(sql_tier.mutual_interest),
                use_offset=False,
            )
        tier_eligible = _eligible_profiles_batch(tier_profiles, soft=soft_tier, allow_demo=False)
        merged = _uniq_profiles_merge(incoming_like_batch_eligible, tier_eligible)
        if merged:
            eligible = merged
            fallback_stage_final = str(stage_name)
            fallback_used_final = bool(stage_name != "strict")
            break

    # Safety fallback: ladder produced nobody eligible — merge non-strict tiers from offset 0.
    if not eligible:
        relaxed_candidates: list[Profile] = []
        for _stage_name, sql_tier, soft_tier in _DISCOVER_FALLBACK_LADDER[1:]:
            tier_profiles = _load_candidates(
                include_demo=False,
                ignore_swipes=False,
                relax_age=int(sql_tier.relax_age_years),
                mutual_interest=bool(sql_tier.mutual_interest),
                use_offset=False,
            )
            tier_eligible = _eligible_profiles_batch(tier_profiles, soft=soft_tier, allow_demo=False)
            relaxed_candidates = _uniq_profiles_merge(relaxed_candidates, tier_eligible)
        if relaxed_candidates:
            eligible = _uniq_profiles_merge(incoming_like_batch_eligible, relaxed_candidates[:limit])
            fallback_stage_final = "relaxed_real"
            fallback_used_final = True

    # Last resort: SQL window had rows but pairing removed everyone — reuse widened window with loose pairing + no soft gates.
    if not eligible and base_candidates:
        rescue_soft = _DiscoverFallbackSoft(False, False, False, False, False, True)
        rescue_profiles = _eligible_profiles_batch(list(base_candidates), soft=rescue_soft, allow_demo=False, advance_debug=False)
        if rescue_profiles:
            eligible = _uniq_profiles_merge(incoming_like_batch_eligible, rescue_profiles[: max(limit, 20)])
            fallback_stage_final = "strict_filters_disabled"
            fallback_used_final = True
            debug["strict_filters_disabled_fallback"] = True

    try:
        eligible_ids = {int(getattr(p, "user_id", 0) or 0) for p in eligible if p and getattr(p, "user_id", None)}
        if "incoming_like_candidate_ids" in locals():
            debug["incoming_like_candidates_included"] = int(
                sum(1 for i in incoming_like_candidate_ids if int(i) in eligible_ids)
            )
    except Exception:
        pass

    real_eligible_count = sum(
        1
        for p in eligible
        if p and int(getattr(p, "user_id", 0) or 0) > 0 and not bool(is_demo_profile(p))
    )

    if not eligible and demo_enabled and strict_count == 0 and real_eligible_count == 0:
        demo_tier_profiles = _load_candidates(
            include_demo=True,
            ignore_swipes=False,
            relax_age=RELAX_AGE_YEARS,
            mutual_interest=False,
            use_offset=False,
        )
        demo_eligible_core = _eligible_profiles_batch(demo_tier_profiles, soft=_DiscoverFallbackSoft(False, False, False, False, False, False), allow_demo=True)
        eligible = _uniq_profiles_merge(incoming_like_batch_eligible, demo_eligible_core)
        if eligible:
            fallback_stage_final = "include_demo"
            fallback_used_final = True
            debug["fallback_demo_ids"] = [
                int(getattr(p, "user_id", 0) or 0)
                for p in eligible
                if p and int(getattr(p, "user_id", 0) or 0) > 0 and bool(is_demo_profile(p))
            ]

    if eligible and demo_enabled and len(eligible) < int(limit) and strict_count == 0 and real_eligible_count == 0:
        demo_fill_candidates = _load_candidates(
            include_demo=True,
            ignore_swipes=False,
            relax_age=RELAX_AGE_YEARS,
            mutual_interest=False,
            use_offset=False,
        )
        seen_ids = {int(getattr(p, "user_id", 0) or 0) for p in eligible}
        wide_soft_demo = _DiscoverFallbackSoft(False, False, False, False, False, False)
        demo_fill = [
            p
            for p in _eligible_profiles_batch(demo_fill_candidates, soft=wide_soft_demo, allow_demo=True)
            if p and bool(is_demo_profile(p)) and int(getattr(p, "user_id", 0) or 0) not in seen_ids
        ]
        demo_fill_limited = demo_fill[: max(0, int(limit) - len(eligible))]
        eligible = eligible + demo_fill_limited
        if demo_fill_limited:
            debug["fallback_demo_ids"] = [
                int(getattr(p, "user_id", 0) or 0)
                for p in demo_fill_limited
                if p and int(getattr(p, "user_id", 0) or 0) > 0
            ]

    if not eligible and bool(getattr(settings, "DEV_TOOLS_ENABLED", False)):
        dev_profiles = q_base.offset(0).limit(candidate_window).all()
        if recent_swiped_ids:
            dev_profiles = [p for p in dev_profiles if p and int(getattr(p, "user_id", 0) or 0) not in recent_swiped_ids]
        dev_eligible = _eligible_profiles_batch(dev_profiles, soft=_DiscoverFallbackSoft(False, False, False, False, False, False), allow_demo=True)
        eligible = _uniq_profiles_merge(incoming_like_batch_eligible, dev_eligible)
        if eligible:
            fallback_stage_final = "dev_any"
            fallback_used_final = True

    debug["strict_count"] = int(strict_count)
    debug["fallback_used"] = bool(fallback_used_final)
    debug["fallback_stage"] = str(fallback_stage_final)
    debug["fallback_step_used"] = str(fallback_stage_final)

    candidates: list[Profile] = list(eligible)
    cards: list[dict] = []
    ranked = RankingEngineService.rank(my_profile, eligible)
    # Subtle quality downranking: reduce visibility of risky profiles without exposing scores.
    decorated = []
    user_ids = [p.user_id for p in eligible if p and getattr(p, "user_id", None)]
    premium_active_map = is_user_premium_map(db, user_ids)
    premium_plus_ids: set[int] = set()
    if user_ids:
        rows_pp = (
            db.query(User.id, User.subscription_status, User.subscription_expires_at)
            .filter(User.id.in_(user_ids))
            .filter(User.subscription_plan == "premium_plus")
            .all()
        )
        for uid, st, exp in rows_pp:
            if not uid:
                continue
            stl = str(st or "").strip().lower()
            if stl in {"active", "past_due"}:
                premium_plus_ids.add(int(uid))
            elif stl == "canceled" and exp is not None:
                ex = to_utc_aware(exp)
                try:
                    if ex and ex > now:
                        premium_plus_ids.add(int(uid))
                except Exception:
                    pass
    premium_until_raw: dict[int, datetime | None] = {}
    if user_ids:
        rows_pu = db.query(User.id, User.premium_until).filter(User.id.in_(user_ids)).all()
        premium_until_raw = {int(uid): pu for uid, pu in rows_pu if uid}
    active_map: dict[int, datetime | None] = {}
    if user_ids:
        rows = db.query(User.id, User.matches_last_seen_at).filter(User.id.in_(user_ids)).all()
        active_map = {int(uid): seen for uid, seen in rows}

    # Mutual-interest boost: users who already liked the viewer get a small ranking bump.
    liked_me_ids: set[int] = set()
    if user_ids:
        rows = (
            db.query(Swipe.swiper_id)
            .filter(Swipe.target_user_id == int(current_user.id))
            .filter(Swipe.liked == True)  # noqa: E712
            .filter(Swipe.swiper_id.in_(user_ids))
            .all()
        )
        liked_me_ids = {int(r[0]) for r in rows if r and r[0]}

    # New-user boost: based on how many swipes the candidate has made (first ~50).
    swipe_counts: dict[int, int] = {}
    if user_ids:
        rows = (
            db.query(Swipe.swiper_id, func.count(Swipe.id))
            .filter(Swipe.swiper_id.in_(user_ids))
            .group_by(Swipe.swiper_id)
            .all()
        )
        swipe_counts = {int(uid): int(cnt or 0) for uid, cnt in rows}

    # Reply volume (messages with reply_to set) in the last 30d — proxy for response habit.
    reply_counts: dict[int, int] = {}
    if user_ids:
        cutoff_reply = now - timedelta(days=30)
        rows = (
            db.query(Message.sender_id, func.count(Message.id))
            .filter(Message.sender_id.in_(user_ids))
            .filter(Message.reply_to_message_id.isnot(None))
            .filter(Message.created_at >= cutoff_reply)
            .group_by(Message.sender_id)
            .all()
        )
        reply_counts = {int(uid): int(cnt or 0) for uid, cnt in rows if uid}

    # Track applied boosts in aggregate (avoid per-card spam).
    mutual_boost_applied = 0
    high_compat_boost_applied = 0
    new_user_boost_applied = 0
    my_emb = VisualEmbedding.deserialize(getattr(my_profile, "visual_embedding", "") or "") if my_profile else None
    verified_seen = 0
    low_quality_seen = 0

    viewer_low_data = False
    if not my_profile:
        viewer_low_data = True
    else:
        viewer_low_data = bool(
            not (getattr(my_profile, "city", "") or "").strip()
            or not (getattr(my_profile, "interests", "") or "").strip()
            or not [x for x in (getattr(my_profile, "photo_urls", "") or "").split(",") if x.strip()]
        )

    def _activity_boost(user_id: int) -> float:
        ts = active_map.get(int(user_id))
        if not ts:
            return 0.0
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=UTC)
        age_days = max(0.0, (now - ts).total_seconds() / (60 * 60 * 24))
        freshness = max(0.0, min(1.0, 1.0 - (age_days / 30.0)))
        return float(ACTIVE_USER_BOOST_MAX) * freshness

    def _active_now(user_id: int) -> bool:
        ts = active_map.get(int(user_id))
        if not ts:
            return False
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=UTC)
        age_s = max(0.0, (now - ts).total_seconds())
        return age_s <= float(ACTIVE_NOW_MINUTES * 60)

    def _is_strong_profile(profile: Profile, quality_flag: str, is_verified: bool) -> bool:
        if quality_flag != "ok":
            return False
        photos = [x.strip() for x in (getattr(profile, "photo_urls", "") or "").split(",") if x.strip()]
        if len(photos) == 0:
            return False
        bio = (getattr(profile, "bio", "") or "").strip()
        if len(bio) < 30:
            return False
        if is_verified:
            return True
        interests = [x.strip() for x in (getattr(profile, "interests", "") or "").split(",") if x.strip()]
        return len(interests) >= 3

    def _daily_jitter(user_id: int) -> float:
        # Stable per-user per-day jitter in [-2.0..+2.0] to reshuffle slightly every day without breaking ranking.
        seed = f"{day_sig}:{int(current_user.id)}:{int(user_id)}".encode("utf-8")
        h = hashlib.sha256(seed).digest()
        n = int.from_bytes(h[:4], "big") / float(2**32 - 1)
        return (n - 0.5) * 4.0

    viewer_city = (getattr(my_profile, "city", "") or "").strip().lower() if my_profile else ""
    viewer_goal = (getattr(my_profile, "relationship_goal", "") or "").strip().lower() if my_profile else ""
    viewer_vibe = (getattr(my_profile, "vibe", "") or "").strip().lower() if my_profile else ""
    viewer_tags: set[str] = set()
    viewer_langs: set[str] = set()
    try:
        if my_profile:
            raw_tags = (getattr(my_profile, "interests", "") or "").strip().lower()
            if raw_tags:
                viewer_tags |= {p.strip() for p in raw_tags.split(",") if p.strip()}
            nl = (getattr(my_profile, "native_language", "") or "").strip().lower()
            if nl:
                viewer_langs.add(nl)
            add = (getattr(my_profile, "additional_languages", "") or "").strip().lower()
            if add:
                viewer_langs |= {p.strip() for p in add.split(",") if p.strip()}
    except Exception:
        viewer_langs = set()

    for item in ranked:
        profile = item.profile
        compat = item.compatibility
        pr = ProfileRiskEvaluator.evaluate_profile_risk(profile)
        penalty = max(0, pr.risk_score - 40) * 0.15  # small, explainable penalty
        adjusted = compat.compatibility_score - penalty
        quality = compute_profile_quality(profile)
        if quality.quality_flag == "low_quality":
            adjusted -= LOW_QUALITY_DISCOVER_PENALTY  # subtle downrank, never hard-hide
            low_quality_seen += 1
            if viewer_first_hook:
                adjusted -= FIRST_HOOK_LOW_QUALITY_EXTRA_PENALTY
        if viewer_fresh_session and quality.quality_flag == "ok":
            adjusted += FIRST_HOOK_FOCUS_BOOST
            if float(compat.compatibility_score or 0) >= 72:
                adjusted += FIRST_HOOK_HIGH_COMPAT_EXTRA
        is_verified = _is_profile_verified_approved(profile)
        cand_premium = bool(premium_active_map.get(int(profile.user_id)))
        discover_tier = 3 if cand_premium and is_verified else (2 if is_verified else 1)
        if int(profile.user_id) in premium_plus_ids:
            adjusted += float(PREMIUM_PLUS_DISCOVER_BIAS)
            discover_tier = max(int(discover_tier), 3)
        if is_verified:
            adjusted += VERIFIED_DISCOVER_BOOST
            verified_seen += 1

        # Smart sorting components (Tinder/Bumble feel):
        # score = interests_overlap + same_city + language_match + activity_score
        same_city = 0
        if viewer_city:
            cand_city = (getattr(profile, "city", "") or "").strip().lower()
            if cand_city and cand_city == viewer_city:
                same_city = 1
        language_match = 0
        if viewer_langs:
            cand_langs: set[str] = set()
            nl = (getattr(profile, "native_language", "") or "").strip().lower()
            if nl:
                cand_langs.add(nl)
            add = (getattr(profile, "additional_languages", "") or "").strip().lower()
            if add:
                cand_langs |= {p.strip() for p in add.split(",") if p.strip()}
            language_match = len(viewer_langs.intersection(cand_langs))
        interests_overlap = 0
        shared_interests: list[str] = []
        if viewer_tags:
            cand_tags = (getattr(profile, "interests", "") or "").strip().lower()
            if cand_tags:
                cand_set = {p.strip() for p in cand_tags.split(",") if p.strip()}
                shared = sorted(list(viewer_tags.intersection(cand_set)))
                interests_overlap = len(shared)
                shared_interests = shared[:3]
        activity_score = _activity_boost(int(profile.user_id))
        smart_score = float(interests_overlap) + float(same_city) + float(min(3, language_match)) + float(activity_score)
        adjusted += smart_score
        rc = int(reply_counts.get(int(profile.user_id), 0))
        response_proxy = min(float(RESPONSE_PROXY_BOOST_MAX), math.log1p(float(rc)) * 1.85)
        adjusted += response_proxy
        if viewer_goal:
            cand_goal = (getattr(profile, "relationship_goal", "") or "").strip().lower()
            if cand_goal and cand_goal == viewer_goal:
                adjusted += 3.0
        if viewer_vibe:
            cand_vibe = (getattr(profile, "vibe", "") or "").strip().lower()
            if cand_vibe and cand_vibe == viewer_vibe:
                adjusted += 2.0
        # Smart Match Boost weights.
        if float(compat.compatibility_score or 0) >= HIGH_COMPAT_THRESHOLD:
            adjusted += HIGH_COMPAT_BOOST
            high_compat_boost_applied += 1
        if int(profile.user_id) in liked_me_ids:
            adjusted += MUTUAL_INTEREST_BOOST
            mutual_boost_applied += 1
        if int(swipe_counts.get(int(profile.user_id), 0)) <= NEW_USER_SWIPES_MAX:
            # Only boost new users who are not low-quality (avoid spam).
            if quality.quality_flag == "ok":
                adjusted += NEW_USER_BOOST
                new_user_boost_applied += 1
        try:
            if is_boost_active(int(profile.user_id)):
                adjusted += BOOSTED_PROFILE_BOOST
        except Exception:
            pass
        # Soft swipe/pass penalties (never hard-remove from candidate pool).
        swipe_info = latest_swipe_by_target.get(int(profile.user_id))
        if swipe_info:
            was_liked, swipe_ts = swipe_info
            if was_liked:
                # If candidate already liked the viewer, ignore prior-like suppression.
                if int(profile.user_id) not in liked_me_ids:
                    adjusted -= 20.0
                    debug["swipe_penalty_applied"] = int(debug.get("swipe_penalty_applied", 0) or 0) + 1
            else:
                age_hours: float | None = None
                if swipe_ts is not None:
                    try:
                        st = swipe_ts
                        if getattr(st, "tzinfo", None) is None:
                            st = st.replace(tzinfo=UTC)
                        age_hours = max(0.0, (now - st).total_seconds() / 3600.0)
                    except Exception:
                        age_hours = None
                if age_hours is not None and age_hours < float(PASS_COOLDOWN_HOURS):
                    adjusted -= 12.0
                    debug["pass_penalty_applied"] = int(debug.get("pass_penalty_applied", 0) or 0) + 1
                else:
                    adjusted -= 8.0
                    debug["pass_penalty_applied"] = int(debug.get("pass_penalty_applied", 0) or 0) + 1
                    debug["recycled_candidates_count"] = int(debug.get("recycled_candidates_count", 0) or 0) + 1
        if not bool(getattr(profile, "onboarding_completed", False)):
            adjusted -= 50.0
            debug["soft_filtered_onboarding"] = int(debug.get("soft_filtered_onboarding", 0) or 0) + 1
        visual_score = None
        if ai_boost and my_emb:
            other_emb = VisualEmbedding.deserialize(getattr(profile, "visual_embedding", "") or "")
            if other_emb and len(other_emb.vector) == len(my_emb.vector):
                sim = max(0.0, min(1.0, cosine_similarity(my_emb.vector, other_emb.vector)))
                visual_score = int(round(sim * 100))
                # Soft weighting: never dominant over core compatibility.
                adjusted = (0.7 * adjusted) + (0.3 * visual_score)
        adjusted += _daily_jitter(int(profile.user_id))
        they_liked_viewer = bool(int(profile.user_id) in liked_me_ids and can_see_who_liked_you)
        interests_list = [x.strip() for x in (getattr(profile, "interests", "") or "").split(",") if x.strip()]
        computed_age = _age_from_dob(getattr(profile, "date_of_birth", None)) or getattr(profile, "age", None)
        vlevel = (getattr(profile, "verification_level", None) or "none").strip().lower() or "none"
        if vlevel not in ("none", "photo", "id"):
            vlevel = "none"
        badge_visible = bool(getattr(profile, "verification_badge_visible", True))
        show_verified_badge = should_show_verified_badge(profile)
        if premium_demo_feed and is_demo_profile(profile):
            show_verified_badge = False
            badge_visible = False
        pu = premium_until_raw.get(int(profile.user_id))
        vibe_raw = (getattr(profile, "vibe", None) or "").strip()
        card = {
            "user_id": profile.user_id,
            "profile_id": getattr(profile, "id", None),
            "display_name": profile.display_name,
            "gender": (getattr(profile, "gender", None) or "").strip(),
            "age": computed_age,
            "city": profile.city,
            "bio": profile.bio,
            "vibe": vibe_raw or None,
            "interests": interests_list,
            "top_interests": interests_list[:3],
            "shared_interests": shared_interests,
            "lifestyle_tags": [x.strip() for x in (getattr(profile, "lifestyle_tags", None) or "").split(",") if x.strip()],
            "photo_urls": [
                normalize_photo_url(x.strip(), demo_profile_gender=getattr(profile, "gender", None))
                for x in (getattr(profile, "photo_urls", "") or "").split(",")
                if x.strip()
            ],
            "compatibility_score": compat.compatibility_score,
            "score_breakdown": compat.score_breakdown,
            "top_reasons": compat.top_reasons,
            "warning_flags": compat.warning_flags,
            # They already liked the viewer — strong mutual-interest signal (client may tease premium).
            "they_liked_you": they_liked_viewer,
            "smart_score": smart_score,
            "badges": {
                "new": bool(int(swipe_counts.get(int(profile.user_id), 0)) <= NEW_USER_SWIPES_MAX),
                "active_now": bool(_active_now(int(profile.user_id))),
                "verified": bool(show_verified_badge),
            },
            "discover_fallback_used": bool(fallback_used_final),
            "discover_fallback_stage": str(fallback_stage_final) if fallback_used_final else None,
            "discover_profile_incomplete": bool(not getattr(profile, "onboarding_completed", False)),
            "discover_missing_photo": bool(
                not (_profile_has_demo_folder_photo(profile) if premium_demo_feed and is_demo_profile(profile) else _profile_has_valid_photo(profile))
            ),
        }
        try:
            card["boost_active"] = bool(is_boost_active(int(profile.user_id)))
        except Exception:
            card["boost_active"] = False
        demo_card = is_demo_profile(profile)
        card["is_demo_profile"] = demo_card
        card["demo_premium_showcase"] = bool(premium_demo_feed) and bool(demo_card)
        card["demo_label"] = DEMO_PROFILE_LABEL if demo_card else None
        card["demo_disclaimer"] = (getattr(profile, "demo_disclaimer", "") or DEMO_PROFILE_DISCLAIMER) if demo_card else None
        if demo_card:
            try:
                _dp = json.loads(getattr(profile, "demo_personality_json", "") or "{}")
                if isinstance(_dp, dict):
                    card["demo_personality_type"] = str(
                        _dp.get("personality_type") or _dp.get("personality") or "calm"
                    )
            except Exception:
                card["demo_personality_type"] = "calm"
        # Safe, human UI flags (no internal reasons exposed).
        card["trusted"] = "high" if quality.quality_flag == "ok" else "low"
        card["profile_quality"] = "high" if quality.quality_flag == "ok" else "low"
        # Keep both for backwards-compatible clients, but prefer `is_verified`.
        card["verified"] = is_verified
        card["is_verified"] = is_verified
        card["verification_level"] = vlevel
        card["verification_badge_visible"] = badge_visible
        card["is_premium"] = cand_premium
        if cand_premium and pu is not None:
            try:
                card["premium_until"] = pu.isoformat() if hasattr(pu, "isoformat") else None
            except Exception:
                card["premium_until"] = None
        else:
            card["premium_until"] = None
        if ai_boost and visual_score is not None:
            card["ai_match"] = visual_score >= 78
            card["visual_compatibility"] = visual_score
        if advanced:
            card["compatibility_reasons"] = compat.top_reasons
        # Include demo flag for strict real-first ordering in mixed decks.
        decorated.append((adjusted, card, pr, quality.quality_flag, is_verified, profile, discover_tier, demo_card))
    # Sort: real profiles first, then premium+verified > verified > normal, then adjusted score.
    decorated.sort(key=lambda x: (bool(x[7]), -float(x[6] or 0), -float(x[0] or 0)))

    # Ensure first 3 cards are strongest candidates.
    strong: list[tuple] = []
    rest: list[tuple] = []
    for row in decorated:
        _adj, card, pr, qflag, is_v, profile, _tier, _is_demo = row
        if _is_strong_profile(profile, qflag, is_v):
            strong.append(row)
        else:
            rest.append(row)
    verified_ok = [r for r in rest if r[3] == "ok" and r[4] is True]
    active_ok = sorted(
        [r for r in rest if r[3] == "ok"],
        key=lambda r: _activity_boost(int(r[1]["user_id"])),
        reverse=True,
    )
    picked: list[tuple] = []
    for bucket in (strong, verified_ok, active_ok, rest):
        for r in bucket:
            if r in picked:
                continue
            picked.append(r)
        if len(picked) >= len(decorated):
            break
    decorated = picked[: len(decorated)]

    # Ensure very high compatibility real candidates appear early (top ~5) without letting demos jump real users.
    # Deterministic: stable by current order.
    high_compat_real = [
        r for r in decorated if not bool(r[7]) and float(r[1].get("compatibility_score") or 0) >= HIGH_COMPAT_THRESHOLD and r[3] == "ok"
    ]
    if high_compat_real:
        remaining = [r for r in decorated if r not in high_compat_real]
        decorated = (high_compat_real + remaining)[: len(decorated)]

    for _adj, card, pr, _qflag, _is_v, _profile, _tier, _is_demo in decorated:
        if pr.risk_score >= 60:
            track_event(db, "suspicious_profile_detected", user_id=card["user_id"], payload={"risk_score": pr.risk_score, "flags": pr.flags})
        cards.append(card)

    # Aggregate analytics for boosts (single event per feed request).
    if mutual_boost_applied > 0:
        track_event(
            db,
            "mutual_interest_boost_applied",
            user_id=current_user.id,
            payload={"count": int(mutual_boost_applied), "window": int(candidate_window)},
        )
    if high_compat_boost_applied > 0:
        track_event(
            db,
            "high_compatibility_boost_applied",
            user_id=current_user.id,
            payload={"count": int(high_compat_boost_applied), "threshold": float(HIGH_COMPAT_THRESHOLD)},
        )
    boosted_shown = int(mutual_boost_applied + high_compat_boost_applied + new_user_boost_applied)
    if boosted_shown > 0:
        track_event(
            db,
            "boosted_profile_shown",
            user_id=current_user.id,
            payload={
                "count": boosted_shown,
                "mutual": int(mutual_boost_applied),
                "high_compat": int(high_compat_boost_applied),
                "new_user": int(new_user_boost_applied),
            },
        )
    track_event(
        db,
        "trust_impact_on_match",
        user_id=current_user.id,
        payload={
            "surface": "discover_feed",
            "candidate_window": int(candidate_window),
            "verified_count": int(verified_seen),
            "low_quality_count": int(low_quality_seen),
            "verified_boost": VERIFIED_DISCOVER_BOOST,
            "low_quality_penalty": LOW_QUALITY_DISCOVER_PENALTY,
        },
    )
    track_event(
        db,
        "discover_feed_viewed",
        user_id=current_user.id,
        payload={
            "count": len(cards[:limit]),
            "first_hook_window": bool(viewer_first_hook),
            "fresh_session": bool(viewer_fresh_session),
        },
    )
    # Real-first ordering: demo profiles must never crowd out real candidates.
    real_out = [c for c in cards if isinstance(c, dict) and not bool(c.get("is_demo_profile"))]
    demo_out = [c for c in cards if isinstance(c, dict) and bool(c.get("is_demo_profile"))]
    if strict_count > 0:
        demo_out = []
    if premium_demo_feed:
        out = demo_out[:limit]
        demo_count = sum(1 for card in out if bool(card.get("is_demo_profile")))
        real_count = sum(1 for card in out if not bool(card.get("is_demo_profile")))
        logger.info("discover_candidate_source", extra={"real_count": int(real_count), "demo_count": int(demo_count), "strict_count": int(strict_count)})
        if demo_count:
            track_event(db, "demo_mode_started", user_id=current_user.id, payload={"surface": "discover_feed", "count": demo_count})
        env = (settings.ENV or "").strip().lower()
        ttl = 60 if env in ("production", "prod") else 25
        try:
            debug["returned_ids"] = [int(card.get("user_id") or 0) for card in out if isinstance(card, dict) and card.get("user_id")]
            logger.info(json.dumps({"event": "discover_feed_debug", **debug}, default=str))
        except Exception:
            pass
        if not debug_response:
            cache_set(ck, out, ttl)
        if debug_response:
            return {"feed": out, "debug": debug}
        return out
    liked_real_out: list[dict] = []
    recent_pass_real_out: list[dict] = []
    unliked_non_recent_pass_real_out: list[dict] = []
    for c in real_out:
        uid = int(c.get("user_id") or 0)
        was_liked, swipe_ts = latest_swipe_by_target.get(uid, (False, None))
        if was_liked and uid not in liked_me_ids:
            liked_real_out.append(c)
            continue
        is_recent_pass = False
        if swipe_ts is not None:
            try:
                st = swipe_ts
                if getattr(st, "tzinfo", None) is None:
                    st = st.replace(tzinfo=UTC)
                is_recent_pass = bool(st >= pass_hide_since)
            except Exception:
                is_recent_pass = False
        if is_recent_pass:
            recent_pass_real_out.append(c)
        else:
            unliked_non_recent_pass_real_out.append(c)
    out = unliked_non_recent_pass_real_out[:limit]
    if len(out) < limit:
        out = out + demo_out[: max(0, limit - len(out))]
    # Recycle recent passes only if needed to avoid empty/tiny feed.
    if len(out) < limit:
        out = out + recent_pass_real_out[: max(0, limit - len(out))]
    if len(out) < limit:
        out = out + liked_real_out[: max(0, limit - len(out))]
    # Variable reward: not every session — occasional “lucky” surface for dopamine (UI-only hints).
    if offset == 0 and out and random.random() < 0.26:
        idx = random.randint(0, min(2, len(out) - 1))
        target = out[idx]
        if isinstance(target, dict):
            roll = random.random()
            cs = float(target.get("compatibility_score") or 0)
            if roll < 0.34 and cs >= 78:
                target["variable_reward"] = "spark_match"
            elif roll < 0.62 and (target.get("profile_quality") == "high" or target.get("trusted") == "high"):
                target["variable_reward"] = "quality_spotlight"
            elif random.random() < 0.5:
                target["variable_reward"] = "lucky_pick"
            if target.get("variable_reward"):
                target["variable_reward_delay_ms"] = int(400 + random.random() * 900)
    demo_count = sum(1 for card in out if bool(card.get("is_demo_profile")))
    real_count = sum(1 for card in out if not bool(card.get("is_demo_profile")))
    logger.info("discover_candidate_source", extra={"real_count": int(real_count), "demo_count": int(demo_count), "strict_count": int(strict_count)})
    if demo_count:
        track_event(db, "demo_mode_started", user_id=current_user.id, payload={"surface": "discover_feed", "count": demo_count})
    env = (settings.ENV or "").strip().lower()
    ttl = 60 if env in ("production", "prod") else 25
    try:
        debug["returned_ids"] = [int(card.get("user_id") or 0) for card in out if isinstance(card, dict) and card.get("user_id")]
        logger.info(json.dumps({"event": "discover_feed_debug", **debug}, default=str))
    except Exception:
        pass
    if not debug_response:
        cache_set(ck, out, ttl)
    if debug_response:
        return {"feed": out, "debug": debug}
    return out


@router.get("/debug-candidate")
def discover_debug_candidate(
    candidate_user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explain why viewer cannot see candidate in Discover."""
    viewer = current_user
    cand_user = db.query(User).filter(User.id == int(candidate_user_id)).first()
    cand_profile = db.query(Profile).filter(Profile.user_id == int(candidate_user_id)).first()
    if not cand_user or not cand_profile:
        raise HTTPException(status_code=404, detail={"error": "candidate_not_found"})
    breakdown = discover_candidate_debug_breakdown(
        db,
        viewer=viewer,
        candidate_user=cand_user,
        candidate_profile=cand_profile,
    )
    reasons = list(breakdown.get("excluded_reasons") or [])

    matched = (
        db.query(Match.id)
        .filter(
            ((Match.user_a_id == int(viewer.id)) & (Match.user_b_id == int(candidate_user_id)))
            | ((Match.user_a_id == int(candidate_user_id)) & (Match.user_b_id == int(viewer.id)))
        )
        .first()
        is not None
    )
    if matched:
        reasons.append("already_matched")
    if "gender_match" in reasons:
        reasons.append("gender")
    if "age_match" in reasons:
        reasons.append("age")
    if "has_photo" in reasons:
        reasons.append("photo")
    if "onboarding_completed" in reasons:
        reasons.append("onboarding")
    reasons = sorted(set(reasons))

    return {
        "viewer_user_id": int(viewer.id),
        "candidate_user_id": int(candidate_user_id),
        "eligible": len(reasons) == 0,
        "reasons": reasons,
        "breakdown": {**breakdown, "eligible": len(reasons) == 0, "excluded_reasons": reasons},
    }


@router.get("")
@router.get("/", include_in_schema=False)
def discover_feed_alias(
    limit: int = 20,
    offset: int = 0,
    verified_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Alias for legacy clients that call GET /api/v1/discover.
    Internally, Discover is served by GET /api/v1/discover/feed.
    """
    return discover_feed(
        limit=limit,
        offset=offset,
        verified_only=verified_only,
        current_user=current_user,
        db=db,
    )
