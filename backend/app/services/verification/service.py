from __future__ import annotations

from app.core.config import settings
from app.services.verification.providers.base import SelfieVerificationProvider
from app.services.verification.providers.mock_provider import MockSelfieVerificationProvider


def get_selfie_verification_provider() -> SelfieVerificationProvider:
    name = str(getattr(settings, "VERIFICATION_PROVIDER", "") or "mock").strip().lower()
    if name in {"mock", "dev"}:
        return MockSelfieVerificationProvider()
    # Future: face match provider hook.
    return MockSelfieVerificationProvider()

