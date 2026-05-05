from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from sqlalchemy.orm import Session
from app.core.security import get_password_hash
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.models.subscription import Subscription
from app.models.user import User
from app.models.oauth_account import OAuthAccount
from app.models.analytics_event import AnalyticsEvent
from app.services.demo_mode import demo_bundled_photo_url
from app.services.visual_embeddings import VisualEmbedding


Base.metadata.create_all(bind=engine)
SEED_DEBUG = True
DEV_DEMO_ANALYTICS_KEY = "funnel_demo_v1"


def serialize_embedding(values: list[float]) -> str:
    return VisualEmbedding(vector=values).serialize()


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _set_if_empty(obj, attr: str, new_value) -> bool:
    current = getattr(obj, attr, None)
    if _is_empty(current):
        setattr(obj, attr, new_value)
        return True
    return False


def ensure_user(
    db: Session,
    now: datetime,
    *,
    email: str,
    password: str,
    name: str,
    bio: str,
    age: int,
    city: str,
    gender: str,
    interested_in: str,
    relationship_goal: str,
    interests: list[str],
    lifestyle_tags: list[str],
    photo_urls: list[str],
    preferred_language: str = "en",
    min_preferred_age: int = 22,
    max_preferred_age: int = 38,
    verified: bool = False,
    visual_embedding: str = "",
) -> tuple[User, Profile]:
    user = db.query(User).filter(User.email == email).first()
    created_user = False
    if not user:
        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            is_active=True,
            matches_last_seen_at=now,
        )
        db.add(user)
        db.flush()
        created_user = True
    else:
        if user.matches_last_seen_at is None:
            user.matches_last_seen_at = now

    # Never seed over real OAuth users (especially Google sign-ins).
    # Seed should only ever affect demo accounts.
    if not created_user:
        try:
            oauth_exists = (
                db.query(OAuthAccount.id)
                .filter(OAuthAccount.user_id == int(user.id))
                .limit(1)
                .first()
                is not None
            )
        except Exception:
            oauth_exists = False
        if oauth_exists or user.hashed_password is None:
            profile = db.query(Profile).filter(Profile.user_id == user.id).first()
            if profile:
                if SEED_DEBUG:
                    print(f"[seed] skip_oauth_user email={email} user_id={user.id}")
                return user, profile
            # Best-effort: avoid crashing seed scripts if a profile is missing.
            profile = Profile(user_id=user.id)
            db.add(profile)
            db.commit()
            db.refresh(profile)
            if SEED_DEBUG:
                print(f"[seed] created_missing_profile_for_oauth_user email={email} user_id={user.id} profile_id={profile.id}")
            return user, profile

    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    created_profile = False
    if not profile:
        profile = Profile(user_id=user.id, display_name=name)
        db.add(profile)
        db.flush()
        created_profile = True

    # Never overwrite existing user/profile data on startup; only fill empty fields.
    seed_filled_empty_fields = False
    seed_filled_empty_fields |= _set_if_empty(profile, "display_name", name)
    seed_filled_empty_fields |= _set_if_empty(profile, "bio", bio)
    if getattr(profile, "age", None) in (None, 0):
        profile.age = age
        seed_filled_empty_fields = True
    seed_filled_empty_fields |= _set_if_empty(profile, "city", city)
    seed_filled_empty_fields |= _set_if_empty(profile, "gender", gender)
    seed_filled_empty_fields |= _set_if_empty(profile, "interested_in", interested_in)
    seed_filled_empty_fields |= _set_if_empty(profile, "relationship_goal", relationship_goal)
    seed_filled_empty_fields |= _set_if_empty(profile, "interests", ",".join(interests))
    seed_filled_empty_fields |= _set_if_empty(profile, "lifestyle_tags", ",".join(lifestyle_tags))
    # CRITICAL: photos must never be reset on startup.
    seed_filled_empty_fields |= _set_if_empty(profile, "photo_urls", ",".join(photo_urls))
    seed_filled_empty_fields |= _set_if_empty(profile, "preferred_language", preferred_language)
    if getattr(profile, "min_preferred_age", None) in (None, 0):
        profile.min_preferred_age = min_preferred_age
        seed_filled_empty_fields = True
    if getattr(profile, "max_preferred_age", None) in (None, 0):
        profile.max_preferred_age = max_preferred_age
        seed_filled_empty_fields = True
    seed_filled_empty_fields |= _set_if_empty(profile, "visual_embedding", visual_embedding)

    # Never reset verification state on startup. If profile is new, we can seed it.
    if created_profile:
        if verified:
            profile.verified = True
            profile.verified_at = profile.verified_at or now
            profile.verification_type = "selfie"
            profile.verification_status = "verified"
            profile.verification_level = "photo"
            profile.verification_updated_at = now
        else:
            profile.verified = False
            profile.verified_at = None
            profile.verification_type = "manual"
            profile.verification_status = "none"
            profile.verification_updated_at = now

    if SEED_DEBUG:
        print(
            f"[seed] email={email} created_user={created_user} created_profile={created_profile} "
            f"seed_filled_empty_fields={seed_filled_empty_fields}"
        )

    db.commit()
    db.refresh(user)
    db.refresh(profile)
    return user, profile


