from __future__ import annotations

import re


ALLOWED_STYLES = {"confident", "chill", "romantic", "direct", "funny"}


class StyleAdapter:
    """Adapts tone without changing intent (deterministic heuristics)."""

    @staticmethod
    def adapt_style(message: str, style: str) -> str:
        text = (message or "").strip()
        if not text:
            return ""

        s = (style or "chill").strip().lower()
        if s not in ALLOWED_STYLES:
            s = "chill"

        # Keep it subtle: no heavy rewriting, just tone markers.
        if s == "direct":
            return re.sub(r"[🙂😉😊]+", "", text).strip()
        if s == "confident":
            if not text.endswith((".", "!", "?")):
                text += "!"
            return text
        if s == "romantic":
            return text + (" " if not text.endswith(("🙂", "✨", "🌙")) else "") + "✨"
        if s == "funny":
            if "🙂" not in text and "😂" not in text:
                return text + " 🙂"
            return text
        # chill
        return text

