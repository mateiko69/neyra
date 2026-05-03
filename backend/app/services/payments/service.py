from app.core.config import settings
from app.services.payments.mock_provider import MockPaymentsProvider
from app.services.payments.paddle_provider import PaddlePaymentsProvider
from app.services.payments.stripe_provider import StripePaymentsProvider


def get_payments_provider():
    p = str(settings.PAYMENTS_PROVIDER or "").strip().lower()
    if p == "stripe":
        return StripePaymentsProvider()
    if p == "paddle":
        return PaddlePaymentsProvider()
    return MockPaymentsProvider()
