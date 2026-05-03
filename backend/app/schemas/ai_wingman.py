from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GenerateRepliesRequest(BaseModel):
    last_message: str = Field(..., min_length=1)
    conversation_context: list[str] = Field(default_factory=list)
    user_style: str = Field(default="chill")
    allow_edgy_mode: bool = False
    locale: str | None = Field(default=None, max_length=8)


class ReplyOptionsRequest(BaseModel):
    last_message: str = Field(..., min_length=1, max_length=1200)
    conversation_context: list[str] = Field(default_factory=list, max_length=20)
    # Optional: persisted preference hint (frontend can store locally).
    user_preferred_style: str | None = Field(default=None, max_length=24)
    locale: str | None = Field(default="en", max_length=24)


class ReplyOptionsResponse(BaseModel):
    options: list[str] = Field(default_factory=list, min_length=1, max_length=3)
    best_reply: str | None = Field(default=None, max_length=240)
    alternatives: list[dict] | None = None
    why_best: str | None = Field(default=None, max_length=220)
    confidence: int | None = Field(default=None, ge=0, le=100)
    stage: str | None = Field(default=None, max_length=16)
    meta: dict | None = None


class BioSuggestRequest(BaseModel):
    interests: list[str] = Field(default_factory=list, max_length=12)
    city: str | None = Field(default=None, max_length=100)
    locale: str | None = Field(default="en", max_length=24)


class CopilotOption(BaseModel):
    label: str = Field(..., max_length=24)
    style: str | None = Field(default=None, max_length=16)
    text: str = Field(..., min_length=1, max_length=420)
    reply: str | None = Field(default=None, max_length=320)
    question: str | None = Field(default=None, max_length=240)
    tone: str | None = Field(default=None, max_length=16)


class ChatCopilotRequest(BaseModel):
    partner_user_id: int = Field(..., ge=1)
    # Frontend may send a mode hint; backend must derive tier from subscription.
    mode: str | None = Field(default=None, max_length=16)
    user_selected_style: str | None = Field(default=None, max_length=24)
    locale: str | None = Field(default=None, max_length=24)


class ChatCopilotResponse(BaseModel):
    strategy: str | None = Field(default=None, max_length=420)
    meeting_readiness: int | None = Field(default=None, ge=0, le=100)
    meeting_suggestion: str | None = Field(default=None, max_length=320)
    best_option_index: int = Field(default=0, ge=0, le=2)
    options: list[CopilotOption] = Field(default_factory=list, min_length=1, max_length=3)
    safety_notes: list[str] = Field(default_factory=list, max_length=6)
    limited: bool = False
    stall: StallDetectionResponse | None = None
    goal_metrics: dict | None = None
    fallback: bool = Field(default=False, description="True when suggestions come from deterministic engine (provider degraded).")
    source: str | None = Field(default=None, max_length=64)
    fallback_reason: str | None = Field(default=None, max_length=64)


class AnalyzeConversationRequest(BaseModel):
    messages: list[str] = Field(default_factory=list)


class InterestStageResponse(BaseModel):
    interest_score: int = Field(..., ge=0, le=100)
    stage: str = Field(..., max_length=12)  # cold|warming|engaged|ready
    mutuality_score: int = Field(..., ge=0, le=100)
    signals: list[str] = Field(default_factory=list, max_length=10)


class TimingEngineRequest(BaseModel):
    messages: list[dict] = Field(default_factory=list, max_length=80)
    last_message_at: str | None = Field(default=None, max_length=64)
    avg_partner_reply_minutes: float | None = None
    partner_active_hours: list[int] = Field(default_factory=list, max_length=24)  # [0..23]
    stall_score: int | None = Field(default=None, ge=0, le=100)
    interest_stage: str | None = Field(default=None, max_length=12)
    mutuality_score: int | None = Field(default=None, ge=0, le=100)
    locale: str | None = Field(default="en", max_length=8)


class TimingEngineResponse(BaseModel):
    should_send_now: bool
    confidence: int = Field(..., ge=0, le=100)
    nudge_type: str = Field(..., max_length=12)  # now|wait|reengage|revive
    best_time_window: str = Field(default="", max_length=64)
    reasoning: str = Field(default="", max_length=220)


class TimedReplyOption(BaseModel):
    style: str = Field(..., max_length=16)  # light|flirty|deep
    text: str = Field(..., min_length=1, max_length=420)
    reply: str | None = Field(default=None, max_length=320)
    question: str | None = Field(default=None, max_length=240)
    tone: str | None = Field(default=None, max_length=16)


