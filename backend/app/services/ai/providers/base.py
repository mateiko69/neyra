from abc import ABC, abstractmethod
from app.models.profile import Profile

class AIProvider(ABC):
    # Unified, stable interface (Wingman + analysis).
    @abstractmethod
    async def generate_openers(self, me: Profile | None, other: Profile, *, locale: str | None = None) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def generate_replies(self, last_message: str, context: list[str], style: str, *, locale: str | None = None) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def analyze_conversation(self, messages: list[str]) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def suggest_next_step(self, analysis: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def improve_reply_draft(
        self,
        draft: str,
        context: list[str],
        user_style: str,
        *,
        mode: str | None = None,
        plan_tier: str | None = None,
        locale: str | None = None,
    ) -> dict:
        """Return {\"suggestions\": [{\"text\", \"style\"}, ...]} (3 items). User must send manually."""
        raise NotImplementedError

    async def opener_suggestions(
        self,
        *,
        match_name: str,
        bio: str,
        interests: list[str],
        conversation_context: list[str],
        style: str,
        plan_tier: str,
        locale: str | None = None,
        city: str = "",
        tags: list[str] | None = None,
    ) -> dict:
        """Return {\"suggestions\": [{\"type\",\"text\"}, ...], \"recommended_index\"} (3 items)."""
        raise NotImplementedError

    @abstractmethod
    async def dating_coach_guidance(self, messages: list[str], *, locale: str | None = None) -> dict:
        """Return {\"tone\", \"ask_next\", \"avoid\"} — short actionable strings."""
        raise NotImplementedError

    @abstractmethod
    def first_messages(self, me: Profile, other: Profile) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def reply_suggestions(self, last_message: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def analyze_profile(self, profile: Profile) -> dict:
        raise NotImplementedError

    # Backward-compatible optional capability names.
    def wingman_generate_openers(self, me: Profile, other: Profile) -> list[dict]:
        raise NotImplementedError

    def wingman_generate_replies(self, last_message: str, context: list[str], user_style: str) -> list[dict]:
        raise NotImplementedError