def ensure_subscription(db: Session, now: datetime, user_id: int, plan_code: str | None) -> None:
    row = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not row:
        row = Subscription(user_id=user_id)
        db.add(row)

    if plan_code:
        row.provider = "mock"
        row.provider_customer_id = f"demo-customer-{user_id}"
        row.provider_subscription_id = f"demo-subscription-{user_id}"
        row.status = "active"
        row.plan_code = plan_code
        row.start_date = now - timedelta(days=2)
        row.end_date = now + timedelta(days=28)
    else:
        row.provider = "mock"
        row.provider_customer_id = ""
        row.provider_subscription_id = ""
        row.status = "inactive"
        row.plan_code = "free"
        row.start_date = None
        row.end_date = None

    db.commit()


def _seed_demo_analytics_events(db: Session, demo_users: dict[str, int]) -> None:
    """
    Dev-only: seed lightweight funnel analytics events for /admin/funnel so local
    environments show meaningful counts immediately. Idempotent by exact payload_json.
    Never runs in production.
    """
    env = (settings.ENV or "").strip().lower()
    if env in ("production", "prod"):
        return

    def ensure_event(name: str, user_id: int, payload: dict) -> None:
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        exists = (
            db.query(AnalyticsEvent)
            .filter(AnalyticsEvent.user_id == int(user_id))
            .filter(AnalyticsEvent.name == str(name))
            .filter(AnalyticsEvent.payload_json == payload_json)
            .first()
        )
        if exists:
            return
        db.add(AnalyticsEvent(user_id=int(user_id), name=str(name), payload_json=payload_json))
        db.commit()

    demo_users = {k: int(v) for k, v in (demo_users or {}).items() if isinstance(v, int) and int(v) > 0}
    if not demo_users:
        return

    # 1) Social login success: simulate 3 users.
    for key in ("admin", "anna", "olena"):
        uid = demo_users.get(key)
        if not uid:
            continue
        ensure_event(
            "social_login_success",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "provider": "google", "user": key},
        )

    # 2) Onboarding completed: simulate 2 users (slight drop-off).
    for key in ("anna", "olena"):
        uid = demo_users.get(key)
        if not uid:
            continue
        ensure_event(
            "onboarding_completed",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "user": key, "locale": "uk"},
        )

    # 3) Discover viewed (AI used): simulate 2 users.
    for key in ("anna", "olena"):
        uid = demo_users.get(key)
        if not uid:
            continue
        ensure_event(
            "ai_compatibility_used_in_match_feed",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "user": key, "plan_tier": "free"},
        )

    # 4) First match created: simulate 1 user.
    uid = demo_users.get("anna")
    if uid:
        ensure_event(
            "first_match_created",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "user": "anna", "match_id": 1},
        )

        # 5) First message prompt shown + AI opener used + first message sent + assisted.
        ensure_event(
            "first_message_prompt_shown",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "user": "anna", "source_surface": "match_moment"},
        )
        ensure_event(
            "ai_opener_used_after_match",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "user": "anna"},
        )
        ensure_event(
            "first_message_sent",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "user": "anna"},
        )
        ensure_event(
            "first_message_ai_assisted",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "user": "anna"},
        )

        # 6) Follow-up suggested (optional) + first reply received.
        ensure_event(
            "first_message_followup_suggested",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "user": "anna"},
        )
        ensure_event(
            "first_reply_received",
            uid,
            {"source": "dev_seed", "demo_key": DEV_DEMO_ANALYTICS_KEY, "user": "anna"},
        )


