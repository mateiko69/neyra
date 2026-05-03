"""Server-side i18n for demo bot fallback lines (when catalog examples + AI are unavailable)."""

from __future__ import annotations

from app.services.app_language import SUPPORTED_APP_LANGUAGES, normalize_app_language

# Keys match frontend `demo.messages.*` for parity / tooling; values are server-owned.

_EN: dict[str, str] = {
    "demo.messages.opener.light": "Hey {name} — nice to match. How's your week going?",
    "demo.messages.opener.flirty": "Hey {name} 🙂 Your profile made me smile — what's your go-to weekend plan?",
    "demo.messages.opener.curious": "Hi {name}! What's something you're into lately?",
    "demo.messages.reply.light": "Thanks for sharing, {name}. What's been the best part of your day?",
    "demo.messages.reply.flirty": "Love that energy 😊 What would you want to do if we met up?",
    "demo.messages.reply.curious": "Interesting — what drew you to that?",
    "demo.messages.revive.light": "Still around, {name}? No pressure — just checking in.",
    "demo.messages.revive.flirty": "Popping back in 🙂 Still curious to chat, {name}?",
    "demo.messages.revive.curious": "Hey {name} — what's one small win from your week?",
    "demo.messages.fallback": "Thanks, {name} — I'm here when you want to keep chatting.",
}

_UK: dict[str, str] = {
    "demo.messages.opener.light": "Привіт, {name} — приємно зійтися. Як твій тиждень?",
    "demo.messages.opener.flirty": "Привіт, {name} 🙂 Твій профіль змусив посміхнутися — який у тебе улюблений план на вихідні?",
    "demo.messages.opener.curious": "Привіт, {name}! Чим ти зараз захоплюєшся?",
    "demo.messages.reply.light": "Дякую, що написали, {name}. Що було найкращим у вашому дні?",
    "demo.messages.reply.flirty": "Класна енергія 😊 Що б ти хотіла зробити, якби зустрілися?",
    "demo.messages.reply.curious": "Цікаво — що тебе до цього підштовхнуло?",
    "demo.messages.revive.light": "Ти ще тут, {name}? Без тиску — просто нагадую про себе.",
    "demo.messages.revive.flirty": "Заглядаю знову 🙂 Усе ще хочеш продовжити розмову, {name}?",
    "demo.messages.revive.curious": "Привіт, {name} — яка одна маленька перемога цього тижня?",
    "demo.messages.fallback": "Дякую, {name} — я тут, коли захочеш продовжити.",
}

_RU: dict[str, str] = {
    "demo.messages.first_match": "Привет, я демо-профиль 👋 Хочешь попробовать ответить с AI-подсказками?",
}

_ES: dict[str, str] = {
    "demo.messages.first_match": "Hola, soy un perfil de demo 👋 ¿Quieres probar responder con sugerencias de IA?",
}

_ZH: dict[str, str] = {
    "demo.messages.first_match": "嗨，我是演示资料 👋 想试试用 AI 回复建议吗？",
}

_ZH_TW: dict[str, str] = {
    "demo.messages.first_match": "嗨，我是示範檔案 👋 想試試用 AI 回覆建議嗎？",
}

_CACHE: dict[str, dict[str, str]] = {}


def _bundle_for_lang(lang: str) -> dict[str, str]:
    code = normalize_app_language(lang)
    if code in _CACHE:
        return _CACHE[code]
    base = dict(_EN)
    if code == "uk":
        base.update(_UK)
    elif code == "ru":
        base.update(_RU)
    elif code == "es":
        base.update(_ES)
    elif code == "zh":
        base.update(_ZH)
    elif code == "zh-TW":
        base.update(_ZH_TW)
    elif code != "en" and code in SUPPORTED_APP_LANGUAGES:
        pass
    _CACHE[code] = base
    return base


def demo_template_key_for_mode(mode: str, engine_personality: str) -> str:
    """Map engine tags to template variant (light / flirty / curious)."""
    mode_l = (mode or "reply").strip().lower()
    if mode_l not in {"opener", "reply", "revive"}:
        mode_l = "reply"
    if engine_personality == "flirty":
        variant = "flirty"
    elif engine_personality == "curious":
        variant = "curious"
    else:
        variant = "light"
    return f"demo.messages.{mode_l}.{variant}"


def get_demo_template_message(mode: str, engine_personality: str, lang: str, partner_name: str) -> str:
    code = normalize_app_language(lang)
    bundle = _bundle_for_lang(code)
    key = demo_template_key_for_mode(mode, engine_personality)
    text = (bundle.get(key) or _EN.get(key) or "").strip()
    if not text:
        text = (_EN.get("demo.messages.fallback") or "").strip()
    name = (partner_name or "there").strip() or "there"
    try:
        return text.format(name=name)[:4000]
    except Exception:
        return text[:4000]


def get_demo_first_match_message(lang: str) -> str:
    code = normalize_app_language(lang)
    if code == "uk":
        return "Привіт, я демо-профіль 👋 Хочеш спробувати відповісти через AI-підказки?"
    if code == "ru":
        return _RU["demo.messages.first_match"]
    if code == "es":
        return _ES["demo.messages.first_match"]
    if code in {"zh", "zh-TW"}:
        return _ZH["demo.messages.first_match"] if code == "zh" else _ZH_TW["demo.messages.first_match"]
    return "Hey, I’m a demo profile 👋 Want to try replying with AI suggestions?"
