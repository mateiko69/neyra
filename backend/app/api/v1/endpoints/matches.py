from datetime import UTC, datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Request
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.services.safety import blocked_user_ids
from app.utils.media_urls import normalize_photo_url
from app.services.ai.locale_pipeline import resolve_http_ai_locale
from app.services.demo_mode import is_demo_profile
from app.services.ai.localized_demo_text import coerce_demo_partner_message_body, localized_voice_message_stub
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.premium import is_user_premium
from app.services.trust.verification_state import is_verified_profile

router = APIRouter()


def _last_message_preview_localized(
    db: Session,
    me: int,
    partner: int,
    *,
    ui_locale: str | None,
    partner_profile: Profile | None,
    partner_user: User | None,
) -> tuple[str | None, str | None]:
    last = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == me, Message.receiver_id == partner),
                and_(Message.sender_id == partner, Message.receiver_id == me),
            )
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if not last:
        return None, None
    preview = (last.content or "").strip()
    if not preview and getattr(last, "voice_url", None):
        preview = localized_voice_message_stub(ui_locale)
    partner_demo = is_demo_profile(partner_profile, partner_user)
    if partner_demo and int(last.sender_id) == int(partner) and normalize_ai_request_locale(ui_locale or "") != "en":
        preview = coerce_demo_partner_message_body(
            raw_db=preview,
            locale=ui_locale,
            message_id=int(last.id),
            sender_is_demo_bot=True,
            route="GET /matches",
        )
    if len(preview) > 140:
        preview = preview[:137] + "…"
    at = last.created_at.isoformat() if last.created_at else None
    return preview, at


# Use "" not "/" so the route is /api/v1/matches (no trailing slash) and clients avoid 307 redirects.
@router.get("")
def list_matches(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    blocked = blocked_user_ids(db, current_user.id)
    rows = (
        db.query(Match)
        .filter((Match.user_a_id == current_user.id) | (Match.user_b_id == current_user.id))
        .order_by(Match.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    result = []
    ui_loc = resolve_http_ai_locale(request, db=db, user_id=int(current_user.id))

    partner_ids = []
    for row in rows:
        partner_id = row.user_b_id if row.user_a_id == current_user.id else row.user_a_id
        if blocked and partner_id in blocked:
            continue
        partner_ids.append(partner_id)
    if partner_ids:
        active_partner_ids = {
            int(r[0])
            for r in db.query(User.id)
            .filter(User.id.in_(partner_ids))
            .filter(User.is_deleted == False)  # noqa: E712
            .all()
            if r and r[0]
        }
        partner_ids = [pid for pid in partner_ids if pid in active_partner_ids]
    profiles = {p.user_id: p for p in db.query(Profile).filter(Profile.user_id.in_(partner_ids)).all()} if partner_ids else {}
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_(partner_ids)).all()} if partner_ids else {}
    premium_map = {int(u.id): bool(is_user_premium(db, int(u.id))) for u in users_by_id.values()} if users_by_id else {}
    for row in rows:
        partner_id = row.user_b_id if row.user_a_id == current_user.id else row.user_a_id
        if blocked and partner_id in blocked:
            continue
        if partner_ids and partner_id not in profiles:
            # Deleted or missing profile; hide from matches list.
            continue
        profile = profiles.get(partner_id)
        first_photo = None
        if profile and profile.photo_urls:
            parts = [x.strip() for x in profile.photo_urls.split(",") if x.strip()]
            if parts:
                first_photo = normalize_photo_url(parts[0], demo_profile_gender=getattr(profile, "gender", None)) or None
        seen = current_user.matches_last_seen_at
        is_new = seen is None or row.created_at > seen
        approved = bool(is_verified_profile(profile)) if profile else False
        partner_premium = bool(premium_map.get(int(partner_id))) if partner_id else False
        preview, preview_at = _last_message_preview_localized(
            db,
            int(current_user.id),
            int(partner_id),
            ui_locale=ui_loc,
            partner_profile=profile,
            partner_user=users_by_id.get(partner_id),
        )
        result.append({
            "match_id": row.id,
            "partner_user_id": partner_id,
            "conversation_id": int(partner_id),
            "partner_display_name": profile.display_name if profile else "Unknown",
            "partner_age": profile.age if profile else None,
            "partner_city": profile.city if profile else "",
            "partner_gender": (profile.gender or "") if profile else "",
            "partner_is_demo_profile": bool(getattr(profile, "is_demo_profile", False)) if profile else False,
            "partner_photo": first_photo,
            "partner_verified": approved,
            "partner_is_premium": partner_premium,
            "matched_at": row.created_at.isoformat() if row.created_at else None,
            "is_new_match": is_new,
            "last_message_preview": preview,
            "last_message_at": preview_at,
            "partner_profile": {
                "display_name": profile.display_name if profile else "Unknown",
                "age": profile.age if profile else None,
                "city": (profile.city or "") if profile else "",
                "photo_url": first_photo,
            },
        })
    return result


@router.post("/mark-seen")
def mark_matches_seen(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user.id).first()
    if user:
        user.matches_last_seen_at = datetime.now(UTC)
        db.add(user)
        db.commit()
    return {"ok": True}
