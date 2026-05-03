"""
Deterministic contextual reply triples for dating chat fallbacks (no new AI).

Used when Gemini/provider fails or validation rejects output. For ``uk`` locale,
prefer answering the partner's actual thread (especially direct questions).
"""

from __future__ import annotations

import re

_UK_FORBIDDEN_ENGLISH_PHRASES = re.compile(
    r"(?i)\b("
    r"what|what's|whats|how|when|where|why|yourself|proud|genuinely|curious|weekend|"
    r"playful|deep|warm|something|anything|nothing|everything|lately|"
    r"tell me|think about|feel like|out loud|about that"
    r")\b"
)


def uk_suggestion_line_has_english_leak(text: str) -> bool:
    """True if copy reads as English / banned tokens for Ukrainian-only UI."""
    t = (text or "").strip()
    if not t:
        return False
    if _UK_FORBIDDEN_ENGLISH_PHRASES.search(t):
        return True
    # Obvious English-only suggestions (Latin sentence, no Cyrillic)
    if re.search(r"[A-Za-z]{6,}", t) and not re.search(r"[\u0400-\u04FF]", t):
        return True
    return False


def guard_uk_variant_pack(variants: dict[str, str], *, last_partner_message: str) -> dict[str, str]:
    """Hard guard: replace leaky Gemini/topic lines with the same contextual UA triple as reply-options."""
    trip = uk_reply_fallback_three_lines(last_partner_message or "", continue_mode=True)
    out: dict[str, str] = {}
    for i, k in enumerate(("light", "flirty", "deep")):
        txt = str(variants.get(k) or "").strip()
        if uk_suggestion_line_has_english_leak(txt):
            out[k] = trip[i]
        else:
            out[k] = txt
    return out


def _ensure_question_short_local(text: str) -> str:
    s = " ".join((text or "").strip().split())
    if not s:
        return "Ок 🙂 я б тут тримав(ла) легкий тон — фактами чи настроєм почнемо?"
    if not s.endswith("?"):
        s = s.rstrip(".!… ")
        s = f"{s}?"
    parts = [p.strip() for p in s.split("?") if p.strip()]
    if len(parts) > 2:
        s = "? ".join(parts[:2]).strip() + "?"
    return s[:320]


def _extract_place_hint(text: str) -> str | None:
    t = (text or "").strip()
    low = t.lower()
    if "верховин" in low:
        return "Верховині"
    if "київ" in low:
        return "Києві"
    if "львів" in low:
        return "Львові"
    if "одес" in low:
        return "Одесі"
    return None


def detect_contextual_fallback_bucket(last_message: str) -> str | None:
    """
    Map partner's last line to a small set of scripted response themes.
    Returns None → caller may use generic (but still locale-safe) fallbacks.
    """
    raw = " ".join((last_message or "").strip().split())
    if not raw:
        return None
    low = raw.lower()

    if any(k in low for k in ("вихідн", "weekend", "викенд", "выходные", "на вихідних")):
        return "weekend"
    if any(
        k in low
        for k in (
            "як справи",
            "як у тебе справи",
            "що робиш",
            "how are you",
            "how've you been",
            "hows your day",
            "how's your day",
            "how is your day",
        )
    ):
        return "mood"
    if any(
        k in low
        for k in (
            "що любиш",
            "любиш робити",
            "цікавить",
            "подобається",
            "хобі",
            "інтерес",
            "what do you love",
            "what are you into",
            "interests",
        )
    ):
        return "interests"
    if any(
        k in low
        for k in (
            "зустріт",
            "зустрин",
            "кава",
            "каву",
            "прогулян",
            "випий",
            "зустрітися",
            "grab coffee",
            "meet up",
            "go for a walk",
        )
    ):
        return "meet"
    return None


