"""
Localized copy for demo threads, matches/conversation previews, and mock AI surfaces.

Phrase rows for categories and UI chrome are keyed by normalize_ai_request_locale() codes.
Non-English responses must not fall back to English literals.
"""

from __future__ import annotations

from app.constants.ai_surface_catalog import BADGE_AI_DEMO, HEADLINE_START_CHAT, MATCHES_PROMPT_OPEN, ai_surface_must
from app.services.ai.ai_fallback_phrases import opener_typed_fallback, timed_reengage_triple, timed_revive_triple
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.english_leak import english_leak_detected
from app.services.ai.locale_pipeline import log_ai_locale_final
from app.services.ai.output_script_locale import sniff_dominant_script_for_log

_NON_EN_FALLBACK_CHAIN: tuple[str, ...] = (
    "uk",
    "de",
    "es",
    "fr",
    "pt",
    "it",
    "pl",
    "ru",
    "zh",
    "zh-TW",
    "ja",
    "ko",
    "nl",
    "sv",
    "da",
    "no",
    "fi",
    "cs",
    "ro",
    "hu",
    "el",
    "bg",
    "ar",
    "he",
    "hi",
    "id",
    "th",
    "vi",
    "tr",
)

_OTHER_OPTIONS: dict[str, str] = {
    "en": "Other options",
    "uk": "Інші варіанти",
    "ru": "Другие варианты",
    "de": "Weitere Optionen",
    "fr": "Autres options",
    "es": "Otras opciones",
    "pt": "Outras opções",
    "it": "Altre opzioni",
    "pl": "Inne opcje",
    "tr": "Diğer seçenekler",
    "zh": "其他选项",
    "zh-TW": "其他選項",
    "ja": "ほかの候補",
    "ko": "다른 옵션",
    "ar": "خيارات أخرى",
    "he": "אפשרויות נוספות",
    "hi": "अन्य विकल्प",
    "id": "Opsi lain",
    "th": "ตัวเลือกอื่น",
    "vi": "Lựa chọn khác",
    "nl": "Meer opties",
    "sv": "Fler alternativ",
    "da": "Andre muligheder",
    "no": "Flere alternativer",
    "fi": "Muut vaihtoehdot",
    "cs": "Další možnosti",
    "ro": "Alte variante",
    "hu": "További lehetőségek",
    "el": "Άλλες επιλογές",
    "bg": "Други варианти",
}

_DEMO_CHAT_BANNER: dict[str, str] = {
    "en": "Demo chat — AI simulation",
    "uk": "Демо-чат — симуляція ШІ",
    "ru": "Демо-чат — симуляция ИИ",
    "de": "Demo-Chat — KI-Simulation",
    "fr": "Chat démo — simulation IA",
    "es": "Chat demo — simulación de IA",
    "pt": "Chat demo — simulação de IA",
    "it": "Chat demo — simulazione IA",
    "pl": "Czat demo — symulacja AI",
    "tr": "Demo sohbet — yapay zekâ simülasyonu",
    "zh": "演示聊天 — AI 模拟",
    "zh-TW": "示範聊天 — AI 模擬",
    "ja": "デモチャット — AIシミュレーション",
    "ko": "데모 채팅 — AI 시뮬레이션",
    "ar": "دردشة تجريبية — محاكاة ذكاء اصطناعي",
    "he": "צ׳אט דמו — סימולציית בינה מלאכותית",
    "hi": "डेमो चैट — AI प्रतिरूपण",
    "id": "Obrolan demo — simulasi AI",
    "th": "แชททดลอง — จำลอง AI",
    "vi": "Chat demo — mô phỏng AI",
    "nl": "Demo-chat — AI-simulatie",
    "sv": "Demochatt — AI-simulation",
    "da": "Demochat — AI-simulation",
    "no": "Demochat — KI-simulering",
    "fi": "Demokeskustelu — tekoälysimulaatio",
    "cs": "Demo chat — simulace AI",
    "ro": "Chat demo — simulare AI",
    "hu": "Demó chat — MI-szimuláció",
    "el": "Επίδειξη συνομιλίας — προσομοίωση AI",
    "bg": "Демо чат — AI симулация",
}

_VOICE_STUB: dict[str, str] = {
    "en": "[Voice message]",
    "uk": "[Голосове повідомлення]",
    "ru": "[Голосовое сообщение]",
    "de": "[Sprachnachricht]",
    "fr": "[Message vocal]",
    "es": "[Mensaje de voz]",
    "pt": "[Mensagem de voz]",
    "it": "[Messaggio vocale]",
    "pl": "[Wiadomość głosowa]",
    "tr": "[Sesli mesaj]",
    "zh": "[语音消息]",
    "zh-TW": "[語音訊息]",
    "ja": "[ボイスメッセージ]",
    "ko": "[음성 메시지]",
    "ar": "[رسالة صوتية]",
    "he": "[הודעת קול]",
    "hi": "[वॉइस संदेश]",
    "id": "[Pesan suara]",
    "th": "[ข้อความเสียง]",
    "vi": "[Tin thoại]",
    "nl": "[Spraakbericht]",
    "sv": "[Röstmeddelande]",
    "da": "[Talebesked]",
    "no": "[Talemelding]",
    "fi": "[Ääniviesti]",
    "cs": "[Hlasová zpráva]",
    "ro": "[Mesaj vocal]",
    "hu": "[Hangüzenet]",
    "el": "[Φωνητικό μήνυμα]",
    "bg": "[Гласово съобщение]",
}


