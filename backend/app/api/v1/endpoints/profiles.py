from datetime import UTC, datetime
import json
import random
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi import Body
from app.api.api_errors import api_error
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.user_ignore import UserIgnore
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.verification_attempt import VerificationAttempt
from app.schemas.profile import PartnerProfilePublic, ProfileOut, ProfilePatch, ProfileUpdate
from app.services.antifraud import score_account_risk
from app.services.match_partner import users_are_matched
from app.services.analytics import track_event
from app.services.ai.cache import bump_user_cache_version
from app.core.config import settings
from app.services.demo_mode import DEMO_PROFILE_DISCLAIMER, DEMO_PROFILE_LABEL, is_demo_profile
from app.services.safety import is_blocked
from app.services.storage.upload_utils import persist_verification_selfie, read_validate_image
from app.services.visual_embeddings import (
    VisualEmbedding,
    compute_visual_embedding_from_bytes,
    compute_visual_embedding_from_url,
    cosine_similarity,
)
from app.utils.media_urls import normalize_photo_url
from app.utils.datetime_utc import to_utc_aware
from app.services.premium import is_user_premium
from app.services.trust.verification_state import (
    VERIFICATION_POSE_CHALLENGES,
    is_verified_profile,
    normalize_verification_status,
    verification_status_for_api,
    verification_type_for_api,
)
from app.services.ai.cache import get_redis

router = APIRouter()
logger = logging.getLogger(__name__)

def _is_production_env() -> bool:
    return (settings.ENV or "").strip().lower() in ("production", "prod")


def _split_csv_list(s: str) -> list[str]:
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def _age_from_dob(dob) -> int | None:
    try:
        if not dob:
            return None
        # `dob` is usually a `date`, but be permissive.
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


def _onboarding_min_complete(profile: Profile | None) -> bool:
    """
    Minimal onboarding completion gate used by the new onboarding flow.
    Required (per product spec):
    - display_name
    - gender
    - interested_in
    - age OR date_of_birth (18+)
    - photos >= 1
    """
    if not profile:
        return False
    if not (getattr(profile, "display_name", "") or "").strip():
        return False
    if not (getattr(profile, "gender", "") or "").strip():
        return False
    if not (getattr(profile, "interested_in", "") or "").strip():
        return False
    photos = [p.strip() for p in (getattr(profile, "photo_urls", "") or "").split(",") if p.strip()]
    if len(photos) < 1:
        return False
    age = getattr(profile, "age", None)
    if age is None:
        age = _age_from_dob(getattr(profile, "date_of_birth", None))
    try:
        if age is None or int(age) < 18:
            return False
    except Exception:
        return False
    return True


def _onboarding_is_complete(profile: Profile | None) -> bool:
    """
    Server-authoritative onboarding completion.
    Must not rely on frontend flags.

    Strict completion (match-ready).
    Required:
    - display_name
    - date_of_birth (18+)
    - city
    - gender
    - interested_in
    - relationship_goal (looking_for)
    - min_preferred_age/max_preferred_age (valid; min>=18, max>=min)
    - vibe
    - photos >= 1
    - interests/tags: at least 3 selected
    - native_language
    """
    if not profile:
        return False
    if not (getattr(profile, "display_name", "") or "").strip():
        return False
    dob = getattr(profile, "date_of_birth", None)
    if not dob:
        return False
    # Enforce 18+ from DOB (age column may be stale).
    age = _age_from_dob(dob)
    if age is None or int(age) < 18:
        return False
    if not (getattr(profile, "city", "") or "").strip():
        return False
    if not (getattr(profile, "vibe", "") or "").strip():
        return False
    if not (getattr(profile, "gender", "") or "").strip():
        return False
    if not (getattr(profile, "interested_in", "") or "").strip():
        return False
    photos = [p.strip() for p in (getattr(profile, "photo_urls", "") or "").split(",") if p.strip()]
    if len(photos) < 1:
        return False
    if not (getattr(profile, "relationship_goal", "") or "").strip():
        return False
    mn = getattr(profile, "min_preferred_age", None)
    mx = getattr(profile, "max_preferred_age", None)
    try:
        if mn is None or mx is None:
            return False
        if int(mn) < 18:
            return False
        if int(mx) < int(mn):
            return False
    except Exception:
        return False
    # Tags/interests: require at least 3.
    tags = [p.strip() for p in (getattr(profile, "interests", "") or "").split(",") if p.strip()]
    if len(tags) < 3:
        return False
    if not (getattr(profile, "native_language", "") or "").strip():
        return False
    return True


