import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import SessionLocal
from app.interfaces.http.router import api_router
from app.middleware.rate_limit import RateLimitMiddleware
from app.models.profile import Profile
from app.models.user import User
from sqlalchemy import inspect, text
from app.services.demo_mode import demo_profiles_public_dir
from app.services.system.errors import record_api_error, record_system_error
from app.services.system.uptime import uptime_seconds

setup_logging()

_dev_http_log = logging.getLogger("neyra.devhttp")
_startup_log = logging.getLogger("neyra.startup")
_STARTED_AT = time.time()


def _is_production_env() -> bool:
    return (settings.ENV or "").strip().lower() in ("production", "prod")


_DEFAULT_PRODUCTION_CORS_ORIGINS: tuple[str, ...] = (
    "https://getneyra.app",
    "https://www.getneyra.app",
)


def _cors_allow_origins() -> list[str]:
    fe = (settings.FRONTEND_URL or "").strip().rstrip("/")
    if not _is_production_env():
        out = {fe, "http://localhost:3000", "http://localhost:8081"}
        return sorted(x for x in out if x)

    raw = (getattr(settings, "CORS_ORIGINS", "") or "").strip()
    extras = [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]
    merged: dict[str, None] = {}
    for d in _DEFAULT_PRODUCTION_CORS_ORIGINS:
        merged.setdefault(d, None)
    for p in extras:
        merged.setdefault(p, None)
    if fe:
        merged.setdefault(fe, None)
    return list(merged.keys())


def _cors_allow_origin_regex() -> str | None:
    if not _is_production_env():
        return None
    if not getattr(settings, "CORS_ALLOW_VERCEL_PREVIEWS", True):
        return None
    # Vercel preview deployments: https://<project>-<branch>-<org>.vercel.app
    return r"^https://[a-zA-Z0-9][a-zA-Z0-9-]{0,100}\.vercel\.app$"


app = FastAPI(title=settings.APP_NAME)
# Standardize on no trailing slashes. We register explicit aliases where needed.
# Disabling redirect_slashes removes Starlette's automatic 307 redirects.
app.router.redirect_slashes = False


@app.exception_handler(RequestValidationError)
async def _dev_request_validation_handler(request: Request, exc: RequestValidationError):
    if not _is_production_env():
        _dev_http_log.warning(
            json.dumps(
                {
                    "event": "request_validation_failed",
                    "path": request.url.path,
                    "method": request.method,
                    "status": 422,
                    "errors": exc.errors(),
                },
                default=str,
            )
        )
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(StarletteHTTPException)
async def _dev_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if not _is_production_env() and exc.status_code in (400, 401, 403, 404, 422, 429):
        detail = exc.detail
        if not isinstance(detail, (str, int, float, bool, type(None))):
            detail = "[complex detail omitted]"
        _dev_http_log.warning(
            json.dumps(
                {
                    "event": "http_exception",
                    "path": request.url.path,
                    "method": request.method,
                    "status": exc.status_code,
                    "detail": detail,
                }
            )
        )
    return await http_exception_handler(request, exc)


@app.middleware("http")
async def _system_doctor_error_capture(request: Request, call_next):
    from app.services.ai.ai_generation_context import reset_ai_generation_log_context
    from app.services.ai.gemini_client import reset_gemini_request_scope

    reset_gemini_request_scope()
    reset_ai_generation_log_context()
    try:
        response = await call_next(request)
        # Count server errors into in-memory doctor metrics.
        if int(getattr(response, "status_code", 0) or 0) >= 500:
            record_api_error(
                message=f"HTTP {int(response.status_code)}",
                path=str(request.url.path),
                method=str(request.method),
                status=int(response.status_code),
            )
        return response
    except Exception as e:
        record_api_error(
            message=str(e) or e.__class__.__name__,
            path=str(request.url.path),
            method=str(request.method),
            status=500,
        )
        record_system_error("exception", f"{e.__class__.__name__}: {str(e)}")
        raise
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_origin_regex=_cors_allow_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    return {"status": "ready"}


# User uploads: public read via GET (no auth — browsers do not send Bearer on <img src>).
# POST remains on /api/v1/uploads/* with authentication.
_upload_prefix = (getattr(settings, "UPLOAD_PUBLIC_PREFIX", None) or f"/{settings.LOCAL_UPLOAD_DIR}").strip()
if not _upload_prefix.startswith("/"):
    _upload_prefix = f"/{_upload_prefix}"

_ALLOWED_PUBLIC_UPLOAD_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".webm", ".m4a", ".aac", ".mp4"})


