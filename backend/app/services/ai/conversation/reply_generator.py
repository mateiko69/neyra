from __future__ import annotations

import re

from app.domain.ai.safety import SafetyPolicy
from app.services.ai.conversation.style_adapter import StyleAdapter
from app.services.ai.ai_request_locale import normalize_ai_request_locale


class ReplyGenerator:
    """Generates reply options (safe / engaging / slightly bold)."""

    @classmethod
    def generate_replies(
        cls,
        last_message: str,
        conversation_context: list[str] | None = None,
        user_style: str = "chill",
        *,
        allow_edgy_mode: bool = False,
        locale: str | None = None,
    ) -> list[dict]:
        loc = normalize_ai_request_locale(locale or "en")
        loc = loc if loc in {"en", "uk", "ru"} else "en"
        last = (last_message or "").strip()
        ctx = [m.strip() for m in (conversation_context or []) if (m or "").strip()]
        recent_text = " ".join(ctx[-6:] + [last]).lower()

        tone = cls._infer_tone(last)
        hook = cls._pick_hook(last, loc).rstrip("?").strip()

        if loc == "en":
            safe = f"Haha I like that 🙂 {hook}?"
            engaging = f"Okay that lands 🙂 {hook}?"
            bold = f"I’d match your energy 😉 {hook}?"
        elif loc == "ru":
            safe = f"Звучит живо 🙂 {hook}?"
            engaging = f"Ок, цепляет 🙂 {hook}?"
            bold = f"Я б без официоза 😉 {hook}?"
        else:
            safe = f"Клас, відгукується 🙂 {hook}?"
            engaging = f"Ок, ловлю 🙂 {hook}?"
            bold = f"Я б легко і без тиску 😉 {hook}?"

        # Avoid repeating context phrasing (simple lexical check).
        safe = cls._avoid_repetition(safe, recent_text)
        engaging = cls._avoid_repetition(engaging, recent_text)
        bold = cls._avoid_repetition(bold, recent_text)

        safe = StyleAdapter.adapt_style(cls._match_tone(safe, tone), user_style)
        engaging = StyleAdapter.adapt_style(cls._match_tone(engaging, tone), user_style)
        bold = StyleAdapter.adapt_style(cls._match_tone(bold, tone), user_style)

        fallback = (
            "Okay 🙂 tiny reset—voice note or text when you continue?"
            if loc == "en"
            else "Окей 🙂 голосом коротко или текстом продолжишь?"
            if loc == "ru"
            else "Окей 🙂 коротко текстом чи голосом продовжиш?"
        )
        out = []
        for text, style in [(safe, "safe"), (engaging, "engaging"), (bold, "slightly_bold")]:
            filtered, flags = SafetyPolicy.filter_or_fallback(text, allow_edgy_mode=allow_edgy_mode, fallback=fallback)
            out.append({"text": filtered, "style": style, "safety_flags": flags})
        return out

    @staticmethod
    def _infer_tone(text: str) -> str:
        t = (text or "").lower()
        if any(e in t for e in ("🙂", "😉", "😂", "😁", "❤️")):
            return "warm"
        if "!" in t:
            return "excited"
        if len(t) <= 10:
            return "dry"
        return "neutral"

    @staticmethod
    def _pick_hook(last_message: str, loc: str) -> str:
        m = (last_message or "").strip()
        low = m.lower()
        if not m:
            return (
                "are you more long-chat tonight or quick-and-cozy"
                if loc == "en"
                else "тебе ближе длинное сообщение или короткое теплое"
                if loc == "ru"
                else "тебе ближче довге повідомлення чи коротке тепле"
            )
        if "?" in m:
            return (
                "would you answer fast or sleep on it first"
                if loc == "en"
                else "ответишь сразу или подумаешь спокойно"
                if loc == "ru"
                else "відповіси швидко чи переспиш з думкою"
            )
        if len(m) <= 12:
            return (
                "headline first or the messy honest version"
                if loc == "en"
                else "сначала коротко или сразу подробно и честно"
                if loc == "ru"
                else "спочатку коротко чи одразу чесно й детально"
            )
        if any(w in low for w in ("weekend", "вихідн", "выходные", "субот", "неділя", "воскрес")):
            return (
                "locked plans or full improvisation"
                if loc == "en"
                else "планы намертво или полная импровизация"
                if loc == "ru"
                else "план намагаєшся тримати чи повна імпровізація"
            )
        if any(w in low for w in ("coffee", "кава", "meet", "зустр", "walk", "прогулян")):
            return (
                "quick coffee or a longer wander"
                if loc == "en"
                else "быстрый кофе или длинная прогулка"
                if loc == "ru"
                else "швидка кава чи довша прогулянка"
            )
        return (
            "the tiny detail or the overall vibe"
            if loc == "en"
            else "маленькая деталь или общее настроение"
            if loc == "ru"
            else "маленька деталь чи загальний настрій"
        )

    @staticmethod
    def _avoid_repetition(reply: str, recent_text: str) -> str:
        r = reply
        # If exact fragments already used, swap synonyms.
        swaps = [
            ("Цікаво", "Слухай"),
            ("звучить", "виглядає"),
            ("найбільше", "найсильніше"),
        ]
        for a, b in swaps:
            if a.lower() in recent_text:
                r = r.replace(a, b)
        return r

    @staticmethod
    def _match_tone(text: str, tone: str) -> str:
        if tone == "dry":
            return re.sub(r"[🙂😉😂❤️✨]+", "", text).strip()
        if tone == "excited" and not text.endswith("!"):
            return text + "!"
        return text

