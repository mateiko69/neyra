from __future__ import annotations

from app.infrastructure.ai.provider_factory import get_ai_provider
import asyncio
from app.services.ai.conversation.reply_assistant import improve_draft_locally


async def improve_reply_variants(
    draft: str,
    conversation_context: list[str] | None,
    user_style: str,
    *,
    allow_edgy_mode: bool = False,
    mode: str | None = None,
    plan_tier: str | None = None,
    locale: str | None = None,
) -> list[dict]:
    """Three improved variants; provider first, then deterministic fallback."""
    provider = get_ai_provider()
    try:
        out = await asyncio.wait_for(
            provider.improve_reply_draft(
            draft,
            conversation_context or [],
            user_style,
            mode=mode,
            plan_tier=plan_tier,
            locale=locale,
            ),
            timeout=8.0,
        )
        suggestions = out.get("suggestions") if isinstance(out, dict) else None
        if suggestions and len(suggestions) >= 3:
            return [{"text": s.get("text", ""), "style": s.get("style", "safe")} for s in suggestions[:3]]
    except Exception:
        pass
    rows = improve_draft_locally(
        draft,
        conversation_context,
        user_style,
        allow_edgy_mode=allow_edgy_mode,
        locale=locale,
    )
    return [{"text": x["text"], "style": x["style"]} for x in rows[:3]]
