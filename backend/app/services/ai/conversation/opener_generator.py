from __future__ import annotations

from app.domain.ai.safety import SafetyPolicy
from app.domain.matching.utils import normalize_tokens, split_csv
from app.models.profile import Profile
from app.services.ai.conversation.style_adapter import StyleAdapter
from app.services.app_language import normalize_app_language


class OpenerGenerator:
    """Generates multi-style openers (deterministic mock-friendly)."""

    GENERIC_BANNED_SUBSTRINGS = ("hi", "how are you", "як справи", "привіт, як")

    @classmethod
    def generate_openers(
        cls,
        me_profile: Profile | None,
        target_profile: Profile,
        *,
        allow_edgy_mode: bool = False,
        locale: str | None = None,
    ) -> list[dict]:
        loc = normalize_app_language(locale or "en")
        loc = loc if loc in {"en", "uk", "ru"} else "en"
        me_interests = normalize_tokens(split_csv(getattr(me_profile, "interests", "") or ""))
        other_interests = normalize_tokens(split_csv(getattr(target_profile, "interests", "") or ""))
        shared = sorted(list(me_interests & other_interests))[:3]
        topic_default = "something from your profile" if loc == "en" else "что-то из твоего профиля" if loc == "ru" else "щось із твого профілю"
        topic = shared[0] if shared else (sorted(list(other_interests))[:1] or [topic_default])[0]

        bio = (getattr(target_profile, "bio", "") or "").strip()
        name = (getattr(target_profile, "display_name", "") or "").strip()
        name_part = f"{name}, " if name else ""

        base_reasons = []
        if shared:
            base_reasons.append(f"based on shared interest in {topic}")
        else:
            base_reasons.append("based on something specific from their profile")

        candidates = [
            {
                "style": "playful",
                "text": (
                    f"{name_part}quick question: {topic} — are you more ‘fan’ or ‘obsessed’? 🙂"
                    if loc == "en"
                    else f"{name_part}вопрос на внимательность: {topic} — ты больше ‘fan’ или ‘obsessed’? 🙂"
                    if loc == "ru"
                    else f"{name_part}питання на уважність: {topic} — ти більше ‘fan’ чи ‘obsessed’? 🙂"
                ),
                "reason": base_reasons[0],
            },
            {
                "style": "confident",
                "text": (
                    f"Okay, {topic} — that’s already a plus. What do you genuinely love about it?"
                    if loc == "en"
                    else f"Окей, {topic} — это уже плюс. Что тебя в этом реально цепляет?"
                    if loc == "ru"
                    else f"Окей, {topic} — це вже плюс. Що тебе в цьому реально захоплює?"
                ),
                "reason": base_reasons[0],
            },
            {
                "style": "curious",
                "text": (
                    f"You mentioned {topic}. How did you get into it—randomly, or has it been part of your life for a while?"
                    if loc == "en"
                    else f"Ты упомянул(а) {topic}. Как ты к этому пришёл/пришла — случайно или давно тянет?"
                    if loc == "ru"
                    else f"Ти згадуєш {topic}. Як ти в це прийшла/прийшов — випадково чи давно тягне?"
                ),
                "reason": base_reasons[0],
            },
            {
                "style": "slightly_bold",
                "text": (
                    f"I’ll bet you have a story about {topic} that would either make me laugh or fall a little. Which one? 😉"
                    if loc == "en"
                    else f"Ставлю ставку: у тебя есть история про {topic}, после которой можно либо смеяться, либо чуть влюбиться. Какая? 😉"
                    if loc == "ru"
                    else f"Ставлю ставку: у тебе є історія про {topic}, після якої можна або сміятись, або закохатись. Яка? 😉"
                ),
                "reason": base_reasons[0],
            },
            {
                "style": "fallback_safe",
                "text": (
                    "I don’t want to start generic. What’s the most interesting part of your life right now—two sentences?"
                    if loc == "en"
                    else "Не хочу начинать банально. Что сейчас в твоей жизни самое интересное — в двух предложениях?"
                    if loc == "ru"
                    else "Не хочу банально. Що зараз у твоєму житті найцікавіше — коротко в 2 речення?"
                ),
                "reason": "safe fallback that still invites depth",
            },
        ]

        # If bio has a question/prompt, use it for one opener (swap in)
        if bio and "?" in bio:
            q = cls._extract_question(bio)
            candidates[2]["text"] = (
                f"{name_part}you asked in your bio “{q}” — want an honest answer? 🙂"
                if loc == "en"
                else f"{name_part}в твоём био был вопрос “{q}” — хочешь честный ответ? 🙂"
                if loc == "ru"
                else f"{name_part}ти в біо питала/питав “{q}” — хочеш чесну відповідь? 🙂"
            )
            candidates[2]["reason"] = "based on a prompt-worthy detail in their bio"

        out: list[dict] = []
        fallbacks = (
            [
                "I checked your profile—there’s plenty to talk about. Want to start with interests or travel? 🙂",
                "Quick one: what are you genuinely excited about right now? 🙂",
                "No generic openers—what’s been the best part of your week so far?",
                "You seem fun. Are you more ‘fan’ or ‘obsessed’ about your favorite obsession? 🙂",
                "You’ve got a nice vibe. What’s something you’d love to do again in the year ahead?",
            ]
            if loc == "en"
            else [
                "Посмотрел(а) профиль — есть о чём поговорить. С чего начнём: интересы или путешествия? 🙂",
                "Короткий вопрос: что тебя сейчас реально вдохновляет? 🙂",
                "Без банальностей — что было лучшим в твоей неделе?",
                "Ты кажешься классной/классным. Ты больше ‘фанат’ или ‘одержим(а)’ своим любимым? 🙂",
                "У тебя хороший вайб. Что бы ты точно хотела/хотел повторить в этом году?",
            ]
            if loc == "ru"
            else [
                "Глянула/глянув профіль — є про що поговорити. З чого почнемо: інтереси чи подорожі? 🙂",
                "Коротке питання: що тебе зараз реально надихає? 🙂",
                "Без банальностей — що було найкращим у твоєму тижні?",
                "Ти здаєшся класною/класним. Ти більше ‘фанат(ка)’ чи ‘одержим(а)’ своїм улюбленим? 🙂",
                "У тебе хороший вайб. Що ти точно хочеш повторити цього року?",
            ]
        )
        for i, c in enumerate(candidates):
            fallback = fallbacks[i % len(fallbacks)]
            text = StyleAdapter.adapt_style(c["text"], "chill")
            filtered, flags = SafetyPolicy.filter_or_fallback(text, allow_edgy_mode=allow_edgy_mode, fallback=fallback)
            if any(b in filtered.lower() for b in cls.GENERIC_BANNED_SUBSTRINGS):
                filtered = fallback
                flags = sorted(set(flags + ["generic_message"]))
            out.append({"text": filtered, "style": c["style"], "reason": c["reason"], "safety_flags": flags})
        return out

    @staticmethod
    def _extract_question(bio: str) -> str:
        # Keep it short: grab first question-ish sentence.
        parts = bio.split("?")
        q = (parts[0].strip()[:80] + "?") if parts and parts[0].strip() else "one question?"
        return q

