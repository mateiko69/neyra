from __future__ import annotations

from app.services.verification.providers.base import SelfieVerificationProvider, SelfieVerificationResult


class MockSelfieVerificationProvider(SelfieVerificationProvider):
    """
    Dev/mock behavior:
    - Require a real selfie capture.
    - If profile photos are missing (e.g. cleared URL or 404 on disk), still allow an MVP result so
      verification is not hard-blocked on a vanished profile file.
    """

    def verify_selfie(self, *, selfie_bytes: bytes, profile_photo_urls: list[str]) -> SelfieVerificationResult:
        if not selfie_bytes:
            return SelfieVerificationResult(status="rejected", confidence=0.0, reason="empty_selfie")
        if not profile_photo_urls:
            return SelfieVerificationResult(status="approved", confidence=0.55, reason="mock_selfie_only_mvp")
        return SelfieVerificationResult(status="approved", confidence=0.9, reason="mock_approved")