def ensure_match(db: Session, user_a_id: int, user_b_id: int, created_at: datetime) -> Match:
    a, b = sorted((int(user_a_id), int(user_b_id)))
    row = db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).first()
    if not row:
        row = Match(user_a_id=a, user_b_id=b, created_at=created_at)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def ensure_thread_messages(db: Session, user_a_id: int, user_b_id: int, rows: list[dict]) -> None:
    existing = (
        db.query(Message)
        .filter(
            ((Message.sender_id == user_a_id) & (Message.receiver_id == user_b_id))
            | ((Message.sender_id == user_b_id) & (Message.receiver_id == user_a_id))
        )
        .count()
    )
    if existing >= len(rows):
        return

    for row in rows[existing:]:
        db.add(
            Message(
                sender_id=int(row["sender_id"]),
                receiver_id=int(row["receiver_id"]),
                content=str(row["content"]).strip(),
                created_at=row["created_at"],
            )
        )
    db.commit()


def run_seed() -> None:
    db = SessionLocal()
    now = datetime.now(UTC)
    try:
        taras_user, _taras_profile = ensure_user(
            db,
            now,
            email="taras@example.com",
            password="password123",
            name="Taras",
            bio="Founder energy, gym mornings, live music, and spontaneous city breaks.",
            age=29,
            city="Kyiv",
            gender="male",
            interested_in="female",
            relationship_goal="relationship",
            interests=["fitness", "music", "travel", "coffee"],
            lifestyle_tags=["confident", "ambitious", "social"],
            photo_urls=[
                demo_bundled_photo_url(catalog_id="seed_taras_1", gender="male"),
                demo_bundled_photo_url(catalog_id="seed_taras_2", gender="male"),
            ],
            preferred_language="uk",
            verified=True,
            visual_embedding=serialize_embedding([0.37, 0.36, 0.34, 0.33, 0.31, 0.30, 0.29, 0.28]),
        )

        olena_user, _olena_profile = ensure_user(
            db,
            now,
            email="olena@example.com",
            password="password123",
            name="Olena",
            bio="Coffee walks, bookstores, and plotting the next train trip.",
            age=27,
            city="Lviv",
            gender="female",
            interested_in="male",
            relationship_goal="relationship",
            interests=["travel", "coffee", "books", "hiking"],
            lifestyle_tags=["active", "romantic", "urban"],
            photo_urls=[
                demo_bundled_photo_url(catalog_id="seed_olena_1", gender="female"),
                demo_bundled_photo_url(catalog_id="seed_olena_2", gender="female"),
            ],
            preferred_language="uk",
            verified=False,
            visual_embedding=serialize_embedding([0.10, 0.16, 0.25, 0.30, 0.28, 0.22, 0.17, 0.12]),
        )

        anna_user, _anna_profile = ensure_user(
            db,
            now,
            email="anna@example.com",
            password="password123",
            name="Anna",
            bio="Design, galleries, vinyl, and late-evening walks through the city.",
            age=25,
            city="Kyiv",
            gender="female",
            interested_in="male",
            relationship_goal="relationship",
            interests=["design", "art", "music", "coffee"],
            lifestyle_tags=["creative", "calm", "stylish"],
            photo_urls=[
                demo_bundled_photo_url(catalog_id="seed_anna_1", gender="female"),
                demo_bundled_photo_url(catalog_id="seed_anna_2", gender="female"),
            ],
            preferred_language="uk",
            verified=True,
            visual_embedding=serialize_embedding([0.36, 0.35, 0.34, 0.32, 0.31, 0.30, 0.28, 0.27]),
        )

        # Extra Discover inventory so the first post-onboarding impression is never sparse.
        iryna_user, _iryna_profile = ensure_user(
            db,
            now,
            email="iryna@example.com",
            password="password123",
            name="Iryna",
            bio="Sunrise hikes, specialty coffee, and postcards from every new place.",
            age=28,
            city="Kyiv",
            gender="female",
            interested_in="male",
            relationship_goal="relationship",
            interests=["travel", "coffee", "hiking", "photography"],
            lifestyle_tags=["warm", "curious", "active"],
            photo_urls=[
                demo_bundled_photo_url(catalog_id="seed_iryna_1", gender="female"),
                demo_bundled_photo_url(catalog_id="seed_iryna_2", gender="female"),
            ],
            preferred_language="uk",
            verified=True,
            visual_embedding=serialize_embedding([0.33, 0.31, 0.29, 0.28, 0.26, 0.25, 0.24, 0.23]),
        )

        sofia_user, _sofia_profile = ensure_user(
            db,
            now,
            email="sofia@example.com",
            password="password123",
            name="Sofia",
            bio="Yoga, sunsets, and tiny cafés with big vibes.",
            age=27,
            city="Kyiv",
            gender="female",
            interested_in="male",
            relationship_goal="relationship",
            interests=["fitness", "coffee", "travel", "music"],
            lifestyle_tags=["calm", "active", "stylish"],
            photo_urls=[
                demo_bundled_photo_url(catalog_id="seed_sofia_1", gender="female"),
                demo_bundled_photo_url(catalog_id="seed_sofia_2", gender="female"),
            ],
            preferred_language="uk",
            verified=False,
            visual_embedding=serialize_embedding([0.34, 0.33, 0.32, 0.31, 0.29, 0.28, 0.27, 0.26]),
        )

        marta_user, _marta_profile = ensure_user(
            db,
            now,
            email="marta@example.com",
            password="password123",
            name="Marta",
            bio="Bookstores, matcha, and planning the next cozy weekend getaway.",
            age=24,
            city="Lviv",
            gender="female",
            interested_in="male",
            relationship_goal="relationship",
            interests=["books", "coffee", "travel", "art"],
            lifestyle_tags=["calm", "romantic", "family"],
            photo_urls=[
                demo_bundled_photo_url(catalog_id="seed_marta_1", gender="female"),
                demo_bundled_photo_url(catalog_id="seed_marta_2", gender="female"),
            ],
            preferred_language="uk",
            verified=False,
            visual_embedding=serialize_embedding([0.31, 0.30, 0.29, 0.28, 0.27, 0.27, 0.26, 0.25]),
        )

        mark_user, _mark_profile = ensure_user(
            db,
            now,
            email="mark@example.com",
            password="password123",
            name="Mark",
            bio="Trail runs, dogs, honest conversations, and weekend road trips.",
            age=31,
            city="Lviv",
            gender="male",
            interested_in="female",
            relationship_goal="relationship",
            interests=["running", "movies", "mountains", "dogs"],
            lifestyle_tags=["active", "kind", "grounded"],
            photo_urls=[
                demo_bundled_photo_url(catalog_id="seed_mark_1", gender="male"),
                demo_bundled_photo_url(catalog_id="seed_mark_2", gender="male"),
            ],
            preferred_language="en",
            verified=False,
            visual_embedding=serialize_embedding([0.14, 0.18, 0.21, 0.24, 0.26, 0.23, 0.19, 0.15]),
        )

        admin_user, _admin_profile = ensure_user(
            db,
            now,
            email="admin@example.com",
            password="password123",
            name="Admin",
            bio="System admin profile.",
            age=35,
            city="Kyiv",
            gender="other",
            interested_in="all",
            relationship_goal="networking",
            interests=["ops"],
            lifestyle_tags=["admin"],
            photo_urls=[
                demo_bundled_photo_url(catalog_id="seed_admin_1", gender="other"),
                demo_bundled_photo_url(catalog_id="seed_admin_2", gender="other"),
            ],
            preferred_language="en",
            verified=False,
        )

        ensure_subscription(db, now, admin_user.id, None)
        ensure_subscription(db, now, taras_user.id, "premium_plus")
        ensure_subscription(db, now, olena_user.id, None)
        ensure_subscription(db, now, anna_user.id, None)
        ensure_subscription(db, now, mark_user.id, "premium")
        ensure_subscription(db, now, iryna_user.id, None)
        ensure_subscription(db, now, sofia_user.id, None)
        ensure_subscription(db, now, marta_user.id, None)

        ensure_match(db, taras_user.id, anna_user.id, now - timedelta(days=4))
        ensure_match(db, taras_user.id, olena_user.id, now - timedelta(days=3))
        ensure_match(db, taras_user.id, sofia_user.id, now - timedelta(days=1))
        ensure_match(db, taras_user.id, marta_user.id, now - timedelta(hours=18))

        # Dev-only: seed demo funnel analytics (idempotent).
        _seed_demo_analytics_events(
            db,
            {
                "admin": int(admin_user.id),
                "taras": int(taras_user.id),
                "anna": int(anna_user.id),
                "olena": int(olena_user.id),
            },
        )

        ensure_thread_messages(
            db,
            taras_user.id,
            anna_user.id,
            [
                {
                    "sender_id": taras_user.id,
                    "receiver_id": anna_user.id,
                    "content": "Hey Anna, your design plus vinyl combo is elite. What record always pulls you back in?",
                    "created_at": now - timedelta(hours=8, minutes=15),
                },
                {
                    "sender_id": anna_user.id,
                    "receiver_id": taras_user.id,
                    "content": "Haha, that is a strong opener. Lately I keep replaying Khruangbin. What about you?",
                    "created_at": now - timedelta(hours=8),
                },
            ],
        )
    finally:
        db.close()
    print("Seed complete.")


if __name__ == "__main__":
    run_seed()
