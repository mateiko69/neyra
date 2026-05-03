#!/usr/bin/env python3
"""
NEYRA AI locale sync: English (`frontend/locales/en.json`) is the source of truth.

- Scans `en.json` and target locale files (uk, es, tr, zh).
- Finds missing keys, empty values, or strings that still match English.
- Auto-translates via `app.services.ai_localization.translate_ui_batch` (same rules as `translate_text`).
- Writes updated `frontend/locales/{uk,es,tr,zh}.json`, then runs `sync-public-locales.mjs` (also updates `public/locales/`).

Requires OPENAI_API_KEY in `backend/.env`. Run from repo root:

  python sync_locales.py
  python sync_locales.py --dry-run
  python sync_locales.py --no-qa
  python sync_locales.py --locale-qc
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
LOCALES_DIR = FRONTEND / "locales"
SYNC_NODE = FRONTEND / "scripts" / "sync-public-locales.mjs"


def _setup_path() -> None:
    sys.path.insert(0, str(BACKEND))
    os.environ["PYTHONPATH"] = str(BACKEND)


def _run_sync_public_locales() -> None:
    if not SYNC_NODE.exists():
        print("skip: missing", SYNC_NODE, file=sys.stderr)
        return
    subprocess.run(
        ["node", str(SYNC_NODE)],
        cwd=str(REPO),
        check=True,
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def _needs_fill(en_val: str, loc_val: str | None) -> bool:
    if loc_val is None:
        return True
    s = str(loc_val).strip()
    if not s:
        return True
    return s == (en_val or "").strip()


def main() -> int:
    _setup_path()
    os.chdir(BACKEND)

    ap = argparse.ArgumentParser(description="AI sync for uk/es/tr/zh from en.json")
    ap.add_argument("--dry-run", action="store_true", help="Print keys only; no API calls")
    ap.add_argument("--no-qa", action="store_true", help="Skip second-pass quality review")
    ap.add_argument(
        "--locale-qc",
        action="store_true",
        help="After batch QA, run per-locale check_translation_quality (uk/es/tr/zh; more API calls, tighter style)",
    )
    ap.add_argument("--batch-size", type=int, default=10, help="Keys per API request (default 10)")
    args = ap.parse_args()

    en_path = LOCALES_DIR / "en.json"
    if not en_path.exists():
        print("Missing", en_path, file=sys.stderr)
        return 1

    _run_sync_public_locales()
    en = _read_json(en_path)
    master_keys = list(en.keys())

    from app.services.ai_localization import (
        TARGET_LOCALE_FILES,
        polish_locale_row,
        quality_pass_batch,
        translate_ui_batch,
    )

    locale_maps: dict[str, dict[str, str]] = {}
    for code in TARGET_LOCALE_FILES:
        p = LOCALES_DIR / f"{code}.json"
        locale_maps[code] = _read_json(p) if p.exists() else {}

    stale: set[str] = set()
    for key in master_keys:
        if key.startswith("locale."):
            # Native labels are shared across all bundles (see sync-public-locales.mjs).
            continue
        en_val = en.get(key, "")
        if not isinstance(en_val, str):
            continue
        for code in TARGET_LOCALE_FILES:
            cur = locale_maps[code].get(key)
            if _needs_fill(en_val, cur):
                stale.add(key)
                break

    if not stale:
        print("All target locales are filled (no English-mirror gaps for uk/es/tr/zh).")
        return 0

    ordered_stale = [k for k in master_keys if k in stale]
    print(f"Keys to translate: {len(ordered_stale)}")

    if args.dry_run:
        for k in ordered_stale[:200]:
            print(f"  {k}")
        if len(ordered_stale) > 200:
            print(f"  ... +{len(ordered_stale) - 200} more")
        return 0

    batch_size = max(1, min(args.batch_size, 20))
    for i in range(0, len(ordered_stale), batch_size):
        chunk_keys = ordered_stale[i : i + batch_size]
        batch_en = {k: str(en[k]) for k in chunk_keys if k in en and isinstance(en[k], str)}
        print(f"Translating batch {i // batch_size + 1} ({len(batch_en)} keys)...")
        translated = translate_ui_batch(batch_en)
        if not args.no_qa:
            translated = quality_pass_batch(batch_en, translated)
        if args.locale_qc:
            for k, row in list(translated.items()):
                if k in batch_en:
                    translated[k] = polish_locale_row(batch_en[k], row, i18n_key=k)
        for k, row in translated.items():
            for code in TARGET_LOCALE_FILES:
                locale_maps[code][k] = row[code]

    for code in TARGET_LOCALE_FILES:
        out: dict[str, str] = {}
        for key in master_keys:
            en_val = en.get(key, "")
            if not isinstance(en_val, str):
                continue
            v = locale_maps[code].get(key, en_val)
            if not (v or "").strip():
                v = en_val
                print(f"warn: {code} {key} fell back to English (empty translation)", file=sys.stderr)
            out[key] = v
        _write_json(LOCALES_DIR / f"{code}.json", out)

    _run_sync_public_locales()
    print("Done. Updated", ", ".join(TARGET_LOCALE_FILES), "→ frontend/locales + public/locales")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
