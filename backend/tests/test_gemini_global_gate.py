"""Tests for process-local + Redis-backed Gemini failure cooldown state."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.ai.gemini_global_gate import (
    is_gemini_global_failure_cooldown_active,
    record_gemini_global_failure,
    reset_gemini_global_failure_memory,
)


def test_record_marks_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_GLOBAL_FAILURE_COOLDOWN_SECONDS", 60, raising=False)
    reset_gemini_global_failure_memory()
    assert not is_gemini_global_failure_cooldown_active()
    record_gemini_global_failure()
    assert is_gemini_global_failure_cooldown_active()


def test_cooldown_ttl_elapses(monkeypatch: pytest.MonkeyPatch) -> None:
    """After cooldown window, memory-backed gate clears (_cooldown_sec floors at 5s)."""
    monkeypatch.setattr(settings, "GEMINI_GLOBAL_FAILURE_COOLDOWN_SECONDS", 5, raising=False)
    reset_gemini_global_failure_memory()

    clock = [1000.0]

    def fake_time() -> float:
        return float(clock[0])

    monkeypatch.setattr("app.services.ai.gemini_global_gate.time.time", fake_time)

    assert not is_gemini_global_failure_cooldown_active()
    record_gemini_global_failure()
    assert is_gemini_global_failure_cooldown_active()

    # max(5, settings) => 5s; advance past window
    clock[0] = 1006.0
    assert not is_gemini_global_failure_cooldown_active()


def test_reset_clears_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_GLOBAL_FAILURE_COOLDOWN_SECONDS", 60, raising=False)
    reset_gemini_global_failure_memory()
    record_gemini_global_failure()
    assert is_gemini_global_failure_cooldown_active()
    reset_gemini_global_failure_memory()
    assert not is_gemini_global_failure_cooldown_active()
