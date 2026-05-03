#!/usr/bin/env sh
# Railway / Docker production web process: bind all interfaces; port from Railway $PORT.
set -eu
cd "$(dirname "$0")/.." || exit 1
PORT="${PORT:-8000}"
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
