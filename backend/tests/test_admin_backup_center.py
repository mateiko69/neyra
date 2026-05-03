from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor, get_db
from app.api.v1.endpoints import admin as admin_mod
from app.core.config import settings


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client(db=None) -> TestClient:
    app = FastAPI()
    app.include_router(admin_mod.router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    if db is not None:
        app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _patch_backup_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    db_file = tmp_path / "neyra.sqlite"
    db_file.write_bytes(b"current-db")
    monkeypatch.setattr(admin_mod, "_backup_dir", lambda: backup_dir.resolve())
    monkeypatch.setattr(admin_mod, "_sqlite_db_path", lambda: db_file.resolve())
    monkeypatch.setattr(settings, "ENV", "development")
    return backup_dir, db_file


def test_backups_list_shape(monkeypatch, tmp_path):
    backup_dir, _db_file = _patch_backup_paths(monkeypatch, tmp_path)
    (backup_dir / "neyra_backup_20260426_120000.sqlite").write_bytes(b"backup")
    res = _client(db=object()).get("/api/v1/admin/backups")
    assert res.status_code == 200
    payload = res.json()
    assert len(payload) == 1
    assert set(payload[0].keys()) == {"filename", "created_at", "size_bytes", "type", "environment"}
    assert payload[0]["filename"] == "neyra_backup_20260426_120000.sqlite"
    assert payload[0]["type"] == "sqlite"
    raw = res.text.lower()
    assert "api_key" not in raw
    assert "password" not in raw
    assert "secret" not in raw


def test_backup_create_requires_confirm(monkeypatch, tmp_path):
    _patch_backup_paths(monkeypatch, tmp_path)
    res = _client(db=object()).post("/api/v1/admin/backups/create", json={})
    assert res.status_code == 400
    assert res.json().get("detail", {}).get("error") == "confirm_required"


def test_backup_create_success(monkeypatch, tmp_path):
    backup_dir, _db_file = _patch_backup_paths(monkeypatch, tmp_path)
    res = _client(db=object()).post("/api/v1/admin/backups/create", json={"confirm": True})
    assert res.status_code == 200
    payload = res.json()
    assert payload.get("success") is True
    assert set(payload.keys()) == {"success", "filename", "size", "size_bytes", "duration", "duration_seconds", "created_at"}
    assert payload["filename"].startswith("neyra_backup_")
    assert int(payload["size"]) == int(payload["size_bytes"]) > 0
    assert isinstance(payload["duration_seconds"], (int, float))
    assert (backup_dir / payload["filename"]).exists()


def test_backup_create_postgresql_writes_sql_file(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://postgres:secret@db:5432/neyra")
    monkeypatch.setattr(admin_mod, "_backup_dir", lambda: backup_dir.resolve())

    def fake_run(cmd, env=None, capture_output=True, text=True, timeout=None):
        out_path = Path(cmd[-1])
        out_path.write_text("-- NEYRA test dump\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch.object(admin_mod.shutil, "which", return_value="/usr/bin/pg_dump"):
        with patch.object(admin_mod.subprocess, "run", side_effect=fake_run):
            res = _client(db=object()).post("/api/v1/admin/backups/create", json={"confirm": True})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload.get("success") is True
    assert str(payload.get("filename") or "").endswith(".sql")
    assert int(payload.get("size") or 0) > 0
    assert (backup_dir / payload["filename"]).exists()


def test_backup_create_postgresql_fails_when_pg_dump_errors(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://postgres:postgres@localhost:5434/neyra")
    monkeypatch.setattr(admin_mod, "_backup_dir", lambda: backup_dir.resolve())

    def failing_run(cmd, env=None, capture_output=True, text=True, timeout=None):
        return subprocess.CompletedProcess(cmd, 1, "", "could not connect to server")

    with patch.object(admin_mod.shutil, "which", return_value="/usr/bin/pg_dump"):
        with patch.object(admin_mod.subprocess, "run", side_effect=failing_run):
            res = _client(db=object()).post("/api/v1/admin/backups/create", json={"confirm": True})
    assert res.status_code == 500
    detail = res.json().get("detail", {})
    assert detail.get("error") == "pg_dump_failed"
    assert "connect" in str(detail.get("detail", "")).lower()


def test_backup_create_postgresql_fails_when_pg_dump_missing(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://postgres:postgres@localhost:5434/neyra")
    monkeypatch.setattr(admin_mod, "_backup_dir", lambda: backup_dir.resolve())
    with patch.object(admin_mod.shutil, "which", return_value=""):
        res = _client(db=object()).post("/api/v1/admin/backups/create", json={"confirm": True})
    assert res.status_code == 500
    assert res.json().get("detail", {}).get("error") == "pg_dump_not_found"


def test_backups_list_includes_sql_dumps(monkeypatch, tmp_path):
    backup_dir, _db_file = _patch_backup_paths(monkeypatch, tmp_path)
    (backup_dir / "neyra_backup_20260426_120000.sqlite").write_bytes(b"x")
    (backup_dir / "neyra_backup_20260426_120001.sql").write_text("-- dump", encoding="utf-8")
    res = _client(db=object()).get("/api/v1/admin/backups")
    assert res.status_code == 200
    names = {row["filename"] for row in res.json()}
    assert names == {"neyra_backup_20260426_120000.sqlite", "neyra_backup_20260426_120001.sql"}
    types = {row["filename"]: row["type"] for row in res.json()}
    assert types["neyra_backup_20260426_120001.sql"] == "postgresql"


def test_backup_restore_rejects_postgresql_database(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://postgres:postgres@localhost:5434/neyra")
    monkeypatch.setattr(admin_mod, "_backup_dir", lambda: backup_dir.resolve())
    b = backup_dir / "neyra_backup_x.sql"
    b.write_text("-- x", encoding="utf-8")
    res = _client(db=object()).post(
        f"/api/v1/admin/backups/{b.name}/restore",
        json={"confirm": True, "confirm_phrase": admin_mod.BACKUP_RESTORE_PHRASE},
    )
    assert res.status_code == 400
    assert res.json().get("detail", {}).get("error") == "not_supported"


def test_backup_create_allowed_in_production_sqlite(monkeypatch, tmp_path):
    """Backup create must not be blocked by ENV=production (restore stays blocked)."""
    backup_dir, _db_file = _patch_backup_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "ENV", "production")
    res = _client(db=object()).post("/api/v1/admin/backups/create", json={"confirm": True})
    assert res.status_code == 200
    payload = res.json()
    assert payload.get("success") is True
    assert (backup_dir / payload["filename"]).exists()


def test_backup_restore_requires_confirm_phrase(monkeypatch, tmp_path):
    backup_dir, db_file = _patch_backup_paths(monkeypatch, tmp_path)
    backup = backup_dir / "neyra_backup_20260426_120000.sqlite"
    backup.write_bytes(b"backup-db")
    res = _client(db=object()).post(
        f"/api/v1/admin/backups/{backup.name}/restore",
        json={"confirm": True, "confirm_phrase": "WRONG"},
    )
    assert res.status_code == 400
    assert res.json().get("detail", {}).get("error") == "restore_phrase_required"
    assert db_file.read_bytes() == b"current-db"


def test_backup_restore_blocked_in_production(monkeypatch, tmp_path):
    backup_dir, _db_file = _patch_backup_paths(monkeypatch, tmp_path)
    backup = backup_dir / "neyra_backup_20260426_120000.sqlite"
    backup.write_bytes(b"backup-db")
    monkeypatch.setattr(settings, "ENV", "production")
    res = _client(db=object()).post(
        f"/api/v1/admin/backups/{backup.name}/restore",
        json={"confirm": True, "confirm_phrase": admin_mod.BACKUP_RESTORE_PHRASE},
    )
    assert res.status_code == 403


def test_backup_filename_validation_blocks_traversal(monkeypatch, tmp_path):
    _patch_backup_paths(monkeypatch, tmp_path)
    res = _client(db=object()).get("/api/v1/admin/backups/..%5Csecret.sqlite/download")
    assert res.status_code == 400
    assert res.json().get("detail", {}).get("error") == "invalid_filename"


def test_backup_restore_success_only_with_phrase(monkeypatch, tmp_path):
    backup_dir, db_file = _patch_backup_paths(monkeypatch, tmp_path)
    backup = backup_dir / "neyra_backup_20260426_120000.sqlite"
    backup.write_bytes(b"backup-db")
    res = _client(db=object()).post(
        f"/api/v1/admin/backups/{backup.name}/restore",
        json={"confirm": True, "confirm_phrase": admin_mod.BACKUP_RESTORE_PHRASE},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["restored"] is True
    assert payload["filename"] == backup.name
    assert db_file.read_bytes() == b"backup-db"
