from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelfieVerificationResult:
    status: str  # pending|approved|rejected
    confidence: float
    reason: str


class SelfieVerificationProvider:
    def verify_selfie(self, *, selfie_bytes: bytes, profile_photo_urls: list[str]) -> SelfieVerificationResult:
        raise NotImplementedError