class TimedRepliesRequest(BaseModel):
    messages: list[dict] = Field(default_factory=list, max_length=80)  # [{role, text}]
    nudge_type: str = Field(..., max_length=12)  # now|wait|reengage|revive
    interest_stage: str | None = Field(default=None, max_length=12)
    mutuality_score: int | None = Field(default=None, ge=0, le=100)
    locale: str | None = Field(default="en", max_length=12)
    language_hint: str | None = Field(default=None, max_length=96)
    last_message_at: str | None = Field(default=None, max_length=64)
    who_sent_last: str | None = Field(default=None, max_length=8)  # me|them


class TimedRepliesResponse(BaseModel):
    options: list[TimedReplyOption] = Field(default_factory=list, max_length=3)
    locale: str = Field(default="en", max_length=12)
    source: str = Field(default="ai", max_length=20)  # ai|fallback|fallback_quota
    goal_metrics: dict | None = None


class TimingDecisionRequest(BaseModel):
    """
    Backward-compatible:
    - Old client sends partner_user_id + messages (server can infer metrics).
    - New client can send metrics only (no partner_user_id, no message bodies).
    """

    # Old fields (optional for new contract)
    partner_user_id: int | None = Field(default=None, ge=1)
    messages: list[dict] = Field(default_factory=list, max_length=80)
    interest_stage: str | None = Field(default=None, max_length=12)  # cold|warming|engaged|ready
    mutuality_score: int | None = Field(default=None, ge=0, le=100)
    stall_score: int | None = Field(default=None, ge=0, le=100)
    locale: str | None = Field(default="en", max_length=8)

    # New contract fields (best-effort; no PII required)
    last_message_at: str | None = Field(default=None, max_length=64)
    message_count: int | None = Field(default=None, ge=0, le=10_000)
    reply_time_avg: float | None = None
    who_sent_last: str | None = Field(default=None, max_length=12)  # me|them
    conversation_length: int | None = Field(default=None, ge=0, le=10_000)


class TimingDecisionMetrics(BaseModel):
    minutes_since_last_message: int = Field(default=0, ge=0, le=60 * 24 * 30)
    avg_partner_reply_minutes: int = Field(default=0, ge=0, le=60 * 24 * 30)
    mutuality_score: int = Field(default=0, ge=0, le=100)
    stall_score: int = Field(default=0, ge=0, le=100)


class TimingDecisionResponse(BaseModel):
    should_send_now: bool
    confidence: int = Field(..., ge=0, le=100)
    nudge_type: str = Field(..., max_length=12)  # now|wait|reengage|revive
    best_time_window: str = Field(default="", max_length=64)
    reasoning: str = Field(default="", max_length=220)
    metrics: TimingDecisionMetrics

    # New thin response fields (for the requested contract)
    decision: str | None = Field(default=None, max_length=16)  # wait|now|revive|escalate


class StallDetectionRequest(BaseModel):
    messages: list[str] = Field(default_factory=list, max_length=80)
    locale: str | None = Field(default="en", max_length=8)


class ComboRequest(BaseModel):
    partner_user_id: int = Field(..., ge=1)
    messages: list[dict] = Field(default_factory=list, max_length=200)
    user_profile: dict = Field(default_factory=dict)
    partner_profile: dict = Field(default_factory=dict)
    locale: str | None = Field(default=None, max_length=8)


class ComboDecision(BaseModel):
    nudge_type: str = Field(..., max_length=12)  # now|wait|reengage|revive
    confidence: int = Field(..., ge=0, le=100)


class ComboSignals(BaseModel):
    interest_score: int = Field(..., ge=0, le=100)
    stage: str = Field(..., max_length=12)  # cold|warming|engaged|ready
    mutuality_score: int = Field(..., ge=0, le=100)
    stall_score: int = Field(..., ge=0, le=100)
    meeting_readiness: int = Field(..., ge=0, le=100)


class ComboUi(BaseModel):
    title: str = Field(default="", max_length=80)
    reason: str = Field(default="", max_length=220)


class ComboOption(BaseModel):
    style: str = Field(..., max_length=16)  # light|flirty|deep
    text: str = Field(..., min_length=1, max_length=420)


class ComboMeeting(BaseModel):
    allowed: bool = False
    suggestions: list[str] = Field(default_factory=list, max_length=3)


