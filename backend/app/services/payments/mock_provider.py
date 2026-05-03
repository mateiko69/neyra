from app.services.payments.base import PaymentsProvider

class MockPaymentsProvider(PaymentsProvider):
    def create_checkout_session(self, user_id: int, plan_code: str) -> dict:
        return {"checkout_url": f"https://payments.example.com/mock?user={user_id}&plan={plan_code}", "provider": "mock"}