def _get_upload_dir() -> Path:
    d = Path(getattr(settings, "UPLOAD_DIR", None) or settings.LOCAL_UPLOAD_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_safe_public_upload_path(relative_path: str) -> Path | None:
    """Map URL path under UPLOAD_PUBLIC_PREFIX to a file inside UPLOAD_DIR (no traversal)."""
    raw = (relative_path or "").strip().replace("\\", "/")
    if not raw:
        return None
    parts = [p for p in raw.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        return None
    suffix = Path(parts[-1]).suffix.lower()
    if suffix not in _ALLOWED_PUBLIC_UPLOAD_SUFFIXES:
        return None
    try:
        base = _get_upload_dir().resolve()
        target = base.joinpath(*parts).resolve()
        target.relative_to(base)
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


_get_upload_dir()


@app.get(_upload_prefix + "/{filepath:path}")
async def serve_public_upload(filepath: str):
    path = _resolve_safe_public_upload_path(filepath)
    if not path:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)

# Demo catalog photos: paths use gender folders, e.g. /demo-profiles/women/demo_001/main.jpg (frontend/public/demo-profiles).
_demo_profiles_dir = demo_profiles_public_dir()
try:
    _demo_profiles_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/demo-profiles",
        StaticFiles(directory=str(_demo_profiles_dir)),
        name="demo-profiles",
    )
except Exception as e:
    _startup_log.warning(
        "demo-profiles static mount skipped: %s (path=%s)",
        e,
        _demo_profiles_dir,
    )


def _redact_database_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        if not parts.scheme:
            return value
        if not parts.password:
            return value
        username = parts.username or ""
        host = parts.hostname or ""
        port = parts.port
        auth = f"{username}:***@" if username else ""
        netloc = f"{auth}{host}"
        if port:
            netloc = f"{netloc}:{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "[unparseable DATABASE_URL]"


def _required_users_columns() -> set[str]:
    return {"trial_active", "trial_expires_at", "ai_free_used_count", "ai_last_used_at"}


def _assert_alembic_head_and_user_columns() -> None:
    """
    Fail-fast schema guard:
    - required users columns must exist
    - current DB alembic revision must match code head
    """
    db = SessionLocal()
    try:
        bind = db.get_bind()
        insp = inspect(bind)
        users_cols = {str(c.get("name") or "") for c in insp.get_columns("users")}
        missing = sorted(_required_users_columns() - users_cols)
        if missing:
            _startup_log.error(
                "startup_schema_guard_failed: missing users columns: %s. Run alembic upgrade head.",
                ", ".join(missing),
            )
            raise RuntimeError(f"Missing required users columns: {', '.join(missing)}")

        current_rev = None
        try:
            current_rev = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        except Exception:
            current_rev = None

        expected_head = None
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            backend_root = Path(__file__).resolve().parents[1]
            cfg = Config(str(backend_root / "alembic.ini"))
            expected_head = ScriptDirectory.from_config(cfg).get_current_head()
        except Exception as e:
            _startup_log.warning("startup_schema_guard_head_resolve_failed: %s", e)

        if expected_head and str(current_rev or "") != str(expected_head):
            if getattr(bind.dialect, "name", "") == "sqlite":
                # Local/dev SQLite often uses `create_all` + session.py autopatch without an alembic_version row.
                _startup_log.warning(
                    "sqlite_alembic_revision_unstamped: current=%s expected_head=%s (skipping strict check)",
                    current_rev,
                    expected_head,
                )
            else:
                _startup_log.error(
                    "startup_schema_guard_failed: alembic revision mismatch current=%s expected_head=%s. Run alembic upgrade head.",
                    current_rev,
                    expected_head,
                )
                raise RuntimeError("Database schema is outdated (alembic revision mismatch)")
    finally:
        db.close()


