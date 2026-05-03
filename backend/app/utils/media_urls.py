"""Normalize stored media paths to stable DB/API values.

We deliberately store and return **relative** URLs for local uploads (e.g. `/uploads/<file>`).
The frontend is responsible for prefixing with the backend public origin for `<img src>`.

Keeping DB values relative avoids leaking internal service hosts, keeps Docker/prod stable,
and ensures a restart does not change stored values.
"""

from __future__ import annotations

import re

# Legacy catalog paths before gendered folders: /demo-profiles/demo_001/main.jpg
_DEMO_LEGACY_MAIN_RE = re.compile(
    r"^(/demo-profiles/)(demo_\d+)/(main\.(?:jpe?g|png|webp))$",
    re.IGNORECASE,
)


def normalize_media_url(url: str | None) -> str:
    """Return a stable stored media value.

    - Keep http(s)/data/blob URLs unchanged
    - Normalize relative uploads to start with `/`
    """
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith(("http://", "https://", "data:", "blob:")):
        return u
    if u.startswith("//"):
        return f"https:{u}"
    return u if u.startswith("/") else f"/{u}"


def _demo_gender_folder(gender: str | None) -> str | None:
    g = (gender or "").strip().lower()
    if g == "woman":
        return "women"
    if g == "man":
        return "men"
    if g == "female":
        return "women"
    if g == "male":
        return "men"
    return None


def normalize_photo_url(url: str | None, *, demo_profile_gender: str | None = None) -> str:
    u = normalize_media_url(url)
    if not u:
        return ""
    path = u.split("?", 1)[0]
    m = _DEMO_LEGACY_MAIN_RE.match(path)
    if not m:
        return u
    folder = _demo_gender_folder(demo_profile_gender)
    if not folder:
        return u
    prefix, slug, main_file = m.group(1), m.group(2), m.group(3).lower()
    if main_file.endswith(".jpeg"):
        main_file = "main.jpg"
    return f"{prefix}{folder}/{slug}/{main_file}"
