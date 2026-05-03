#!/usr/bin/env sh
# Railway / Docker production web process: bind all interfaces; port from Railway $PORT.
set -eu
cd "$(dirname "$0")/.." || exit 1

python <<'PY'
import sys

from pydantic import ValidationError
from sqlalchemy.engine.url import make_url

try:
    from app.core.config import settings
except ValidationError:
    sys.stderr.write(
        "[start_web_production] Failed to load app settings.\n"
        "[start_web_production] Verify DATABASE_URL in Railway variables (secret value never printed).\n"
    )
    raise SystemExit(1)

try:
    make_url(settings.DATABASE_URL)
except Exception:
    sys.stderr.write(
        "[start_web_production] DATABASE_URL could not be parsed as a SQLAlchemy URL.\n"
        "[start_web_production] Use Railway PostgreSQL DATABASE_URL (postgresql://...).\n"
    )
    raise SystemExit(1)
PY

alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
