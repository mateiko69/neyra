import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url


def _running_in_container() -> bool:
    return Path("/.dockerenv").exists()

def _running_tests() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    argv = " ".join(sys.argv).lower()
    return "pytest" in argv


def _demo_bot_default_enabled() -> bool:
    env = str(os.environ.get("ENV", "") or "").strip().lower()
    if env in {"production", "prod"}:
        return False
    return True

def _is_weak_secret(value: str) -> bool:
    v = str(value or "").strip()
    if not v:
        return True
    low = v.lower()
    if low in {"change-me", "changeme", "default", "secret", "password"}:
        return True
    if "change-me" in low or "changeme" in low or "replace" in low:
        return True
    # Too short for HMAC/JWT signing and similar uses.
    if len(v) < 32:
        return True
    # Repeated single character (e.g. "aaaaaaaa...")
    if len(set(v)) <= 2 and len(v) >= 16:
        return True
    return False

def _warn_if_weak_prod_secrets(secret_key: str, admin_token: str) -> None:
    env = str(os.environ.get("ENV", "") or "").strip().lower()
    if env not in {"production", "prod"}:
        return
    # Avoid noisy warnings in tests.
    if _running_tests():
        return
    weak_secret = _is_weak_secret(secret_key)
    weak_admin = bool(admin_token) and _is_weak_secret(admin_token)
    if not (weak_secret or weak_admin):
        return
    msg = [
        "[SECURITY] Weak production secrets detected.",
        "Set a strong SECRET_KEY and a long random ADMIN_BOT_SERVICE_TOKEN before real deployment.",
        "This warning does not print secret values.",
    ]
    if weak_secret:
        msg.append("- SECRET_KEY looks default/weak")
    if weak_admin:
        msg.append("- ADMIN_BOT_SERVICE_TOKEN looks default/weak")
    print("\n".join(msg), file=sys.stderr)

def _default_database_url() -> str:
    """
    Fallback when DATABASE_URL is absent from env.
    Tests: SQLite test DB unless DATABASE_URL explicitly set (non-empty).
    Production (ENV production/prod): no default — must supply DATABASE_URL in env.
    Development: SQLite at ./local.db when DATABASE_URL absent or blank.
    Otherwise: local Docker Compose Postgres wiring (host dev default).
    """
    raw_present = os.environ.get("DATABASE_URL")
    explicit = raw_present is not None and bool(str(raw_present).strip())

    if _running_tests() and not explicit:
        return "sqlite:///./neyra_test.db"

    env_tag = str(os.environ.get("ENV", "") or "").strip().lower()
    if env_tag in {"production", "prod"}:
        return ""

    if not explicit:
        return "sqlite:///./local.db"

    return "postgresql://postgres:postgres@localhost:5434/neyra"

def _default_redis_url() -> str:
    if _running_tests() and not os.environ.get("REDIS_URL"):
        return ""
    return "redis://localhost:6381/0"

