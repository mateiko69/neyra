from app.services.ai.cache import cache_key


def test_cache_key_stable_for_same_payload():
    a = cache_key("x", {"a": 1, "b": 2})
    b = cache_key("x", {"b": 2, "a": 1})
    assert a == b

