"""Tests for privacy-safe Pattern Insights (aggregates only, no raw chat persistence)."""

from __future__ import annotations

from app.services.learning.pattern_insights import generate_insights_from_aggregates

_BANNED_SUBSTRINGS = ("message_text", "raw_text", "content", "full_text", "bio", "chat")


def _collect_keys(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k).lower())
            _collect_keys(v, out)
    elif isinstance(obj, list):
        for it in obj:
            _collect_keys(it, out)


def test_insights_suppressed_when_few_messages():
    agg = {
        "window_days": 14,
        "outgoing_messages_sampled": 4,
        "opener_by_tone": {"playful": {"replied": 4, "ignored": 0}, "serious": {"replied": 0, "ignored": 4}},
    }
    assert generate_insights_from_aggregates(agg) == []


def test_playful_opener_insight_when_enough_samples():
    agg = {
        "window_days": 14,
        "outgoing_messages_sampled": 20,
        "opener_by_tone": {"playful": {"replied": 9, "ignored": 1}, "serious": {"replied": 2, "ignored": 8}},
        "liked_messages_by_partner_quality": {
            "low_quality": {"replied": 0, "ignored": 0},
            "ok": {"replied": 0, "ignored": 0},
        },
        "by_shared_interests": {"none": {"replied": 0, "ignored": 0}, "some": {"replied": 0, "ignored": 0}},
        "stop_after_first_reply": {"numerator": 0, "denominator": 0},
        "replied_24h": 10,
        "ignored_24h": 10,
    }
    ins = generate_insights_from_aggregates(agg)
    ids = [i["id"] for i in ins]
    assert "playful_openers_win" in ids


def test_insight_payloads_contain_no_sensitive_key_names():
    agg = {
        "window_days": 14,
        "outgoing_messages_sampled": 30,
        "opener_by_tone": {"playful": {"replied": 10, "ignored": 2}, "serious": {"replied": 2, "ignored": 10}},
        "liked_messages_by_partner_quality": {
            "low_quality": {"replied": 1, "ignored": 9},
            "ok": {"replied": 9, "ignored": 1},
        },
        "by_shared_interests": {"none": {"replied": 2, "ignored": 10}, "some": {"replied": 10, "ignored": 2}},
        "stop_after_first_reply": {"numerator": 8, "denominator": 12},
        "replied_24h": 8,
        "ignored_24h": 20,
    }
    ins = generate_insights_from_aggregates(agg)
    keys: set[str] = set()
    _collect_keys(ins, keys)
    for banned in _BANNED_SUBSTRINGS:
        assert banned not in keys
    for i in ins:
        assert "body" in i and "title" in i
        assert isinstance(i.get("actions"), list)
