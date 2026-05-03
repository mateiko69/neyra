"""
First-match helpers for onboarding: ranked real candidates, then demo fallback.
Gender preference mirrors Discover (see discover.py).
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.match import Match
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.user import User
from app.services.ai.ranking_engine.service import RankingEngineService
from app.services.safety import blocked_user_ids, ignored_user_ids

_FEMALE_TOKENS: tuple[str, ...] = ("woman", "female", "girl", "f")
_MALE_TOKENS: tuple[str, ...] = ("man", "male", "guy", "m")


def _viewer_gender_bucket(viewer_profile: Profile | None) -> str | None:
    if not viewer_profile:
        return None
    g = (getattr(viewer_profile, "gender", None) or "").strip().lower()
    if g in ("man", "male", "guy", "m", "masculine"):
        return "male"
    if g in ("woman", "female", "girl", "f", "feminine"):
        return "female"
    return None


def _discover_gender_tokens(viewer_profile: Profile | None) -> list[str] | None:
    if not viewer_profile:
        return None
    pref = (getattr(viewer_profile, "preferred_gender", None) or "").strip().lower()
    if pref == "male":
        return list(_MALE_TOKENS)
    if pref == "female":
        return list(_FEMALE_TOKENS)
    if pref in ("everyone", "all", "any"):
        return None
    interest = (getattr(viewer_profile, "interested_in", None) or "").strip().lower()
    if interest == "women":
        return list(_FEMALE_TOKENS)
    if interest == "men":
        return list(_MALE_TOKENS)
    if interest == "everyone":
        return None
    bucket = _viewer_gender_bucket(viewer_profile)
    if bucket == "male":
        return list(_FEMALE_TOKENS)
    if bucket == "female":
        return list(_MALE_TOKENS)
    return None


def _apply_discover_gender_filter(query, viewer_profile: Profile | None):
    tokens = _discover_gender_tokens(viewer_profile)
    if not tokens:
        return query
    lg = func.lower(func.trim(Profile.gender))
    return query.filter(lg.in_(tokens))


def count_matches_for_user(db: Session, user_id: int) -> int:
    uid = int(user_id)
    return int(db.query(Match).filter(or_(Match.user_a_id == uid, Match.user_b_id == uid)).count())


def newest_match_for_user(db: Session, user_id: int) -> Match | None:
    uid = int(user_id)
    return (
        db.query(Match)
        .filter(or_(Match.user_a_id == uid, Match.user_b_id == uid))
        .order_by(Match.id.desc())
        .first()
    )


def partner_user_id_from_match(row: Match, viewer_id: int) -> int:
    if int(row.user_a_id) == int(viewer_id):
        return int(row.user_b_id)
    return int(row.user_a_id)


def first_demo_profile_for_starter(db: Session) -> Profile | None:
    return (
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(User.is_demo == True)  # noqa: E712
        .order_by(Profile.user_id.asc())
        .first()
    )


def _base_real_candidate_query(db: Session, viewer_id: int):
    swiped_ids_stmt = select(Swipe.target_user_id).where(Swipe.swiper_id == int(viewer_id))
    blocked_ids = blocked_user_ids(db, int(viewer_id))
    ignored_ids = ignored_user_ids(db, int(viewer_id))
    q = (
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(Profile.user_id != int(viewer_id))
        .filter(~Profile.user_id.in_(swiped_ids_stmt))
        .filter(User.is_deleted == False)  # noqa: E712
        .filter(User.is_banned == False)  # noqa: E712
        .filter(Profile.is_demo_profile == False)  # noqa: E712
        .filter(User.is_demo == False)  # noqa: E712
    )
    try:
        admin_emails = set(settings.admin_emails_list())
        if admin_emails:
            q = q.filter(~User.email.in_(list(admin_emails)))
    except Exception:
        pass
    q = q.filter((Profile.display_name.is_(None)) | (Profile.display_name != "Admin"))
    if blocked_ids:
        q = q.filter(~Profile.user_id.in_(blocked_ids))
    if ignored_ids:
        q = q.filter(~Profile.user_id.in_(ignored_ids))
    q = q.filter(Profile.photo_urls.isnot(None)).filter(func.trim(Profile.photo_urls) != "")
    return q


def pick_ranked_starter_candidate(db: Session, viewer_id: int, viewer_profile: Profile | None) -> Profile | None:
    """Highest compatibility among eligible real profiles (Discover-style filters), then without gender filter."""
    q = _base_real_candidate_query(db, viewer_id)
    q = _apply_discover_gender_filter(q, viewer_profile)
    candidates = q.limit(400).all()
    ranked = RankingEngineService.rank(viewer_profile, candidates)
    if ranked:
        return ranked[0].profile

    q_broad = _base_real_candidate_query(db, viewer_id)
    candidates_broad = q_broad.limit(400).all()
    ranked_broad = RankingEngineService.rank(viewer_profile, candidates_broad)
    if ranked_broad:
        return ranked_broad[0].profile
    return None
