from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.deps import get_db
from app.api.v1.endpoints.ai import router
from app.db.base import Base


class DummyUser:
    id = 1


def _build_client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)

    def _get_db_override():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai")
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    app.dependency_overrides[get_db] = _get_db_override
    return TestClient(app)


def test_opener_endpoint_returns_three_typed_suggestions():
    client = _build_client()

    response = client.post(
        "/api/v1/ai/opener",
        json={
            "match_name": "Anna",
            "bio": "Люблю подорожі і каву",
            "interests": ["travel", "coffee"],
            "city": "Київ",
            "tags": ["digital nomad"],
            "style": "playful",
            "locale": "uk",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["suggestions"]) == 3
    assert len(payload["items"]) == 3
    types = [x["type"] for x in payload["items"]]
    assert types == ["safe", "flirty", "smart"]
    assert payload.get("recommended_index") in {0, 1, 2}
    assert all(isinstance(item, str) and item.strip() for item in payload["suggestions"])
    assert all("?" in item or " чи " in item.lower() or " або " in item.lower() for item in payload["suggestions"])


def test_opener_endpoint_falls_back_to_forced_choice_when_empty_profile():
    client = _build_client()

    response = client.post(
        "/api/v1/ai/opener",
        json={
            "match_name": "Anna",
            "bio": "",
            "interests": [],
            "locale": "uk",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["suggestions"]) == 3
    assert len(payload["items"]) == 3
    assert [x["type"] for x in payload["items"]] == ["safe", "flirty", "smart"]
    assert all(item.strip() for item in payload["suggestions"])
    first = payload["suggestions"][0].lower()
    assert "?" in first or " or " in first or " чи " in first or " або " in first


def test_opener_endpoint_filters_risky_inputs_and_still_returns_three():
    client = _build_client()

    response = client.post(
        "/api/v1/ai/opener",
        json={
            "match_name": "Anna",
            "bio": "",
            "interests": ["hookup", "bed"],
            "style": "confident",
            "locale": "uk",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["suggestions"]) == 3
    assert len(payload["items"]) == 3
    assert all("hookup" not in item.lower() for item in payload["suggestions"])
    assert all("bed" not in item.lower() for item in payload["suggestions"])
