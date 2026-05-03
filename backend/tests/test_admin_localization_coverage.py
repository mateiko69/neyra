from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_actor, get_admin_user, get_db
from app.api.v1.endpoints.admin import router
from app.services.localization import coverage as coverage_mod


class DummyAdmin:
    id = 1
    email = "admin@example.com"


class _FakeDb:
    def query(self, model):
        return self


def _client(*, is_admin: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin")
    if is_admin:
        app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
        app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    else:
        from fastapi import HTTPException

        app.dependency_overrides[get_admin_user] = lambda: (_ for _ in ()).throw(HTTPException(status_code=403))
        app.dependency_overrides[get_admin_actor] = lambda: (_ for _ in ()).throw(HTTPException(status_code=403))
    app.dependency_overrides[get_db] = lambda: _FakeDb()
    return TestClient(app)


def test_localization_gemini_translate_forbidden_in_production_without_flag(monkeypatch):
    import app.api.v1.endpoints.admin as adm

    monkeypatch.setattr(adm.settings, "ENV", "production", raising=False)
    monkeypatch.setattr(adm.settings, "LOCALIZATION_DEV_TOOLS_ENABLED", False, raising=False)
    client = _client(is_admin=True)
    res = client.post("/api/v1/admin/localization/gemini/translate", json={"locales": "de"})
    assert res.status_code == 403


def test_localization_coverage_endpoint_shape():
    client = _client(is_admin=True)
    res = client.get("/api/v1/admin/localization/coverage")
    assert res.status_code == 200
    body = res.json()
    assert "locales" in body and isinstance(body["locales"], list)
    assert "generated_at" in body
    assert "summary" in body and isinstance(body["summary"], dict)
    dumped = json.dumps(body)
    # Ensure we never leak real secrets in admin JSON. Note: i18n keys may legitimately
    # contain words like "password" (e.g. auth.common.password), so we avoid generic needles.
    assert "SECRET_KEY" not in dumped
    assert "TELEGRAM_BOT_TOKEN" not in dumped
    assert "ADMIN_BOT_SERVICE_TOKEN" not in dumped
    by_code = {x["code"]: x for x in body["locales"]}
    assert "en" in by_code
    en_row = by_code["en"]
    assert en_row["coverage"] == 100
    assert en_row["total_keys"] > 50
    assert en_row["missing"] == 0
    assert en_row["identical_to_en"] == 0
    assert any(c != "en" and by_code[c]["coverage"] < 100 for c in by_code), "expected at least one locale below 100%"
    for row in body["locales"]:
        assert row["total_keys"] == en_row["total_keys"]
        assert isinstance(row.get("top_missing_keys"), list)
        assert isinstance(row.get("top_identical_to_en_keys"), list)
        assert isinstance(row.get("top_untranslated_keys"), list)


def test_coverage_service_missing_file_no_crash(monkeypatch, tmp_path):
    loc = tmp_path / "frontend" / "locales"
    loc.mkdir(parents=True)
    (loc / "en.json").write_text(json.dumps({"a": "1", "b": "2", "c": "3"}), encoding="utf-8")
    monkeypatch.setattr(coverage_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(coverage_mod, "COVERAGE_LOCALE_CODES", ["en", "ja", "ghost"])
    out = coverage_mod.compute_localization_coverage()
    ghost = next(x for x in out["locales"] if x["code"] == "ghost")
    assert ghost["missing"] == 3
    assert ghost["translated_keys"] == 0
    assert ghost["coverage"] == 0
    en_row = next(x for x in out["locales"] if x["code"] == "en")
    assert en_row["coverage"] == 100


def test_coverage_core_ui_overlay_counts_translations(monkeypatch, tmp_path):
    loc = tmp_path / "frontend" / "locales"
    scripts = tmp_path / "frontend" / "scripts"
    loc.mkdir(parents=True)
    scripts.mkdir(parents=True)
    (loc / "en.json").write_text(
        json.dumps({"nav.discover": "Discover", "only.en": "Hello"}),
        encoding="utf-8",
    )
    (loc / "uk.json").write_text(json.dumps({"only.en": "Hello"}), encoding="utf-8")
    (scripts / "core-ui-translations.json").write_text(
        json.dumps({"uk": {"nav.discover": "Знайомства"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(coverage_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(coverage_mod, "COVERAGE_LOCALE_CODES", ["en", "uk"])
    out = coverage_mod.compute_localization_coverage()
    uk = next(x for x in out["locales"] if x["code"] == "uk")
    assert uk["translated_keys"] >= 1
    assert uk["coverage"] > 0
    assert uk["core_overlay_keys"] == 1


def test_coverage_service_partial_translation(monkeypatch, tmp_path):
    loc = tmp_path / "frontend" / "locales"
    loc.mkdir(parents=True)
    (loc / "en.json").write_text(json.dumps({"a": "one", "b": "two"}), encoding="utf-8")
    (loc / "ja.json").write_text(json.dumps({"a": "いち", "b": "two"}), encoding="utf-8")
    monkeypatch.setattr(coverage_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(coverage_mod, "COVERAGE_LOCALE_CODES", ["en", "ja"])
    out = coverage_mod.compute_localization_coverage()
    ja = next(x for x in out["locales"] if x["code"] == "ja")
    assert ja["translated_keys"] == 1
    assert ja["identical_to_en"] == 1
    assert ja["coverage"] == 50
