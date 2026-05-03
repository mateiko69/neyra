from __future__ import annotations

import html
import json
import logging
from datetime import UTC, datetime, timedelta
import random
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.utils.media_urls import normalize_photo_url
from app.models.ai_interaction_event import AiInteractionEvent
from app.models.ai_trial_usage import AiTrialUsage
from app.models.analytics_event import AnalyticsEvent
from app.models.app_setting import AppSetting
from app.models.device_token import DeviceToken
from app.models.match import Match
from app.models.message import Message
from app.models.message_reaction import MessageReaction
from app.models.oauth_account import OAuthAccount
from app.models.profile import Profile
from app.models.referral_reward_grant import ReferralRewardGrant
from app.models.subscription import Subscription
from app.models.swipe import Swipe
from app.models.thread_read_state import ThreadReadState
from app.models.user import User
from app.models.user_ai_memory import UserAiMemory
from app.models.user_ai_profile import UserAiProfile
from app.models.user_block import UserBlock
from app.models.user_ignore import UserIgnore
from app.models.user_report import UserReport
from app.models.verification_attempt import VerificationAttempt


DEMO_MODE_SETTING_KEY = "demo_mode_enabled"
DEMO_LIVE_SETTING_KEY = "demo_live_behavior"
DEMO_LAST_ERROR_KEY = "demo_bot_last_error"
DEMO_PROFILE_LABEL = "AI demo profile — not a real person"
DEMO_PROFILE_DISCLAIMER = "AI demo profile — not a real person"
DEMO_CHAT_LABEL = "Demo chat — AI simulation"
DEMO_TARGET_COUNT = 25

_log_demo = logging.getLogger("neyra.demo_seed")


def _frontend_repo_root() -> Path:
    """
    Directory that contains `frontend/` with public assets.

    - Dev (monorepo): .../backend/app/services/demo_mode.py -> parents[2] is `backend/`, repo root is its parent.
    - Docker: /app/app/services/demo_mode.py -> parents[2] is `/app` (mount `./frontend` at /app/frontend).
    """
    here = Path(__file__).resolve()
    pkg_parent = here.parents[2]
    if pkg_parent.name == "backend":
        return pkg_parent.parent
    return pkg_parent


def demo_profiles_public_dir() -> Path:
    return _frontend_repo_root() / "frontend" / "public" / "demo-profiles"


def demo_profiles_json_path() -> Path:
    return demo_profiles_public_dir() / "demo_profiles.json"


