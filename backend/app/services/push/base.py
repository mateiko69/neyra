from abc import ABC, abstractmethod

class PushProvider(ABC):
    @abstractmethod
    def send(self, token: str, title: str, body: str) -> dict:
        raise NotImplementedError
