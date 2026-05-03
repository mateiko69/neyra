from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.cultural_tone import cultural_tone_prompt_lines
from app.services.ai.gemini_client import GeminiClient
from app.services.ai.output_script_locale import text_matches_requested_locale
from app.services.ai.safe_ai import log_ai_fallback_triggered, safe_ai_generate_async
from app.services.ai.providers.http_json import call_and_parse_json

log = logging.getLogger("neyra.ai.locale_rewrite")


class _SingleTextOut(BaseModel):
    text: str = Field(..., max_length=600)


class _LinesOut(BaseModel):
    lines: list[str] = Field(..., min_length=1, max_length=5)


def _strict_rewrite_prompt(locale: str, text: str) -> tuple[str, str]:
    loc = normalize_ai_request_locale(locale)
    tone_block = cultural_tone_prompt_lines(loc)
    system = (
        f"{tone_block}\n"
        f"You rewrite dating-chat lines strictly into locale {loc}. "
        "Return STRICT JSON only: {\"text\":\"...\"}. "
        "No explanations. Preserve meaning. One sentence preferred; end with a question when the input ends with one."
    )
    user = f"INPUT:\n{text.strip()}\n"
    return system, user


def _batch_translate_prompt(locale: str, lines: list[str]) -> tuple[str, str]:
    loc = normalize_ai_request_locale(locale)
    tone_block = cultural_tone_prompt_lines(loc)
    system = (
        f"{tone_block}\n"
        f"Translate each English line into locale {loc} for a dating app. "
        f"Return STRICT JSON only: {{\"lines\":[\"...\", ...]}} with the SAME number of strings. "
        "Natural, native phrasing — not literal machine translation."
    )
    user = "LINES_JSON:\n" + json.dumps(lines, ensure_ascii=False)
    return system, user


async def _rewrite_openai(system: str, user: str) -> str:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")
    url = "https://api.openai.com/v1/responses"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": settings.AI_MODEL,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": user}]},
        ],
        "temperature": 0.2,
        "max_output_tokens": min(256, int(settings.AI_MAX_TOKENS)),
    }
    async with httpx.AsyncClient() as client:
        parsed = await call_and_parse_json(
            client=client,
            url=url,
            headers=headers,
            payload=payload,
            out_model=_SingleTextOut,
            timeout_s=25.0,
            retry_once=True,
        )
    return (parsed.text or "").strip()


async def strict_rewrite_to_locale(text: str, locale: str | None) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    loc = normalize_ai_request_locale(locale)
    system, user = _strict_rewrite_prompt(loc, raw)
    if GeminiClient.enabled():

        async def _strict_gemini() -> str:
            gem = GeminiClient()
            out = await gem.generate_json(
                system_prompt=system,
                user_prompt=user,
                out_model=_SingleTextOut,
                timeout_s=12.0,
                max_retries=1,
                temperature=0.2,
                max_output_tokens=min(256, int(settings.AI_MAX_TOKENS)),
                model=settings.GEMINI_CHAT_MODEL,
            )
            return (out.text or "").strip()

        async def _strict_fb() -> str:
            return ""

        gem_txt = await safe_ai_generate_async(_strict_gemini, _strict_fb, endpoint="locale_rewrite/strict", locale=loc)
        if gem_txt:
            return gem_txt
    try:
        return await _rewrite_openai(system, user)
    except Exception as e:
        log_ai_fallback_triggered(
            endpoint="locale_rewrite/strict_openai",
            locale=loc,
            reason=type(e).__name__,
            error_message=str(e),
            provider="openai",
        )
        return raw


async def batch_translate_lines(lines: list[str], locale: str | None) -> list[str]:
    loc = normalize_ai_request_locale(locale)
    clean = [(x or "").strip() for x in lines if (x or "").strip()]
    if not clean:
        return []
    if loc == "en":
        return clean
    system, user = _batch_translate_prompt(loc, clean)
    if GeminiClient.enabled():

        async def _batch_gemini() -> list[str]:
            gem = GeminiClient()
            out = await gem.generate_json(
                system_prompt=system,
                user_prompt=user,
                out_model=_LinesOut,
                timeout_s=14.0,
                max_retries=1,
                temperature=0.2,
                max_output_tokens=min(320, int(settings.AI_MAX_TOKENS)),
                model=settings.GEMINI_CHAT_MODEL,
            )
            got = [(x or "").strip() for x in (out.lines or [])]
            if len(got) != len(clean) or not all(got):
                raise ValueError("batch_translate_shape_mismatch")
            return got

        async def _batch_gemini_fb() -> list[str] | None:
            return None

        gem_lines = await safe_ai_generate_async(_batch_gemini, _batch_gemini_fb, endpoint="locale_rewrite/batch", locale=loc)
        if gem_lines is not None:
            return gem_lines
    try:
        # OpenAI path: reuse single JSON object via responses API
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY missing")
        url = "https://api.openai.com/v1/responses"
        headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "model": settings.AI_MODEL,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": user}]},
            ],
            "temperature": 0.2,
            "max_output_tokens": min(400, int(settings.AI_MAX_TOKENS)),
        }
        async with httpx.AsyncClient() as client:
            parsed = await call_and_parse_json(
                client=client,
                url=url,
                headers=headers,
                payload=payload,
                out_model=_LinesOut,
                timeout_s=28.0,
                retry_once=True,
            )
        got = [(x or "").strip() for x in (parsed.lines or [])]
        if len(got) == len(clean) and all(got):
            return got
    except Exception as e:
        log_ai_fallback_triggered(
            endpoint="locale_rewrite/batch_openai",
            locale=loc,
            reason=type(e).__name__,
            error_message=str(e),
            provider="openai",
        )
    return clean


async def enforce_text_locale(text: str, locale: str | None) -> str:
    """Second pass + lock: rewrite until heuristic matches or return best effort."""
    loc = normalize_ai_request_locale(locale)
    cur = (text or "").strip()
    if not cur:
        return ""
    if text_matches_requested_locale(cur, loc):
        return cur
    once = await strict_rewrite_to_locale(cur, loc)
    if once and text_matches_requested_locale(once, loc):
        return once
    twice = await strict_rewrite_to_locale(once or cur, loc)
    if twice and text_matches_requested_locale(twice, loc):
        return twice
    return once or cur