class ComboResponse(BaseModel):
    decision: ComboDecision
    signals: ComboSignals
    ui: ComboUi
    options: list[ComboOption] = Field(default_factory=list, max_length=3)
    meeting: ComboMeeting


class StallDetectionResponse(BaseModel):
    is_stalled: bool = False
    stall_score: int = Field(default=0, ge=0, le=100)
    reasons: list[str] = Field(default_factory=list, max_length=6)


class MeetingReadinessRequest(BaseModel):
    # Backward compatible:
    # - old clients: ["hi", "how are you"]
    # - new clients: [{role:"me"|"them", text:"...", ts_ms?:123}]
    messages: list = Field(default_factory=list, max_length=120)
    # Prefer passing partner_user_id so server can enforce safety gates.
    partner_user_id: int | None = Field(default=None, ge=1)
    # Optional legacy name from some clients; treated as partner_user_id when present.
    thread_id: int | None = Field(default=None, ge=1)
    locale: str | None = Field(default="en", max_length=8)
    city: str | None = Field(default=None, max_length=100)
    conversation_stats: dict | None = None
    # When true, server records that the meeting card was shown (cooldown + free-tier usage).
    mark_shown: bool = False
    response_time_seconds: float | None = None
    who_initiates: str | None = Field(default=None, max_length=12)  # me|them|both|unknown
    avg_message_length: float | None = None


class MeetingOption(BaseModel):
    kind: str = Field(..., max_length=16)  # coffee|walk|drinks|custom
    label: str = Field(..., max_length=40)
    text: str = Field(..., min_length=1, max_length=240)


class MeetingReadinessResponse(BaseModel):
    # New Meeting Engine contract (preferred by clients).
    stage: str = Field(..., max_length=12)  # early|warming|ready|stalled
    score: int = Field(..., ge=0, le=100)
    reason: str = Field(default="", max_length=500)
    suggested_action: str = Field(..., max_length=24)  # keep_chatting|ask_deeper|suggest_meeting|revive
    meeting_options: list[MeetingOption] = Field(default_factory=list, max_length=4)

    # Back-compat fields (older clients may still read these).
    meeting_readiness: int = Field(..., ge=0, le=100)
    reasoning: list[str] = Field(default_factory=list, max_length=8)
    risk_level: str = Field(..., max_length=8)  # low|medium|high
    # Legacy v2 meeting engine fields.
    confidence: int | None = Field(default=None, ge=0, le=100)
    suggest_action: str | None = Field(default=None, max_length=24)  # continue|escalate|suggest_meeting

    # Conversation closer (chat → meeting); optional for older clients.
    readiness_score: int | None = Field(default=None, ge=0, le=100)
    closer_stage: str | None = Field(
        default=None,
        max_length=24,
    )  # opener|early_chat|engaged|high_interest|stalled|ready_for_meeting
    closer_suggestions: list[str] = Field(default_factory=list, max_length=3)
    show_moment_hint: bool = False


class MeetingReadyResponse(BaseModel):
    """Focused payload for meeting momentum UI (/ai/meeting-ready)."""

    readiness_score: int = Field(..., ge=0, le=100)
    closer_stage: str = Field(..., max_length=24)
    suggestions: list[str] = Field(default_factory=list, max_length=3)
    show_moment_hint: bool = False


class MeetingOptionsRequest(BaseModel):
    messages: list[str] = Field(default_factory=list, max_length=80)
    meeting_readiness: int = Field(..., ge=0, le=100)
    locale: str | None = Field(default="en", max_length=8)


class MeetingOptionsResponse(BaseModel):
    meeting_options: list[str] = Field(default_factory=list, max_length=3)


class ConversationQualityRequest(BaseModel):
    """Conversation quality metrics from last messages.

    messages: list of {role:"me"|"them", text:str, ts_ms?:int} (ts optional)
    """

    messages: list[dict] = Field(default_factory=list, max_length=80)


class ConversationQualityResponse(BaseModel):
    score: int = Field(..., ge=0, le=100)
    status: str = Field(..., max_length=8)  # cold|warm|hot


class ReviveOption(BaseModel):
    type: str = Field(..., max_length=24)  # topic_shift|personal_hook|playful
    text: str = Field(..., min_length=1, max_length=420)


class ReviveResponse(BaseModel):
    options: list[ReviveOption] = Field(default_factory=list, min_length=3, max_length=3)