def _rewrite_local_service_url(raw_url: str, *, service_host: str, localhost_port: int) -> str:
    value = (raw_url or "").strip()
    if not value or _running_in_container():
        return value
    parts = urlsplit(value)
    if parts.hostname != service_host:
        return value

    auth = ""
    if parts.username:
        auth = parts.username
        if parts.password:
            auth = f"{auth}:{parts.password}"
        auth = f"{auth}@"

    port = localhost_port
    netloc = f"{auth}localhost:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None if _running_tests() else ".env",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "NEYRA"
    ENV: str = "development"
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    DATABASE_URL: str = _default_database_url()
    REDIS_URL: str = _default_redis_url()
    # Browser-facing frontend URL (used for OAuth redirects). Must never be a Docker-internal hostname.
    FRONTEND_URL: str = "http://localhost:3000"
    PUBLIC_FRONTEND_URL: str = "http://localhost:3000"
    # Optional production alias (Railway/Vercel): when set, overrides FRONTEND_URL + PUBLIC_FRONTEND_URL to this origin.
    APP_PUBLIC_URL: str = ""
    # Comma-separated allowed browser origins for CORS (production). Must include https://your-web-app (no path).
    # If empty in production, defaults to FRONTEND_URL plus built-in getneyra.app hosts (see app.main CORS builder).
    CORS_ORIGINS: str = ""
    # When true, also allow any https://*.vercel.app origin (preview deployments).
    CORS_ALLOW_VERCEL_PREVIEWS: bool = True
    # Docker/internal frontend URL (used for in-container checks like Deep QA).
    INTERNAL_FRONTEND_URL: str = "http://neyra-web:3000"
    ADMIN_EMAILS: str = "admin@example.com"
    # When enabled, the app attempts an eager DB connect check on import/startup.
    # In Docker we want this on (paired with compose healthchecks); in local tests it's usually off.
    DB_EAGER_CONNECT: bool = _running_in_container()

    # Feature flags (operational toggles; safe defaults for dev)
    ENABLE_AI_SUGGESTIONS: bool = True
    ENABLE_ADVANCED_MATCHING: bool = True
    ENABLE_PREMIUM_FEATURES: bool = True
    DEMO_MODE: bool = True
    DEMO_MODE_DEFAULT_ENABLED: bool = True
    AI_STRICT_MONETIZATION: bool = False
    QA_AGENT_ENABLED: bool = False
    QA_AGENT_DEMO_ONLY: bool = True
    # When true, the API allows living demo behavior (delayed demo replies) and the background tick runs.
    # Still requires demo mode + admin "live behavior" enabled in DB. Default off for safer prod deploys.
    DEMO_LIVE_BEHAVIOR: bool = False
    # Demo chat bot controls (product walkthrough in Discover/Chat).
    DEMO_BOT_CHAT_ENABLED: bool = _demo_bot_default_enabled()
    DEMO_BOT_REPLY_DELAY_SECONDS: int = 2
    DEMO_BOT_FIRST_MESSAGE_ENABLED: bool = _demo_bot_default_enabled()
    # Dev-only override: treat all users as premium. Ignored in production.
    DEV_FORCE_PREMIUM: bool = False
    # When true, admin localization Gemini endpoints are allowed even if ENV=production.
    LOCALIZATION_DEV_TOOLS_ENABLED: bool = False
    # General dev-only endpoints (reset swipes, etc). Must be explicitly enabled.
    DEV_TOOLS_ENABLED: bool = False

    # Swipe loop tuning (controls match dopamine frequency).
    # Applied only when a reciprocal like exists and a match would normally be created.
    # 0.25 ~= 25% match rate on mutual likes.
    SWIPE_MATCH_CREATE_PROBABILITY: float = 1.0 if _running_tests() else 0.27

    AI_PROVIDER: str = "mock"
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # Dedicated Gemini model override.
    # NOTE: Chat endpoints must prefer GEMINI_CHAT_MODEL; GEMINI_MODEL is legacy/global.
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"
    # Gemini model routing (separate knobs for cost/quality by use-case).
    # - chat: in-product suggestions (fast/cheap)
    # - analysis: admin/system deep reasoning
    # - localization: i18n generation/QA (structured JSON)
    # Use env-provided models when available; defaults are kept modern/stable.
    GEMINI_CHAT_MODEL: str = "gemini-2.5-flash-lite"
    GEMINI_ANALYSIS_MODEL: str = "gemini-2.5-flash-lite"
    GEMINI_LOCALIZATION_MODEL: str = "gemini-2.5-flash-lite"
    AI_MODEL: str = "gpt-4o-mini"  # Non-gemini providers only (never used by GeminiClient model chain).
    AI_MAX_TOKENS: int = 450
    AI_TEMPERATURE: float = 0.85
    AI_CACHE_TTL_SECONDS: int = 3600
    # After any Gemini HTTP failure, suppress further Gemini POSTs for this many seconds (memory + Redis mirror).
    GEMINI_GLOBAL_FAILURE_COOLDOWN_SECONDS: int = 60
    # When True, only GEMINI_ALLOWED_SURFACES (or built-in defaults) may call Gemini; others raise → caller fallback.
    GEMINI_PRIORITY_SURFACES_ONLY: bool = False
    # Optional CSV override for allowed surfaces (empty → chat-brain, timed-replies, chat-copilot, admin-debug).
    GEMINI_ALLOWED_SURFACES: str = ""

    # AI rate limiting (per-user). Premium gets higher limits via entitlements.
    AI_CALLS_PER_MINUTE_FREE: int = 12
    AI_CALLS_PER_DAY_FREE: int = 40
    AI_CALLS_PER_MINUTE_PREMIUM: int = 30
    AI_CALLS_PER_DAY_PREMIUM: int = 400

    STORAGE_PROVIDER: str = "local"
    # Local upload storage (filesystem directory) + public URL prefix (served by FastAPI StaticFiles).
    # Examples:
    # - UPLOAD_DIR=/app/uploads
    # - UPLOAD_PUBLIC_PREFIX=/uploads
    UPLOAD_DIR: str = "uploads"
    UPLOAD_PUBLIC_PREFIX: str = "/uploads"
    # Backwards-compat: older env var still supported when UPLOAD_* not set.
    LOCAL_UPLOAD_DIR: str = "uploads"
    # Browser-reachable base URL for locally stored uploads (no trailing slash).
    PUBLIC_BACKEND_URL: str = "http://localhost:8000"
    S3_BUCKET: str = ""
    S3_REGION: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""

    PAYMENTS_PROVIDER: str = "mock"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # Paddle Billing (Merchant of Record) — subscriptions
    # Product/price IDs from Paddle Dashboard (sandbox vs live).
    PADDLE_WEBHOOK_SECRET: str = ""
    PADDLE_PRICE_ID_PREMIUM_MONTHLY: str = ""
    PADDLE_PRICE_ID_PREMIUM_PLUS_MONTHLY: str = ""

    PUSH_PROVIDER: str = "mock"
    FIREBASE_CREDENTIALS_JSON: str = ""

    # Daily.co video calls (MVP)
    DAILY_API_KEY: str = ""
    DAILY_DOMAIN: str = ""  # e.g. "your-domain.daily.co"

    # Retention worker (push nudges + revive + micro rewards)
    RETENTION_WORKER: bool = True
    RETENTION_TICK_MIN_SECONDS: int = 240
    RETENTION_TICK_MAX_SECONDS: int = 600

    # AI Growth Engine (global metrics → safe actions)
    GROWTH_ENGINE_WORKER: bool = True
    GROWTH_ENGINE_TICK_MIN_SECONDS: int = 300
    GROWTH_ENGINE_TICK_MAX_SECONDS: int = 900

    # Learning worker (behavior → compact user memory → better AI suggestions)
    LEARNING_WORKER: bool = True
    LEARNING_TICK_MIN_SECONDS: int = 600
    LEARNING_TICK_MAX_SECONDS: int = 1800

    # A/B testing for UI copy (analytics → promote winners)
    AB_ENGINE_WORKER: bool = True
    AB_ENGINE_TICK_MIN_SECONDS: int = 900
    AB_ENGINE_TICK_MAX_SECONDS: int = 3600

    RATE_LIMIT_PER_MINUTE: int = 60
    # When false, IP rate limiting is disabled (local/stress testing only). Production should keep true.
    RATE_LIMIT_ENABLED: bool = True
    QUEUE_NAME: str = "app_events"

    # OAuth / social sign-in (enable per provider in production)
    ENABLE_GOOGLE_OAUTH: bool = False
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = ""
    ENABLE_APPLE_OAUTH: bool = False
    APPLE_OAUTH_CLIENT_ID: str = ""
    APPLE_TEAM_ID: str = ""
    APPLE_KEY_ID: str = ""
    APPLE_PRIVATE_KEY: str = ""
    APPLE_REDIRECT_URI: str = ""
    ENABLE_FACEBOOK_OAUTH: bool = False
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""
    FACEBOOK_REDIRECT_URI: str = ""
    # Dev-only: enable mock social login endpoints (never enable in production).
    AUTH_DEV_SOCIAL: bool = False

    # Verification
    VERIFICATION_PROVIDER: str = "mock"
    VERIFICATION_ATTEMPTS_PER_DAY: int = 5

    # Telegram Admin Bot internal auth (service token for admin endpoints only).
    ADMIN_BOT_SERVICE_TOKEN: str = ""

    @model_validator(mode="after")
    def _apply_app_public_url(self):
        pub = (self.APP_PUBLIC_URL or "").strip().rstrip("/")
        if pub:
            object.__setattr__(self, "FRONTEND_URL", pub)
            object.__setattr__(self, "PUBLIC_FRONTEND_URL", pub)
        return self

    @field_validator("PUBLIC_BACKEND_URL", mode="before")
    @classmethod
    def public_backend_fallback(cls, v):
        if v is None:
            return "http://localhost:8000"
        if isinstance(v, str) and not v.strip():
            return "http://localhost:8000"
        return v

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def database_url_prepare(cls, v):
        if v is None:
            return ""
        if not isinstance(v, str):
            return v
        s = str(v).strip().strip('"').strip("'")
        if s.startswith("postgres://"):
            s = "postgresql://" + s[len("postgres://") :]
        return _rewrite_local_service_url(s, service_host="db", localhost_port=5434)

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def database_url_normalize(cls, v: object, info: ValidationInfo) -> str:
        if isinstance(v, str):
            v_str = v.strip()
        else:
            v_str = ""

        env_val = (info.data.get("ENV") if info.data else None) or "development"
        production = str(env_val).strip().lower() in {"production", "prod"}

        if not v_str:
            if production:
                raise ValueError(
                    "DATABASE_URL is unset or empty. In production, set DATABASE_URL to your PostgreSQL "
                    "connection string (Railway Postgres provides this)."
                )
            return "sqlite:///./local.db"

        try:
            make_url(v_str)
        except Exception:
            raise ValueError(
                "DATABASE_URL could not be parsed as a SQLAlchemy database URL "
                "(check scheme and formatting; secrets are never logged)."
            ) from None

        return v_str

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def redis_url_fallback(cls, v):
        if not isinstance(v, str):
            return v
        return _rewrite_local_service_url(v, service_host="redis", localhost_port=6381)

    def admin_emails_list(self) -> list[str]:
        return [x.strip().lower() for x in self.ADMIN_EMAILS.split(",") if x.strip()]

settings = Settings()
_warn_if_weak_prod_secrets(settings.SECRET_KEY, settings.ADMIN_BOT_SERVICE_TOKEN)
