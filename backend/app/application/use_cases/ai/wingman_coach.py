from __future__ import annotations

from app.infrastructure.ai.provider_factory import get_ai_provider
from app.services.ai.conversation.dating_coach import coach_heuristic


def _valid_guidance(d: dict) -> bool:
    return all(
        isinstance(d.get(k), str) and str(d.get(k, "")).strip()
        for k in ("tone", "ask_next", "avoid")
    )


async def dating_coach(messages: list[str] | None) -> dict:
    msgs = [m.strip() for m in (messages or []) if (m or "").strip()]
    provider = get_ai_provider()
    try:
        out = await provider.dating_coach_guidance(msgs)
        if isinstance(out, dict) and _valid_guidance(out):
            return {
                "tone": out["tone"].strip()[:320],
                "ask_next": out["ask_next"].strip()[:320],
                "avoid": out["avoid"].strip()[:320],
            }
    except Exception:
        pass
    return coach_heuristic(msgs)
