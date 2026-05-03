from __future__ import annotations

from app.services.viral.hook_engine import HookEngine


def generate_hook(user_id: int, context: dict) -> dict:
    return HookEngine().generate_hook(user_id, context)