class StartOpener(BaseModel):
    style: str = Field(..., max_length=16)  # light|flirty|curious
    text: str = Field(..., min_length=1, max_length=420)


class StartStrategyRequest(BaseModel):
    partner_user_id: int = Field(..., ge=1)
    # Optional: if the thread already has 0–2 messages, include them for better continuity.
    messages: list[str] = Field(default_factory=list, max_length=3)
    locale: str | None = Field(default="en", max_length=8)
    # Frontend override: MUST follow current UI locale (ignore profile preferred_language).
    language: str | None = Field(default=None, max_length=16)


class StartStrategyResponse(BaseModel):
    strategy: str | None = Field(default=None, max_length=420)
    confidence: int | None = Field(default=None, ge=0, le=100)
    hooks: list[str] = Field(default_factory=list, max_length=6)
    openers: list[StartOpener] = Field(default_factory=list, min_length=1, max_length=3)


class NextStepRequest(BaseModel):
    # Legacy: analyzer payload
    analysis: dict | None = None

    # New: lightweight locale hint (no analysis required)
    locale: str | None = Field(default="en", max_length=8)


class GenerateOpenersRequest(BaseModel):
    conversation_context: list[str] = Field(default_factory=list)
    language_hint: str | None = Field(default=None, max_length=96)
    style: str | None = Field(default="default", max_length=32)
    allow_edgy_mode: bool = False
    locale: str | None = Field(default=None, max_length=8)


class GenerateOpenerSuggestionsRequest(BaseModel):
    match_name: str = Field(..., min_length=1, max_length=80)
    bio: str = Field(default="", max_length=1000)
    interests: list[str] = Field(default_factory=list)
    conversation_context: list[str] = Field(default_factory=list)
    style: str | None = Field(default=None, max_length=32)
    city: str = Field(default="", max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=24)
    locale: str | None = Field(default=None, max_length=12)
    language_hint: str | None = Field(default=None, max_length=96)


class OpenerSuggestionItem(BaseModel):
    type: Literal["safe", "flirty", "smart"]
    text: str = Field(..., min_length=1, max_length=280)


class GenerateOpenerSuggestionsResponse(BaseModel):
    items: list[OpenerSuggestionItem] = Field(default_factory=list, min_length=3, max_length=3)
    suggestions: list[str] = Field(default_factory=list, min_length=3, max_length=3)
    recommended_index: int = Field(default=1, ge=0, le=2)


class OpenersResponseItem(BaseModel):
    text: str
    style: str
    reason: str
    safety_flags: list[str] = Field(default_factory=list)


class RepliesResponseItem(BaseModel):
    text: str
    style: str
    safety_flags: list[str] = Field(default_factory=list)


class ImproveReplyRequest(BaseModel):
    draft: str = Field(..., min_length=1, max_length=4000)
    conversation_context: list[str] = Field(default_factory=list)
    user_style: str = Field(default="chill")
    allow_edgy_mode: bool = False
    mode: str | None = Field(default=None, max_length=32)
    locale: str | None = Field(default=None, max_length=12)
    language_hint: str | None = Field(default=None, max_length=96)


class CoachGuidanceRequest(BaseModel):
    messages: list[str] = Field(default_factory=list)


class ReadinessMessage(BaseModel):
    role: str = Field(..., max_length=8)  # "me" | "them"
    text: str = Field(default="", max_length=2000)


class ReadinessScoreRequest(BaseModel):
    messages: list[ReadinessMessage] = Field(default_factory=list)
    draft: str | None = Field(default=None, max_length=2000)
    plan_tier: str = Field(default="free", max_length=32)
    locale: str | None = Field(default=None, max_length=12)
    language_hint: str | None = Field(default=None, max_length=96)


class ReadinessScoreResponse(BaseModel):
    score: int = Field(..., ge=0, le=100)
    level: str = Field(..., max_length=12)  # "low" | "medium" | "high"
    insight: str = Field(default="", max_length=160)
    tips: list[str] = Field(default_factory=list, max_length=2)
    locale: str = Field(default="en", max_length=12)
    source: str = Field(default="ai", max_length=16)  # ai|fallback


class CoachMessage(BaseModel):
    role: str = Field(..., max_length=8)  # "me" | "them"
    text: str = Field(default="", max_length=2000)


class CoachRequest(BaseModel):
    messages: list[CoachMessage] = Field(default_factory=list)
    draft: str | None = Field(default=None, max_length=2000)
    readiness_score: int | None = Field(default=None, ge=0, le=100)
    locale: str | None = Field(default=None, max_length=12)
    language_hint: str | None = Field(default=None, max_length=96)


