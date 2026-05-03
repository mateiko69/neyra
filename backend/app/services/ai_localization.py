from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import settings
from app.services.ai.providers.http_json import JSONParseError, _extract_json
from app.services.localization.locale import language_name, normalize_locale
from app.services.ai.gemini_client import GeminiClient

# All supported app locales except English (matches frontend `LOCALES` minus `en`).
TARGET_LOCALE_FILES: Final[tuple[str, ...]] = (
    "uk",
    "ru",
    "es",
    "pt",
    "fr",
    "de",
    "it",
    "pl",
    "tr",
    "zh",
    "zh-TW",
    "ja",
    "ko",
    "hi",
    "id",
    "vi",
    "th",
    "ar",
    "he",
    "nl",
    "sv",
    "cs",
    "ro",
    "hu",
    "el",
    "da",
    "fi",
    "no",
)
TARGET_LOCALE_SET: Final[frozenset[str]] = frozenset(TARGET_LOCALE_FILES)

STYLE_GUIDE: Final[str] = (
    "NEYRA is a premium dating product: confident, warm, human. "
    "No corporate filler, no cringe, no machine-translated stiffness."
)

# Shared QC / rewrite rules (all locales).
QUALITY_STYLE_RULES: Final[str] = (
    "Voice must be: friendly, confident, premium, and human — never stiff or generic.\n"
    "Reject: robotic tone, literal calques, marketing clichés, overly long UI lines.\n"
    "Keep register consistent (informal vs formal) within the string.\n"
    "If the line is already natural and on-brand, return it unchanged in fixed_text."
)

# Primary instruction block (user-facing prompt).
TRANSLATE_UI_DIRECTIVE: Final[str] = (
    "Translate UI text for a premium dating app. "
    "Keep it short, natural, human, emotionally engaging — never robotic."
)


def context_instructions(i18n_key: str) -> str:
    """Tone hints from key path: buttons → short; chat → natural; premium → emotional; system → clear."""
    raw = (i18n_key or "").strip()
    lower = raw.lower()
    parts = lower.split(".")
    head = parts[0] if parts else ""

    hints: list[str] = []
    # Buttons / actions → short
    if "button" in parts or head == "actions" or ".btn." in f".{lower}.":
        hints.append("Type: button / action — keep it very short (often 1–3 words).")
    # Chat → natural
    if head == "chat" or "composer" in parts or "message" in parts:
        hints.append("Type: chat — natural, conversational, like real messaging.")
    # Premium → emotional (still tasteful)
    if "premium" in parts or "paywall" in parts or "subscription" in parts or head in {"premium", "billing", "paywall"}:
        hints.append("Type: premium — warm, elevated, emotionally engaging; never tacky.")
    # System (errors, diagnostics) → clear
    if head == "errors" or lower.startswith("errors.") or "system" in parts:
        hints.append("Type: system — clear, direct, easy to scan; calm and neutral.")
    if "title" in parts or "heading" in parts or "header" in parts:
        hints.append("Title line: concise punch; may be slightly longer than a button.")
    if "placeholder" in parts or "hint" in parts:
        hints.append("Placeholder: short hint; informal where it fits the app.")
    if not hints:
        hints.append("General UI: concise, clear, on-brand.")
    return " ".join(hints)


def _locale_names_block() -> str:
    lines = []
    for code in TARGET_LOCALE_FILES:
        lines.append(f'- "{code}": {language_name(code)}')
    return "\n".join(lines)


def _locale_keys_csv() -> str:
    return ", ".join(f'"{c}"' for c in TARGET_LOCALE_FILES)


def _translation_inner_shape_example() -> str:
    return "{" + ", ".join(f'"{c}":"<text>"' for c in TARGET_LOCALE_FILES) + "}"


def build_system_prompt() -> str:
    return "\n".join(
        [
            STYLE_GUIDE,
            "",
            "You translate product UI strings from English into multiple languages.",
            "Context rules when classifying by key path:",
            "- buttons → short",
            "- chat → natural",
            "- premium → emotional",
            "- system → clear",
            "",
            "Preserve placeholders exactly: tokens like {name}, {count}, {0}, %s, and HTML/Markdown must remain unchanged.",
            "Do not add quotes around outputs unless the English source already uses matching quotes.",
            "",
            "Output MUST be a single JSON object. No markdown fences, no commentary.",
            "",
            TRANSLATE_UI_DIRECTIVE,
        ]
    )


