from __future__ import annotations

import time

_STARTED_AT = time.time()


def uptime_seconds() -> int:
    return max(0, int(time.time() - _STARTED_AT))

