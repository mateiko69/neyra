"""Map Paddle Billing payloads → NEYRA user subscription mirror (subscription-driven activation)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.subscription import Subscription
from app.models.user import User
from app.services.monetization.plan_entitlements import (
    PRODUCT_PREMIUM_MONTHLY,
    PRODUCT_PREMIUM_PLUS_MONTHLY,
    normalize_internal_plan,
    price_id_to_internal_plan,
)
from app.services.monetization.subscription_sync import apply_subscription_mirror
from app.services.paddle_service import (
    extract_email_from_data,
    extract_revenue_fields,
    log_webhook_structured,
    resolve_user_for_webhook,
)
from app.utils.datetime_utc import to_utc_aware

logger = logging.getLogger("neyra.paddle")


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_utc_aware(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return to_utc_aware(datetime.fromisoformat(s))
    except Exception:
        return None


def _first_price_id(items: Any) -> str | None:
    if not isinstance(items, list):
        return None
    for it in items:
        if not isinstance(it, dict):
            continue
        price = it.get("price")
        pid = None
        if isinstance(price, dict):
            pid = price.get("id")
        pid = pid or it.get("price_id")
        if pid:
            return str(pid).strip()
    return None


def _custom_data(planish: dict[str, Any]) -> dict[str, Any]:
    raw = planish.get("custom_data")
    if isinstance(raw, dict):
        return raw
    return {}


def _custom_data_warn_missing(planish: dict[str, Any], *, event_type: str) -> None:
    raw = planish.get("custom_data")
    if raw is None:
        logger.warning("paddle_webhook_custom_data_absent event_type=%s", event_type)
    elif isinstance(raw, dict) and not raw:
        logger.warning("paddle_webhook_custom_data_empty event_type=%s", event_type)
    elif isinstance(raw, dict) and not any(raw.get(k) not in (None, "") for k in ("user_id", "neyra_user_id", "userid")):
        logger.warning("paddle_webhook_custom_data_no_user_keys event_type=%s", event_type)


def _custom_data_declares_user_id(cd: dict[str, Any]) -> bool:
    if not cd:
        return False
    return any(cd.get(k) not in (None, "") for k in ("user_id", "neyra_user_id", "userid"))


def _resolve_internal_plan(planish: dict[str, Any]) -> str:
    cd = _custom_data(planish)
    pk = str(cd.get("plan_key") or cd.get("product_key") or "").strip().lower()
    if pk in {PRODUCT_PREMIUM_MONTHLY, "premium"}:
        return "premium"
    if pk in {PRODUCT_PREMIUM_PLUS_MONTHLY, "premium_plus"}:
        return "premium_plus"
    pid = _first_price_id(planish.get("items")) or _first_price_id(planish.get("line_items"))
    if not pid:
        det = planish.get("details")
        if isinstance(det, dict):
            pid = _first_price_id(det.get("line_items")) or _first_price_id(det.get("items"))
    mapped = price_id_to_internal_plan(pid)
    return mapped if mapped else "premium"


def _raw_paddle_status(planish: dict[str, Any]) -> str:
    return str(planish.get("status") or "").strip().lower()


def _period_end(planish: dict[str, Any]) -> datetime | None:
    cur = planish.get("current_billing_period") or {}
    if isinstance(cur, dict):
        end = _parse_dt(cur.get("ends_at") or cur.get("end_date"))
        if end:
            return end
        end = _parse_dt(cur.get("endsAt"))
        if end:
            return end
    bp = planish.get("billing_period")
    if isinstance(bp, dict):
        end = _parse_dt(bp.get("ends_at") or bp.get("end_date") or bp.get("endsAt"))
        if end:
            return end
    return _parse_dt(planish.get("next_billed_at"))


def _paddle_subscription_row(db: Session, user_id: int, paddle_subscription_id: str) -> Subscription | None:
    ps = str(paddle_subscription_id or "").strip()
    if ps:
        row = (
            db.query(Subscription)
            .filter(
                Subscription.user_id == int(user_id),
                Subscription.provider_subscription_id == ps[:255],
            )
            .first()
        )
        if row:
            return row
    return db.query(Subscription).filter(Subscription.user_id == int(user_id)).first()


def _subscription_activation_allows_premium(
    db: Session,
    user_id: int,
    event_type: str,
    raw_status: str,
    *,
    confident_custom_user_id: bool,
    target_plan: str,
) -> bool:
    """
    Subscription-driven activation (not transaction.completed).

    - **premium**: `trialing` may grant access (e.g. 5-day trial); `subscription.updated` trialing
      also allowed when user already paid or checkout had custom_data user id.
    - **premium_plus**: no Paddle trial — ignore `trialing`; only `active` may activate premium_plus.
    """
    r = str(raw_status or "").strip().lower()
    tp = normalize_internal_plan(target_plan)
    if tp not in {"premium", "premium_plus"}:
        tp = "premium"

    if tp == "premium_plus" and r == "trialing":
        logger.info(
            "paddle_webhook_premium_plus_trial_ignored user_id=%s event_type=%s",
            int(user_id),
            event_type,
        )
        return False

    if tp == "premium_plus":
        return r == "active"

    u = db.query(User).filter(User.id == int(user_id)).first()
    plan = normalize_internal_plan(getattr(u, "subscription_plan", None)) if u else "free"
    has_paid_mirror = plan in {"premium", "premium_plus"}

    if event_type == "subscription.created":
        return r in {"active", "trialing"}

    if event_type == "subscription.updated":
        if r == "active":
            return True
        if r == "trialing":
            return has_paid_mirror or confident_custom_user_id
        return False

    return True


def _should_skip_stale_subscription_event(
    db: Session,
    *,
    user_id: int,
    subscription_id: str,
    occurred_at: datetime | None,
) -> bool:
    if occurred_at is None or not subscription_id:
        return False
    row = _paddle_subscription_row(db, int(user_id), subscription_id)
    if row is None or row.paddle_last_webhook_occurred_at is None:
        return False
    last = to_utc_aware(row.paddle_last_webhook_occurred_at)
    inc = to_utc_aware(occurred_at)
    if inc < last:
        logger.info(
            "paddle_webhook_stale_ignored user_id=%s subscription_id=%s incoming=%s stored=%s",
            user_id,
            subscription_id,
            inc.isoformat(),
            last.isoformat(),
        )
        return True
    return False


def handle_subscription_event(
    db: Session,
    event_type: str,
    data_obj: dict[str, Any],
    *,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    cd = _custom_data(data_obj)
    _custom_data_warn_missing(data_obj, event_type=event_type)
    email = extract_email_from_data(data_obj)
    user_id, used_email_fallback = resolve_user_for_webhook(db, custom_data=cd, email=email)
    if used_email_fallback:
        logger.warning("paddle_webhook_email_fallback_used user_id=%s event_type=%s", user_id, event_type)

    subscription_id = str(data_obj.get("id") or "").strip()
    if event_type.startswith("subscription.") and not subscription_id:
        logger.critical(
            "paddle_webhook_missing_subscription_id event_type=%s user_id=%s",
            event_type,
            user_id,
        )

    raw = _raw_paddle_status(data_obj)
    paid_plan = _resolve_internal_plan(data_obj)
    expires = _period_end(data_obj)
    now = datetime.now(UTC)
    confident_uid = _custom_data_declares_user_id(cd)

    rev = extract_revenue_fields(data_obj, plan_hint=paid_plan)
    log_webhook_structured(
        event_type=event_type,
        user_id=user_id,
        subscription_id=subscription_id or None,
        status=raw or None,
        amount=rev.get("amount"),
        currency=rev.get("currency"),
        plan=rev.get("plan"),
        extra={
            "email_fallback": used_email_fallback,
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
        },
    )

    if not user_id:
        logger.warning(
            "paddle_webhook_missing_user event=%s subscription_id=%s",
            event_type,
            subscription_id or None,
        )
        return {"ok": False, "skipped": True, "reason": "missing_user_id"}

    if subscription_id and _should_skip_stale_subscription_event(
        db,
        user_id=int(user_id),
        subscription_id=subscription_id,
        occurred_at=occurred_at,
    ):
        return {"ok": True, "skipped": True, "reason": "stale_event", "user_id": int(user_id)}

    customer_id = str(data_obj.get("customer_id") or "").strip()
    if isinstance(data_obj.get("customer"), dict):
        customer_id = str(data_obj["customer"].get("id") or customer_id)

    started = _parse_dt(data_obj.get("started_at"))

    internal_plan_final: str
    mirror_status: str
    expires_out: datetime | None

    if raw in {"expired"}:
        internal_plan_final = "free"
        mirror_status = "inactive"
        expires_out = None
    elif raw in {"paused", "inactive"}:
        internal_plan_final = "free"
        mirror_status = "inactive"
        expires_out = None
    elif raw == "past_due":
        internal_plan_final = paid_plan
        mirror_status = "past_due"
        expires_out = expires
    elif raw in {"canceled", "cancelled"}:
        if expires is not None and expires > now:
            internal_plan_final = paid_plan
            mirror_status = "canceled"
            expires_out = expires
        else:
            internal_plan_final = "free"
            mirror_status = "inactive"
            expires_out = None
    elif raw in {"active", "trialing"}:
        allows = _subscription_activation_allows_premium(
            db,
            int(user_id),
            event_type,
            raw,
            confident_custom_user_id=confident_uid,
            target_plan=paid_plan,
        )
        if not allows:
            if not (
                normalize_internal_plan(paid_plan) == "premium_plus"
                and str(raw).strip().lower() == "trialing"
            ):
                logger.info(
                    "paddle_webhook_activation_skipped user_id=%s event=%s status=%s plan=%s",
                    user_id,
                    event_type,
                    raw,
                    normalize_internal_plan(paid_plan),
                )
            return {
                "ok": True,
                "skipped": True,
                "reason": "activation_policy",
                "user_id": int(user_id),
            }
        internal_plan_final = paid_plan
        mirror_status = "trialing" if raw == "trialing" else "active"
        expires_out = expires
    else:
        internal_plan_final = "free"
        mirror_status = "inactive"
        expires_out = None

    try:
        apply_subscription_mirror(
            db,
            user_id=int(user_id),
            internal_plan=internal_plan_final,
            status=mirror_status,
            expires_at=expires_out,
            provider="paddle",
            provider_customer_id=customer_id[:255] if customer_id else "",
            provider_subscription_id=subscription_id[:255] if subscription_id else "",
            start_date=started,
            paddle_webhook_occurred_at=occurred_at,
        )
    except Exception:
        logger.exception(
            "paddle_webhook_persist_failed user_id=%s subscription_id=%s",
            user_id,
            subscription_id,
        )
        return {"ok": False, "user_id": int(user_id), "error": "persist_failed"}

    return {"ok": True, "user_id": int(user_id), "plan": internal_plan_final, "status": mirror_status}


def handle_transaction_completed(
    db: Session,
    data_obj: dict[str, Any],
    *,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """transaction.completed does not activate premium — subscriptions drive entitlements."""
    cd = _custom_data(data_obj)
    _custom_data_warn_missing(data_obj, event_type="transaction.completed")
    tid = str(data_obj.get("id") or "")[:64]
    paid_plan = _resolve_internal_plan(data_obj)
    rev = extract_revenue_fields(data_obj, plan_hint=paid_plan)
    log_webhook_structured(
        event_type="transaction.completed",
        user_id=None,
        subscription_id=str(data_obj.get("subscription_id") or "")[:64] or None,
        status=str(data_obj.get("status") or "") or None,
        amount=rev.get("amount"),
        currency=rev.get("currency"),
        plan=rev.get("plan"),
        extra={
            "transaction_id": tid or None,
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
        },
    )
    return {"ok": True, "skipped": True, "reason": "premium_via_subscription_only"}


def handle_transaction_revoked(
    db: Session,
    data_obj: dict[str, Any],
    *,
    event_type: str,
    occurred_at: datetime | None = None,
    reason: str,
) -> dict[str, Any]:
    """Refund or chargeback — remove premium immediately."""
    cd = _custom_data(data_obj)
    _custom_data_warn_missing(data_obj, event_type=event_type)
    email = extract_email_from_data(data_obj)
    user_id, used_email_fallback = resolve_user_for_webhook(db, custom_data=cd, email=email)
    if used_email_fallback:
        logger.warning("paddle_webhook_email_fallback_used user_id=%s event_type=%s", user_id, event_type)

    paid_plan = _resolve_internal_plan(data_obj)
    rev = extract_revenue_fields(data_obj, plan_hint=paid_plan)
    subscription_id = str(data_obj.get("subscription_id") or "").strip()

    log_webhook_structured(
        event_type=event_type,
        user_id=user_id,
        subscription_id=subscription_id or None,
        status=str(data_obj.get("status") or "") or None,
        amount=rev.get("amount"),
        currency=rev.get("currency"),
        plan=rev.get("plan"),
        extra={
            "revoke_reason": reason,
            "email_fallback": used_email_fallback,
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
        },
    )

    if not user_id:
        logger.warning(
            "paddle_webhook_revoke_missing_user event=%s subscription_id=%s",
            event_type,
            subscription_id or None,
        )
        return {"ok": False, "skipped": True, "reason": "missing_user_id", "revoke": reason}

    customer_id = str(data_obj.get("customer_id") or "").strip()
    if isinstance(data_obj.get("customer"), dict):
        customer_id = str(data_obj["customer"].get("id") or customer_id)

    try:
        apply_subscription_mirror(
            db,
            user_id=int(user_id),
            internal_plan="free",
            status="inactive",
            expires_at=None,
            provider="paddle",
            provider_customer_id=customer_id[:255] if customer_id else "",
            provider_subscription_id=subscription_id[:255] if subscription_id else "",
            paddle_webhook_occurred_at=occurred_at,
        )
    except Exception:
        logger.exception(
            "paddle_webhook_revoke_persist_failed user_id=%s event=%s",
            user_id,
            event_type,
        )
        return {"ok": False, "user_id": int(user_id), "error": "persist_failed", "revoke": reason}

    logger.warning(
        "paddle_webhook_premium_revoked user_id=%s reason=%s event_type=%s",
        user_id,
        reason,
        event_type,
    )
    return {"ok": True, "user_id": int(user_id), "revoked": True, "reason": reason}
