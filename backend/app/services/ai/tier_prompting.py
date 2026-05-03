"""Inject subscription tier capabilities into model prompts (avoid orchestrator import cycles)."""


def capability_prompt_block(plan_tier: str | None) -> str:
    tier = (plan_tier or "free").strip().lower()
    if tier == "premium_plus":
        return (
            "\nSubscriber tier: PREMIUM_PLUS. Use advanced dating timing judgment, revival strategies, "
            "and meeting-readiness suggestions when appropriate. Be concise; avoid repeating this line.\n"
        )
    if tier == "premium":
        return (
            "\nSubscriber tier: PREMIUM. Prioritize thoughtful pacing toward a real date while staying low-pressure.\n"
        )
    return ""
