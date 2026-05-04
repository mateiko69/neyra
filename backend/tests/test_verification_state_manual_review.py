from types import SimpleNamespace

from app.services.trust.verification_state import (
    normalize_verification_status,
    verification_status_for_api,
)


def test_normalize_verification_status_accepts_manual_review() -> None:
    assert normalize_verification_status("pending_manual_review") == "pending_manual_review"
    assert normalize_verification_status("PENDING_MANUAL_REVIEW") == "pending_manual_review"


def test_verification_status_for_api_returns_manual_review() -> None:
    profile = SimpleNamespace(verification_status="pending_manual_review")
    assert verification_status_for_api(profile) == "pending_manual_review"

