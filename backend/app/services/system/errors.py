from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemErrorEvent:
    ts: float
    kind: str
    message: str
    path: str | None = None
    method: str | None = None
    status: int | None = None

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "message": self.message,
            "path": self.path,
            "method": self.method,
            "status": self.status,
        }


_errors = deque(maxlen=50)
_api_error_timestamps = deque(maxlen=2000)


def record_api_error(*, message: str, path: str, method: str, status: int) -> None:
    now = time.time()
    _api_error_timestamps.append(now)
    _errors.append(
        SystemErrorEvent(
            ts=now,
            kind="api_error",
            message=(message or "")[:2000],
            path=(path or "")[:200],
            method=(method or "")[:16],
            status=int(status or 0),
        )
    )


def record_system_error(kind: str, message: str) -> None:
    now = time.time()
    _errors.append(SystemErrorEvent(ts=now, kind=(kind or "error")[:32], message=(message or "")[:2000]))


def api_errors_last_24h() -> int:
    now = time.time()
    cutoff = now - 60 * 60 * 24
    while _api_error_timestamps and _api_error_timestamps[0] < cutoff:
        _api_error_timestamps.popleft()
    return len(_api_error_timestamps)


def last_errors(limit: int = 10) -> list[dict]:
    n = max(0, min(50, int(limit or 10)))
    items = list(_errors)[-n:]
    return [e.to_dict() for e in reversed(items)]

