from app.services.viral.hook_engine import HookEngine
from app.services.viral.referral_engine import ReferralEngine


def test_hook_engine_new_match():
    hook = HookEngine().generate_hook(1, {"type": "new_match"})
    assert "trigger" in hook and "action" in hook and "reward" in hook and "investment" in hook


def test_referral_code_stable():
    a = ReferralEngine.referral_code(42)
    b = ReferralEngine.referral_code(42)
    assert a == b