def _is_verified_approved(profile: Profile | None) -> bool:
    """Back-compat name: verification is driven by `verification_status == verified`."""
    return is_verified_profile(profile)


def _profile_out_normalized(profile: Profile, db: Session, user: User) -> ProfileOut:
    out = ProfileOut.model_validate(profile)
    parts = [p.strip() for p in (out.photo_urls or "").split(",") if p.strip()]
    g = (getattr(profile, "gender", None) or None)
    normalized = ",".join(normalize_photo_url(p, demo_profile_gender=g) for p in parts)
    is_demo = is_demo_profile(profile)
    is_v = is_verified_profile(profile)
    level = (getattr(profile, "verification_level", None) or "none").strip().lower() or "none"
    if level not in ("none", "photo", "id"):
        level = "none"
    badge_visible = bool(getattr(profile, "verification_badge_visible", True))
    v_status_api = verification_status_for_api(profile)
    v_type_api = verification_type_for_api(profile)
    pu = to_utc_aware(getattr(user, "premium_until", None))
    premium_active = bool(is_user_premium(db, int(user.id)))
    return out.model_copy(
        update={
            "photo_urls": normalized,
            "verification_status": v_status_api,
            "verification_type": v_type_api,
            "verification_level": level,
            "verification_badge_visible": badge_visible,
            "is_verified": is_v,
            "verified": is_v,
            "is_premium": premium_active,
            "premium_until": pu,
            "is_demo_profile": is_demo,
            "demo_label": DEMO_PROFILE_LABEL if is_demo else None,
            "demo_disclaimer": (getattr(profile, "demo_disclaimer", "") or DEMO_PROFILE_DISCLAIMER) if is_demo else None,
        }
    )


def _get_or_create_verification_attempt(db: Session, *, user_id: int, day: str) -> VerificationAttempt:
    attempt = db.query(VerificationAttempt).filter(VerificationAttempt.user_id == user_id, VerificationAttempt.day == day).first()
    if attempt:
        return attempt
    attempt = VerificationAttempt(user_id=user_id, day=day, count=0, updated_at=datetime.now(UTC))
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        attempt = db.query(VerificationAttempt).filter(VerificationAttempt.user_id == user_id, VerificationAttempt.day == day).first()
        if attempt:
            return attempt
        raise
    db.refresh(attempt)
    return attempt


@router.get("/me", response_model=ProfileOut)
def get_my_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    out = _profile_out_normalized(profile, db, current_user)
    try:
        out = out.model_copy(update={"last_active_at": getattr(current_user, "last_active_at", None)})
    except Exception:
        pass
    return out


@router.get("/founder-welcome")
def founder_welcome_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    show = bool(getattr(profile, "onboarding_completed", False)) and not bool(getattr(profile, "founder_welcome_seen", False))
    return {
        "show": show,
        "founder_welcome_seen": bool(getattr(profile, "founder_welcome_seen", False)),
        "onboarding_completed": bool(getattr(profile, "onboarding_completed", False)),
    }