class CoachAction(BaseModel):
    type: str = Field(..., max_length=24)  # rewrite|opener|ask_question|voice_step|date_step
    label: str = Field(default="", max_length=48)


class CoachResponse(BaseModel):
    state: str = Field(..., max_length=16)  # idle|nudge|opportunity|caution
    message: str = Field(default="", max_length=180)
    actions: list[CoachAction] = Field(default_factory=list, max_length=2)
    health_score: int | None = Field(default=None, ge=0, le=100)
    attraction_level: str | None = Field(default=None, max_length=12)
    drop_risk: str | None = Field(default=None, max_length=12)
    trend: str | None = Field(default=None, max_length=12)
    signals: list[str] = Field(default_factory=list, max_length=10)
    diagnosis: str | None = Field(default=None, max_length=320)
    next_move: str | None = Field(default=None, max_length=220)
    next_suggestions: list[str] = Field(default_factory=list, max_length=3)
    locale: str = Field(default="en", max_length=12)
    source: str = Field(default="ai", max_length=16)  # ai|fallback


class EscalationMessage(BaseModel):
    role: str = Field(..., max_length=8)  # "me" | "them"
    text: str = Field(default="", max_length=2000)


class EscalationReadinessRequest(BaseModel):
    messages: list[EscalationMessage] = Field(default_factory=list)
    readiness_score: int | None = Field(default=None, ge=0, le=100)
    coach_state: str | None = Field(default=None, max_length=16)  # idle|nudge|opportunity|caution
    locale: str | None = Field(default=None, max_length=8)


class EscalationReadinessResponse(BaseModel):
    voice_ready: bool = False
    video_ready: bool = False
    date_ready: bool = False
    primary_step: str = Field(default="none", max_length=8)  # none|voice|video|date
    confidence: int = Field(default=0, ge=0, le=100)
    message: str = Field(default="", max_length=180)


class RecoveryMessage(BaseModel):
    role: str = Field(..., max_length=8)  # "me" | "them"
    text: str = Field(default="", max_length=2000)


class RecoveryRequest(BaseModel):
    messages: list[RecoveryMessage] = Field(default_factory=list)
    last_message_age_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 14)
    readiness_score: int | None = Field(default=None, ge=0, le=100)
    coach_state: str | None = Field(default=None, max_length=16)  # idle|nudge|opportunity|caution
    locale: str | None = Field(default=None, max_length=8)


class RecoveryResponse(BaseModel):
    state: str = Field(default="idle", max_length=16)  # idle|soft_nudge|revive|let_it_breathe
    message: str = Field(default="", max_length=180)
    suggestions: list[str] = Field(default_factory=list, max_length=3)


class CompatibilityScoreRequest(BaseModel):
    viewer_profile_id: int = Field(..., ge=1)
    candidate_profile_id: int = Field(..., ge=1)
    locale: str | None = Field(default=None, max_length=8)


class CompatibilityScoreBatchRequest(BaseModel):
    viewer_profile_id: int = Field(..., ge=1)
    candidate_profile_ids: list[int] = Field(default_factory=list, max_length=25)
    locale: str | None = Field(default=None, max_length=8)


class CompatibilityScoreResponse(BaseModel):
    score: int = Field(default=0, ge=0, le=100)
    level: str = Field(default="medium", max_length=12)  # low|medium|high
    reasons: list[str] = Field(default_factory=list, max_length=3)
    visual_score: int | None = Field(default=None, ge=0, le=100)
    vibe_score: int | None = Field(default=None, ge=0, le=100)
    symmetry_score: int | None = Field(default=None, ge=0, le=100)
    available: bool = False


class CompatibilityScoreBatchResult(BaseModel):
    candidate_profile_id: int = Field(..., ge=1)
    score: int = Field(default=0, ge=0, le=100)
    level: str = Field(default="medium", max_length=12)  # low|medium|high
    reasons: list[str] = Field(default_factory=list, max_length=3)
    visual_score: int | None = Field(default=None, ge=0, le=100)
    vibe_score: int | None = Field(default=None, ge=0, le=100)
    symmetry_score: int | None = Field(default=None, ge=0, le=100)
    available: bool = False


class CompatibilityScoreBatchResponse(BaseModel):
    results: list[CompatibilityScoreBatchResult] = Field(default_factory=list, max_length=25)
