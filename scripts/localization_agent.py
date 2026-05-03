from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]

SUPPORTED_LOCALES = [
    "en",
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
]


REPORT_DIR = REPO_ROOT / "reports"
REPORT_JSON = REPORT_DIR / "localization_report.json"
REPORT_LOG = REPORT_DIR / "localization_agent.log"


HARD_CODED_TEXT_RE = re.compile(r">([^<{][^<]{2,120})<")
MIXED_KYIV_RE = re.compile(r"\b(в|у)\s+Kyiv\b|\bin\s+Київ\b")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _log(line: str) -> None:
    _safe_mkdir(REPORT_DIR)
    REPORT_LOG.write_text((REPORT_LOG.read_text(encoding="utf-8") if REPORT_LOG.exists() else "") + line + "\n", encoding="utf-8")


def _backup_file(path: Path) -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{ts}")
    shutil.copy2(path, backup)
    return backup


def scan_locale_files(frontend_dir: Path) -> dict:
    locales_dir = frontend_dir / "locales"
    existing = {p.stem: p for p in locales_dir.glob("*.json")}
    missing_files = [loc for loc in SUPPORTED_LOCALES if loc not in existing]

    en_path = existing.get("en")
    en_keys: set[str] = set()
    if en_path and en_path.exists():
        try:
            en_json = json.loads(_read_text(en_path))
            if isinstance(en_json, dict):
                en_keys = set(en_json.keys())
        except Exception:
            pass

    missing_keys: dict[str, list[str]] = {}
    for loc, p in existing.items():
        if loc not in SUPPORTED_LOCALES:
            continue
        try:
            data = json.loads(_read_text(p))
        except Exception:
            missing_keys[loc] = sorted(list(en_keys))
            continue
        if not isinstance(data, dict):
            missing_keys[loc] = sorted(list(en_keys))
            continue
        keys = set(data.keys())
        missing = sorted(list(en_keys - keys))
        if missing:
            missing_keys[loc] = missing

    return {
        "locales_dir": str(locales_dir),
        "missing_locale_files": missing_files,
        "missing_translation_keys": missing_keys,
        "en_key_count": len(en_keys),
    }


def scan_hardcoded_strings(paths: Iterable[Path]) -> list[dict]:
    findings: list[dict] = []
    for p in paths:
        try:
            text = _read_text(p)
        except Exception:
            continue
        if "node_modules" in p.parts or ".next" in p.parts:
            continue
        for m in HARD_CODED_TEXT_RE.finditer(text):
            raw = m.group(1).strip()
            if not raw or raw.startswith("{") or raw.startswith("["):
                continue
            if "MISSING:" in raw:
                continue
            # Skip if it's likely just punctuation / arrows.
            if len(re.sub(r"[\W_]+", "", raw)) < 3:
                continue
            findings.append(
                {
                    "file": str(p.relative_to(REPO_ROOT)),
                    "snippet": raw[:120],
                }
            )
            if len(findings) >= 300:
                return findings
    return findings


def scan_prompt_issues(backend_dir: Path) -> list[dict]:
    prompt_dir = backend_dir / "app" / "services" / "ai" / "prompts"
    findings: list[dict] = []
    for p in prompt_dir.glob("*.txt"):
        text = _read_text(p)
        if MIXED_KYIV_RE.search(text):
            findings.append({"file": str(p.relative_to(REPO_ROOT)), "type": "mixed_location_phrase", "rule": "no 'в Kyiv' / 'in Київ'"})
    return findings


def build_report() -> dict:
    frontend_dir = REPO_ROOT / "frontend"
    backend_dir = REPO_ROOT / "backend"

    tsx_files = list(frontend_dir.rglob("*.tsx")) + list(frontend_dir.rglob("*.ts")) + list(frontend_dir.rglob("*.jsx")) + list(frontend_dir.rglob("*.js"))
    py_files = list(backend_dir.rglob("*.py"))

    locales = scan_locale_files(frontend_dir)
    hardcoded = scan_hardcoded_strings([p for p in tsx_files if p.is_file()])
    prompt_issues = scan_prompt_issues(backend_dir)

    return {
        "generated_at": _now_iso(),
        "supported_locales": SUPPORTED_LOCALES,
        "summary": {
            "missing_locale_files": len(locales["missing_locale_files"]),
            "locales_missing_keys_locales": len(locales["missing_translation_keys"]),
            "hardcoded_strings": len(hardcoded),
            "prompt_issues": len(prompt_issues),
        },
        "locales": locales,
        "hardcoded_strings": hardcoded,
        "prompt_issues": prompt_issues,
        "notes": [
            "Scan is heuristic and conservative; fix mode only applies high-confidence changes.",
        ],
    }


def write_report(report: dict) -> None:
    _safe_mkdir(REPORT_DIR)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fix_missing_locale_files(report: dict) -> list[dict]:
    """High-confidence safe fix: create missing locale JSON files as empty objects."""
    frontend_locales_dir = REPO_ROOT / "frontend" / "locales"
    _safe_mkdir(frontend_locales_dir)
    changes: list[dict] = []
    for loc in report.get("locales", {}).get("missing_locale_files", []):
        # Keep filesystem-friendly locale filenames.
        name = f"{loc}.json"
        path = frontend_locales_dir / name
        if path.exists():
            continue
        path.write_text("{}\n", encoding="utf-8")
        changes.append({"type": "create_locale_file", "file": str(path.relative_to(REPO_ROOT))})
        _log(f"[fix] created {path}")
    return changes


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="NEYRA Localization & Geo AI Agent (offline scan/fix/report).")
    ap.add_argument("--scan", action="store_true", help="Scan and write JSON report (no modifications).")
    ap.add_argument("--report", action="store_true", help="Alias for --scan.")
    ap.add_argument("--fix", action="store_true", help="Apply safe fixes with backups (high confidence only).")
    args = ap.parse_args(argv)

    if not (args.scan or args.report or args.fix):
        ap.print_help()
        return 2

    report = build_report()
    write_report(report)
    _log(f"[report] wrote {REPORT_JSON} at {report['generated_at']}")

    if args.fix:
        changes = []
        changes.extend(fix_missing_locale_files(report))
        report2 = build_report()
        report2["autofix"] = {"applied_at": _now_iso(), "changes": changes}
        write_report(report2)
        _log(f"[fix] applied {len(changes)} changes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

