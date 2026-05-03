from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.premium import PREMIUM_FEATURES, has_premium_access

def test_premium_features_defined():
    assert "unlimited_ai_suggestions" in PREMIUM_FEATURES


class _FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._row


class _FakeDB:
    def __init__(self, row):
        self._row = row

    def query(self, _model):
        return _FakeQuery(self._row)


def test_premium_plus_counts_as_premium_access(monkeypatch):
    monkeypatch.setattr("app.services.premium.settings.ENABLE_PREMIUM_FEATURES", True)
    sub = SimpleNamespace(
        user_id=1,
        status="active",
        plan_code="premium_plus",
        start_date=datetime.now(UTC) - timedelta(days=1),
        end_date=datetime.now(UTC) + timedelta(days=30),
    )
    assert has_premium_access(_FakeDB(sub), 1, "unlimited_ai_suggestions") is True
