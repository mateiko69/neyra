from __future__ import annotations

from app.domain.viral.types import HookLoop


class HookEngine:
    """Generates a 4-step Hook Model loop (Trigger → Action → Reward → Investment).

    Output is short, emotionally engaging, and grounded in real contexts.
    """

    def generate_hook(self, user_id: int, context: dict) -> dict:
        ctype = (context.get("type") or "").strip()
        if ctype == "new_match":
            hook = HookLoop(
                trigger="You have a new match",
                action="Open NEYRA",
                reward="Get a tailored opener that fits their vibe",
                investment="Send a message and start your connection",
            )
            return hook.to_dict()

        if ctype == "new_message":
            hook = HookLoop(
                trigger="Your match replied",
                action="Open chat",
                reward="3 quick reply options that sound like you",
                investment="Keep the streak going with one follow-up question",
            )
            return hook.to_dict()

        if ctype == "inactive":
            hook = HookLoop(
                trigger="You’re missing momentum",
                action="Check Discover",
                reward="Fresh matches ranked by conversation potential",
                investment="Update one detail in your profile to boost results",
            )
            return hook.to_dict()

        # Default: safe, non-spammy loop
        return HookLoop(
            trigger="A good connection is one swipe away",
            action="Open Discover",
            reward="Compatibility + conversation potential insights",
            investment="Like and start a real conversation",
        ).to_dict()

