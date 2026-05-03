from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.services.monetization.subscription_service import SubscriptionService
from app.utils.datetime_utc import to_utc_aware

PREMIUM_FEATURES = {"see_advanced_compatibility", "unlimited_ai_suggestions", "priority_visibility", "ai_match_boost"}


def _dev_force_premium() -> bool:
    try:
        return bool(getattr(settings, "DEV_FORCE_PREMIUM", False)) and str(getattr(settings, "ENV", "") or "").strip().lower() != "production"
    except Exception:
        return False


def _trial_active(user: User) -> bool:
    until = to_utc_aware(getattr(user, "premium_until", None))
    if until is None:
        return False
    try:
        now = datetime.now(UTC)
        return now < until
    except Exception:
        return False


def is_user_premium(db: Session, user_id: int) -> bool:
    """Paid subscription (any tier), mirror fields, legacy subscription row, or active premium trial."""
    if _dev_force_premium():
        return True
    plan = SubscriptionService().get_active_plan(db, int(user_id))
    if plan in {"premium", "premium_plus"}:
        return True
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    return _trial_active(user)


def is_user_premium_map(db: Session, user_ids: list[int]) -> dict[int, bool]:
    """Batch variant for feed ranking."""
    ids = [int(x) for x in user_ids if int(x) > 0]
    if not ids:
        return {}
    if _dev_force_premium():
        return {u: True for u in ids}
    out = {u: False for u in ids}
    subsrv = SubscriptionService()
    needs_trial_lookup: list[int] = []
    for u in ids:
        try:
            if subsrv.get_active_plan(db, u) in {"premium", "premium_plus"}:
                out[u] = True
            else:
                needs_trial_lookup.append(u)
        except Exception:
            needs_trial_lookup.append(u)
    if not needs_trial_lookup:
        return out
    user_rows = db.query(User).filter(User.id.in_(needs_trial_lookup)).all()
    for u_row in user_rows:
        if u_row and _trial_active(u_row):
            out[int(u_row.id)] = True
    return out


def has_premium_access(db: Session, user_id: int, feature_name: str) -> bool:
    if not settings.ENABLE_PREMIUM_FEATURES:
        return True
    if _dev_force_premium():
        return True
    if feature_name not in PREMIUM_FEATURES:
        return True
    return bool(is_user_premium(db, user_id))
