from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings


def _default_report_path() -> Path:
    # Default to repo-root /reports/localization_report.json when running from backend/.
    # In containers, this can be overridden by LOCALIZATION_REPORT_PATH.
    base = Path(__file__).resolve()
    repo_root = base.parents[4]  # backend/app/services/localization/report.py -> repo root
    return repo_root / "reports" / "localization_report.json"


def load_localization_report() -> dict:
    raw = str(getattr(settings, "LOCALIZATION_REPORT_PATH", "") or "").strip()
    path = Path(raw) if raw else _default_report_path()
    if not path.exists():
        return {"generated_at": None, "summary": {}, "missing": True, "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("path", str(path))
            return data
    except Exception:
        pass
    return {"generated_at": None, "summary": {}, "missing": True, "path": str(path), "error": "invalid_json"}

