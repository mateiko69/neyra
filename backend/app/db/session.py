import time
import logging
from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401

_log = logging.getLogger("neyra.db.startup")

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

def _should_eager_check_db() -> bool:
    """
    Eager DB connect checks are useful in containers to avoid crash loops,
    but they make local test collection fail when Postgres isn't running.
    Default: lazy-connect (no eager check) unless explicitly enabled.
    """
    value = str(getattr(settings, "DB_EAGER_CONNECT", "") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}

def _create_engine_with_retry():
    engine_kwargs = {
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }
    # SQLite doesn't support these pool args.
    if not settings.DATABASE_URL.startswith("sqlite"):
        engine_kwargs.update(
            {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_recycle": 1800,
            }
        )
    engine = create_engine(settings.DATABASE_URL, **engine_kwargs)
    # Retry DB availability on startup to avoid container crash when Postgres isn't ready yet.
    if _should_eager_check_db() and not settings.DATABASE_URL.startswith("sqlite"):
        attempts = 10
        delay_s = 1.0
        last_err: Exception | None = None
        for _ in range(attempts):
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                last_err = None
                break
            except Exception as e:
                last_err = e
                time.sleep(delay_s)
        if last_err is not None:
            # Production resilience: do not crash process if DB is slow/unready during import.
            _log.warning("db_eager_connect_unavailable_starting_anyway: %s", last_err)
    return engine


engine = _create_engine_with_retry()
try:
    _du = getattr(engine.url, "drivername", "unknown")
    _log.info("database_engine dialect=%s driver=%s", getattr(engine.dialect, "name", "unknown"), _du)
except Exception:
    pass
