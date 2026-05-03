"""Verify frontend public locale bundles (parity with en.json, no secrets)."""

from __future__ import annotations

import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_public_locales_same_keys_as_english():
    public = _repo_root() / "frontend" / "public" / "locales"
    en_path = public / "en.json"
    assert en_path.exists()
    en = json.loads(en_path.read_text(encoding="utf-8"))
    en_keys = sorted(en.keys())
    assert len(en_keys) > 50
    for path in sorted(public.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert sorted(data.keys()) == en_keys, path.name
        for k, v in data.items():
            assert isinstance(v, str) and v.strip(), f"{path.name} {k}"


def test_public_locales_no_obvious_secrets():
    public = _repo_root() / "frontend" / "public" / "locales"
    bad = ("BEGIN PRIVATE", "api_key", "sk-", "Bearer ")
    for path in public.glob("*.json"):
        raw = path.read_text(encoding="utf-8").lower()
        for b in bad:
            assert b.lower() not in raw, path.name
