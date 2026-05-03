"""Shared pytest hooks for NEYRA backend tests."""

from __future__ import annotations

import pytest

from app.services.ai.ai_generation_context import reset_ai_generation_log_context
from app.services.ai.gemini_global_gate import reset_gemini_global_failure_memory
from app.services.ai.gemini_client import reset_gemini_request_scope


@pytest.fixture(autouse=True)
def _reset_gemini_cross_test_state() -> None:
    """Isolate tests: 60s global Gemini cooldown is process-local and would otherwise leak between cases."""
    reset_gemini_global_failure_memory()
    reset_gemini_request_scope()
    reset_ai_generation_log_context()
    yield
    reset_gemini_global_failure_memory()
    reset_gemini_request_scope()
    reset_ai_generation_log_context()
