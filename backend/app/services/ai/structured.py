from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


OpenerStyle = Literal["playful", "confident", "curious", "slightly_bold", "fallback_safe"]
ReplyStyle = Literal["safe", "engaging", "slightly_bold"]


class OpenerSuggestion(BaseModel):
    text: str = Field(..., min_length=1, max_length=220)
    style: OpenerStyle
    reason: str = Field(..., min_length=1, max_length=140)


class OpenersOut(BaseModel):
    suggestions: list[OpenerSuggestion] = Field(default_factory=list, min_length=3, max_length=5)


class ReplySuggestion(BaseModel):
    text: str = Field(..., min_length=1, max_length=220)
    style: ReplyStyle


class RepliesOut(BaseModel):
    suggestions: list[ReplySuggestion] = Field(default_factory=list, min_length=3, max_length=3)


class AssistSuggestion(BaseModel):
    """Simple suggestion payload for chat assist surfaces (openers / rewrites)."""

    text: str = Field(..., min_length=1, max_length=220)


class AssistOut(BaseModel):
    suggestions: list[AssistSuggestion] = Field(default_factory=list, min_length=3, max_length=3)
    recommended_index: int = Field(default=0, ge=0, le=2)


OpenerAssistType = Literal["safe", "flirty", "smart"]


class AssistOpenerItem(BaseModel):
    """One opener line with a fixed psychological lane (safe / flirty / smart)."""

    type: OpenerAssistType
    text: str = Field(..., min_length=1, max_length=220)


class AssistOpenersOut(BaseModel):
    suggestions: list[AssistOpenerItem] = Field(default_factory=list, min_length=3, max_length=3)
    recommended_index: int = Field(default=1, ge=0, le=2)


class ConversationAnalysisOut(BaseModel):
    interest_level: int = Field(..., ge=0, le=100)
    response_quality: int = Field(..., ge=0, le=100)
    risk_of_drop: int = Field(..., ge=0, le=100)
    energy_level: Literal["low", "medium", "high"]
    flags: list[str] = Field(default_factory=list)


class NextStepOut(BaseModel):
    suggestions: list[str] = Field(default_factory=list, min_length=1, max_length=4)
    rationale: str = Field(default="")


class DatingCoachOut(BaseModel):
    """Short, actionable dating-coach guidance (no auto-send; user stays in control)."""

    tone: str = Field(..., min_length=1, max_length=320)
    ask_next: str = Field(..., min_length=1, max_length=320)
    avoid: str = Field(..., min_length=1, max_length=320)


class CopilotOptionOut(BaseModel):
    label: str = Field(..., min_length=1, max_length=24)
    text: str = Field(..., min_length=1, max_length=420)


class ChatCopilotOut(BaseModel):
    strategy: str | None = Field(default=None, max_length=420)
    meeting_readiness: int | None = Field(default=None, ge=0, le=100)
    meeting_suggestion: str | None = Field(default=None, max_length=320)
    options: list[CopilotOptionOut] = Field(default_factory=list, min_length=3, max_length=3)
    safety_notes: list[str] = Field(default_factory=list, max_length=6)


class CopilotSingleReplyOut(BaseModel):
    text: str = Field(..., min_length=1, max_length=420)


class CopilotTripleLineOut(BaseModel):
    """Single Gemini round-trip for chat-copilot (light / flirty / deep)."""

    light: str = Field(default="", max_length=420)
    flirty: str = Field(default="", max_length=420)
    deep: str = Field(default="", max_length=420)

