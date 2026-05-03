from app.services.ai.providers.base import AIProvider
from app.services.ai.conversation.opener_generator import OpenerGenerator
from app.services.ai.conversation.reply_generator import ReplyGenerator
from app.services.ai.conversation.conversation_analyzer import ConversationAnalyzer
from app.services.ai.conversation.escalation_advisor import EscalationAdvisor
from app.services.ai.conversation.reply_assistant import improve_draft_locally
from app.services.ai.conversation.dating_coach import coach_heuristic
from app.services.ai.ai_request_locale import normalize_ai_request_locale

class MockAIProvider(AIProvider):
    def first_messages(self, me, other):
        interests = [x.strip() for x in (other.interests or "").split(",") if x.strip()]
        topic = interests[0] if interests else "your interests"
        return [
            f"Hey. You have a strong vibe. What do you enjoy most about {topic}?",
            f"I liked your profile. What’s the story behind your interest in {topic}?",
            "I don’t want to start generic—what’s actually interesting in your life lately?",
        ]

    def reply_suggestions(self, last_message):
        return [
            "Interesting. What matters most to you here?",
            "That sounds real. Want to tell me a bit more?",
            "This already feels like an actual conversation 🙂",
        ]

    def analyze_profile(self, profile):
        return {"style": "social", "completeness": 72, "risk_flags": []}

    def wingman_generate_openers(self, me, other):
        return OpenerGenerator.generate_openers(me, other, allow_edgy_mode=False)

    def wingman_generate_replies(self, last_message, context, user_style):
        return ReplyGenerator.generate_replies(last_message, conversation_context=context, user_style=user_style, allow_edgy_mode=False)

    async def generate_openers(self, me, other, *, locale: str | None = None) -> dict:
        return {
            "suggestions": [
                {"text": x["text"], "style": x["style"], "reason": x["reason"]}
                for x in OpenerGenerator.generate_openers(me, other, allow_edgy_mode=False, locale=locale)
            ]
        }

    async def generate_replies(self, last_message: str, context: list[str], style: str, *, locale: str | None = None) -> dict:
        return {
            "suggestions": [
                {"text": x["text"], "style": x["style"]}
                for x in ReplyGenerator.generate_replies(
                    last_message,
                    conversation_context=context,
                    user_style=style,
                    allow_edgy_mode=False,
                    locale=locale,
                )
            ]
        }

    async def analyze_conversation(self, messages: list[str]) -> dict:
        return ConversationAnalyzer.analyze_conversation(messages).to_dict()

    async def suggest_next_step(self, analysis: dict) -> dict:
        # EscalationAdvisor expects a ConversationAnalysis; keep it simple by reusing analysis dict.
        from app.application.use_cases.ai.wingman_next_step import suggest_next_step as _suggest
        return _suggest(analysis)

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
        rows = improve_draft_locally(draft, context, user_style, allow_edgy_mode=False, locale=locale)
        return {"suggestions": [{"text": x["text"], "style": x["style"]} for x in rows]}

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
        _ = normalize_ai_request_locale(locale)
        name = (match_name or "").strip()
        hook_city = (city or "").strip()
        tag0 = str((tags or [])[0] or "").strip() if tags else ""
        greeting = f"Hi{name and f', {name}' or ''}"
        rows = [
            {
                "type": "safe",
                "text": f"{greeting} — coffee shop calm or busy city energy: which fits you today?".strip(),
            },
            {
                "type": "flirty",
                "text": f"{greeting or 'Hey'} — be honest: more ‘plans’ or ‘see what happens’?",
            },
            {
                "type": "smart",
                "text": (
                    f"You mention {tag0}—what pulled you into it first, curiosity or habit?"
                    if tag0
                    else (
                        f"If {hook_city} had a ‘perfect Saturday’, would it be outdoors or cozy indoors?"
                        if hook_city
                        else "If your week had a headline, what would the one-liner be?"
                    )
                ),
            },
        ]
        return {
            "suggestions": rows,
            "recommended_index": 1,
        }

    async def dating_coach_guidance(self, messages: list[str], *, locale: str | None = None) -> dict:
        return coach_heuristic(messages)