@router.post("/founder-welcome/seen")
def mark_founder_welcome_seen(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    first_seen = not bool(getattr(profile, "founder_welcome_seen", False))
    profile.founder_welcome_seen = True
    db.add(profile)
    db.commit()
    if first_seen:
        track_event(db, "founder_welcome_seen", user_id=current_user.id, payload={"source": "post_registration"})
    return {"ok": True, "founder_welcome_seen": True}

@router.patch("/me", response_model=ProfileOut)
def patch_my_profile(payload: ProfilePatch, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    onboarding_before = bool(getattr(profile, "onboarding_completed", False))
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail=api_error("profile.no_fields_to_update"))

    # Client may request onboarding completion, but backend enforces completeness.
    requested_onboarding_completed = None
    if "onboarding_completed" in updates:
        requested_onboarding_completed = bool(updates.pop("onboarding_completed"))

    # Track changes (dev-only diagnostics).
    before_values: dict[str, object] = {k: getattr(profile, k, None) for k in updates.keys()}
    changed_fields: set[str] = set()

    # Photo convenience: accept `photo_url` / `primary_photo_url` and map into `photo_urls`.
    photo_url = str(updates.pop("photo_url", "") or "").strip()
    primary_photo_url = str(updates.pop("primary_photo_url", "") or "").strip()
    if primary_photo_url or photo_url:
        before_values.setdefault("photo_urls", getattr(profile, "photo_urls", None))
        current = [p.strip() for p in (profile.photo_urls or "").split(",") if p.strip()]
        if primary_photo_url:
            # Ensure it exists and becomes index 0.
            current = [p for p in current if p != primary_photo_url]
            current.insert(0, primary_photo_url)
        elif photo_url:
            if photo_url not in current:
                current.append(photo_url)
        new_photo_urls = ",".join(current[:12])
        if (profile.photo_urls or "") != new_photo_urls:
            profile.photo_urls = new_photo_urls
            changed_fields.add("photo_urls")

    for field, value in updates.items():
        # Prevent accidental empty display_name via PATCH.
        if field == "display_name" and isinstance(value, str) and not value.strip():
            continue
        if getattr(profile, field, None) != value:
            changed_fields.add(field)
        setattr(profile, field, value)

    # If profile is now complete, lock onboarding as completed.
    try:
        is_complete = _onboarding_is_complete(profile)
        if requested_onboarding_completed is True:
            if not is_complete:
                raise HTTPException(status_code=400, detail=api_error("profile.onboarding_incomplete"))
            setattr(profile, "onboarding_completed", True)
        elif is_complete:
            setattr(profile, "onboarding_completed", True)
    except Exception:
        pass
    onboarding_after = bool(getattr(profile, "onboarding_completed", False))
    if (not onboarding_before) and onboarding_after:
        logger.info("onboarding_completed_set user_id=%s profile_id=%s", int(current_user.id), int(getattr(profile, "id", 0) or 0))
    db.add(profile)
    commit_ok = True
    try:
        db.commit()
    except Exception as e:
        commit_ok = False
        db.rollback()
        if not _is_production_env():
            logger.exception(
                json.dumps(
                    {
                        "event": "profile_save",
                        "method": "PATCH",
                        "path": "/api/v1/profiles/me",
                        "user_id": int(current_user.id),
                        "profile_id": int(getattr(profile, "id", 0) or 0),
                        "onboarding_completed_before": onboarding_before,
                        "onboarding_completed_after": onboarding_after,
                        "changed_fields": sorted(list(changed_fields)),
                        "commit_success": False,
                        "error": str(e),
                    },
                    default=str,
                )
            )
        else:
            logger.error("profile_save_failed user_id=%s method=PATCH", int(current_user.id))
        raise HTTPException(status_code=500, detail=api_error("profile.save_failed")) from e
    db.refresh(profile)
    logger.info({"event": "onboarding_check", "user_id": int(current_user.id), "completed": bool(getattr(profile, "onboarding_completed", False))})
    track_event(db, "profile_patched", user_id=current_user.id, payload={"fields": list(updates.keys())})
    bump_user_cache_version("discover_feed", int(current_user.id))

    if not _is_production_env():
        logger.info(
            json.dumps(
                {
                    "event": "profile_save",
                    "method": "PATCH",
                    "path": "/api/v1/profiles/me",
                    "user_id": int(current_user.id),
                    "profile_id": int(profile.id),
                    "onboarding_completed_before": onboarding_before,
                    "onboarding_completed_after": onboarding_after,
                    "changed_fields": sorted(list(changed_fields)),
                    "commit_success": bool(commit_ok),
                },
                default=str,
            )
        )
    out = _profile_out_normalized(profile, db, current_user)
    try:
        out = out.model_copy(update={"last_active_at": getattr(current_user, "last_active_at", None)})
    except Exception:
        pass
    return out


@router.put("/me", response_model=ProfileOut)
def update_my_profile(payload: ProfileUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    onboarding_before = bool(getattr(profile, "onboarding_completed", False))

    # Treat PUT as "replace provided fields" (idempotent, safe for partial clients):
    # only apply fields that the client explicitly sent. This prevents accidental resets
    # when the client sends a schema-shaped body with defaults/empties.
    incoming = payload.model_dump(exclude_unset=True)
    fields_set = getattr(payload, "model_fields_set", set()) or set()

    before_values: dict[str, object] = {k: getattr(profile, k, None) for k in incoming.keys()}
    changed_fields: set[str] = set()

    # Protect photo persistence: never overwrite existing photos with missing/empty values on PUT.
    existing_photos = (profile.photo_urls or "").strip()
    incoming_photo_urls = str(incoming.get("photo_urls", "") or "").strip()
    if existing_photos:
        existing_list = [p.strip() for p in existing_photos.split(",") if p.strip()]
        incoming_list = [p.strip() for p in incoming_photo_urls.split(",") if p.strip()]

        if ("photo_urls" not in fields_set) or (incoming_photo_urls == ""):
            # Client didn't mean to update photos; keep exactly what we have.
            incoming["photo_urls"] = existing_photos
        else:
            # Client sent a potentially stale list; never allow PUT to drop existing photos.
            merged = incoming_list + [p for p in existing_list if p not in incoming_list]
            merged_csv = ",".join(merged[:12])
            if merged_csv != incoming_photo_urls:
                incoming["photo_urls"] = merged_csv

    for field, value in incoming.items():
        # Never allow PUT to clear user-entered strings with empty defaults.
        if isinstance(value, str) and value.strip() == "":
            existing = getattr(profile, field, None)
            if isinstance(existing, str) and existing.strip():
                continue
        # Never allow PUT to null out existing numeric preferences unless explicitly set.
        if value is None and getattr(profile, field, None) is not None:
            continue
        if getattr(profile, field, None) != value:
            changed_fields.add(field)
        setattr(profile, field, value)

    # If profile is now complete, lock onboarding as completed (server-authoritative).
    try:
        if _onboarding_is_complete(profile):
            setattr(profile, "onboarding_completed", True)
    except Exception:
        pass
    onboarding_after = bool(getattr(profile, "onboarding_completed", False))
    if (not onboarding_before) and onboarding_after:
        logger.info("onboarding_completed_set user_id=%s profile_id=%s", int(current_user.id), int(getattr(profile, "id", 0) or 0))

    # Precompute visual embedding when photos change (internal-only).
    try:
        parts = [p.strip() for p in (profile.photo_urls or "").split(",") if p.strip()]
        primary = normalize_photo_url(parts[0], demo_profile_gender=getattr(profile, "gender", None)) if parts else ""
        emb = compute_visual_embedding_from_url(primary) if primary else None
        profile.visual_embedding = emb.serialize() if emb else ""
    except Exception:
        profile.visual_embedding = profile.visual_embedding or ""

    db.add(profile)
    commit_ok = True
    try:
        db.commit()
    except Exception as e:
        commit_ok = False
        db.rollback()
        if not _is_production_env():
            logger.exception(
                json.dumps(
                    {
                        "event": "profile_save",
                        "method": "PUT",
                        "path": "/api/v1/profiles/me",
                        "user_id": int(current_user.id),
                        "profile_id": int(getattr(profile, "id", 0) or 0),
                        "onboarding_completed_before": onboarding_before,
                        "onboarding_completed_after": onboarding_after,
                        "changed_fields": sorted(list(changed_fields)),
                        "commit_success": False,
                        "error": str(e),
                    },
                    default=str,
                )
            )
        else:
            logger.error("profile_save_failed user_id=%s method=PUT", int(current_user.id))
        raise HTTPException(status_code=500, detail=api_error("profile.save_failed")) from e
    db.refresh(profile)
    logger.info({"event": "onboarding_check", "user_id": int(current_user.id), "completed": bool(getattr(profile, "onboarding_completed", False))})
    track_event(db, "profile_updated", user_id=current_user.id, payload={"profile_id": profile.id})
    bump_user_cache_version("discover_feed", int(current_user.id))

    if not _is_production_env():
        logger.info(
            json.dumps(
                {
                    "event": "profile_save",
                    "method": "PUT",
                    "path": "/api/v1/profiles/me",
                    "user_id": int(current_user.id),
                    "profile_id": int(profile.id),
                    "onboarding_completed_before": onboarding_before,
                    "onboarding_completed_after": onboarding_after,
                    "changed_fields": sorted(list(changed_fields)),
                    "commit_success": bool(commit_ok),
                },
                default=str,
            )
        )
    out = _profile_out_normalized(profile, db, current_user)
    try:
        out = out.model_copy(update={"last_active_at": getattr(current_user, "last_active_at", None)})
    except Exception:
        pass
    return out

@router.get("/me/risk")
def my_profile_risk(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    return score_account_risk(profile.__dict__)


@router.get("/partner/{user_id}", response_model=PartnerProfilePublic)
def get_partner_public_profile(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail=api_error("profile.use_me_endpoint"))
    if not users_are_matched(db, current_user.id, user_id):
        # Allow opening profile in two safe cases:
        # - incoming-like flow (they liked the viewer)
        incoming_like = (
            db.query(Swipe.id)
            .filter(Swipe.swiper_id == int(user_id))
            .filter(Swipe.target_user_id == int(current_user.id))
            .filter(Swipe.liked == True)  # noqa: E712
            .first()
            is not None
        )
        if not incoming_like:
            # - discover-visible flow (e.g. tapping a Discover card)
            discover_visible = False
            try:
                if not is_blocked(db, int(current_user.id), int(user_id)):
                    viewer_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
                    cand_profile = db.query(Profile).filter(Profile.user_id == user_id).first()
                    if viewer_profile and cand_profile and _onboarding_min_complete(cand_profile):
                        already_swiped = (
                            db.query(Swipe.id)
                            .filter(Swipe.swiper_id == int(current_user.id), Swipe.target_user_id == int(user_id))
                            .first()
                            is not None
                        )
                        ignored = (
                            db.query(UserIgnore)
                            .filter(UserIgnore.user_id == int(current_user.id), UserIgnore.ignored_user_id == int(user_id))
                            .first()
                            is not None
                        )
                        if not already_swiped and not ignored:
                            # Symmetric age preference check (matches Discover behavior).
                            v_age = getattr(viewer_profile, "age", None)
                            c_age = getattr(cand_profile, "age", None)
                            mn = int(getattr(viewer_profile, "min_preferred_age", 18) or 18)
                            mx = int(getattr(viewer_profile, "max_preferred_age", 99) or 99)
                            cmn = int(getattr(cand_profile, "min_preferred_age", 18) or 18)
                            cmx = int(getattr(cand_profile, "max_preferred_age", 99) or 99)
                            if v_age is None or c_age is None:
                                discover_visible = True
                            else:
                                discover_visible = (mn <= int(c_age) <= mx) and (cmn <= int(v_age) <= cmx)
            except Exception:
                discover_visible = False

        if not incoming_like and not discover_visible:
            # Keep security (403), but return a stable structured error for UX.
            raise HTTPException(status_code=403, detail=api_error("chat.match_required"))
    partner = db.query(User).filter(User.id == user_id).first()
    if not partner or bool(getattr(partner, "is_deleted", False)):
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    parts = [p.strip() for p in (profile.photo_urls or "").split(",") if p.strip()]
    g = (getattr(profile, "gender", None) or None)
    normalized = [normalize_photo_url(p, demo_profile_gender=g) for p in parts]
    ignored_by_me = (
        db.query(UserIgnore)
        .filter(UserIgnore.user_id == current_user.id, UserIgnore.ignored_user_id == user_id)
        .first()
        is not None
    )
    # Retention: count profile views for the viewed user (no UI leakage).
    # Store the event on the viewed user's timeline so daily nudges can query counts cheaply.
    try:
        if not bool(getattr(partner, "is_demo", False)):
            track_event(db, "profile_viewed", user_id=int(user_id), payload={"viewer_user_id": int(current_user.id)})
    except Exception:
        pass
    is_v = _is_verified_approved(profile)
    level = (getattr(profile, "verification_level", None) or "none").strip().lower() or "none"
    if level not in ("none", "photo", "id"):
        level = "none"
    badge_visible = bool(getattr(profile, "verification_badge_visible", True))
    pu = to_utc_aware(getattr(partner, "premium_until", None))
    partner_premium = bool(is_user_premium(db, int(partner.id)))
    return PartnerProfilePublic(
        user_id=user_id,
        ignored_by_me=bool(ignored_by_me),
        display_name=(profile.display_name or "").strip() or "Unknown",
        age=profile.age,
        city=(profile.city or "").strip(),
        bio=(profile.bio or "").strip(),
        interests=_split_csv_list(profile.interests),
        lifestyle_tags=_split_csv_list(profile.lifestyle_tags),
        photo_urls=normalized,
        relationship_goal=(profile.relationship_goal or "relationship").strip() or "relationship",
        verified=is_v,
        is_verified=is_v,
        verification_level=level,
        verification_badge_visible=badge_visible,
        is_premium=partner_premium,
        premium_until=pu,
        is_demo_profile=is_demo_profile(profile, partner),
        demo_label=DEMO_PROFILE_LABEL if is_demo_profile(profile, partner) else None,
        demo_disclaimer=(getattr(profile, "demo_disclaimer", "") or DEMO_PROFILE_DISCLAIMER)
        if is_demo_profile(profile, partner)
        else None,
    )


@router.post("/me/verify")
def verify_my_profile(
    frames: list[UploadFile] = File(...),
    verification_source: str = Form(default="camera"),
    captured_at: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lightweight photo verification (MVP).

    Client submits several selfie frames captured from a live camera stream.
    We compute an internal embedding, check that frames are not static (basic liveness),
    then compare to the user's primary profile photo embedding.
    """
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))

    if str(verification_source or "").strip().lower() != "camera":
        raise HTTPException(status_code=400, detail=api_error("profile.verify.live_camera_required"))

    if not frames or len(frames) < 6:
        raise HTTPException(status_code=400, detail=api_error("profile.verify.clip_required"))

    embeddings: list[VisualEmbedding] = []
    for f in frames[:14]:
        blob = f.file.read()
        emb = compute_visual_embedding_from_bytes(blob)
        if emb:
            embeddings.append(emb)

    if len(embeddings) < 4:
        raise HTTPException(status_code=400, detail=api_error("profile.verify.frames_read_failed"))

    # Basic anti-spoof: reject near-identical frame sequences.
    first = embeddings[0].vector
    last = embeddings[-1].vector
    motion = 1.0 - max(0.0, min(1.0, cosine_similarity(first, last)))
    if motion < 0.005:
        raise HTTPException(status_code=400, detail=api_error("profile.verify.motion_required"))

    # Average embedding over frames
    dim = len(embeddings[0].vector)
    avg = [0.0] * dim
    for e in embeddings:
        if len(e.vector) != dim:
            continue
        for i, x in enumerate(e.vector):
            avg[i] += x
    avg = [x / float(len(embeddings)) for x in avg]
    verification_emb = VisualEmbedding(avg)

    # Compare to profile photo embedding (precomputed on profile update)
    photo_emb = VisualEmbedding.deserialize(getattr(profile, "visual_embedding", "") or "")
    if not photo_emb:
        parts = [p.strip() for p in (profile.photo_urls or "").split(",") if p.strip()]
        primary = normalize_photo_url(parts[0], demo_profile_gender=getattr(profile, "gender", None)) if parts else ""
        photo_emb = compute_visual_embedding_from_url(primary) if primary else None
        profile.visual_embedding = photo_emb.serialize() if photo_emb else ""

    if not photo_emb:
        raise HTTPException(status_code=400, detail=api_error("profile.verify.needs_primary_photo"))

    sim = max(0.0, min(1.0, cosine_similarity(verification_emb.vector, photo_emb.vector)))
    verified = sim >= 0.82

    profile.verification_embedding = verification_emb.serialize()
    profile.verification_type = "selfie"
    profile.verification_status = "verified" if verified else "none"
    profile.verification_level = "photo" if verified else "none"
    profile.verification_updated_at = datetime.now(UTC)
    profile.verified = bool(verified) and profile.verification_status == "verified"
    profile.verified_at = datetime.now(UTC) if profile.verified else None
    db.add(profile)
    db.commit()

    track_event(db, "profile_verified", user_id=current_user.id, payload={"verified": verified, "similarity": round(sim, 4)})
    return {"verified": verified, "similarity": round(sim, 4)}


def _verification_degraded_response() -> dict:
    return {
        "ok": True,
        "status": "pending",
        "message": "Verification received. Your profile will show as pending until review completes.",
        "verification_status": "pending",
        "similarity": 0.0,
        "degraded": True,
    }


@router.post("/verification/selfie")
async def verification_selfie(
    frames: list[UploadFile] | None = File(default=None),
    selfie: UploadFile | None = File(default=None),
    verification_source: str = Form(default="camera"),
    captured_at: str | None = Form(default=None),
    pose_challenge: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Single-photo verification (one clear selfie). Multi-frame / liveness capture removed."""
    try:
        profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
        if not profile:
            raise HTTPException(status_code=404, detail=api_error("profile.not_found"))

        src = str(verification_source or "").strip().lower() or "camera"
        if src not in {"camera", "upload"}:
            raise HTTPException(status_code=400, detail=api_error("validation.invalid_payload"))

        pc = (pose_challenge or "").strip().lower()
        if pc and pc not in VERIFICATION_POSE_CHALLENGES:
            raise HTTPException(status_code=400, detail=api_error("profile.verify.invalid_pose"))

        day = datetime.now(UTC).strftime("%Y%m%d")
        max_per_day = int(getattr(settings, "VERIFICATION_ATTEMPTS_PER_DAY", 5) or 5)
        attempt = _get_or_create_verification_attempt(db, user_id=int(current_user.id), day=day)
        if int(attempt.count or 0) >= max_per_day:
            raise HTTPException(status_code=429, detail=api_error("profile.verify.rate_limited"))

        inputs: list[UploadFile] = []
        if selfie is not None:
            inputs.append(selfie)
        if frames:
            inputs.extend([f for f in frames if f is not None])
        # Exactly one image (first wins if client sends extras).
        one: UploadFile | None = inputs[0] if inputs else None
        if one is None:
            raise HTTPException(status_code=400, detail=api_error("profile.verify.missing_frames"))

        logger.info(
            "verification_request_received user_id=%s mode=single source=%s captured_at=%s",
            int(current_user.id),
            src,
            str(captured_at or ""),
        )

        stored_url = ""
        content: bytes | None = None
        ext = "jpg"
        try:
            if not getattr(one, "filename", ""):
                raise HTTPException(status_code=400, detail=api_error("profile.verify.missing_filename"))
            content, ext = await read_validate_image(one)
            stored_url = persist_verification_selfie(int(current_user.id), ext, content)
        except HTTPException:
            raise
        except Exception:
            logger.exception("verification_single_image_read_failed user_id=%s", int(current_user.id))
            return _verification_degraded_response()

        if not content:
            return _verification_degraded_response()

        attempt.count = int(attempt.count or 0) + 1
        attempt.updated_at = datetime.now(UTC)
        db.add(attempt)

        status = "pending"
        sim = 0.0
        verification_emb: VisualEmbedding | None = None
        try:
            verification_emb = compute_visual_embedding_from_bytes(content)
            photo_emb = VisualEmbedding.deserialize(getattr(profile, "visual_embedding", "") or "")
            if not photo_emb:
                parts = [p.strip() for p in (profile.photo_urls or "").split(",") if p.strip()]
                primary = normalize_photo_url(parts[0], demo_profile_gender=getattr(profile, "gender", None)) if parts else ""
                photo_emb = compute_visual_embedding_from_url(primary) if primary else None
                if photo_emb:
                    profile.visual_embedding = photo_emb.serialize()

            if verification_emb and photo_emb:
                sim = max(0.0, min(1.0, cosine_similarity(verification_emb.vector, photo_emb.vector)))
                if sim >= 0.78:
                    status = "verified"
                elif sim >= 0.66:
                    status = "pending"
                else:
                    status = "rejected"
            else:
                status = "pending"
        except Exception:
            logger.exception("verification_embedding_failed user_id=%s", int(current_user.id))
            status = "pending"
            sim = 0.0

        logger.info(
            "verification_result user_id=%s profile_id=%s mode=single similarity=%s status=%s",
            int(current_user.id),
            int(profile.id),
            round(float(sim), 4),
            status,
        )

        if verification_emb:
            profile.verification_embedding = verification_emb.serialize()
        profile.verification_type = "selfie"
        profile.verification_selfie_url = stored_url or ""
        profile.verification_status = status
        profile.verification_level = "photo" if status == "verified" else "none"
        profile.verification_updated_at = datetime.now(UTC)
        profile.verified = status == "verified"
        profile.verified_at = datetime.now(UTC) if profile.verified else None

        db.add(profile)
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("verification_selfie_db_commit_failed user_id=%s profile_id=%s", int(current_user.id), int(profile.id))
            return _verification_degraded_response()

        try:
            track_event(
                db,
                "verification_selfie_submitted",
                user_id=current_user.id,
                payload={"status": status, "similarity": round(float(sim), 4), "frames_count": 1},
            )
        except Exception:
            logger.exception("verification_selfie_track_event_failed user_id=%s", int(current_user.id))

        api_status = "approved" if status == "verified" else ("pending" if status == "pending" else "rejected")
        return {
            "ok": status in ("verified", "pending"),
            "status": api_status,
            "message": "Verification submitted for review."
            if status == "pending"
            else ("Profile verified" if status == "verified" else "Could not verify against profile photo"),
            "verification_status": api_status,
            "similarity": round(float(sim), 4),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("verification_selfie_unhandled user_id=%s", int(getattr(current_user, "id", 0) or 0))
        return _verification_degraded_response()


@router.post("/verification/start")
def verification_start(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    pose_challenge = random.choice(tuple(VERIFICATION_POSE_CHALLENGES))
    track_event(
        db,
        "verification_started",
        user_id=current_user.id,
        payload={"status": getattr(profile, "verification_status", "none"), "pose_challenge": pose_challenge},
    )
    return {
        "session_id": f"v1:{current_user.id}:{int(datetime.now(UTC).timestamp())}",
        "instructions": "Take a clear selfie in good light. Your verification photo is used only for verification.",
        "pose_challenge": pose_challenge,
        "steps_total": 3,
    }


@router.post("/verification/submit")
def verification_submit(
    payload: dict = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Deprecated: previously accepted selfie_url (upload-based verification).
    # Trust requirement: verification must be captured live from camera frames.
    raise HTTPException(status_code=400, detail=api_error("profile.verify.live_camera_required"))

    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    selfie_url = str(payload.get("selfie_url", "")).strip()
    if not selfie_url:
        raise HTTPException(status_code=400, detail=api_error("profile.verify.selfie_url_required"))
    if len(selfie_url) > 2000:
        raise HTTPException(status_code=400, detail=api_error("profile.verify.selfie_url_too_long"))

    # Lightweight usability checks: ensure photo exists and is readable (best-effort).
    emb = compute_visual_embedding_from_url(selfie_url) if selfie_url else None
    if not emb:
        profile.verification_status = "rejected"
        profile.verification_type = "selfie"
        profile.verification_updated_at = datetime.now(UTC)
        profile.verification_selfie_url = selfie_url
        profile.verified = False
        profile.verified_at = None
        db.add(profile)
        db.commit()
        track_event(db, "verification_submitted", user_id=current_user.id, payload={"ok": False})
        raise HTTPException(status_code=400, detail=api_error("profile.verify.selfie_unreadable"))

    profile.verification_status = "pending"
    profile.verification_type = "selfie"
    profile.verification_updated_at = datetime.now(UTC)
    profile.verification_selfie_url = selfie_url
    profile.verified = False
    profile.verified_at = None
    db.add(profile)
    db.commit()
    track_event(db, "verification_submitted", user_id=current_user.id, payload={"ok": True})
    return {"verification_status": "pending"}


@router.get("/verification/status")
def verification_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    status_value = normalize_verification_status(getattr(profile, "verification_status", "none"))
    api_status = verification_status_for_api(profile)
    verified = is_verified_profile(profile)
    track_event(
        db,
        "verification_status_viewed",
        user_id=current_user.id,
        payload={"status": status_value, "verified": verified, "api_status": api_status},
    )
    if verified:
        # Dedup badge seen analytics (daily), fail-open.
        try:
            r = get_redis()
            key = f"verify:badge_seen:{current_user.id}:{datetime.now(UTC).strftime('%Y%m%d')}"
            if r.set(key, "1", nx=True, ex=60 * 60 * 30):
                track_event(db, "verification_badge_seen", user_id=current_user.id, payload={})
        except Exception:
            pass
    return {
        "verified": verified,
        "verification_status": api_status,
        "verification_status_raw": status_value,
        "verification_type": verification_type_for_api(profile),
    }
