"""
Localization coverage metrics from frontend/locales/*.json (read-only, no secrets).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.localization.runtime_agent import EXPECTED_LOCALE_FILES

# en + all supported non-English locale codes (matches frontend/lib/i18n/locales.ts).
COVERAGE_LOCALE_CODES: list[str] = ["en", *sorted(EXPECTED_LOCALE_FILES)]

TOP_KEYS_LIMIT = 20

# Values that look like an i18n key leaked into UI (no spaces, dot-separated).
_RAW_VALUE_LIKE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z0-9_.-]+)+$", re.I)


def _looks_like_raw_i18n_value(val: str) -> bool:
    t = (val or "").strip()
    if len(t) < 8 or len(t) > 96:
        return False
    if " " in t or "{" in t or "}" in t or "/" in t:
        return False
    if t.lower().startswith("http"):
        return False
    return bool(_RAW_VALUE_LIKE_KEY_RE.match(t))


def _repo_root() -> Path:
    """Resolve monorepo root even if cwd/layout differs (Docker, partial checkouts)."""
    here = Path(__file__).resolve()
    for depth in range(3, min(12, len(here.parents))):
        root = here.parents[depth]
        if (root / "frontend" / "locales").is_dir():
            return root
    return here.parents[4]


def _locales_dir() -> Path:
    return _repo_root() / "frontend" / "locales"


def _core_ui_translations_path() -> Path:
    return _repo_root() / "frontend" / "scripts" / "core-ui-translations.json"


def _load_core_ui_overlays() -> dict[str, dict[str, str]]:
    """Per-locale string patches (e.g. core nav labels) merged on top of locales/*.json."""
    path = _core_ui_translations_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for loc, val in raw.items():
        if not isinstance(loc, str) or not isinstance(val, dict):
            continue
        out[loc] = {k: v for k, v in val.items() if isinstance(k, str) and isinstance(v, str)}
    return out


def _load_string_dict(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out


def _round_pct(translated: int, total: int) -> int:
    if total <= 0:
        return 0
    return int(round(100.0 * float(translated) / float(total)))


def compute_localization_coverage(*, locale_codes: list[str] | None = None) -> dict[str, Any]:
    """
    For each locale:
    - Merges `frontend/scripts/core-ui-translations.json` overlay on top of `locales/{code}.json`
      so patched core keys count toward coverage.
    - total_keys: union of en.json keys and keys present in any core-ui locale overlay
    - translated_keys: merged value non-empty and differs from English baseline for that key
    - missing / identical_to_en / empty: as before, evaluated on merged map
    """
    codes = locale_codes if locale_codes is not None else COVERAGE_LOCALE_CODES
    d = _locales_dir()
    en_path = d / "en.json"
    en: dict[str, str] = {}
    if en_path.exists():
        en = _load_string_dict(en_path)

    core_overlays = _load_core_ui_overlays()
    en_overlay = core_overlays.get("en") or {}
    extra_from_core: set[str] = set()
    for loc_code, patch in core_overlays.items():
        if loc_code != "en" and isinstance(patch, dict):
            extra_from_core |= {k for k in patch if isinstance(k, str)}
    extra_from_en_overlay = {k for k in en_overlay if isinstance(k, str)}

    reference_keys = sorted(set(en.keys()) | extra_from_core | extra_from_en_overlay)
    # If en.json is empty/missing but core-ui patches exist, still measure overlay coverage.
    if not reference_keys and core_overlays:
        reference_keys = sorted(
            {k for patch in core_overlays.values() if isinstance(patch, dict) for k in patch if isinstance(k, str)}
        )
        if not en:
            en = {k: v for k, v in en_overlay.items() if isinstance(k, str) and isinstance(v, str)}
    total_keys = len(reference_keys)
    locales_out: list[dict[str, Any]] = []

    for code in codes:
        if code == "en":
            locales_out.append(
                {
                    "code": "en",
                    "coverage": 100 if total_keys > 0 else 0,
                    "coverage_unique_pct": 100 if total_keys > 0 else 0,
                    "coverage_present_pct": 100 if total_keys > 0 else 0,
                    "total_keys": total_keys,
                    "translated_keys": total_keys,
                    "missing": 0,
                    "identical_to_en": 0,
                    "fallback_keys": 0,
                    "empty": 0,
                    "raw_keys": 0,
                    "top_missing_keys": [],
                    "top_identical_to_en_keys": [],
                    "top_raw_key_values": [],
                    "top_untranslated_keys": [],
                    "core_overlay_keys": len(core_overlays.get(code) or {}) if code in core_overlays else 0,
                }
            )
            continue

        loc_file = _load_string_dict(d / f"{code}.json")
        overlay = core_overlays.get(code) or {}
        merged: dict[str, str] = {**loc_file, **overlay}
        missing = 0
        identical = 0
        empty = 0
        translated = 0
        raw_keys = 0
        missing_keys_list: list[str] = []
        identical_keys_list: list[str] = []
        empty_keys_list: list[str] = []
        raw_keys_list: list[str] = []

        for key in reference_keys:
            en_val = en.get(key, "")
            if key not in merged:
                missing += 1
                if len(missing_keys_list) < TOP_KEYS_LIMIT:
                    missing_keys_list.append(key)
                continue
            val = merged[key]
            if not val.strip():
                empty += 1
                if len(empty_keys_list) < TOP_KEYS_LIMIT:
                    empty_keys_list.append(key)
                continue
            if _looks_like_raw_i18n_value(val):
                raw_keys += 1
                if len(raw_keys_list) < TOP_KEYS_LIMIT:
                    raw_keys_list.append(key)
            if val == en_val:
                identical += 1
                if len(identical_keys_list) < TOP_KEYS_LIMIT:
                    identical_keys_list.append(key)
            else:
                translated += 1

        # % keys that differ from English (true translation work).
        cov = _round_pct(translated, total_keys)
        # % keys present with non-empty value (includes intentional English fallback).
        present = total_keys - missing - empty
        cov_present = _round_pct(present, total_keys)
        top_untranslated: list[dict[str, str]] = []
        for k in missing_keys_list:
            if len(top_untranslated) >= TOP_KEYS_LIMIT:
                break
            top_untranslated.append({"key": k, "reason": "missing"})
        for k in identical_keys_list:
            if len(top_untranslated) >= TOP_KEYS_LIMIT:
                break
            top_untranslated.append({"key": k, "reason": "identical_to_en"})
        for k in empty_keys_list:
            if len(top_untranslated) >= TOP_KEYS_LIMIT:
                break
            top_untranslated.append({"key": k, "reason": "empty"})

        locales_out.append(
            {
                "code": code,
                "coverage": cov,
                "coverage_unique_pct": cov,
                "coverage_present_pct": cov_present,
                "total_keys": total_keys,
                "translated_keys": translated,
                "missing": missing,
                "identical_to_en": identical,
                "fallback_keys": identical,
                "empty": empty,
                "raw_keys": raw_keys,
                "top_missing_keys": missing_keys_list,
                "top_identical_to_en_keys": identical_keys_list,
                "top_raw_key_values": raw_keys_list,
                "top_untranslated_keys": top_untranslated,
                "core_overlay_keys": len(overlay),
            }
        )

    non_en = [x for x in locales_out if str(x.get("code") or "") != "en"]
    summary = {
        "missing_keys_total": int(sum(int(x.get("missing") or 0) for x in non_en)),
        "empty_keys_total": int(sum(int(x.get("empty") or 0) for x in non_en)),
        "raw_value_leaks_total": int(sum(int(x.get("raw_keys") or 0) for x in non_en)),
        "en_fallback_keys_total": int(sum(int(x.get("identical_to_en") or 0) for x in non_en)),
        "unique_translated_keys_total": int(sum(int(x.get("translated_keys") or 0) for x in non_en)),
    }

    return {
        "locales": locales_out,
        "summary": summary,
        "generated_at": datetime.now(UTC).isoformat(),
        "reference_key_count": total_keys,
        "core_ui_overlay_locales": sorted(core_overlays.keys()),
    }
