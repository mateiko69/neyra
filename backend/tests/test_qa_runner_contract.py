import json


def _parse_runner_text(text: str):
    try:
        return json.loads(text or "")
    except Exception:
        return None


def test_qa_runner_contract_valid_json_parses():
    payload = {
        "ok": True,
        "browser_used": True,
        "auth_used": True,
        "score": 100,
        "runtime_seconds": 12.3,
        "pages_visited": 7,
        "buttons_clicked": 9,
        "screenshots": ["test-results/x.png"],
        "issues": [],
    }
    parsed = _parse_runner_text(json.dumps(payload))
    assert isinstance(parsed, dict)
    assert parsed.get("ok") is True
    assert parsed.get("browser_used") is True
    assert isinstance(parsed.get("issues"), list)


def test_qa_runner_contract_invalid_json_is_none():
    parsed = _parse_runner_text("NOT JSON\nlog line\n")
    assert parsed is None