def _build_batch_user_prompt(batch: dict[str, str]) -> str:
    ctx_block = "\n".join(f"- {k}: {context_instructions(k)}" for k in batch)
    pairs = "\n".join(f'{json.dumps(k, ensure_ascii=False)}: {json.dumps(en, ensure_ascii=False)}' for k, en in batch.items())
    return "\n".join(
        [
            "For each i18n key below, translate the English string into ALL of these locales:",
            _locale_names_block(),
            "",
            "Context per key:",
            ctx_block,
            "",
            "Keys and English source:",
            "{",
            pairs,
            "}",
            "",
            "Return JSON shape:",
            '{"translations":{"<key>":' + _translation_inner_shape_example() + ", ...}}",
            f"Use exactly these locale keys in each inner object (no extras, no omissions): {_locale_keys_csv()}.",
        ]
    )


def _validate_locale_grid(v: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    required = TARGET_LOCALE_SET
    for key, row in v.items():
        if not isinstance(row, dict):
            raise ValueError(f"{key}: row must be object")
        missing = required - set(row.keys())
        if missing:
            raise ValueError(f"{key}: missing locales {sorted(missing)}")
        for loc, text in row.items():
            if loc not in required:
                raise ValueError(f"{key}: unexpected locale {loc}")
            if not (text or "").strip():
                raise ValueError(f"{key}.{loc}: empty")
    return v


class BatchTranslationPayload(BaseModel):
    translations: dict[str, dict[str, str]]

    @field_validator("translations")
    @classmethod
    def _each_locale(cls, v: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        return _validate_locale_grid(v)


class BatchQualityPayload(BaseModel):
    translations: dict[str, dict[str, str]]

    @field_validator("translations")
    @classmethod
    def _each_locale_quality(cls, v: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        return _validate_locale_grid(v)


class SingleStringQualityPayload(BaseModel):
    fixed_text: str
    issues: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class TranslationQualityResult:
    """Result of ``check_translation_quality`` (auto-fixed copy + what was wrong)."""

    text: str
    changed: bool
    issues: tuple[str, ...]


_PLACEHOLDER_RE = re.compile(r"(\{[^{}]+\}|%[sd]|<\/?[a-zA-Z][^>]*>)")


def _placeholders(s: str) -> list[str]:
    return _PLACEHOLDER_RE.findall(s or "")


def _violates_placeholders(en: str, translated: str) -> bool:
    return _placeholders(en) != _placeholders(translated)


def _extract_text_from_openai_response(data: dict[str, Any]) -> str:
    ot = data.get("output_text")
    if isinstance(ot, str) and ot.strip():
        return ot
    chunks: list[str] = []
    for blk in data.get("output") or []:
        if not isinstance(blk, dict):
            continue
        for c in blk.get("content") or []:
            if not isinstance(c, dict):
                continue
            t = c.get("text")
            if c.get("type") in ("output_text", "text") and isinstance(t, str):
                chunks.append(t)
    return "".join(chunks)


def _openai_responses_parse_json(
    system_prompt: str,
    user_prompt: str,
    model: type[BaseModel],
    *,
    max_output_tokens: int | None = None,
    temperature: float | None = None,
) -> BaseModel:
    if not (settings.OPENAI_API_KEY or "").strip():
        raise RuntimeError("OPENAI_API_KEY is required for AI localization")

    url = "https://api.openai.com/v1/responses"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}
    toks = max_output_tokens if max_output_tokens is not None else max(800, min(int(settings.AI_MAX_TOKENS), 4096))
    temp = temperature if temperature is not None else min(float(settings.AI_TEMPERATURE), 0.6)
    payload: dict[str, Any] = {
        "model": settings.AI_MODEL,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
        "temperature": temp,
        "max_output_tokens": toks,
    }

    last_err: Exception | None = None
    with httpx.Client(timeout=120.0) as client:
        for attempt in range(2):
            try:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
                raw_text = _extract_text_from_openai_response(body)
                if not raw_text.strip():
                    raise JSONParseError("empty model output")
                js = json.loads(_extract_json(raw_text))
                return model.model_validate(js)
            except (httpx.HTTPError, json.JSONDecodeError, JSONParseError, ValidationError) as e:
                last_err = e
                if attempt == 0:
                    time.sleep(1.2)
                    continue
                break
    raise RuntimeError(f"OpenAI localization failed: {last_err}")


def _gemini_parse_json(system_prompt: str, user_prompt: str, model: type[BaseModel]) -> BaseModel:
    if not GeminiClient.enabled():
        raise RuntimeError("GEMINI_API_KEY is required for Gemini localization")
    client = GeminiClient()
    import asyncio

    out = asyncio.run(
        client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            out_model=model,
            timeout_s=40.0,
            max_retries=1,
            temperature=0.35,
            max_output_tokens=min(4096, max(int(settings.AI_MAX_TOKENS), 1200)),
            model=settings.GEMINI_LOCALIZATION_MODEL,
        )
    )
    return out


def translate_ui_batch(batch: dict[str, str]) -> dict[str, dict[str, str]]:
    """Translate multiple keys at once. Each key maps to locale → string."""
    if not batch:
        return {}
    user = _build_batch_user_prompt(batch)
    # Prefer Gemini localization model if configured; fallback to OpenAI.
    try:
        out = _gemini_parse_json(build_system_prompt(), user, BatchTranslationPayload)
    except Exception:
        out = _openai_responses_parse_json(build_system_prompt(), user, BatchTranslationPayload)
    result: dict[str, dict[str, str]] = {}
    for k, en_text in batch.items():
        if k not in out.translations:
            raise RuntimeError(f"Model omitted key {k!r}")
        row = {loc: out.translations[k][loc] for loc in TARGET_LOCALE_FILES}
        for loc, text in row.items():
            if _violates_placeholders(en_text, text):
                raise RuntimeError(f"Placeholder mismatch for key {k!r} locale {loc}")
        result[k] = row
    return result


def build_quality_system_prompt() -> str:
    return "\n".join(
        [
            STYLE_GUIDE,
            "",
            QUALITY_STYLE_RULES,
            "",
            "You are a senior localization QA editor for a dating app UI.",
            "Review translations for: unnatural phrasing, lines much longer than needed for UI, robotic or machine tone, "
            "and inconsistent style/register.",
            "Keep meaning identical. Preserve placeholders exactly ({name}, {count}, etc.).",
            "Return ONLY JSON: {\"translations\":{<key>:" + _translation_inner_shape_example() + ", ...}}",
            "Fix only what needs fixing; if a string is already good, keep it.",
        ]
    )


def _build_single_quality_system_prompt() -> str:
    return "\n".join(
        [
            "You review and rewrite UI strings for a premium dating app.",
            STYLE_GUIDE,
            "",
            QUALITY_STYLE_RULES,
            "",
            "Check the given text (already in the target language) for:",
            "- unnatural phrasing or calques",
            "- unnecessary length (UI copy should be tight unless the language needs more words)",
            "- robotic or generic tone",
            "- inconsistent style (mixed formal/informal, etc.)",
            "",
            "Auto-fix problems in fixed_text. If nothing is wrong, set fixed_text to the same string.",
            "Respond ONLY with JSON: {\"fixed_text\":\"...\",\"issues\":[\"...\"]} — issues may be [].",
            "issues: short English labels for what you fixed (e.g. \"too_long\", \"robotic\", \"unnatural\").",
        ]
    )


def check_translation_quality(
    text: str,
    language: str,
    *,
    reference_english: str | None = None,
    i18n_key: str | None = None,
) -> TranslationQualityResult:
    """
    AI quality pass on one string in ``language`` (any supported app locale code).

    Returns auto-fixed text when the model finds problems; otherwise the original.
    Use ``reference_english`` when checking a translated line so placeholders stay aligned with English.
    ``i18n_key`` adds the same context hints as translation (buttons, chat, premium, system).
    """
    raw = (text or "").strip()
    if not raw:
        return TranslationQualityResult(text="", changed=False, issues=())

    loc = normalize_locale(language)
    lang_label = language_name(loc)
    ctx = context_instructions(i18n_key or "") if i18n_key else ""

    user_parts = [
        f"TARGET_LANGUAGE_CODE: {loc}",
        f"TARGET_LANGUAGE: {lang_label}",
        "",
        "TEXT_IN_TARGET_LANGUAGE:",
        json.dumps(raw, ensure_ascii=False),
    ]
    if reference_english is not None:
        user_parts.extend(
            [
                "",
                "ENGLISH_SOURCE (meaning + placeholders; keep every placeholder token identical in fixed_text):",
                json.dumps(str(reference_english), ensure_ascii=False),
            ]
        )
    if ctx:
        user_parts.extend(["", f"KEY_CONTEXT: {ctx}"])
    user_prompt = "\n".join(user_parts)

    out = _openai_responses_parse_json(
        _build_single_quality_system_prompt(),
        user_prompt,
        SingleStringQualityPayload,
        max_output_tokens=min(1024, max(int(settings.AI_MAX_TOKENS), 512)),
        temperature=0.35,
    )

    fixed = (out.fixed_text or "").strip()
    if not fixed:
        return TranslationQualityResult(text=raw, changed=False, issues=tuple(out.issues or ()))

    if reference_english is not None and _violates_placeholders(str(reference_english), fixed):
        return TranslationQualityResult(text=raw, changed=False, issues=("placeholder_mismatch_ignored",))

    issues_t = tuple(str(x).strip() for x in (out.issues or []) if str(x).strip())
    changed = fixed != raw
    return TranslationQualityResult(text=fixed, changed=changed, issues=issues_t)


def polish_locale_row(
    english: str,
    row: dict[str, str],
    *,
    i18n_key: str | None = None,
    only_locales: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """
    Run :func:`check_translation_quality` on each target string (all :data:`TARGET_LOCALE_FILES` by default).
    Use for a second pass after translation so every language gets the same style rules.
    """
    codes = only_locales if only_locales is not None else TARGET_LOCALE_FILES
    out: dict[str, str] = dict(row)
    for loc in codes:
        if loc not in row:
            continue
        res = check_translation_quality(
            row[loc],
            loc,
            reference_english=english,
            i18n_key=i18n_key,
        )
        out[loc] = res.text
    return out


def quality_pass_batch(en_batch: dict[str, str], translated: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Second AI pass: polish translations; returns full locale rows per key."""
    if not translated:
        return {}
    payload_obj = {
        k: {"en": en_batch[k], **translated[k]}
        for k in translated
        if k in en_batch
    }
    user = (
        "Review and improve these UI translations.\n"
        "JSON input (en + target locales):\n"
        f"{json.dumps(payload_obj, ensure_ascii=False, indent=2)}\n\n"
        'Return JSON: {"translations":{...}} with keys '
        + _locale_keys_csv()
        + " only per entry."
    )
    out = _openai_responses_parse_json(build_quality_system_prompt(), user, BatchQualityPayload)
    fixed: dict[str, dict[str, str]] = {}
    for k in translated:
        if k not in en_batch:
            continue
        base = translated[k]
        src_row = out.translations.get(k) or {}
        cleaned = {loc: (src_row.get(loc) or base[loc]) for loc in TARGET_LOCALE_FILES}
        for loc, text in cleaned.items():
            if _violates_placeholders(en_batch[k], text):
                cleaned[loc] = translated[k][loc]
        fixed[k] = cleaned
    return fixed


def translate_text(key: str, text: str, *, polish: bool = False) -> dict[str, str]:
    """
    Translate one English UI string into every locale in :data:`TARGET_LOCALE_FILES`.

    Args:
        key: i18n key (used for context rules, e.g. chat.actions.delete).
        text: English source string.
        polish: If True, run :func:`check_translation_quality` per locale (extra API calls).

    Returns:
        Dict mapping locale code → translated string (all :data:`TARGET_LOCALE_FILES` keys).
    """
    out = translate_ui_batch({key: text})
    row = dict(out[key])
    if polish:
        row = polish_locale_row(text, row, i18n_key=key)
    return row


def translate_one_key(i18n_key: str, english_text: str) -> dict[str, str]:
    """Backward-compatible alias for translate_text."""
    return translate_text(i18n_key, english_text)
