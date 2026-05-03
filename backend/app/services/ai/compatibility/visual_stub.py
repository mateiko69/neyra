from __future__ import annotations

from dataclasses import dataclass

from app.models.profile import Profile
from app.services.visual_embeddings import VisualEmbedding, cosine_similarity


@dataclass(frozen=True)
class VisualResult:
    visual_score: int | None
    symmetry_score: int | None
    unusable_reason_bucket: str | None


class VisualScorer:
    """Privacy-conscious visual compatibility hook (v1).

    Uses existing stored `Profile.visual_embedding` when present. No raw embeddings
    or photo contents are returned or logged. Symmetry remains unavailable in v1.
    """

    def check_photo_usability(self, *, viewer: Profile, candidate: Profile) -> tuple[bool, str]:
        viewer_photos = [x.strip() for x in (getattr(viewer, "photo_urls", "") or "").split(",") if x.strip()]
        if not viewer_photos:
            return False, "no_photos_viewer"
        candidate_photos = [x.strip() for x in (getattr(candidate, "photo_urls", "") or "").split(",") if x.strip()]
        if not candidate_photos:
            return False, "no_photos_candidate"

        v_emb = VisualEmbedding.deserialize(getattr(viewer, "visual_embedding", "") or "")
        if not v_emb:
            return False, "no_embedding_viewer"
        c_emb = VisualEmbedding.deserialize(getattr(candidate, "visual_embedding", "") or "")
        if not c_emb:
            return False, "no_embedding_candidate"
        if len(v_emb.vector) != len(c_emb.vector):
            return False, "embedding_shape_mismatch"
        return True, "ok"

    def compare_face_embeddings(self, *, viewer: Profile, candidate: Profile) -> float | None:
        v_emb = VisualEmbedding.deserialize(getattr(viewer, "visual_embedding", "") or "")
        c_emb = VisualEmbedding.deserialize(getattr(candidate, "visual_embedding", "") or "")
        if not v_emb or not c_emb:
            return None
        if len(v_emb.vector) != len(c_emb.vector):
            return None
        sim = cosine_similarity(v_emb.vector, c_emb.vector)
        return max(0.0, min(1.0, float(sim)))

    def estimate_visual_harmony(self, similarity: float) -> int:
        # Conservative mapping: keep mid-range unless similarity is strong.
        # similarity 0.0 -> 45, 0.7 -> ~70, 0.9 -> ~84, 1.0 -> 90
        s = max(0.0, min(1.0, float(similarity)))
        score = 45.0 + (s ** 1.6) * 45.0
        return int(round(max(0.0, min(100.0, score))))

    def estimate_symmetry_signal(self, *_args, **_kwargs) -> int | None:
        # v1: no symmetry model wired yet.
        return None

    def score_pair(self, *, viewer: Profile, candidate: Profile) -> VisualResult:
        ok, reason = self.check_photo_usability(viewer=viewer, candidate=candidate)
        if not ok:
            return VisualResult(visual_score=None, symmetry_score=None, unusable_reason_bucket=reason)
        sim = self.compare_face_embeddings(viewer=viewer, candidate=candidate)
        if sim is None:
            return VisualResult(visual_score=None, symmetry_score=None, unusable_reason_bucket="unknown")
        visual_score = self.estimate_visual_harmony(sim)
        symmetry_score = self.estimate_symmetry_signal()
        return VisualResult(visual_score=visual_score, symmetry_score=symmetry_score, unusable_reason_bucket=None)

