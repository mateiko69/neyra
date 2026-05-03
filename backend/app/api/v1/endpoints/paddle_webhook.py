"""Paddle Billing webhooks (subscriptions + transactions)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.services.paddle_service import (
    is_paddle_event_processed,
    parse_event,
    record_paddle_event_processed,
    summarize_event_for_log,
    verify_signature,
)
from app.services.payments import paddle_webhook_handlers as paddle_wh

logger = logging.getLogger("neyra.paddle")

router = APIRouter()


def _should_verify_signature() -> bool:
    env = str(getattr(settings, "ENV", "") or "").strip().lower()
    secret = str(getattr(settings, "PADDLE_WEBHOOK_SECRET", "") or "").strip()
    if env in {"production", "prod"}:
        return bool(secret)
    return bool(secret)


@router.post("/webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    raw_body = await request.body()
    sig_header = request.headers.get("Paddle-Signature")

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        logger.exception("paddle_webhook_invalid_json")
        return JSONResponse(
            status_code=200,
            content={"received": True, "ok": False, "error": "invalid_json"},
        )

    verify = _should_verify_signature()
    if verify:
        ok = verify_signature(
            secret=str(settings.PADDLE_WEBHOOK_SECRET or ""),
            raw_body=raw_body,
            paddle_signature_header=sig_header,
        )
        if not ok:
            logger.warning("paddle_webhook_signature_failed")
            return JSONResponse(
                status_code=200,
                content={"received": False, "error": "invalid_signature"},
            )
    else:
        if str(getattr(settings, "ENV", "") or "").strip().lower() in {"production", "prod"}:
            logger.error("paddle_webhook_missing_secret_production")
            return JSONResponse(
                status_code=200,
                content={"received": False, "error": "missing_webhook_secret"},
            )

    parsed = parse_event(payload)
    et = parsed.event_type
    data_obj = parsed.data
    eid = parsed.event_id
    occurred_at = parsed.occurred_at

    try:
        logger.info("paddle_webhook_received %s", summarize_event_for_log(parsed))
    except Exception:
        logger.info("paddle_webhook_received event_type=%s", et)

    if is_paddle_event_processed(db, eid):
        logger.info("paddle_webhook_duplicate event_id=%s", eid)
        return JSONResponse(
            status_code=200,
            content={"received": True, "duplicate": True, "event_id": eid},
        )

    try:
        if et == "transaction.completed":
            out = paddle_wh.handle_transaction_completed(db, data_obj, occurred_at=occurred_at)
        elif et == "transaction.refunded":
            out = paddle_wh.handle_transaction_revoked(
                db,
                data_obj,
                event_type=et,
                occurred_at=occurred_at,
                reason="refunded",
            )
        elif et == "transaction.chargeback_created":
            out = paddle_wh.handle_transaction_revoked(
                db,
                data_obj,
                event_type=et,
                occurred_at=occurred_at,
                reason="chargeback",
            )
        elif et.startswith("subscription."):
            out = paddle_wh.handle_subscription_event(db, et, data_obj, occurred_at=occurred_at)
        else:
            out = {"received": True, "ignored": True, "event_type": et}

        if out.get("error") != "persist_failed":
            record_paddle_event_processed(db, eid)

        body: dict = {"received": True, "event_type": et, **out}
        return JSONResponse(status_code=200, content=body)
    except Exception:
        logger.exception("paddle_webhook_handler_failed event_type=%s", et)
        return JSONResponse(
            status_code=200,
            content={"received": True, "ok": False, "event_type": et, "error": "handler_exception"},
        )
