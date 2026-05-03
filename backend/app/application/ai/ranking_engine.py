from __future__ import annotations


class RankingEngine:
    """Future ML ranking seam.

    This is intentionally minimal: the existing system does not use ranking yet.
    """

    @staticmethod
    def rank(candidate_user_ids: list[int]) -> list[int]:
        return candidate_user_ids

