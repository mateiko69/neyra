"""Paddle Billing webhook helpers: signature verification, payload parsing, user resolution."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.paddle_webhook_event import PaddleWebhookEvent
from app.models.user import User
from app.services.payments.paddle_signature import verify_paddle_signature

logger = logging.getLogger("neyra.paddle")


def verify_signature(*, secret: str, raw_body: bytes, paddle_signature_header: str | None) -> bool:
    """Verify `Paddle-Signature` HMAC (Paddle Billing v2). Delegates to shared implementation."""
    return verify_paddle_signature(
        secret=secret,
        raw_body=raw_body,
        paddle_signature_header=paddle_signature_header,
    )


def extract_email_from_data(data_obj: dict[str, Any]) -> str | None:
    """Best-effort email from a Paddle `data` object (shape varies by resource)."""
    if not isinstance(data_obj, dict):
        return None
    direct = data_obj.get("email")
    if isinstance(direct, str) and direct.strip():
        return direct.strip().lower()
    cust = data_obj.get("customer")
    if isinstance(cust, dict):
        em = cust.get("email")
        if isinstance(em, str) and em.strip():
            return em.strip().lower()
    bd = data_obj.get("billing_details")
    if isinstance(bd, dict):
        em = bd.get("email")
        if isinstance(em, str) and em.strip():
            return em.strip().lower()
    addr = data_obj.get("address")
    if isinstance(addr, dict):
        em = addr.get("email")
        if isinstance(em, str) and em.strip():
            return em.strip().lower()
    return None


def resolve_neyra_user_id(db: Session, *, custom_data: dict[str, Any], email: str | None) -> int | None:
    """Backward-compatible wrapper; prefer `resolve_user_for_webhook`."""
    uid, _ = resolve_user_for_webhook(db, custom_data=custom_data, email=email)
    return uid


def resolve_user_for_webhook(db: Session, *, custom_data: dict[str, Any], email: str | None) -> tuple[int | None, bool]:
    """
    Link Paddle payloads to NEYRA users.

    Primary: `custom_data.user_id` (also accepts legacy `neyra_user_id`, `userid` in custom_data).
    Fallback: match `email` to User.email — logs a warning when used.
    """
    if isinstance(custom_data, dict):
        for key in ("user_id",):
            raw = custom_data.get(key)
            if raw is not None:
                try:
                    return int(str(raw).strip()), False
                except Exception:
                    pass
        for key in ("neyra_user_id", "userid"):
            raw = custom_data.get(key)
            if raw is not None:
                try:
                    return int(str(raw).strip()), False
                except Exception:
                    pass
    if email:
        em = email.strip().lower()
        if em:
            u = db.query(User).filter(User.email == em).first()
            if u is not None:
                logger.warning(
                    "paddle_webhook_user_fallback_email email=%s user_id=%s",
                    em,
                    int(u.id),
                )
                return int(u.id), True
    return None, False


def is_paddle_event_processed(db: Session, event_id: str | None) -> bool:
    """True if we already stored this Paddle notification id."""
    if not event_id or not str(event_id).strip():
        return False
    eid = str(event_id).strip()[:255]
    return db.query(PaddleWebhookEvent).filter(PaddleWebhookEvent.event_id == eid).first() is not None


def record_paddle_event_processed(db: Session, event_id: str | None) -> None:
    """Persist idempotency key after successful handling (best-effort)."""
    if not event_id or not str(event_id).strip():
        return
    eid = str(event_id).strip()[:255]
    if db.query(PaddleWebhookEvent).filter(PaddleWebhookEvent.event_id == eid).first():
        return
    db.add(PaddleWebhookEvent(event_id=eid))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def log_webhook_structured(
    *,
    event_type: str,
    user_id: int | None,
    subscription_id: str | None,
    status: str | None,
    amount: str | None = None,
    currency: str | None = None,
    plan: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event_type": event_type,
        "user_id": user_id,
        "subscription_id": subscription_id,
        "status": status,
    }
    if amount is not None:
        payload["amount"] = amount
    if currency is not None:
        payload["currency"] = currency
    if plan is not None:
        payload["plan"] = plan
    payload.update(extra or {})
    logger.info("paddle_webhook_struct %s", json.dumps(payload, default=str))


def extract_revenue_fields(data_obj: dict[str, Any], *, plan_hint: str | None = None) -> dict[str, Any]:
    """Best-effort amount/currency from Paddle transaction or subscription payloads."""
    out: dict[str, Any] = {"amount": None, "currency": None, "plan": plan_hint}
    if not isinstance(data_obj, dict):
        return out
    cur = data_obj.get("currency_code") or data_obj.get("currency")
    if cur:
        out["currency"] = str(cur).strip().upper()[:12]
    details = data_obj.get("details")
    if isinstance(details, dict):
        totals = details.get("totals")
        if isinstance(totals, dict):
            for key in ("grand_total", "total", "subtotal", "earnings"):
                v = totals.get(key)
                if v is not None and str(v).strip():
                    out["amount"] = str(v)
                    break
    if out["amount"] is None:
        for key in ("total", "total_amount", "amount", "unit_totals"):
            v = data_obj.get(key)
            if v is not None and str(v).strip():
                out["amount"] = str(v)
                break
    return out


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return None


def parse_occurred_at_from_envelope(payload: dict[str, Any]) -> datetime | None:
    """Paddle notification time for ordering (top-level or nested in data)."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for src in (payload, data):
        for key in ("occurred_at", "occurredAt", "created_at", "createdAt"):
            dt = _parse_iso_datetime(src.get(key))
            if dt is not None:
                return dt
    return None


@dataclass(frozen=True)
class ParsedPaddleEvent:
    event_type: str
    event_id: str | None
    data: dict[str, Any]
    occurred_at: datetime | None


def parse_event(payload: dict[str, Any]) -> ParsedPaddleEvent:
    """
    Normalize Paddle webhook JSON.

    Expects top-level `event_type` (or legacy `type`) and nested `data` object.
    """
    et = str(payload.get("event_type") or payload.get("type") or "").strip()
    eid = payload.get("event_id") or payload.get("id")
    event_id = str(eid).strip() if eid is not None else None
    raw = payload.get("data")
    data_obj: dict[str, Any] = raw if isinstance(raw, dict) else {}
    occurred_at = parse_occurred_at_from_envelope(payload)
    return ParsedPaddleEvent(
        event_type=et,
        event_id=event_id or None,
        data=data_obj,
        occurred_at=occurred_at,
    )


def summarize_event_for_log(parsed: ParsedPaddleEvent) -> dict[str, Any]:
    """Safe structured fields for logging (no secrets)."""
    d = parsed.data
    cd = d.get("custom_data") if isinstance(d.get("custom_data"), dict) else {}
    return {
        "event_type": parsed.event_type,
        "event_id": parsed.event_id,
        "occurred_at": parsed.occurred_at.isoformat() if parsed.occurred_at else None,
        "paddle_customer_id": str(d.get("customer_id") or "")[:64] or None,
        "paddle_subscription_id": str(d.get("id") or d.get("subscription_id") or "")[:64] or None,
        "status": str(d.get("status") or "")[:32] or None,
        "has_custom_user_id": any(k in cd for k in ("user_id", "neyra_user_id", "userid")),
    }