@app.on_event("startup")
def _startup_diagnostics() -> None:
    """
    Dev-only diagnostics to reduce confusion when the dev DB gets wiped (e.g. `docker compose down -v`).
    Best-effort: must never crash the app.
    """
    if _is_production_env():
        return

    # AI config diagnostics (no secrets).
    try:
        _startup_log.info(
            json.dumps(
                {
                    "event": "startup_ai_config",
                    "ai_provider": str(getattr(settings, "AI_PROVIDER", "") or ""),
                    "gemini_model": str(getattr(settings, "GEMINI_MODEL", "") or ""),
                    "gemini_chat_model": str(getattr(settings, "GEMINI_CHAT_MODEL", "") or ""),
                    "gemini_analysis_model": str(getattr(settings, "GEMINI_ANALYSIS_MODEL", "") or ""),
                    "gemini_localization_model": str(getattr(settings, "GEMINI_LOCALIZATION_MODEL", "") or ""),
                    "ai_model": str(getattr(settings, "AI_MODEL", "") or ""),
                    "has_gemini_key": bool(str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()),
                    "dev_force_premium": bool(getattr(settings, "DEV_FORCE_PREMIUM", False)) and str(getattr(settings, "ENV", "") or "").strip().lower() != "production",
                },
                default=str,
            )
        )
        if bool(getattr(settings, "DEV_FORCE_PREMIUM", False)) and str(getattr(settings, "ENV", "") or "").strip().lower() != "production":
            _startup_log.info("DEV MODE: Premium forced for all users")
        provider = str(getattr(settings, "AI_PROVIDER", "") or "").strip().lower()
        if provider == "gemini" and not bool(str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()):
            _startup_log.error(json.dumps({"event": "startup_ai_config_error", "provider": "gemini", "error": "GEMINI_API_KEY is missing"}, default=str))
    except Exception:
        pass

    db_url = str(getattr(settings, "DATABASE_URL", "") or "")
    db_url_redacted = _redact_database_url(db_url)

    diag: dict = {
        "event": "startup_db_diagnostics",
        "database_url": db_url_redacted,
        "alembic_revision": None,
        "users_count": None,
        "profiles_count": None,
        "db_looks_fresh_empty": None,
    }

    try:
        db = SessionLocal()
        try:
            # Alembic current revision (best-effort).
            try:
                rev = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
                diag["alembic_revision"] = str(rev) if rev else None
            except Exception:
                diag["alembic_revision"] = None

            # Lightweight row counts.
            try:
                diag["users_count"] = int(db.query(User).count())
            except Exception:
                diag["users_count"] = None
            try:
                diag["profiles_count"] = int(db.query(Profile).count())
            except Exception:
                diag["profiles_count"] = None

            users_count = diag.get("users_count")
            profiles_count = diag.get("profiles_count")
            revision = diag.get("alembic_revision")
            diag["db_looks_fresh_empty"] = bool(
                (users_count in (None, 0))
                or (profiles_count in (None, 0))
                or (revision in (None, "", "None"))
            )
        finally:
            db.close()
    except Exception as e:
        diag["error"] = str(e)

    _startup_log.info(json.dumps(diag, default=str))


@app.on_event("startup")
def _startup_schema_guard() -> None:
    _assert_alembic_head_and_user_columns()


@app.on_event("startup")
async def _startup_demo_living_worker() -> None:
    """Background ticks for living demo behavior (delayed replies, revives). Non-blocking for API workers."""
    import asyncio
    import logging
    import random
    import threading
    import time

    from app.db.session import SessionLocal
    from app.services.chat_manager import set_app_event_loop
    from app.services.demo_behavior import run_demo_behavior_tick

    set_app_event_loop(asyncio.get_running_loop())
    log = logging.getLogger("neyra.demo_behavior")

    if not bool(getattr(settings, "DEMO_LIVE_BEHAVIOR", False)):
        log.info("demo_behavior_runner_disabled env DEMO_LIVE_BEHAVIOR=false")
        return

    def run() -> None:
        time.sleep(random.uniform(2.0, 8.0))
        while True:
            try:
                time.sleep(random.uniform(30.0, 90.0))
                db = SessionLocal()
                try:
                    run_demo_behavior_tick(db)
                finally:
                    db.close()
            except Exception:
                log.exception("demo_tick_thread")

    threading.Thread(target=run, name="demo-behavior", daemon=True).start()


@app.on_event("startup")
async def _startup_retention_worker() -> None:
    """Background retention worker (daily nudges + revive + micro rewards)."""
    import logging
    import random
    import threading
    import time

    from app.db.session import SessionLocal
    from app.services.retention.retention_jobs import run_retention_tick

    log = logging.getLogger("neyra.retention")
    if not bool(getattr(settings, "RETENTION_WORKER", True)):
        log.info("retention_worker_disabled env RETENTION_WORKER=false")
        return

    min_s = float(getattr(settings, "RETENTION_TICK_MIN_SECONDS", 240) or 240)
    max_s = float(getattr(settings, "RETENTION_TICK_MAX_SECONDS", 600) or 600)
    if max_s < min_s:
        max_s = min_s

    def run() -> None:
        time.sleep(random.uniform(3.0, 12.0))
        while True:
            try:
                time.sleep(random.uniform(min_s, max_s))
                db = SessionLocal()
                try:
                    stats = run_retention_tick(db)
                    try:
                        log.info("retention_tick %s", stats)
                    except Exception:
                        pass
                finally:
                    db.close()
            except Exception:
                log.exception("retention_tick_thread")

    threading.Thread(target=run, name="retention-worker", daemon=True).start()


