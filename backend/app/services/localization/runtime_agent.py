"""
Runtime localization quality scan + safe fix (no user data, no secrets).

Scans frontend/locales/*.json for structural issues. Safe fix only fills missing keys
from English and replaces obvious raw i18n-key placeholders — never deletes keys.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Must match frontend/lib/i18n/locales.ts SUPPORTED_LOCALE_CODES (excluding en for optional files).
EXPECTED_LOCALE_FILES = frozenset(
    {
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
    }
)

RAW_KEY_VALUE_RE = re.compile(
    r"(^locale\.[a-z]{2}(?:-[A-Z]{2})?$)|" r"(^locale\.[a-z0-9_.-]+$)|" r"(\b[a-z][a-z0-9_]{1,20}\.[a-z][a-z0-9_.]{2,40}$)",
    re.IGNORECASE,
)

# Ukrainian display: Latin exonyms that should be Cyrillic in uk locale values (high-confidence fix hints).
UK_CITY_LATIN_IN_UK = {
    "Kyiv": "Київ",
    "Kiev": "Київ",
    "Lviv": "Львів",
    "Kharkiv": "Харків",
    "Odesa": "Одеса",
    "Odessa": "Одеса",
    "Dnipro": "Дніпро",
    "Chernivtsi": "Чернівці",
    "Ivano-Frankivsk": "Івано-Франківськ",
    "Verkhovyna": "Верховина",
}


def _repo_root_from_here() -> Path:
    # backend/app/services/localization/runtime_agent.py -> parents[4] = repo root
    return Path(__file__).resolve().parents[4]


def _locales_dir() -> Path:
    return _repo_root_from_here() / "frontend" / "locales"


def _load_json(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out


def _looks_like_raw_key_token(value: str) -> bool:
    s = (value or "").strip()
    if not s:
        return False
    if s.startswith("locale.") and len(s) < 80:
        return True
    if RAW_KEY_VALUE_RE.search(s):
        return True
    return False


def _scan_mixed_with_en(en: dict[str, str], loc: str, data: dict[str, str]) -> list[dict[str, Any]]:
    if loc not in {"uk", "ru"}:
        return []
    issues: list[dict[str, Any]] = []
    for key, val in data.items():
        if key not in en:
            continue
        ev = en[key]
        if val != ev:
            continue
        if len(val) < 20:
            continue
        # Mostly ASCII prose likely still English in a Cyrillic locale file.
        if loc == "uk" and val.isascii() and any(c.isalpha() for c in val):
            issues.append(
                {
                    "type": "mixed_language_strings",
                    "severity": "warning",
                    "locale_file": f"{loc}.json",
                    "key": key,
                    "hint": "value_identical_to_en_long_ascii",
                }
            )
    return issues


def _scan_bad_city_uk(data: dict[str, str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for key, val in data.items():
        for latin, cyr in UK_CITY_LATIN_IN_UK.items():
            if latin in val and cyr not in val:
                issues.append(
                    {
                        "type": "bad_city_cases",
                        "severity": "warning",
                        "locale_file": "uk.json",
                        "key": key,
                        "hint": "latin_city_in_uk",
                        "detail": {"latin": latin, "expected_cyrillic": cyr},
                    }
                )
    return issues


def run_localization_agent_scan() -> dict[str, Any]:
    d = _locales_dir()
    issues: list[dict[str, Any]] = []
    if not d.exists():
        return {
            "status": "fail",
            "summary": {
                "missing_keys": 0,
                "raw_keys_visible": 0,
                "mixed_language_strings": 0,
                "bad_city_cases": 0,
                "unsupported_locales": 1,
            },
            "issues": [{"type": "config", "severity": "fail", "message": "frontend/locales not found"}],
        }

    en_path = d / "en.json"
    if not en_path.exists():
        return {
            "status": "fail",
            "summary": {
                "missing_keys": 0,
                "raw_keys_visible": 0,
                "mixed_language_strings": 0,
                "bad_city_cases": 0,
                "unsupported_locales": 0,
            },
            "issues": [{"type": "config", "severity": "fail", "message": "en.json missing"}],
        }

    en = _load_json(en_path)
    en_keys = set(en.keys())
    missing_total = 0
    raw_total = 0
    mixed_total = 0
    bad_city_total = 0

    present_files: set[str] = set()
    for path in sorted(d.glob("*.json")):
        name = path.name
        if name == "en.json":
            continue
        loc = path.stem
        present_files.add(loc)
        if loc not in EXPECTED_LOCALE_FILES and loc not in {"en"}:
            issues.append(
                {
                    "type": "unsupported_locales",
                    "severity": "warning",
                    "message": "unexpected_locale_file",
                    "locale_file": name,
                }
            )

        data = _load_json(path)
        missing = en_keys - set(data.keys())
        missing_total += len(missing)
        for k in sorted(missing)[:200]:
            issues.append(
                {
                    "type": "missing_keys",
                    "severity": "warning",
                    "locale_file": name,
                    "key": k,
                }
            )
        if len(missing) > 200:
            issues.append(
                {
                    "type": "missing_keys",
                    "severity": "warning",
                    "locale_file": name,
                    "message": f"truncated_list_total_missing={len(missing)}",
                }
            )

        for key, val in data.items():
            if _looks_like_raw_key_token(val):
                raw_total += 1
                issues.append(
                    {
                        "type": "raw_keys_visible",
                        "severity": "fail",
                        "locale_file": name,
                        "key": key,
                        "hint": "value_looks_like_i18n_key",
                    }
                )

        mixed = _scan_mixed_with_en(en, loc, data)
        mixed_total += len(mixed)
        issues.extend(mixed)

        if loc == "uk":
            bc = _scan_bad_city_uk(data)
            bad_city_total += len(bc)
            issues.extend(bc)

    # Only unexpected locale files on disk (not "missing expected" — optional locales ship when ready).
    unexpected_on_disk = sorted(present_files - EXPECTED_LOCALE_FILES)
    unsupported = len(unexpected_on_disk)
    for loc in unexpected_on_disk:
        issues.append(
            {
                "type": "unsupported_locales",
                "severity": "warning",
                "message": "unexpected_locale_file",
                "locale_file": f"{loc}.json",
            }
        )

    summary = {
        "missing_keys": int(missing_total),
        "raw_keys_visible": int(raw_total),
        "mixed_language_strings": int(mixed_total),
        "bad_city_cases": int(bad_city_total),
        "unsupported_locales": int(unsupported),
    }

    status = "pass"
    if summary["raw_keys_visible"] > 0 or summary["missing_keys"] > 500:
        status = "fail"
    elif summary["missing_keys"] > 0 or summary["unsupported_locales"] > 0 or summary["bad_city_cases"] > 0:
        status = "warning"

    return {
        "status": status,
        "summary": summary,
        "issues": issues,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _write_report(repo: Path, payload: dict[str, Any]) -> Path:
    reports = repo / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = reports / f"localization_agent_safe_fix_{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def apply_localization_agent_safe_fix(*, confirm: bool, mode: str) -> dict[str, Any]:
    if not confirm:
        return {"ok": False, "error": "confirm_required"}
    if (mode or "").strip().lower() != "safe":
        return {"ok": False, "error": "unsupported_mode"}

    scan_before = run_localization_agent_scan()
    d = _locales_dir()
    en_path = d / "en.json"
    en = _load_json(en_path)
    repo = _repo_root_from_here()

    diff: dict[str, Any] = {"files": {}, "notes": []}

    for path in sorted(d.glob("*.json")):
        if path.name == "en.json":
            continue
        loc = path.stem
        if loc not in EXPECTED_LOCALE_FILES:
            continue
        data = _load_json(path)
        original = dict(data)
        changed = False

        # Fill missing keys from English (never delete).
        for k, v in en.items():
            if k not in data:
                data[k] = v
                changed = True

        # Replace obvious raw placeholder values with English string for that key.
        for k in list(data.keys()):
            val = data.get(k, "")
            if not _looks_like_raw_key_token(val):
                continue
            if k in en and en[k] and not _looks_like_raw_key_token(en[k]):
                data[k] = en[k]
                changed = True

        # High-confidence Ukrainian city Latin → Cyrillic in values (substring replace).
        if loc == "uk":
            for k, val in list(data.items()):
                new_val = val
                for latin, cyr in UK_CITY_LATIN_IN_UK.items():
                    if latin in new_val and cyr not in new_val:
                        new_val = new_val.replace(latin, cyr)
                if new_val != val:
                    data[k] = new_val
                    changed = True

        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            diff["files"][path.name] = {
                "keys_added": sorted(set(data.keys()) - set(original.keys())),
                "keys_touched": sorted([k for k in data if data[k] != original.get(k)]),
            }

    report_path = _write_report(
        repo,
        {
            "mode": "safe",
            "scan_before": scan_before,
            "diff": diff,
            "finished_at": datetime.now(UTC).isoformat(),
        },
    )
    scan_after = run_localization_agent_scan()
    return {
        "ok": True,
        "report_path": str(report_path),
        "scan_before": scan_before,
        "scan_after": scan_after,
        "diff_summary": {k: len(v.get("keys_touched", [])) for k, v in diff["files"].items()},
    }