def _pick_row(table: dict[str, str], locale: str | None) -> str:
    loc = normalize_ai_request_locale(locale or "en")
    if loc == "en":
        return table["en"]
    direct = table.get(loc)
    if direct:
        return direct
    for fb in _NON_EN_FALLBACK_CHAIN:
        v = table.get(fb)
        if v:
            return v
    return table["en"]


def localized_other_options(locale: str | None) -> str:
    return _pick_row(_OTHER_OPTIONS, locale)


def localized_demo_chat_banner(locale: str | None) -> str:
    return _pick_row(_DEMO_CHAT_BANNER, locale)


def localized_voice_message_stub(locale: str | None) -> str:
    return _pick_row(_VOICE_STUB, locale)


def localized_demo_profile_badge(locale: str | None) -> str:
    loc = normalize_ai_request_locale(locale or "en")
    if loc == "en":
        return "AI demo profile — not a real person"
    try:
        return ai_surface_must(loc, BADGE_AI_DEMO)
    except Exception:
        return _pick_row(_DEMO_CHAT_BANNER, loc)


def matches_preview_fallback_line(locale: str | None) -> str:
    """Long-form empty-thread hint; uses surface catalog headline (localized)."""
    loc = normalize_ai_request_locale(locale or "en")
    try:
        return ai_surface_must(loc, HEADLINE_START_CHAT)
    except Exception:
        return opener_typed_fallback(loc)[0][1]


def matches_one_tap_prompt(locale: str | None) -> str:
    loc = normalize_ai_request_locale(locale or "en")
    try:
        return ai_surface_must(loc, MATCHES_PROMPT_OPEN)
    except Exception:
        return opener_typed_fallback(loc)[0][1]


def three_demo_openers(locale: str | None) -> tuple[str, str, str]:
    loc = normalize_ai_request_locale(locale or "en")
    rows = opener_typed_fallback(loc)[:3]
    return (str(rows[0][1]), str(rows[1][1]), str(rows[2][1]))


def three_demo_replies(locale: str | None) -> tuple[str, str, str]:
    loc = normalize_ai_request_locale(locale or "en")
    return timed_reengage_triple(loc)


def virtual_demo_outbound_line(*, locale: str | None, message_id: int) -> str:
    loc = normalize_ai_request_locale(locale or "en")
    typed = opener_typed_fallback(loc)
    tr = timed_revive_triple(loc)
    rg = timed_reengage_triple(loc)
    pool: list[str] = [
        str(typed[0][1]),
        str(typed[1][1]),
        str(typed[2][1]),
        str(rg[0]),
        str(rg[1]),
        str(rg[2]),
        str(tr[0]),
        str(tr[1]),
        str(tr[2]),
    ]
    idx = abs(int(message_id)) % len(pool)
    return pool[idx].strip()


def coerce_demo_partner_message_body(
    *,
    raw_db: str,
    locale: str | None,
    message_id: int,
    sender_is_demo_bot: bool,
    route: str = "messages_thread",
) -> str:
    """
    For demo-bot outbound lines, non-English UIs must not keep stale English DB copy.
    """
    loc = normalize_ai_request_locale(locale or "en")
    raw = (raw_db or "").strip()
    if not sender_is_demo_bot:
        return raw
    if loc == "en":
        return raw
    synth = virtual_demo_outbound_line(locale=loc, message_id=message_id)
    if english_leak_detected(raw, locale=loc):
        log_ai_locale_final(
            route=route,
            locale=loc,
            source="demo_virtualize_leak",
            cache_hit=False,
            fallback_used=True,
            output_language_guess=sniff_dominant_script_for_log(raw[:560]),
            output_snippet=raw[:560],
        )
    return synth


def leak_guard_replace(
    text: str | None,
    *,
    locale: str | None,
    route: str,
    source: str,
    replacement_pool: Iterable[str],
) -> str:
    loc = normalize_ai_request_locale(locale or "en")
    t = (text or "").strip()
    if loc == "en" or not t:
        return t
    if not english_leak_detected(t, locale=loc):
        return t
    pool = [str(x).strip() for x in replacement_pool if str(x).strip()]
    if not pool:
        pool = [virtual_demo_outbound_line(locale=loc, message_id=hash(t) % 10_000)]
    rep = pool[abs(hash(t)) % len(pool)]
    log_ai_locale_final(
        route=route,
        locale=loc,
        source=source,
        cache_hit=False,
        fallback_used=True,
        output_language_guess=sniff_dominant_script_for_log(rep[:560]),
        output_snippet=t[:560],
    )
    return rep


def localized_demo_smalltalk_reply(locale: str | None, *, user_message_lower: str, context_lines: int) -> str:
    """build_demo_reply pools without English literals."""
    loc = normalize_ai_request_locale(locale or "en")
    a, b, c = three_demo_replies(loc)
    x, y, z = three_demo_openers(loc)
    pool = [a, b, c, x, y, z]
    um = user_message_lower
    if "coffee" in um or "drink" in um or "meet" in um:
        pool = [timed_reengage_triple(loc)[0], z, b]
    elif "music" in um or "film" in um or "movie" in um:
        pool = [a, c, x]
    elif "hi" in um or "hello" in um or context_lines == 0:
        pool = [x, y, a]
    idx = abs(hash(um)) % len(pool)
    return pool[idx]
