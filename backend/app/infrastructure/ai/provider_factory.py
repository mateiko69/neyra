from app.core.config import settings
from app.services.ai.providers.gemini_provider import GeminiProvider
from app.services.ai.providers.mock_provider import MockAIProvider
from app.services.ai.providers.openai_provider import OpenAIProvider


def get_ai_provider():
    if settings.AI_PROVIDER == "openai":
        return OpenAIProvider()
    if settings.AI_PROVIDER == "gemini":
        return GeminiProvider()
    return MockAIProvider()