def load_demo_profiles_catalog() -> list[dict]:
    p = demo_profiles_json_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("profiles"), list):
        return [x for x in data["profiles"] if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _demo_email_catalog_id(catalog_id: str) -> str:
    return f"demo+{str(catalog_id).strip()}@neyra.local"


def _apply_demo_trust_and_premium(user: User, profile: Profile, index: int, now: datetime) -> None:
    """Deterministic mix for feeds: ~10% ID verified, ~30% photo verified, ~20% premium."""
    r = (index * 17 + 23) % 100
    if r < 10:
        profile.verification_status = "verified"
        profile.verification_level = "id"
        profile.verified = True
        profile.verified_at = now
    elif r < 40:
        profile.verification_status = "verified"
        profile.verification_level = "photo"
        profile.verified = True
        profile.verified_at = now
    else:
        profile.verification_status = "none"
        profile.verification_level = "none"
        profile.verified = False
        profile.verified_at = None
    profile.verification_badge_visible = True
    premium_roll = ((index * 31 + 7) % 100) < 20
    if premium_roll:
        user.premium_until = now + timedelta(days=180)
    else:
        user.premium_until = None


def _catalog_gender_to_profile_gender(entry: dict) -> str:
    """Profile.gender from catalog only (no index/random)."""
    gp = str(entry.get("gender_profile") or "").strip().lower()
    if gp in ("woman", "man"):
        return gp
    g = str(entry.get("gender") or "").strip().lower()
    if g in ("woman", "man"):
        return g
    if g == "female":
        return "woman"
    if g == "male":
        return "man"
    return "woman"


def _apply_catalog_demo_row(db: Session, entry: dict, index: int, now: datetime, stats: dict) -> None:
    cid = str(entry.get("id") or "").strip()
    if not cid:
        stats["skipped"] += 1
        _log_demo.info("demo_seed_skip empty catalog id index=%s", index)
        return
    email = _demo_email_catalog_id(cid)
    user = db.query(User).filter(User.email == email).first()
    if user and not bool(getattr(user, "is_demo", False)):
        stats["skipped"] += 1
        _log_demo.warning("demo_seed_skip email conflict with real user email=%s", email)
        print(f"SKIP (non-demo user owns {email}): {cid}")
        return

    if not user:
        user = User(
            email=email,
            hashed_password=None,
            is_active=True,
            is_demo=True,
            created_at=now - timedelta(days=index + 1),
            last_active_at=now - timedelta(hours=index + 1),
            matches_last_seen_at=now - timedelta(hours=index + 1),
        )
        db.add(user)
        db.flush()
        stats["created"] += 1
        print(f"CREATED user {cid} ({email}) gender={_catalog_gender_to_profile_gender(entry)}")
    else:
        user.is_demo = True
        user.is_active = True
        user.is_deleted = False
        user.is_banned = False
        user.last_active_at = user.last_active_at or (now - timedelta(hours=index + 1))
        user.matches_last_seen_at = user.matches_last_seen_at or (now - timedelta(hours=index + 1))
        db.add(user)
        stats["updated"] += 1
        print(f"UPDATED user {cid} ({email}) gender={_catalog_gender_to_profile_gender(entry)}")

    profile = db.query(Profile).filter(Profile.user_id == int(user.id)).first()
    if not profile:
        profile = Profile(user_id=int(user.id), display_name=str(entry.get("display_name") or "Demo"))

    dp = entry.get("demo_personality")
    if isinstance(dp, dict) and dp:
        profile.demo_personality_json = json.dumps(dp)
    else:
        profile.demo_personality_json = "{}"
        ensure_demo_personality_json(profile)

    photo = str(entry.get("photo_main_path") or "").strip()
    profile.photo_urls = photo if photo else profile.photo_urls

    profile.display_name = str(entry.get("display_name") or profile.display_name or "Demo")
    profile.age = int(entry.get("age") or profile.age or 25)
    profile.city = str(entry.get("city") or "")
    profile.gender = _catalog_gender_to_profile_gender(entry)
    stats["gender_assigned"].append(f"{cid}:{profile.gender}")
    profile.interested_in = str(entry.get("interested_in") or "")
    profile.relationship_goal = str(entry.get("relationship_goal") or "relationship")
    profile.interests = str(entry.get("interests") or "")
    profile.lifestyle_tags = str(entry.get("lifestyle_tags") or "")
    profile.bio = str(entry.get("bio") or "")
    profile.onboarding_completed = True
    profile.founder_welcome_seen = True
    profile.is_demo_profile = True
    profile.demo_disclaimer = DEMO_PROFILE_DISCLAIMER
    profile.preferred_language = str(entry.get("preferred_language") or "en").strip() or "en"
    parts = [p.strip() for p in (profile.photo_urls or "").split(",") if p.strip()]
    if parts:
        profile.photo_urls = ",".join(
            normalize_photo_url(p, demo_profile_gender=profile.gender) for p in parts
        )
    _apply_demo_trust_and_premium(user, profile, index, now)
    db.add(user)
    db.add(profile)


def sync_demo_profiles_from_catalog(db: Session, *, limit: int | None = None) -> dict:
    """Idempotent upsert from `demo_profiles.json`. Does not touch non-demo users except skip on email conflict."""
    catalog = load_demo_profiles_catalog()
    if not catalog:
        print(f"No catalog at {demo_profiles_json_path()}")
        return {"ok": False, "error": "missing_catalog", "path": str(demo_profiles_json_path())}
    cap = len(catalog) if limit is None else max(1, min(len(catalog), int(limit)))
    now = _now()
    stats = {"ok": True, "created": 0, "updated": 0, "skipped": 0, "gender_assigned": []}
    for index, entry in enumerate(catalog[:cap]):
        _apply_catalog_demo_row(db, entry, index, now, stats)
    db.commit()
    stats["total_demo_profiles"] = int(
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(User.is_demo == True, Profile.is_demo_profile == True)  # noqa: E712
        .count()
    )
    print(f"Done: created={stats['created']} updated={stats['updated']} skipped={stats['skipped']} total_demo={stats['total_demo_profiles']}")
    return stats


DEMO_PROFILE_SPECS: list[dict[str, object]] = [
    {
        "slug": "maya",
        "display_name": "Maya",
        "age": 27,
        "city": "Kyiv",
        "gender": "woman",
        "interested_in": "men",
        "goal": "relationship",
        "interests": "modern art, slow coffee, weekend hikes, indie films",
        "lifestyle": "creative, curious, calm",
        "bio": "Design-minded and easy to talk to. Likes small galleries, warm cafes, and plans that leave room for a little surprise.",
        "colors": ("#6F5CFF", "#F4D35E"),
    },
    {
        "slug": "leo",
        "display_name": "Leo",
        "age": 30,
        "city": "Lviv",
        "gender": "man",
        "interested_in": "women",
        "goal": "relationship",
        "interests": "jazz, mountain walks, cooking, books",
        "lifestyle": "grounded, warm, outdoors",
        "bio": "A calm conversation person who can cook a good dinner and still say yes to a last-minute walk through the old town.",
        "colors": ("#168AAD", "#FFD166"),
    },
    {
        "slug": "nora",
        "display_name": "Nora",
        "age": 25,
        "city": "Warsaw",
        "gender": "woman",
        "interested_in": "men",
        "goal": "serious",
        "interests": "running, design, street food, podcasts",
        "lifestyle": "active, thoughtful, city",
        "bio": "Usually moving, sometimes overthinking, always happy to find a new place with excellent dumplings and good light.",
        "colors": ("#EF476F", "#06D6A0"),
    },
    {
        "slug": "adam",
        "display_name": "Adam",
        "age": 32,
        "city": "Berlin",
        "gender": "man",
        "interested_in": "women",
        "goal": "relationship",
        "interests": "photography, cycling, techno, museums",
        "lifestyle": "creative, independent, social",
        "bio": "Low-key photographer, high-key museum wanderer. Happiest when a simple plan turns into a good story.",
        "colors": ("#2D3142", "#F4A261"),
    },
    {
        "slug": "sofia",
        "display_name": "Sofia",
        "age": 29,
        "city": "Lisbon",
        "gender": "woman",
        "interested_in": "men",
        "goal": "relationship",
        "interests": "ocean walks, architecture, wine, language learning",
        "lifestyle": "sunny, curious, relaxed",
        "bio": "Soft spot for tiled streets, tiny restaurants, and people who ask real questions instead of only trading facts.",
        "colors": ("#118AB2", "#FFB703"),
    },
    {
        "slug": "milan",
        "display_name": "Milan",
        "age": 28,
        "city": "Prague",
        "gender": "man",
        "interested_in": "women",
        "goal": "serious",
        "interests": "climbing, architecture, ramen, cinema",
        "lifestyle": "active, steady, curious",
        "bio": "Climbs on weekdays, searches for great ramen on weekends, and appreciates direct kindness more than perfect small talk.",
        "colors": ("#4A4E69", "#C9ADA7"),
    },
    {
        "slug": "elena",
        "display_name": "Elena",
        "age": 31,
        "city": "Barcelona",
        "gender": "woman",
        "interested_in": "men",
        "goal": "relationship",
        "interests": "ceramics, dancing, beach mornings, psychology",
        "lifestyle": "expressive, warm, balanced",
        "bio": "Ceramics student, patient listener, and believer that good chemistry feels calm before it feels dramatic.",
        "colors": ("#E76F51", "#2A9D8F"),
    },
    {
        "slug": "tom",
        "display_name": "Tom",
        "age": 34,
        "city": "Amsterdam",
        "gender": "man",
        "interested_in": "women",
        "goal": "relationship",
        "interests": "bikes, design systems, board games, bakeries",
        "lifestyle": "organized, playful, thoughtful",
        "bio": "Product person with a bakery map, a bike for every weather, and a weakness for clever questions over loud rooms.",
        "colors": ("#3A86FF", "#FFBE0B"),
    },
    {
        "slug": "anna",
        "display_name": "Anna",
        "age": 26,
        "city": "Vienna",
        "gender": "woman",
        "interested_in": "men",
        "goal": "relationship",
        "interests": "classical music, parks, science, tea",
        "lifestyle": "gentle, focused, reflective",
        "bio": "Scientist in the week, concert-listener when possible. Likes kindness, good tea, and people who mean what they say.",
        "colors": ("#8338EC", "#FB5607"),
    },
    {
        "slug": "erik",
        "display_name": "Erik",
        "age": 29,
        "city": "Tallinn",
        "gender": "man",
        "interested_in": "women",
        "goal": "serious",
        "interests": "sailing, startups, nature, documentaries",
        "lifestyle": "calm, ambitious, outdoors",
        "bio": "Quietly ambitious, happiest near water, and much better in real conversations than in short bios.",
        "colors": ("#006D77", "#E29578"),
    },
    {
        "slug": "claire",
        "display_name": "Claire",
        "age": 33,
        "city": "Paris",
        "gender": "woman",
        "interested_in": "men",
        "goal": "relationship",
        "interests": "books, galleries, long dinners, city walks",
        "lifestyle": "romantic, thoughtful, social",
        "bio": "Book notes in every bag, dinner reservations only when the conversation deserves another hour.",
        "colors": ("#D81159", "#8F2D56"),
    },
    {
        "slug": "alex",
        "display_name": "Alex",
        "age": 27,
        "city": "London",
        "gender": "man",
        "interested_in": "women",
        "goal": "relationship",
        "interests": "comedy, football, coffee, volunteering",
        "lifestyle": "friendly, energetic, kind",
        "bio": "Equal parts dry humor and practical care. Always up for a match, a market, or a real conversation.",
        "colors": ("#0B3954", "#BFD7EA"),
    },
    {
        "slug": "freja",
        "display_name": "Freja",
        "age": 28,
        "city": "Copenhagen",
        "gender": "woman",
        "interested_in": "men",
        "goal": "serious",
        "interests": "interiors, swimming, slow mornings, sustainability",
        "lifestyle": "minimal, warm, active",
        "bio": "Likes clean design, cold swims, and the kind of date where both people leave feeling a little more understood.",
        "colors": ("#70D6FF", "#FF70A6"),
    },
    {
        "slug": "oskar",
        "display_name": "Oskar",
        "age": 35,
        "city": "Stockholm",
        "gender": "man",
        "interested_in": "women",
        "goal": "relationship",
        "interests": "skiing, podcasts, cooking, dogs",
        "lifestyle": "steady, outdoors, generous",
        "bio": "Good at breakfast, winter plans, and remembering the small thing you mentioned once.",
        "colors": ("#073B4C", "#06D6A0"),
    },
    {
        "slug": "giulia",
        "display_name": "Giulia",
        "age": 30,
        "city": "Rome",
        "gender": "woman",
        "interested_in": "men",
        "goal": "relationship",
        "interests": "food history, ruins, cinema, family dinners",
        "lifestyle": "warm, expressive, grounded",
        "bio": "Food history nerd, film person, and a strong believer that small honest moments beat perfect lines.",
        "colors": ("#BC6C25", "#A7C957"),
    },
    {
        "slug": "mark",
        "display_name": "Mark",
        "age": 31,
        "city": "Vilnius",
        "gender": "man",
        "interested_in": "women",
        "goal": "serious",
        "interests": "trail running, synth music, design, chess",
        "lifestyle": "focused, playful, active",
        "bio": "Trail runner with a synth playlist, a tidy kitchen, and a soft spot for smart, playful honesty.",
        "colors": ("#5A189A", "#80FFDB"),
    },
]


def _now() -> datetime:
    return datetime.now(UTC)


def _bool_from_setting(raw: str | None) -> bool | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if isinstance(parsed, dict) and isinstance(parsed.get("enabled"), bool):
        return bool(parsed["enabled"])
    if isinstance(parsed, bool):
        return bool(parsed)
    return None


def _setting_row(db: Session) -> AppSetting | None:
    return db.query(AppSetting).filter(AppSetting.key == DEMO_MODE_SETTING_KEY).first()


def is_demo_mode_enabled(db: Session) -> bool:
    # Hard env gate: when DEMO_MODE=false, demo profiles are fully excluded.
    if not bool(getattr(settings, "DEMO_MODE", False)):
        return False
    row = _setting_row(db)
    value = _bool_from_setting(getattr(row, "value_json", None) if row else None)
    if value is not None:
        return value
    return bool(getattr(settings, "DEMO_MODE_DEFAULT_ENABLED", True))


def set_demo_mode_enabled(db: Session, enabled: bool) -> bool:
    row = _setting_row(db)
    if not row:
        row = AppSetting(key=DEMO_MODE_SETTING_KEY, value_json="{}")
    row.value_json = json.dumps({"enabled": bool(enabled)})
    row.updated_at = _now()
    db.add(row)
    db.commit()
    return bool(enabled)


def _demo_svg_data_uri(display_name: str, colors: tuple[str, str]) -> str:
    initials = "".join(part[:1] for part in display_name.split()[:2]).upper() or "N"
    bg, accent = colors
    safe_initials = html.escape(initials)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1200" viewBox="0 0 900 1200">
<defs>
<linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="{html.escape(bg)}"/><stop offset="1" stop-color="{html.escape(accent)}"/></linearGradient>
<filter id="s"><feDropShadow dx="0" dy="24" stdDeviation="32" flood-opacity=".28"/></filter>
</defs>
<rect width="900" height="1200" fill="url(#g)"/>
<circle cx="720" cy="150" r="190" fill="rgba(255,255,255,.18)"/>
<circle cx="160" cy="980" r="260" fill="rgba(255,255,255,.16)"/>
<g filter="url(#s)">
<circle cx="450" cy="440" r="170" fill="rgba(255,255,255,.78)"/>
<rect x="210" y="650" width="480" height="320" rx="160" fill="rgba(255,255,255,.72)"/>
</g>
<text x="450" y="1038" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-size="72" font-weight="800" fill="rgba(255,255,255,.92)">{safe_initials}</text>
</svg>"""
    return "data:image/svg+xml;charset=utf-8," + quote(svg, safe="")


def _photo_urls_for_spec(spec: dict[str, object]) -> str:
    colors = spec.get("colors")
    if not isinstance(colors, tuple) or len(colors) != 2:
        colors = ("#6F5CFF", "#F4D35E")
    return _demo_svg_data_uri(str(spec.get("display_name") or "Demo"), colors)[:7800]


def _demo_email(slug: str) -> str:
    return f"demo+{slug}@neyra.local"


def demo_user_ids(db: Session) -> list[int]:
    return [
        int(r[0])
        for r in db.query(User.id).filter(User.is_demo == True).all()  # noqa: E712
        if r and r[0]
    ]


def is_demo_profile(profile: Profile | None, user: User | None = None) -> bool:
    return bool(
        (profile is not None and bool(getattr(profile, "is_demo_profile", False)))
        or (user is not None and bool(getattr(user, "is_demo", False)))
    )


def is_demo_user(user: User | None = None, profile: Profile | None = None) -> bool:
    """Unified demo detector used by discover/swipe/chat flows."""
    if user is not None and bool(getattr(user, "is_demo", False)):
        return True
    if profile is not None and bool(getattr(profile, "is_demo_profile", False)):
        return True
    email = str(getattr(user, "email", "") or "").strip().lower()
    if email.startswith("demo+") and email.endswith("@neyra.local"):
        return True
    source = str(getattr(profile, "source", "") or "").strip().lower()
    if source in {"demo", "demo_profile", "demo-bot"}:
        return True
    return False


def demo_live_defaults() -> dict:
    return {"enabled": False, "ignore_rate": 0.3, "speed": "normal"}


def get_demo_live_settings(db: Session) -> dict:
    row = db.query(AppSetting).filter(AppSetting.key == DEMO_LIVE_SETTING_KEY).first()
    base = demo_live_defaults()
    if not row or not getattr(row, "value_json", None):
        return base
    try:
        data = json.loads(row.value_json)
    except Exception:
        return base
    if not isinstance(data, dict):
        return base
    if "enabled" in data:
        base["enabled"] = bool(data["enabled"])
    if "ignore_rate" in data:
        try:
            base["ignore_rate"] = max(0.05, min(0.9, float(data["ignore_rate"])))
        except Exception:
            pass
    if str(data.get("speed") or "").strip().lower() in {"fast", "normal", "slow"}:
        base["speed"] = str(data["speed"]).strip().lower()
    return base


def set_demo_live_settings(
    db: Session,
    *,
    enabled: bool | None = None,
    ignore_rate: float | None = None,
    ignore_rate_delta: float | None = None,
    speed: str | None = None,
) -> dict:
    cur = get_demo_live_settings(db)
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    if ignore_rate is not None:
        cur["ignore_rate"] = max(0.05, min(0.9, float(ignore_rate)))
    if ignore_rate_delta is not None:
        cur["ignore_rate"] = max(0.05, min(0.9, float(cur["ignore_rate"]) + float(ignore_rate_delta)))
    if speed is not None and str(speed).strip().lower() in {"fast", "normal", "slow"}:
        cur["speed"] = str(speed).strip().lower()
    row = db.query(AppSetting).filter(AppSetting.key == DEMO_LIVE_SETTING_KEY).first()
    if not row:
        row = AppSetting(key=DEMO_LIVE_SETTING_KEY, value_json="{}")
    row.value_json = json.dumps(cur)
    row.updated_at = _now()
    db.add(row)
    db.commit()
    return cur


def is_demo_live_enabled(db: Session) -> bool:
    if not bool(getattr(settings, "DEMO_LIVE_BEHAVIOR", False)):
        return False
    return bool(is_demo_mode_enabled(db) and get_demo_live_settings(db).get("enabled"))


def ensure_demo_personality_json(profile: Profile | None) -> None:
    if not profile or not getattr(profile, "is_demo_profile", False):
        return
    try:
        cur = json.loads(getattr(profile, "demo_personality_json", None) or "{}")
    except Exception:
        cur = {}
    if not isinstance(cur, dict):
        cur = {}
    import random

    legacy_map = {
        "flirty": "playful",
        "dry": "sarcastic",
        "cold": "sarcastic",
        "curious": "deep",
        "calm": "warm",
        "confident": "playful",
    }
    p_raw = str(cur.get("personality") or "").strip().lower()
    if p_raw in legacy_map:
        cur["personality"] = legacy_map[p_raw]

    defaults = {
        "personality": random.choice(["playful", "deep", "sarcastic", "warm"]),
        "style": random.choice(["warm", "playful", "calm", "bold"]),
        "interests": random.sample(
            ["travel", "coffee", "music", "movies", "hiking", "food", "books", "nightlife", "pets", "gaming", "art"],
            k=random.randint(2, 4),
        ),
        "humor_style": random.choice(["dry", "warm", "silly", "deadpan"]),
        "humor": random.choice(["light", "dry", "soft_tease"]),
        "emotional_style": random.choice(["steady", "expressive", "guarded"]),
        "dating_goal": random.choice(["relationship", "dating", "chat"]),
        "response_speed": random.choice(["fast", "normal", "slow"]),
        "reply_speed": random.choice(["fast", "normal", "slow"]),
        "reply_delay_min": 5,
        "reply_delay_max": 25,
        "flirt_level": random.randint(1, 2),
        "flirt_level_label": random.choice(["low", "medium", "high"]),
        "engagement_level": round(random.uniform(0.35, 0.95), 2),
        "preferred_topics": [],
        "boundaries": "Keep it respectful; no explicit content; no pressure to meet.",
    }
    for k, v in defaults.items():
        if k not in cur or cur[k] in (None, "", []):
            cur[k] = v
    # Merge legacy preferred_topics into interests if interests empty
    if (not cur.get("interests")) and isinstance(cur.get("preferred_topics"), list) and cur["preferred_topics"]:
        cur["interests"] = list(cur["preferred_topics"])
    if not isinstance(cur.get("interests"), list):
        cur["interests"] = defaults["interests"]
    try:
        cur["reply_delay_min"] = int(max(3, min(60, int(cur.get("reply_delay_min", 5)))))
        cur["reply_delay_max"] = int(max(cur["reply_delay_min"], min(120, int(cur.get("reply_delay_max", 25)))))
    except Exception:
        cur["reply_delay_min"], cur["reply_delay_max"] = 5, 25
    try:
        cur["flirt_level"] = int(max(0, min(3, int(cur.get("flirt_level", 1)))))
    except Exception:
        cur["flirt_level"] = 1
    fl_lab = str(cur.get("flirt_level_label") or "").strip().lower()
    if fl_lab not in {"low", "medium", "high"}:
        if int(cur["flirt_level"]) <= 1:
            fl_lab = "low"
        elif int(cur["flirt_level"]) == 2:
            fl_lab = "medium"
        else:
            fl_lab = "high"
    cur["flirt_level_label"] = fl_lab
    if str(cur.get("style") or "").strip().lower() not in {"warm", "playful", "calm", "bold"}:
        cur["style"] = "warm"
    if str(cur.get("humor") or "").strip().lower() not in {"light", "dry", "soft_tease"}:
        cur["humor"] = "light"
    if str(cur.get("reply_speed") or "").strip().lower() not in {"fast", "normal", "slow"}:
        cur["reply_speed"] = str(cur.get("response_speed") or "normal").strip().lower()
    if str(cur.get("personality") or "").strip().lower() not in {"playful", "deep", "sarcastic", "warm"}:
        cur["personality"] = defaults["personality"]

    profile.demo_personality_json = json.dumps(cur)


def is_demo_user_id(db: Session, user_id: int) -> bool:
    row = (
        db.query(User.is_demo, Profile.is_demo_profile)
        .outerjoin(Profile, Profile.user_id == User.id)
        .filter(User.id == int(user_id))
        .first()
    )
    if not row:
        return False
    return bool(row[0]) or bool(row[1])


def ensure_demo_profiles(db: Session, target_count: int = DEMO_TARGET_COUNT) -> int:
    catalog = load_demo_profiles_catalog()
    now = _now()
    if catalog:
        target = max(1, min(int(target_count or DEMO_TARGET_COUNT), len(catalog)))
        stats = {"created": 0, "updated": 0, "skipped": 0, "gender_assigned": []}
        for index, entry in enumerate(catalog[:target]):
            _apply_catalog_demo_row(db, entry, index, now, stats)
        db.commit()
        return int(
            db.query(Profile)
            .join(User, User.id == Profile.user_id)
            .filter(User.is_demo == True, Profile.is_demo_profile == True)  # noqa: E712
            .count()
        )

    target = max(1, min(int(target_count or DEMO_TARGET_COUNT), len(DEMO_PROFILE_SPECS)))
    specs = DEMO_PROFILE_SPECS[:target]
    for index, spec in enumerate(specs):
        slug = str(spec["slug"])
        email = _demo_email(slug)
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                hashed_password=None,
                is_active=True,
                is_demo=True,
                created_at=now - timedelta(days=index + 1),
                last_active_at=now - timedelta(hours=index + 1),
                matches_last_seen_at=now - timedelta(hours=index + 1),
            )
            db.add(user)
            db.flush()
        else:
            user.is_demo = True
            user.is_active = True
            user.is_deleted = False
            user.is_banned = False
            user.last_active_at = user.last_active_at or (now - timedelta(hours=index + 1))
            user.matches_last_seen_at = user.matches_last_seen_at or (now - timedelta(hours=index + 1))
            db.add(user)

        profile = db.query(Profile).filter(Profile.user_id == int(user.id)).first()
        if not profile:
            profile = Profile(user_id=int(user.id), display_name=str(spec["display_name"]))
        profile.display_name = str(spec["display_name"])
        profile.age = int(spec["age"])
        profile.city = str(spec["city"])
        profile.gender = str(spec["gender"])
        profile.interested_in = str(spec["interested_in"])
        profile.relationship_goal = str(spec["goal"])
        profile.interests = str(spec["interests"])
        profile.lifestyle_tags = str(spec["lifestyle"])
        profile.bio = str(spec["bio"])
        profile.photo_urls = _photo_urls_for_spec(spec)
        profile.onboarding_completed = True
        profile.founder_welcome_seen = True
        profile.is_demo_profile = True
        profile.demo_disclaimer = DEMO_PROFILE_DISCLAIMER
        profile.preferred_language = "en"
        ensure_demo_personality_json(profile)
        _apply_demo_trust_and_premium(user, profile, index, now)
        db.add(user)
        db.add(profile)
    db.commit()
    return int(db.query(Profile).join(User, User.id == Profile.user_id).filter(User.is_demo == True, Profile.is_demo_profile == True).count())  # noqa: E712


def clear_demo_conversations(db: Session) -> dict:
    ids = demo_user_ids(db)
    if not ids:
        return {"demo_users": 0, "messages_deleted": 0, "matches_deleted": 0, "swipes_deleted": 0}
    message_ids = [
        int(r[0])
        for r in db.query(Message.id).filter(or_(Message.sender_id.in_(ids), Message.receiver_id.in_(ids))).all()
        if r and r[0]
    ]
    reactions_deleted = 0
    messages_deleted = 0
    if message_ids:
        reactions_deleted = int(db.query(MessageReaction).filter(MessageReaction.message_id.in_(message_ids)).delete(synchronize_session=False) or 0)
        messages_deleted = int(db.query(Message).filter(Message.id.in_(message_ids)).delete(synchronize_session=False) or 0)
    matches_deleted = int(db.query(Match).filter(or_(Match.user_a_id.in_(ids), Match.user_b_id.in_(ids))).delete(synchronize_session=False) or 0)
    swipes_deleted = int(db.query(Swipe).filter(or_(Swipe.swiper_id.in_(ids), Swipe.target_user_id.in_(ids))).delete(synchronize_session=False) or 0)
    read_deleted = int(
        db.query(ThreadReadState)
        .filter(or_(ThreadReadState.user_id.in_(ids), ThreadReadState.partner_user_id.in_(ids)))
        .delete(synchronize_session=False)
        or 0
    )
    reports_deleted = int(
        db.query(UserReport)
        .filter(or_(UserReport.reporter_id.in_(ids), UserReport.reported_user_id.in_(ids)))
        .delete(synchronize_session=False)
        or 0
    )
    blocks_deleted = int(
        db.query(UserBlock)
        .filter(or_(UserBlock.blocker_id.in_(ids), UserBlock.blocked_id.in_(ids)))
        .delete(synchronize_session=False)
        or 0
    )
    ignores_deleted = int(
        db.query(UserIgnore)
        .filter(or_(UserIgnore.user_id.in_(ids), UserIgnore.ignored_user_id.in_(ids)))
        .delete(synchronize_session=False)
        or 0
    )
    db.commit()
    return {
        "demo_users": len(ids),
        "messages_deleted": messages_deleted,
        "message_reactions_deleted": reactions_deleted,
        "matches_deleted": matches_deleted,
        "swipes_deleted": swipes_deleted,
        "thread_reads_deleted": read_deleted,
        "reports_deleted": reports_deleted,
        "blocks_deleted": blocks_deleted,
        "ignores_deleted": ignores_deleted,
    }


def purge_all_demo_users(db: Session) -> dict:
    """
    Delete every user with is_demo=True and dependent rows (ORM bulk deletes).
    Does not touch real users (only User.is_demo == True defines the purge set).
    """
    ids = demo_user_ids(db)
    if not ids:
        return {"ok": True, "removed_users": 0, "note": "no_demo_users"}

    id_list = [int(x) for x in ids]
    conv = clear_demo_conversations(db)

    def _del_count(q) -> int:
        return int(q.delete(synchronize_session=False) or 0)

    extras: dict[str, int] = {}
    extras["analytics_events_deleted"] = _del_count(db.query(AnalyticsEvent).filter(AnalyticsEvent.user_id.in_(id_list)))
    extras["ai_interaction_events_deleted"] = _del_count(
        db.query(AiInteractionEvent).filter(
            or_(
                AiInteractionEvent.user_id.in_(id_list),
                AiInteractionEvent.partner_user_id.in_(id_list),
            )
        )
    )
    extras["user_ai_memory_deleted"] = _del_count(db.query(UserAiMemory).filter(UserAiMemory.user_id.in_(id_list)))
    extras["user_ai_profile_deleted"] = _del_count(db.query(UserAiProfile).filter(UserAiProfile.user_id.in_(id_list)))
    extras["ai_trial_usage_deleted"] = _del_count(db.query(AiTrialUsage).filter(AiTrialUsage.user_id.in_(id_list)))
    extras["oauth_accounts_deleted"] = _del_count(db.query(OAuthAccount).filter(OAuthAccount.user_id.in_(id_list)))
    extras["subscriptions_deleted"] = _del_count(db.query(Subscription).filter(Subscription.user_id.in_(id_list)))
    extras["device_tokens_deleted"] = _del_count(db.query(DeviceToken).filter(DeviceToken.user_id.in_(id_list)))
    extras["referral_reward_grants_deleted"] = _del_count(
        db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id.in_(id_list))
    )
    extras["verification_attempts_deleted"] = _del_count(
        db.query(VerificationAttempt).filter(VerificationAttempt.user_id.in_(id_list))
    )
    extras["profiles_deleted"] = _del_count(db.query(Profile).filter(Profile.user_id.in_(id_list)))
    extras["users_deleted"] = _del_count(db.query(User).filter(User.id.in_(id_list), User.is_demo == True))  # noqa: E712

    db.commit()
    out = {"ok": True, "removed_users": extras["users_deleted"], **conv, **extras}
    _log_demo.info("purge_all_demo_users %s", out)
    return out


def regenerate_demo_profiles(db: Session) -> dict:
    cleared = clear_demo_conversations(db)
    ids = demo_user_ids(db)
    profiles_deleted = 0
    users_deleted = 0
    if ids:
        profiles_deleted = int(db.query(Profile).filter(Profile.user_id.in_(ids)).delete(synchronize_session=False) or 0)
        users_deleted = int(db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False) or 0)
        db.commit()
    count = ensure_demo_profiles(db)
    return {
        **cleared,
        "profiles_deleted": profiles_deleted,
        "users_deleted": users_deleted,
        "demo_profiles": count,
    }


def demo_engagement_metrics(db: Session) -> dict:
    ids = demo_user_ids(db)
    demo_profiles_count = int(
        db.query(Profile)
        .join(User, User.id == Profile.user_id)
        .filter(User.is_demo == True, Profile.is_demo_profile == True)  # noqa: E712
        .count()
    )
    demo_conversations = 0
    demo_messages = 0
    if ids:
        demo_conversations = int(db.query(Match).filter(or_(Match.user_a_id.in_(ids), Match.user_b_id.in_(ids))).count())
        demo_messages = int(db.query(Message).filter(or_(Message.sender_id.in_(ids), Message.receiver_id.in_(ids))).count())

    event_names = [
        "demo_mode_started",
        "demo_profile_viewed",
        "demo_chat_started",
        "demo_first_message_sent",
        "demo_reply_sent",
        "demo_reply_ignored",
        "demo_revive_sent",
        "ai_suggestion_used_in_demo",
        "founder_welcome_seen",
        "feedback_clicked",
        "invite_clicked",
        "support_clicked",
    ]
    event_counts = {
        name: int(db.query(AnalyticsEvent).filter(AnalyticsEvent.name == name).count())
        for name in event_names
    }
    return {
        "demo_profiles": demo_profiles_count,
        "demo_conversations": demo_conversations,
        "demo_messages": demo_messages,
        "events": event_counts,
    }


def demo_mode_status(db: Session) -> dict:
    metrics = demo_engagement_metrics(db)
    today_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    demo_matches_created_today = int(
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.name == "demo_chat_started")
        .filter(AnalyticsEvent.created_at >= today_start)
        .count()
    )
    demo_messages_sent_today = int(
        db.query(AnalyticsEvent)
        .filter(AnalyticsEvent.name.in_(["demo_first_message_sent", "demo_reply_sent", "demo_revive_sent"]))
        .filter(AnalyticsEvent.created_at >= today_start)
        .count()
    )
    last_error = get_demo_last_error(db)
    env_flag = bool(getattr(settings, "DEMO_LIVE_BEHAVIOR", False))
    lb = get_demo_live_settings(db)
    return {
        "enabled": is_demo_mode_enabled(db),
        "live_behavior": lb,
        "demo_live_behavior_env": env_flag,
        "demo_live_effective": bool(env_flag and is_demo_mode_enabled(db) and lb.get("enabled")),
        "environment": (settings.ENV or "development").strip().lower(),
        "demo_profiles": int(metrics.get("demo_profiles") or 0),
        "demo_conversations": int(metrics.get("demo_conversations") or 0),
        "demo_matches_created_today": demo_matches_created_today,
        "demo_messages_sent_today": demo_messages_sent_today,
        "last_demo_bot_error": last_error,
        "metrics": metrics,
    }


def set_demo_last_error(db: Session, message: str) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == DEMO_LAST_ERROR_KEY).first()
    if not row:
        row = AppSetting(key=DEMO_LAST_ERROR_KEY, value_json="{}")
    row.value_json = json.dumps(
        {
            "message": str(message or "").strip()[:500],
            "at": _now().isoformat(),
        }
    )
    row.updated_at = _now()
    db.add(row)
    db.commit()


def get_demo_last_error(db: Session) -> dict | None:
    row = db.query(AppSetting).filter(AppSetting.key == DEMO_LAST_ERROR_KEY).first()
    if not row or not getattr(row, "value_json", None):
        return None
    try:
        out = json.loads(row.value_json)
    except Exception:
        return None
    return out if isinstance(out, dict) else None


def build_demo_reply(profile: Profile | None, user_message: str, context: list[str] | None = None) -> str:
    # If the user asked a direct question, answer it using the speaker (demo) profile first.
    try:
        from app.services.ai.orchestrator import AIOrchestrator

        ui_loc = getattr(profile, "preferred_language", None) if profile else None
        direct = AIOrchestrator.generate_demo_reply(
            speaker_profile=profile,
            partner_profile=None,
            user_message=user_message or "",
            ui_locale=str(ui_loc).strip() if ui_loc else None,
        )
        if direct:
            return direct
    except Exception:
        pass

    name = (getattr(profile, "display_name", "") or "there").strip()
    text = (user_message or "").strip().lower()
    context_count = len([x for x in (context or []) if str(x or "").strip()])
    tag = "Demo profile — not a real person."
    playful = [
        f"Haha okay — you’ve got {name}’s attention 🙂 What’s one thing you’re weirdly passionate about? {tag}",
        f"Cheeky question: if we skipped small talk, what would you actually want to talk about? {tag}",
        f"I like that energy. What’s been the highlight of your week so far? {tag}",
    ]
    curious = [
        f"Interesting — what drew you to say that? {tag}",
        f"I’m curious: what does a perfect Sunday look like for you? {tag}",
        f"Nice. What are you into lately when you’re not on here? {tag}",
    ]
    if "coffee" in text or "drink" in text or "meet" in text:
        pool = [
            f"That sounds fun 🙂 Are you more of a chill café person or a walk-and-talk person? {tag}",
            f"Love it. What kind of spot would feel easy for a first meet? {tag}",
        ]
    elif "music" in text or "film" in text or "movie" in text:
        pool = [
            f"Good taste — what’s one thing I should watch or listen to this week? {tag}",
            f"Nice — what’s your go-to comfort watch or album lately? {tag}",
        ]
    elif "hi" in text or "hello" in text or context_count == 0:
        pool = playful + curious
    else:
        pool = curious + playful
    return random.choice(pool)
