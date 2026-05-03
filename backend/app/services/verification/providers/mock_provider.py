from __future__ import annotations

from app.services.verification.providers.base import SelfieVerificationProvider, SelfieVerificationResult


class MockSelfieVerificationProvider(SelfieVerificationProvider):
    """
    Dev/mock behavior:
    - Approve only if selfie bytes exist AND profile has at least one photo.
    - Never approve based on social login or profile completeness.
    """

    def verify_selfie(self, *, selfie_bytes: bytes, profile_photo_urls: list[str]) -> SelfieVerificationResult:
        if not selfie_bytes:
            return SelfieVerificationResult(status="rejected", confidence=0.0, reason="empty_selfie")
        if not profile_photo_urls:
            return SelfieVerificationResult(status="rejected", confidence=0.1, reason="no_profile_photo")
        return SelfieVerificationResult(status="approved", confidence=0.9, reason="mock_approved")

