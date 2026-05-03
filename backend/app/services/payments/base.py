from abc import ABC, abstractmethod

class PaymentsProvider(ABC):
    @abstractmethod
    def create_checkout_session(self, user_id: int, plan_code: str) -> dict:
        raise NotImplementedError
