from __future__ import annotations

import hashlib


class ShareEngine:
    """Generates share moments payload (image URL placeholder + share text).

    Real image rendering can be added later (e.g., server-side template or CDN).
    """

    def generate_share_card(self, user_id: int, event: dict) -> dict:
        etype = (event.get("type") or "").strip()
        seed = f"{user_id}:{etype}".encode("utf-8")
        img_id = hashlib.sha256(seed).hexdigest()[:12]
        image_url = f"/share/{img_id}.png"  # placeholder path for future renderer

        if etype == "match":
            return {"image_url": image_url, "share_text": "It’s a match on NEYRA ✨"}
        if etype == "best_opener":
            return {"image_url": image_url, "share_text": "Best opener I’ve seen today. NEYRA Wingman is wild ✨"}
        if etype == "glow_up":
            return {"image_url": image_url, "share_text": "Conversation glow-up moment ✨ (powered by NEYRA)"}
        return {"image_url": image_url, "share_text": "Dating, but higher-quality. NEYRA ✨"}

