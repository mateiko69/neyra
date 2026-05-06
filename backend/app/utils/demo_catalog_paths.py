"""Canonical demo profile photo paths with safe production fallbacks."""

from __future__ import annotations

import re

_DEMO_MAIN_RE = re.compile(r"^/demo-profiles/(men|women)/([^/]+)/main\.(jpe?g)$", re.IGNORECASE)

# Known-safe bundled assets that must always exist in production fallback chains.
_SAFE_WOMEN = (
    "/demo-profiles/women/demo_001/main.jpg",
    "/demo-profiles/women/demo_002/main.jpg",
    "/demo-profiles/women/demo_003/main.jpg",
)
_SAFE_MEN = (
    "/demo-profiles/men/demo_001/main.jpg",
)


def demo_safe_primary_photo_url(gender: str | None = None, *, seed: int | None = None) -> str:
    g = (gender or "").strip().lower()
    if g in {"man", "male", "men", "m"}:
        pool = _SAFE_MEN
    else:
        pool = _SAFE_WOMEN
    if not pool:
        return "/demo-profiles/women/demo_001/main.jpg"
    idx = int(seed or 0) % len(pool)
    return pool[idx]


def demo_catalog_main_photo_url(catalog_id: str) -> str:
    """Map catalog id like `woman_demo_001` → `/demo-profiles/women/demo_001/main.jpg`."""
    raw = (catalog_id or "").strip()
    if not raw:
        return demo_safe_primary_photo_url("woman")
    lower = raw.lower()
    if lower.startswith("man_"):
        slug = raw[len("man_") :].strip() or "demo_001"
        if not slug:
            return demo_safe_primary_photo_url("man")
        return f"/demo-profiles/men/{slug}/main.jpg"
    if lower.startswith("woman_"):
        slug = raw[len("woman_") :].strip() or "demo_001"
        if not slug:
            return demo_safe_primary_photo_url("woman")
        return f"/demo-profiles/women/{slug}/main.jpg"
    return demo_safe_primary_photo_url("woman")


def is_demo_catalog_primary_photo_url(url: str | None) -> bool:
    u = (url or "").strip().split("?", 1)[0].strip()
    return bool(_DEMO_MAIN_RE.match(u))
