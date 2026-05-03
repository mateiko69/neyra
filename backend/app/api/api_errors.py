"""Stable, localizable API error bodies. Clients read detail.code; logs carry technical context."""

from __future__ import annotations

from typing import Any


def api_error(code: str, **extra: Any) -> dict[str, Any]:
    """Return a FastAPI-compatible detail dict. Do not put secrets or PII in extra."""
    out: dict[str, Any] = {"code": code}
    for k, v in extra.items():
        if k == "code" or v is None:
            continue
        out[k] = v
    return out
