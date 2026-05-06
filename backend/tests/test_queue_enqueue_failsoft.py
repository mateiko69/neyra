from __future__ import annotations

import app.services.queue as queue_mod


def test_enqueue_swallows_redis_rpush_errors(monkeypatch):
    class _BadRedis:
        def rpush(self, *_args, **_kwargs):  # pragma: no cover - exercised via monkeypatch
            raise ConnectionError("simulated redis outage")

    monkeypatch.setattr(queue_mod, "client", _BadRedis())
    # Must not raise — match / swipe flows depend on this being best-effort only.
    queue_mod.enqueue("match_created", {"match_id": 1, "user_a_id": 1, "user_b_id": 2})