# In test mode with SQLite, create tables automatically so unit tests don't require migrations.
if settings.DATABASE_URL.startswith("sqlite"):
    try:
        Base.metadata.create_all(bind=engine)
        # Lightweight SQLite schema patching for dev/tests.
        # SQLite `create_all()` does not ALTER existing tables to add new columns,
        # so a persistent local sqlite db can drift behind models.
        with engine.connect() as conn:
            try:
                cols = [r[1] for r in conn.execute(text("PRAGMA table_info('profiles')")).fetchall()]
                if "onboarding_completed" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN onboarding_completed BOOLEAN NOT NULL DEFAULT 0"))
                    conn.commit()
                if "founder_welcome_seen" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN founder_welcome_seen BOOLEAN NOT NULL DEFAULT 0"))
                if "is_demo_profile" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN is_demo_profile BOOLEAN NOT NULL DEFAULT 0"))
                if "demo_disclaimer" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN demo_disclaimer TEXT NOT NULL DEFAULT ''"))
                # Normalized location fields (best-effort; real deployments use Alembic).
                if "city_original" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN city_original VARCHAR(100) NOT NULL DEFAULT ''"))
                if "city_en" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN city_en VARCHAR(100) NOT NULL DEFAULT ''"))
                if "city_local" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN city_local VARCHAR(100) NOT NULL DEFAULT ''"))
                if "city_locative_uk" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN city_locative_uk VARCHAR(100) NOT NULL DEFAULT ''"))
                if "country_code" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN country_code VARCHAR(2) NOT NULL DEFAULT ''"))
                if "region" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN region VARCHAR(64) NOT NULL DEFAULT ''"))
                if "timezone" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT ''"))
                if "demo_personality_json" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN demo_personality_json TEXT NOT NULL DEFAULT '{}'"))
                if "demo_reply_scheduled_at" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN demo_reply_scheduled_at DATETIME"))
                if "demo_first_message_sent_at" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN demo_first_message_sent_at DATETIME"))
                if "demo_last_auto_message_at" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN demo_last_auto_message_at DATETIME"))
                if "demo_pending_json" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN demo_pending_json TEXT NOT NULL DEFAULT '{}'"))
                if "preferred_gender" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN preferred_gender VARCHAR(32) NOT NULL DEFAULT ''"))
                if "native_language" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN native_language VARCHAR(8) NOT NULL DEFAULT ''"))
                if "additional_languages" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN additional_languages TEXT NOT NULL DEFAULT ''"))
                if "date_of_birth" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN date_of_birth DATE"))
                if "vibe" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN vibe VARCHAR(32) NOT NULL DEFAULT ''"))
                if "height_cm" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN height_cm INTEGER"))
                if "job_title" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN job_title VARCHAR(100) NOT NULL DEFAULT ''"))
                # Verification fields (best-effort; real deployments use Alembic).
                if "verification_level" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN verification_level VARCHAR(16) NOT NULL DEFAULT 'none'"))
                if "verification_badge_visible" not in cols:
                    conn.execute(text("ALTER TABLE profiles ADD COLUMN verification_badge_visible BOOLEAN NOT NULL DEFAULT 1"))
                conn.commit()
            except Exception:
                # Best-effort only; real deployments use Alembic migrations (Postgres).
                pass
            try:
                cols = [r[1] for r in conn.execute(text("PRAGMA table_info('users')")).fetchall()]
                if "email_verified" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 0"))
                if "email_verified_at" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN email_verified_at DATETIME"))
                if "premium_until" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN premium_until DATETIME"))
                if "is_trial" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_trial BOOLEAN NOT NULL DEFAULT 0"))
                if "is_trial_used" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_trial_used BOOLEAN NOT NULL DEFAULT 0"))
                if "trial_started_at" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN trial_started_at DATETIME"))
                if "created_at" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN created_at DATETIME"))
                if "last_active_at" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_active_at DATETIME"))
                if "is_banned" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_banned BOOLEAN NOT NULL DEFAULT 0"))
                if "is_demo" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT 0"))
                if "referral_code" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN referral_code VARCHAR(16)"))
                if "referred_by_user_id" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN referred_by_user_id INTEGER"))
                if "subscription_plan" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN subscription_plan VARCHAR(32) NOT NULL DEFAULT 'free'"))
                if "subscription_status" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN subscription_status VARCHAR(32) NOT NULL DEFAULT 'inactive'"))
                if "subscription_expires_at" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN subscription_expires_at DATETIME"))
                # Trial + AI usage mirrors (0041+); SQLite dev DBs may predate migrations.
                if "trial_active" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN trial_active BOOLEAN NOT NULL DEFAULT 0"))
                if "trial_expires_at" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN trial_expires_at DATETIME"))
                if "ai_free_used_count" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN ai_free_used_count INTEGER NOT NULL DEFAULT 0"))
                if "ai_last_used_at" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN ai_last_used_at DATETIME"))
                conn.commit()
            except Exception:
                pass

            try:
                cols = [r[1] for r in conn.execute(text("PRAGMA table_info('messages')")).fetchall()]
                if "is_demo_simulation" not in cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN is_demo_simulation BOOLEAN NOT NULL DEFAULT 0"))
                conn.commit()
            except Exception:
                pass

            try:
                cols = [r[1] for r in conn.execute(text("PRAGMA table_info('ai_interaction_events')")).fetchall()]
                if cols and "thread_id" not in cols:
                    conn.execute(text("ALTER TABLE ai_interaction_events ADD COLUMN thread_id VARCHAR(64)"))
                    conn.commit()
            except Exception:
                pass

            try:
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS app_settings ("
                        "id INTEGER NOT NULL PRIMARY KEY, "
                        "key VARCHAR(100) NOT NULL UNIQUE, "
                        "value_json TEXT NOT NULL DEFAULT '{}', "
                        "updated_at DATETIME NOT NULL)"
                    )
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_app_settings_key ON app_settings (key)"))
                conn.commit()
            except Exception:
                pass

            try:
                cols = [r[1] for r in conn.execute(text("PRAGMA table_info('user_reports')")).fetchall()]
                if "category" not in cols:
                    conn.execute(text("ALTER TABLE user_reports ADD COLUMN category VARCHAR(32) NOT NULL DEFAULT 'other'"))
                if "status" not in cols:
                    conn.execute(text("ALTER TABLE user_reports ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'open'"))
                conn.commit()
            except Exception:
                pass

            # Promo codes table (create_all handles this for fresh DBs; keep best-effort fallback).
            try:
                conn.execute(text("SELECT 1 FROM promo_codes LIMIT 1"))
            except Exception:
                # If table is missing, ignore; tests/dev can rely on create_all on startup.
                pass

            try:
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS referral_reward_grants ("
                        "id INTEGER NOT NULL PRIMARY KEY, "
                        "user_id INTEGER NOT NULL, "
                        "milestone_key VARCHAR(16) NOT NULL, "
                        "premium_days INTEGER NOT NULL, "
                        "created_at DATETIME NOT NULL, "
                        "FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE, "
                        "UNIQUE (user_id, milestone_key))"
                    )
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_referral_reward_grants_user_id ON referral_reward_grants (user_id)")
                )
                conn.commit()
            except Exception:
                pass
    except Exception:
        pass
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
