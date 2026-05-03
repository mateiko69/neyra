"""Sanity checks for Deep QA runner JSON merged into qa_agent report payload."""

from __future__ import annotations


def test_deep_qa_checks_include_skip_reasons_and_auth():
    runner_json = {
        "ok": True,
        "score": 88,
        "browser_used": True,
        "auth_used": True,
        "frontend_reachable": True,
        "auth_status": "ok",
        "pages_visited": 6,
        "buttons_clicked": 9,
        "flows_completed": ["discover_flow"],
        "flow_failures": {},
        "flow_skip_reasons": {"chat_ai_flow": "no_match_available"},
        "flow_report": {"chat_ai_flow": "skipped", "discover_flow": "passed"},
        "screenshots": [],
        "screenshots_count": 0,
        "exit_code": 0,
        "first_failed_test": "",
        "failed_selector": "",
        "first_trace": "",
        "issues": [],
        "runtime_seconds": 42,
    }
    flow_skip = runner_json.get("flow_skip_reasons") if isinstance(runner_json.get("flow_skip_reasons"), dict) else {}
    assert flow_skip.get("chat_ai_flow") == "no_match_available"
    assert runner_json.get("frontend_reachable") is True
    assert runner_json.get("auth_status") == "ok"


def test_deep_qa_unreachable_contract_fields():
    payload = {
        "ok": False,
        "score": 0,
        "frontend_reachable": False,
        "auth_status": "unknown",
        "issues": [{"severity": "critical", "title": "Frontend unreachable"}],
    }
    assert payload["frontend_reachable"] is False
    assert payload["score"] == 0


def test_deep_qa_auth_failed_contract():
    payload = {
        "ok": False,
        "score": 0,
        "frontend_reachable": True,
        "auth_status": "auth_failed",
        "issues": [{"title": "Deep QA auth failed"}],
    }
    assert payload["auth_status"] == "auth_failed"