@app.on_event("startup")
async def _startup_growth_engine_worker() -> None:
    """Background AI Growth Engine loop (metrics → actions)."""
    import logging
    import random
    import threading
    import time

    from app.db.session import SessionLocal
    from app.services.growth_engine import GrowthEngine

    log = logging.getLogger("neyra.growth_engine")
    if not bool(getattr(settings, "GROWTH_ENGINE_WORKER", True)):
        log.info("growth_engine_worker_disabled env GROWTH_ENGINE_WORKER=false")
        return

    min_s = float(getattr(settings, "GROWTH_ENGINE_TICK_MIN_SECONDS", 300) or 300)
    max_s = float(getattr(settings, "GROWTH_ENGINE_TICK_MAX_SECONDS", 900) or 900)
    if max_s < min_s:
        max_s = min_s

    def run() -> None:
        time.sleep(random.uniform(4.0, 14.0))
        engine = GrowthEngine()
        while True:
            try:
                time.sleep(random.uniform(min_s, max_s))
                db = SessionLocal()
                try:
                    out = engine.run_once(db)
                    try:
                        log.info("growth_engine_tick %s", out.get("applied"))
                    except Exception:
                        pass
                finally:
                    db.close()
            except Exception:
                log.exception("growth_engine_tick_thread")

    threading.Thread(target=run, name="growth-engine", daemon=True).start()


@app.on_event("startup")
async def _startup_learning_worker() -> None:
    """Background learning loop (reply/ignore patterns → UserAiMemory)."""
    import logging
    import random
    import threading
    import time

    from app.db.session import SessionLocal
    from app.services.learning.message_learning import run_message_learning_tick
    from app.services.learning.pattern_insights import run_pattern_insights_tick

    log = logging.getLogger("neyra.learning")
    if not bool(getattr(settings, "LEARNING_WORKER", True)):
        log.info("learning_worker_disabled env LEARNING_WORKER=false")
        return

    min_s = float(getattr(settings, "LEARNING_TICK_MIN_SECONDS", 600) or 600)
    max_s = float(getattr(settings, "LEARNING_TICK_MAX_SECONDS", 1800) or 1800)
    if max_s < min_s:
        max_s = min_s

    def run() -> None:
        time.sleep(random.uniform(6.0, 18.0))
        while True:
            try:
                time.sleep(random.uniform(min_s, max_s))
                db = SessionLocal()
                try:
                    stats = run_message_learning_tick(db)
                    try:
                        log.info("learning_tick processed=%s users_updated=%s", stats.processed, stats.users_updated)
                    except Exception:
                        pass
                    try:
                        pi = run_pattern_insights_tick(db)
                        log.info("pattern_insights_tick users_updated=%s", pi.users_updated)
                    except Exception:
                        log.exception("pattern_insights_tick_thread")
                finally:
                    db.close()
            except Exception:
                log.exception("learning_tick_thread")

    threading.Thread(target=run, name="learning-worker", daemon=True).start()


@app.on_event("startup")
async def _startup_ab_engine_worker() -> None:
    """Background A/B evaluation (promote winning copy from ab_* analytics)."""
    import logging
    import random
    import threading
    import time

    from app.db.session import SessionLocal
    from app.services.ab_engine import evaluate_experiments

    log = logging.getLogger("neyra.ab_engine")
    if not bool(getattr(settings, "AB_ENGINE_WORKER", True)):
        log.info("ab_engine_worker_disabled env AB_ENGINE_WORKER=false")
        return

    min_s = float(getattr(settings, "AB_ENGINE_TICK_MIN_SECONDS", 900) or 900)
    max_s = float(getattr(settings, "AB_ENGINE_TICK_MAX_SECONDS", 3600) or 3600)
    if max_s < min_s:
        max_s = min_s

    def run() -> None:
        time.sleep(random.uniform(8.0, 22.0))
        while True:
            try:
                time.sleep(random.uniform(min_s, max_s))
                db = SessionLocal()
                try:
                    out = evaluate_experiments(db)
                    try:
                        log.info("ab_engine_tick %s", out.get("summary"))
                    except Exception:
                        pass
                finally:
                    db.close()
            except Exception:
                log.exception("ab_engine_tick_thread")

    threading.Thread(target=run, name="ab-engine", daemon=True).start()


@app.get("/")
def root():
    return {"status": "ok", "app": settings.APP_NAME}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
