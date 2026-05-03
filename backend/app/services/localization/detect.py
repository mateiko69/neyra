from __future__ import annotations

from typing import Iterable

from fastapi import Request

from app.services.localization.locale import normalize_locale


def _parse_accept_language(value: str | None) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    parts = []
    for chunk in raw.split(","):
        token = chunk.split(";")[0].strip()
        if token:
            parts.append(token)
    return parts


def detect_user_locale(
    request: Request,
    *,
    user_manual_locale: str | None = None,
    device_locale: str | None = None,
    ip_country_locale: str | None = None,
) -> str:
    """Priority:
    1) manual user setting (profile or explicit)
    2) browser language (Accept-Language)
    3) device language (optional header/client-provided)
    4) country/IP fallback (optional)
    5) English fallback
    """
    if user_manual_locale:
        return normalize_locale(user_manual_locale)

    accept = request.headers.get("accept-language")
    for candidate in _parse_accept_language(accept):
        norm = normalize_locale(candidate)
        if norm:
            return norm

    if device_locale:
        return normalize_locale(device_locale)

    if ip_country_locale:
        return normalize_locale(ip_country_locale)

    return "en"

