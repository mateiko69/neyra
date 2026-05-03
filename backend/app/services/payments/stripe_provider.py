from app.services.payments.base import PaymentsProvider

class StripePaymentsProvider(PaymentsProvider):
    def create_checkout_session(self, user_id: int, plan_code: str) -> dict:
        return {"note": "Implement Stripe checkout here", "user_id": user_id, "plan_code": plan_code}
