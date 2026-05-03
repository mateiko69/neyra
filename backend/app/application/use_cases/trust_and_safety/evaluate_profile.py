from __future__ import annotations

from app.services.trust.profile_risk_evaluator import ProfileRiskEvaluator


def evaluate_profile_risk(profile) -> dict:
    return ProfileRiskEvaluator.evaluate_profile_risk(profile).to_dict()