_UK_TRIPLES: dict[str, tuple[str, str, str]] = {
    "weekend": (
        "О, про вихідні — класна тема 😄 я б обрав(ла) щось між «ну спокійно» і маленькою пригодою — ти більше за лежачий ранок чи одразу в рух?",
        "Звучить як ідеальні вихідні без перегрузу 😉 я люблю простір для імпровізації — ти більше за прогулянку + каву чи спонтанну поїздку?",
        "Мені заходить формат «видихнув(ла) і зробив(ла) одну річ для себе» 🙂 тобі на вихідних важливіше тиша чи нові емоції?",
    ),
    "mood": (
        "Тепло відповісти легко 😄 я сьогодні скоріше за легкий тон — ти більше за короткий чекін чи хочеш розгорнутися повністю?",
        "Ок, ловлю 🙂 я зазвичай заряджаюсь маленькими штуками — ти більше від людей чи від тиші після дня?",
        "Інколи найкраще — чесно і без шуму 🙂 ти зараз більше хочеш підтримку словами чи просто «я тут»?",
    ),
    "interests": (
        "Клас, що відкриваєш це 🙂 я часто забиваю подкастом і новою кав’ярнею — ти більше за рух по місту чи домашній затишок?",
        "Я із задоволенням пробую щось руками або серіал «на одну серію» 😄 ти більше за активний вечір чи спокійний ритуал?",
        "Люблю, коли хобі не «для галочки» 🙂 ти більше про щось соціальне чи про соло-зону без пояснень?",
    ),
    "meet": (
        "Звучить мило і без пресингу 😄 я б спробував(ла) формат «коротко і по-людськи» — тобі ближче будній вечір чи вихідний день?",
        "Мені ок, якщо це недовго і можна просто поговорити 🙂 ти більше за каву «на ногах» чи повільну прогулянку?",
        "Я б без офіційності — маленька кава або 20 хвилин на повітрі 🙂 тобі комфортніше коли все заплановано чи коли спонтанно?",
    ),
}


def uk_contextual_reply_triple_or_none(last_message: str) -> tuple[str, str, str] | None:
    b = detect_contextual_fallback_bucket(last_message)
    if not b:
        return None
    return _UK_TRIPLES.get(b)


def uk_reply_fallback_three_lines(last_message: str, *, continue_mode: bool) -> list[str]:
    """Three Ukrainian lines for copilot / reply-options style fallbacks."""
    spec = uk_contextual_reply_triple_or_none(last_message)
    if spec:
        return [_ensure_question_short_local(s) for s in spec]

    msg = " ".join((last_message or "").strip().split())
    low = msg.lower()
    place = _extract_place_hint(last_message)
    where_uk = f" поблизу {place}" if place else ""

    if continue_mode:
        light = _ensure_question_short_local(
            f"Клас, це відгукується 🙂 я б розкрив(ла) це без натиску — тобі ближче спершу факти чи настрій{where_uk}?"
        )
        flirty = _ensure_question_short_local(
            "Зачіпило 😉 я люблю, коли є маленький грайливий зигзаг — хочеш короткий меседж або голосом на ходу?"
        )
        deep = _ensure_question_short_local(
            "Чую 🙂 для тебе тут важливіше голова чи серце — що відчувається сильніше?"
        )
        if ("places" in low or "місця" in low or "места" in low) and (
            "people" in low or "люди" in low or "людьми" in low
        ):
            light = _ensure_question_short_local(
                "Звучить як здоровий мікс 🙂 ти більше за розглядати краєвид чи людей навколо?"
            )
            flirty = _ensure_question_short_local(
                "Ок, я б там загубив(ла) годину без скандалу 😉 секретна точка огляду чи повільна кава?"
            )
            deep = _ensure_question_short_local(
                "Тобі там ближче тиша природи чи тепло людей — що зараз переважає?"
            )
    else:
        light = _ensure_question_short_local(
            f"Цікаво 🙂 я б відповів(ла) щось легке — хочеш спершу контекст чи одразу емоцію{where_uk}?"
        )
        flirty = _ensure_question_short_local(
            "Ловлю 🙂 мікро-вибір: короткий голос чи акуратний текст, коли продовжиш?"
        )
        deep = _ensure_question_short_local(
            "Зрозуміло 🙂 ти зараз більше про план на тиждень чи «подивимось як піде»?"
        )
    return [light, flirty, deep]


def uk_emergency_fallback_triple() -> tuple[str, str, str]:
    """Ultra-safe UA rows for sanitise / emergency pools — never English."""
    return (
        _ensure_question_short_local(
            "Клас 🙂 мені зараз ближче щось легке — ти більше за довгу вечірню розмову чи коротке тепле повідомлення?"
        ),
        _ensure_question_short_local(
            "Ок, відчуваю настрій 😉 я б обрав(ла) грайливо без тиску — план на тиждень чи повна імпровізація?"
        ),
        _ensure_question_short_local(
            "Слухай 🙂 я після дня заряджаюсь то людьми, то тишею — тобі зараз ближче що?"
        ),
    )


def uk_chat_brain_overlay(mode: str, last_partner_message: str | None) -> dict[str, str] | None:
    """Optional replacement dict for `_fallback_pack` when UA + detected intent."""
    if not (last_partner_message or "").strip():
        return None
    trip = uk_contextual_reply_triple_or_none(last_partner_message)
    if not trip:
        return None
    m = (mode or "reply").strip().lower()
    if m not in {"reply", "auto", "deepen", "flirty"}:
        return None
    a, b, c = trip
    return {"light": _ensure_question_short_local(a), "flirty": _ensure_question_short_local(b), "deep": _ensure_question_short_local(c)}
