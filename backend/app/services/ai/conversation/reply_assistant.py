from __future__ import annotations

import re

from app.domain.ai.safety import SafetyPolicy
from app.services.ai.conversation.style_adapter import StyleAdapter
from app.services.ai.centralized import fallback_reply_triplet
from app.services.ai.ai_request_locale import normalize_chat_ai_locale


def improve_draft_locally(
    draft: str,
    conversation_context: list[str] | None,
    user_style: str,
    *,
    allow_edgy_mode: bool = False,
    locale: str | None = None,
) -> list[dict]:
    """Deterministic improve-reply: three concise variants from the user's draft."""
    loc_raw = normalize_chat_ai_locale(locale or "en")
    if loc_raw not in {"en", "uk", "ru"}:
        fb = fallback_reply_triplet(locale=loc_raw)

        def _one_fb(text: str, style: str) -> dict:
            cleaned, flags = SafetyPolicy.filter_or_fallback(
                text.strip(),
                allow_edgy_mode=allow_edgy_mode,
                fallback=fb[0],
            )
            return {"text": cleaned, "style": style, "safety_flags": flags}

        return [
            _one_fb(fb[0], "polish"),
            _one_fb(fb[1], "more_natural"),
            _one_fb(fb[2], "shorter"),
            _one_fb(fb[0], "flirty"),
            _one_fb(fb[1], "witty"),
            _one_fb(fb[2], "direct"),
            _one_fb(fb[0], "thoughtful"),
            _one_fb(fb[1], "tease_lightly"),
        ]

    loc = loc_raw
    ctx = [m.strip() for m in (conversation_context or []) if (m or "").strip()]
    base = (draft or "").strip()
    if not base and ctx:
        base = ctx[-1]
    if not base:
        if loc == "en":
            base = "Hi! How’s your day going?"
        elif loc == "ru":
            base = "Привет! Как проходит твой день?"
        else:
            base = "Привіт! Як у тебе день?"

    recent = " ".join(ctx[-4:] + [base]).lower()

    def _one(s: str, style: str) -> dict:
        t = StyleAdapter.adapt_style(s.strip(), user_style)
        if loc == "en":
            fallback = "Try a short, human reply: what are you most curious about in this conversation right now?"
        elif loc == "ru":
            fallback = "Попробуй коротко и по‑человечески: что тебе сейчас больше всего интересно в этом разговоре?"
        else:
            fallback = "Спробуй коротко і по-людськи: що тебе зараз найбільше цікавить у цій розмові?"
        cleaned, flags = SafetyPolicy.filter_or_fallback(t, allow_edgy_mode=allow_edgy_mode, fallback=fallback)
        return {"text": cleaned, "style": style, "safety_flags": flags}

    # Clearer: tighten + one concrete follow-up
    clearer = base
    if not re.search(r"\?", clearer):
        if loc == "en":
            clearer = f"{clearer.rstrip('.! ')} — what matters most to you here?"
        elif loc == "ru":
            clearer = f"{clearer.rstrip('.! ')} — что для тебя здесь самое важное?"
        else:
            clearer = f"{clearer.rstrip('.! ')} — що для тебе тут найважливіше?"
    clearer = _dedupe_phrase(clearer, recent, loc)

    # Warmer: light acknowledgment + draft
    warm = base
    if loc == "en":
        if not warm.lower().startswith(("thanks", "love", "nice", "hey", "hi")):
            warm = f"Love that—thanks for sharing. {base}"
    elif loc == "ru":
        if not warm.lower().startswith(("спасибо", "класс", "круто", "супер", "привет")):
            warm = f"Класс, спасибо что поделился(лась). {base}"
    else:
        if not warm.lower().startswith(("дякую", "клас", "круто", "супер", "привіт")):
            warm = f"Клас, дякую що поділився/лась. {base}"
    warm = _dedupe_phrase(warm, recent, loc)

    # Slightly bolder: curiosity + micro-share invitation
    if loc == "en":
        bold = f"{base.rstrip('.! ')} — what do you think about it, honestly?"
    elif loc == "ru":
        bold = f"{base.rstrip('.! ')} — а ты сам(а) как к этому относишься?"
    else:
        bold = f"{base.rstrip('.! ')} — а ти сам/сама як до цього ставишся?"
    if len(bold) > 200:
        if loc == "en":
            bold = f"{base.rstrip('.! ')} — what’s your take?"
        elif loc == "ru":
            bold = f"{base.rstrip('.! ')} — расскажешь свою версию?"
        else:
            bold = f"{base.rstrip('.! ')} — розкажеш свою версію?"
    bold = _dedupe_phrase(bold, recent, loc)

    # Extra variants for Premium Plus modes can be requested at the API layer by mapping
    # modes to these style labels. Keep these deterministic and safe.
    if loc == "en":
        flirty = f"{base.rstrip('.! ')} 🙂 honestly — what do you want most from this conversation right now?"
        witty = f"{base.rstrip('.! ')} 😄 quick question: what would you pick right now?"
        direct = f"{base.rstrip('.! ')}. Be direct: what matters most to you here?"
        thoughtful = f"{base.rstrip('.! ')} — what does this topic mean to you, really?"
        tease = f"{base.rstrip('.! ')} 😄 if I get too serious, will you stop me?"
    elif loc == "ru":
        flirty = f"{base.rstrip('.! ')} 🙂 а если честно — чего ты сейчас больше всего хочешь от этого разговора?"
        witty = f"{base.rstrip('.! ')} 😄 окей, вопрос на скорость: что выберешь прямо сейчас?"
        direct = f"{base.rstrip('.! ')}. Скажи прямо: что для тебя здесь самое важное?"
        thoughtful = f"{base.rstrip('.! ')} — что в этой теме для тебя правда важнее всего?"
        tease = f"{base.rstrip('.! ')} 😄 если я отвечу слишком серьёзно, остановишь меня?"
    else:
        flirty = f"{base.rstrip('.! ')} 🙂 а якщо чесно — що ти зараз найбільше хочеш від цієї розмови?"
        witty = f"{base.rstrip('.! ')} 😄 окей, питання на швидкість: що обереш прямо зараз?"
        direct = f"{base.rstrip('.! ')}. Скажи прямо: що для тебе найважливіше тут?"
        thoughtful = f"{base.rstrip('.! ')} — що в цій темі для тебе справді значить найбільше?"
        tease = f"{base.rstrip('.! ')} 😄 якщо я відповім занадто серйозно, ти мене зупиниш?"
    flirty = _dedupe_phrase(flirty, recent, loc)
    witty = _dedupe_phrase(witty, recent, loc)
    direct = _dedupe_phrase(direct, recent, loc)
    thoughtful = _dedupe_phrase(thoughtful, recent, loc)
    tease = _dedupe_phrase(tease, recent, loc)

    out = [
        _one(clearer, "polish"),
        _one(warm, "more_natural"),
        _one(bold, "shorter"),
        _one(flirty, "flirty"),
        _one(witty, "witty"),
        _one(direct, "direct"),
        _one(thoughtful, "thoughtful"),
        _one(tease, "tease_lightly"),
    ]
    return out


def _dedupe_phrase(text: str, recent_lower: str, loc: str) -> str:
    t = text
    if loc == "en":
        pairs = [("Interesting", "Honestly"), ("love", "nice"), ("most important", "main thing")]
    elif loc == "ru":
        pairs = [("Интересно", "Слушай"), ("класс", "супер"), ("важнее", "главное")]
    else:
        pairs = [("Цікаво", "Слухай"), ("клас", "супер"), ("важливіше", "головне")]
    for a, b in pairs:
        if a.lower() in recent_lower:
            t = t.replace(a, b)
    return t
