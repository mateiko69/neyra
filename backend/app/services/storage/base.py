from abc import ABC, abstractmethod

class StorageProvider(ABC):
    @abstractmethod
    def save(self, filename: str, content: bytes) -> str:
        raise NotImplementedError

    def delete(self, url_or_key: str) -> None:
        """Best-effort delete for an already persisted object (optional)."""
        return
