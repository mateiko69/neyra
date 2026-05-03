from __future__ import annotations

from app.infrastructure.ai.provider_factory import get_ai_provider
from app.models.profile import Profile
from app.services.ai.conversation.opener_generator import OpenerGenerator


async def generate_openers(
    me_profile: Profile | None,
    target_profile: Profile,
    *,
    allow_edgy_mode: bool = False,
    locale: str | None = None,
) -> list[dict]:
    """Generate multi-style openers via provider, with deterministic fallback."""

    provider = get_ai_provider()
    try:
        out = await provider.generate_openers(me_profile, target_profile, locale=locale)
        suggestions = out.get("suggestions") if isinstance(out, dict) else None
        if suggestions:
            return suggestions
    except Exception:
        pass
    return OpenerGenerator.generate_openers(me_profile, target_profile, allow_edgy_mode=allow_edgy_mode, locale=locale)

