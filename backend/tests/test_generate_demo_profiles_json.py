from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_GEN_PATH = _BACKEND_ROOT / "scripts" / "generate_demo_profiles_json.py"


def _load_generate_module():
    spec = importlib.util.spec_from_file_location("generate_demo_profiles_json", _GEN_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load_generate_module()


def test_detect_gender_from_path_women_men_only() -> None:
    assert gen.detect_gender_from_path("women/demo_001/main.jpg") == "woman"
    assert gen.detect_gender_from_path("men/demo_101/main.jpg") == "man"
    assert gen.detect_gender_from_path(r"demo-profiles\men\demo_020\main.jpg") == "man"


def test_detect_gender_flat_defaults_woman() -> None:
    assert gen.detect_gender_from_path("demo_001/main.jpg") == "woman"


def test_scan_skips_without_main_jpg(tmp_path: Path) -> None:
    root = tmp_path / "demo-profiles"
    (root / "women" / "demo_001").mkdir(parents=True)
    (root / "women" / "demo_001" / "main.jpg").write_bytes(b"x")
    (root / "women" / "demo_002").mkdir(parents=True)  # no main.jpg — ignored (not scanned)
    (root / "bad_name").mkdir(parents=True)
    (root / "bad_name" / "main.jpg").write_bytes(b"x")

    entries, skipped = gen.scan_demo_folders(root)
    assert [e["id"] for e in entries] == ["woman_demo_001"]
    reasons = {name.replace("\\", "/"): r for name, r in skipped}
    assert reasons.get("bad_name/main.jpg") == "parent_not_demo_digits"


def test_scan_numeric_order_nested(tmp_path: Path) -> None:
    root = tmp_path / "demo-profiles"
    for fid in ("demo_010", "demo_002", "demo_001"):
        d = root / "women" / fid
        d.mkdir(parents=True)
        (d / "main.jpg").write_bytes(b"1")

    entries, _ = gen.scan_demo_folders(root)
    assert [e["id"] for e in entries] == ["woman_demo_001", "woman_demo_002", "woman_demo_010"]


def test_scan_allows_same_folder_name_women_and_men(tmp_path: Path) -> None:
    root = tmp_path / "demo-profiles"
    (root / "women" / "demo_001").mkdir(parents=True)
    (root / "women" / "demo_001" / "main.jpg").write_bytes(b"1")
    (root / "men" / "demo_001").mkdir(parents=True)
    (root / "men" / "demo_001" / "main.jpg").write_bytes(b"1")

    entries, _ = gen.scan_demo_folders(root)
    ids = {e["id"] for e in entries}
    assert ids == {"woman_demo_001", "man_demo_001"}


def test_build_profiles_gender_from_path_not_index(tmp_path: Path) -> None:
    root = tmp_path / "demo-profiles"
    (root / "women" / "demo_001").mkdir(parents=True)
    (root / "women" / "demo_001" / "main.jpg").write_bytes(b"1")
    (root / "men" / "demo_020").mkdir(parents=True)
    (root / "men" / "demo_020" / "main.jpg").write_bytes(b"1")

    entries, _ = gen.scan_demo_folders(root)
    profiles = gen.build_profiles_from_scan_entries(entries)
    assert len(profiles) == 2
    by_id = {p["id"]: p for p in profiles}
    w = by_id["woman_demo_001"]
    m = by_id["man_demo_020"]
    assert w["gender_profile"] == "woman"
    assert w["gender"] == "woman"
    assert w["photo_main_path"] == "/demo-profiles/women/demo_001/main.jpg"
    assert 18 <= int(w["age"]) <= 30
    assert m["gender_profile"] == "man"
    assert m["gender"] == "man"
    assert m["photo_main_path"] == "/demo-profiles/men/demo_020/main.jpg"
    assert 20 <= int(m["age"]) <= 35


REQUIRED_TOP_LEVEL = (
    "id",
    "gender",
    "display_name",
    "age",
    "city",
    "gender_profile",
    "interested_in",
    "relationship_goal",
    "interests",
    "lifestyle_tags",
    "bio",
    "photo_main_path",
    "demo_personality",
)


def test_write_json_atomic_roundtrip(tmp_path: Path) -> None:
    out = tmp_path / "demo_profiles.json"
    payload = {"version": 5, "profiles": []}
    gen.write_json_atomic(out, payload)
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 5
    assert data["profiles"] == []


def test_demo_profiles_json_path_contains_frontend_segment() -> None:
    from app.services.demo_mode import demo_profiles_json_path

    p = demo_profiles_json_path()
    parts = p.parts
    assert "frontend" in parts
    assert "public" in parts
    assert "demo-profiles" in parts
    assert p.name == "demo_profiles.json"


def test_end_to_end_catalog_shape(tmp_path: Path) -> None:
    demo_root = tmp_path / "demo-profiles"
    (demo_root / "women" / "demo_005").mkdir(parents=True)
    (demo_root / "women" / "demo_005" / "main.jpg").write_bytes(b"jpg")
    out = tmp_path / "out.json"

    entries, _ = gen.scan_demo_folders(demo_root)
    profs = gen.build_profiles_from_scan_entries(entries)
    gen.write_json_atomic(out, {"version": 5, "profiles": profs})

    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["version"] == 5
    assert len(raw["profiles"]) == 1
    row = raw["profiles"][0]
    for k in REQUIRED_TOP_LEVEL:
        assert k in row, f"missing {k}"
    assert row["id"] == "woman_demo_005"
    assert row["gender_profile"] == "woman"
    assert row["photo_main_path"] == "/demo-profiles/women/demo_005/main.jpg"
    assert DEMO_DISCLAIMER_FRAGMENT in row["bio"]


DEMO_DISCLAIMER_FRAGMENT = "Demo profile 🤖"
