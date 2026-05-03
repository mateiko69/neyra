from __future__ import annotations

from app.core.config import settings
from app.services.monetization.plan_entitlements import PRODUCT_PREMIUM_MONTHLY, PRODUCT_PREMIUM_PLUS_MONTHLY
from app.services.payments.base import PaymentsProvider


class PaddlePaymentsProvider(PaymentsProvider):
    """Client-side Paddle Checkout: backend returns IDs + deep links."""

    def create_checkout_session(self, user_id: int, plan_code: str) -> dict:
        plan = str(plan_code or "premium").strip().lower()
        plan_key = PRODUCT_PREMIUM_MONTHLY if plan == "premium" else PRODUCT_PREMIUM_PLUS_MONTHLY
        premium_price = str(getattr(settings, "PADDLE_PRICE_ID_PREMIUM_MONTHLY", "") or "").strip()
        plus_price = str(getattr(settings, "PADDLE_PRICE_ID_PREMIUM_PLUS_MONTHLY", "") or "").strip()

        items: list[dict] = []
        if plan == "premium_plus":
            pid = plus_price or premium_price
        else:
            pid = premium_price or plus_price
        if pid:
            items.append({"price_id": pid, "quantity": 1})

        checkout_url_base = (
            # Paddle overlay / Checkout URL is assembled on the frontend in production using Paddle.js.
            f"{settings.PUBLIC_FRONTEND_URL.rstrip('/')}/premium?checkout=paddle"
        )
        return {
            "provider": "paddle",
            "plan_code": plan,
            "product_key": plan_key,
            "price_id_primary": pid,
            "items": items,
            "custom_data": {"user_id": str(int(user_id)), "plan_key": plan_key},
            "checkout_url_hint": checkout_url_base,
            "pricing": {"premium_monthly_usd": "9.99", "premium_plus_monthly_usd": "19.99"},
            "instruction": "Open Paddle Checkout on the web app with returned price IDs and custom_data.",
        }
