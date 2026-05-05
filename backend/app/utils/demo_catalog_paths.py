"""Canonical `/demo-profiles/{men|women}/{slug}/main.jpg` paths for catalog-backed demos."""

from __future__ import annotations

import re

_DEMO_MAIN_RE = re.compile(r"^/demo-profiles/(men|women)/([^/]+)/main\.(jpe?g)$", re.IGNORECASE)


def demo_catalog_main_photo_url(catalog_id: str) -> str:
    """Map catalog id like `woman_demo_001` → `/demo-profiles/women/demo_001/main.jpg`."""
    raw = (catalog_id or "").strip()
    if not raw:
        return "/demo-profiles/women/demo_001/main.jpg"
    lower = raw.lower()
    if lower.startswith("man_"):
        slug = raw[len("man_") :].strip() or "demo_001"
        return f"/demo-profiles/men/{slug}/main.jpg"
    if lower.startswith("woman_"):
        slug = raw[len("woman_") :].strip() or "demo_001"
        return f"/demo-profiles/women/{slug}/main.jpg"
    return "/demo-profiles/women/demo_001/main.jpg"


def is_demo_catalog_primary_photo_url(url: str | None) -> bool:
    u = (url or "").strip().split("?", 1)[0].strip()
    return bool(_DEMO_MAIN_RE.match(u))
