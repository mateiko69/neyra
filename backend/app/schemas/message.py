from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AssistMetaPayload(BaseModel):
    """Client-reported AI assist usage on send (privacy-safe; no raw draft)."""

    kind: Literal["suggestion", "rewrite"] = "suggestion"
    mode: str = Field(default="", max_length=64)
    source: str = Field(default="", max_length=32)
    variant: str | None = Field(default=None, max_length=32)
    brain_mode: str | None = Field(default=None, max_length=64)
    was_recommended: bool | None = None
    conversation_stage: str | None = Field(default=None, max_length=64)
    conversation_mode: str | None = Field(default=None, max_length=64)
    edited_after_insert: bool | None = None


class MessageCreate(BaseModel):
    receiver_id: int = Field(..., ge=1)
    content: str = Field(default="", max_length=80000)
    conversation_context: list[str] = Field(default_factory=list)
    reply_to_message_id: int | None = Field(default=None, ge=1)
    voice_url: str | None = Field(default=None, max_length=4096)
    voice_mime: str | None = Field(default=None, max_length=80)
    voice_duration_ms: int | None = Field(default=None, ge=0)
    idempotency_key: str | None = Field(default=None, max_length=160)
    assist_meta: AssistMetaPayload | None = None

    @field_validator("content", mode="before")
    @classmethod
    def coerce_content(cls, v) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator("voice_url", mode="before")
    @classmethod
    def coerce_voice_url(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @field_validator("voice_mime", mode="before")
    @classmethod
    def coerce_voice_mime(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @field_validator("idempotency_key", mode="before")
    @classmethod
    def coerce_idempotency_key(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @model_validator(mode="after")
    def ensure_message_has_content_or_voice(self):
        has_text = bool((self.content or "").strip())
        has_voice = bool((self.voice_url or "").strip())
        if not has_text and not has_voice:
            raise ValueError("content cannot be empty")
        return self

    @field_validator("conversation_context", mode="before")
    @classmethod
    def coerce_context(cls, v):
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        out: list[str] = []
        for item in v:
            if item is None:
                continue
            out.append(str(item).strip())
        return out
