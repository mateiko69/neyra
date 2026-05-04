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

# Railway Postgres may accept connections before all roles/extensions are ready — retry migrations.
_MAX=40
_I=1
_OK=0
while [ "$_I" -le "$_MAX" ]; do
  if alembic upgrade head; then
    _OK=1
    break
  fi
  echo "[start_web_production] alembic upgrade head failed (attempt $_I/$_MAX); retry in 2s..." >&2
  sleep 2
  _I=$((_I + 1))
done
if [ "$_OK" -ne 1 ]; then
  echo "[start_web_production] alembic could not reach head after $_MAX attempts. Fix DATABASE_URL or migration errors." >&2
  exit 1
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
