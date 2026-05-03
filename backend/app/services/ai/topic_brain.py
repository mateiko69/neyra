"""
Topic intelligence for dating conversation AI: curated hooks + lightweight topic detection.

Copy is maintained in English; prompts require the LLM to translate into LANGUAGE.
"""

from __future__ import annotations

import random
import re
from typing import Any, Literal

TopicId = Literal[
    "travel",
    "movies",
    "music",
    "fashion",
    "food",
    "fitness",
    "work",
    "books",
    "pets",
    "nightlife",
    "art",
    "hobbies",
    "local",
    "relationships",
    "humor",
    "support",
    "general",
]

# When topic detection is uncertain, inject full anchor set so models avoid dead-end replies.
TOPIC_CONFIDENCE_LOW_THRESHOLD = 0.46

TOPIC_LINE_KINDS = ("opener", "playful", "deep", "meeting_bridge")

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "movies": (
        "movie",
        "film",
        "cinema",
        "netflix",
        "series",
        "show",
        "фільм",
        "кино",
        "серіал",
    ),
    "music": ("music", "song", "concert", "spotify", "band", "музик", "пісн", "концерт"),
    "fashion": ("style", "outfit", "fashion", "dress", "sneaker", "одяг", "стиль"),
    "travel": (
        "travel",
        "trip",
        "flight",
        "vacation",
        "abroad",
        "подорож",
        "путешеств",
        "відпочинок",
    ),
    "food": (
        "food",
        "coffee",
        "restaurant",
        "cafe",
        "cook",
        "recipe",
        "sushi",
        "wine",
        "їжа",
        "кав",
        "ресторан",
    ),
    "fitness": ("gym", "workout", "run", "yoga", "fitness", "спортзал", "тренуван"),
    "work": ("work", "job", "business", "startup", "office", "робот", "бізнес", "кар'єр"),
    "books": ("book", "read", "novel", "книг", "чита"),
    "art": ("art", "gallery", "museum", "paint", "музей", "галере", "мистецт"),
    "pets": ("dog", "cat", "pet", "puppy", "кот", "собак", "пес"),
    "nightlife": ("club", "party", "bar", "night", "клуб", "вечірк"),
    "hobbies": ("hobby", "game", "photo", "craft", "хобі"),
    "local": ("city", "neighborhood", "nearby", "місто", "район", "поблизу"),
    "relationships": ("relationship", "dating", "ex", "feelings", "стосунк", "отношен"),
    "humor": ("funny", "joke", "laugh", "мем", "жарт", "смішн"),
    "support": ("stress", "tired", "anxious", "hard day", "втом", "тривож", "важк"),
}

# English seed lines — model must output in target locale; used in prompts + fallbacks.
# Each topic: opener (warm hook), playful, deep question, meeting_bridge (move chat toward a plan).
TOPIC_SEEDS: dict[str, dict[str, tuple[str, ...]]] = {
    "travel": {
        "opener": (
            "I’m curious — when you travel, is it more ‘see everything’ or ‘pick one vibe and stay’?",
            "Quick read: are you the one who books flights first or the one who packs the night before? 😄",
            "What’s the last trip that still lives in your head rent-free?",
        ),
        "playful": (
            "Okay, spontaneous traveler or spreadsheet-planner type? 😄",
            "If your weekend had a one-way ticket, where are we landing first?",
            "Be honest: plans in notes or ‘we’ll figure it out’ energy?",
        ),
        "deep": (
            "What place changed how you see life, even a little?",
            "When you travel, are you chasing rest or a version of yourself?",
            "What’s a trip you still think about for no logical reason?",
        ),
        "meeting_bridge": (
            "We should trade travel fails over coffee sometime — I’ll bring the bad decisions.",
            "If you’re up for it, we could compare ‘best wrong turn’ stories in person.",
            "This energy calls for swapping dream destinations over something warm to drink.",
        ),
    },
    "movies": {
        "opener": (
            "What are you watching lately — anything you’d actually recommend?",
            "Are you more ‘one perfect movie’ or ‘accidentally finish a whole series’?",
            "Okay, I need a read: comfort rewatch person or always something new?",
        ),
        "playful": (
            "Okay, important question 😄 are you more thriller at night or comfort movies?",
            "Are you ‘one more episode’ or ‘strictly one movie’?",
            "What’s your guilty-rewatch — the one you’d never admit first?",
        ),
        "deep": (
            "What kind of story makes you feel seen lately?",
            "Do you watch to escape or to understand people better?",
            "Which film stayed with you longer than you expected?",
        ),
        "meeting_bridge": (
            "We should do a tiny ‘you pick / I pick’ movie night sometime.",
            "I’d trade recommendations — loser buys the snacks.",
            "Cozy watch-list swap over coffee — I’m serious.",
        ),
    },
    "music": {
        "opener": (
            "What’s in your headphones this week — algorithm chaos or a curated playlist?",
            "I need a vibe check: live show person or perfect-sound-at-home person?",
            "What song have you replayed way too many times lately?",
        ),
        "playful": (
            "Playlists: curated masterpieces or beautiful chaos?",
            "Concert person or ‘I love the album at home’ person?",
            "What song is unfairly good for your mood today?",
        ),
        "deep": (
            "What music era feels like ‘your’ era?",
            "Do lyrics matter to you or is it all about the vibe?",
            "What artist feels like a personality trait for you?",
        ),
        "meeting_bridge": (
            "Send me one song you’d put me onto — I’ll return the favor in person.",
            "We should build a two-person playlist and road-test it.",
            "Coffee + ‘what are you listening to’ — I’m down.",
        ),
    },
    "fashion": {
        "opener": (
            "Random but fun: are you more ‘outfit planned’ or ‘grab what feels right’?",
            "Is style for you comfort-first, statement-first, or depends on the day?",
            "What’s one thing in your closet that always gets compliments?",
        ),
        "playful": (
            "Okay, important question 😄 sneakers you baby or beat up on purpose?",
            "Are you ‘capsule wardrobe’ or ‘options are security’?",
            "Hot take: accessories matter more than the outfit — defend yourself.",
        ),
        "deep": (
            "Does how you dress change how you feel day to day?",
            "What’s a look that makes you feel most like yourself?",
            "Is fashion expression for you, armor, or both?",
        ),
        "meeting_bridge": (
            "We should do a ‘favorite local shop’ tour sometime — low pressure, good people-watching.",
            "I’d love to hear your style story over coffee.",
            "If we meet up, I’m stealing one outfit recommendation from you.",
        ),
    },
    "food": {
        "opener": (
            "What’s your food mood today — cozy, spicy, or something new?",
            "Are you more ‘I know my spots’ or ‘let’s try whatever looks good’?",
            "Coffee first: non-negotiable ritual or nice bonus?",
        ),
        "playful": (
            "Food hot take: brunch is a lifestyle, not a meal — yes or no?",
            "Adventurous eater or ‘I know what I like and I’m not sorry’?",
            "Sushi: gateway food or full personality trait? 😄",
        ),
        "deep": (
            "What food feels like home to you?",
            "Do you eat to explore or to comfort?",
            "What’s a meal you’d travel for?",
        ),
        "meeting_bridge": (
            "We should compare favorite spots — winner picks the next outing.",
            "I owe you a coffee-and-snacks recommendation trade.",
            "Let’s do a ‘one dish you swear by’ exchange in real life.",
        ),
    },
    "fitness": {
        "opener": (
            "How do you like to move — gym, outdoors, or ‘whatever fits the day’?",
            "Are you training toward something or just keeping the vibes steady?",
            "Morning workout or ‘please don’t talk to me before coffee’?",
        ),
        "playful": (
            "Gym grind or outdoor-run person? Be honest 😄",
            "Are you ‘train either way’ or ‘needs the perfect playlist’?",
            "What’s your cheat meal hierarchy?",
        ),
        "deep": (
            "What does being strong mean to you lately — body, head, or both?",
            "When did movement start feeling like self-care for you?",
            "What’s a win you’re proud of that sounds small out loud?",
        ),
        "meeting_bridge": (
            "We should trade favorite routes or gyms — friendly competition optional.",
            "Recovery coffee after a walk counts as a plan — I’m in.",
            "If you’re up for it, we could do something active + eat after.",
        ),
    },
    "work": {
        "opener": (
            "What does your week usually look like — structured chaos or actual structure?",
            "Are you more ‘love what I do’ or ‘work is work, life is elsewhere’?",
            "What’s the part of your day that actually feels like yours?",
        ),
        "playful": (
            "Okay, important question 😄 inbox zero fantasy or inbox surrender reality?",
            "Meetings: useful or tax on your soul — be honest.",
            "Are you a ‘close the laptop at 6’ person or ‘it depends’?",
        ),
        "deep": (
            "What are you building or learning right now that matters to you?",
            "What would make work feel more human for you this year?",
            "When do you feel most proud of how you show up professionally?",
        ),
        "meeting_bridge": (
            "We should grab coffee and swap ‘work plot twists’ — I’ll bring the drama.",
            "If you want, we could do a chill coworking-coffee thing sometime.",
            "I’d love to hear more about what you do over something warm to drink.",
        ),
    },
    "books": {
        "opener": (
            "What are you reading right now — or what was the last thing that stuck?",
            "Fiction at night, non-fiction by day, or total chaos?",
            "Are you a one-book-at-a-time person or five half-started masterpieces?",
        ),
        "playful": (
            "Okay, important question 😄 ending matters more than the premise — yes or no?",
            "Do you dog-ear pages or is that a crime?",
            "What book do you recommend when you want someone to know you?",
        ),
        "deep": (
            "What story changed your mind about something?",
            "Do you read to escape, to learn, or to feel less alone?",
            "What author feels like a friend you’ve never met?",
        ),
        "meeting_bridge": (
            "We should do a bookstore-or-cafe swap — you pick, I’ll show up curious.",
            "I’ll trade you one book recommendation for one coffee.",
            "If we meet, I want your ‘if you only read one’ pick.",
        ),
    },
    "pets": {
        "opener": (
            "Do you have a pet, or are you more ‘I borrow other people’s dogs’?",
            "Team dog, team cat, or team ‘surprise me’?",
            "What’s the cutest thing an animal has done to you lately?",
        ),
        "playful": (
            "Important question 😄 pet photos: immediate send or strategic wait?",
            "Are you the strict parent or the one who sneaks treats?",
            "If your pet had a dating profile, what would the bio say?",
        ),
        "deep": (
            "What do animals give you that people sometimes don’t?",
            "Did you grow up with pets — did that shape you?",
            "What’s something you’ve learned from caring for an animal?",
        ),
        "meeting_bridge": (
            "If we meet, I’m hoping for a respectful pet intro — fair warning.",
            "Dog-walk coffee sounds dangerously wholesome and I’m into it.",
            "We should compare pet stories in person — I’ll bring patience for photos.",
        ),
    },
    "nightlife": {
        "opener": (
            "What’s your night-out style — low-key bar, dancing, or home with a good drink?",
            "Are you more ‘one good spot’ or ‘let’s see where the night goes’?",
            "What’s a night you still talk about?",
        ),
        "playful": (
            "Okay, important question 😄 dancing: yes, maybe, or only after one drink?",
            "Are you ‘last to leave’ or ‘I have a bedtime and boundaries’?",
            "Cocktails: adventurous order or same safe favorite?",
        ),
        "deep": (
            "What makes a night feel memorable for you — people, place, or energy?",
            "Do you recharge alone after social nights, or ride the high?",
            "What’s your relationship with FOMO lately?",
        ),
        "meeting_bridge": (
            "We should pick a chill spot and see if the vibe matches the chat.",
            "If you’re up for it, I’d love a low-pressure ‘one drink’ plan.",
            "Let’s trade favorite spots — I’ll let you choose first.",
        ),
    },
    "relationships": {
        "opener": (
            "What are you actually looking for on here — slow burn or see-what-happens?",
            "How do you like getting to know someone — texting first or meeting sooner?",
            "What makes a conversation feel ‘real’ to you early on?",
        ),
        "playful": (
            "Bold question in small font: texting chemistry or in-person spark first?",
            "Are you a ‘define things early’ or ‘let it breathe’ person?",
            "Green flags only: what’s one that makes you lean in?",
        ),
        "deep": (
            "What’s a green flag you didn’t expect you’d care about?",
            "What makes you feel safe when you’re getting to know someone?",
            "What’s something you’re trying to do differently in dating lately?",
        ),
        "meeting_bridge": (
            "I like how honest this chat feels — worth keeping it going offline sometime.",
            "If we keep vibing, we should swap a low-pressure plan.",
            "Coffee or a walk — your pick, no pressure.",
        ),
    },
    "art": {
        "opener": (
            "Are you more museums, street art, or ‘I just like pretty things’?",
            "What’s the last creative thing you saw that stuck with you?",
            "Do you make anything, or are you strictly an appreciator?",
        ),
        "playful": (
            "Okay, important question 😄 would you read the plaque or just take the photo?",
            "Are you ‘I have opinions about fonts’ or ‘I don’t notice’?",
            "Gallery day: power walk or slow wander?",
        ),
        "deep": (
            "What kind of art makes you feel something fast?",
            "Do you seek beauty on purpose, or does it find you?",
            "What’s something creative you wish you had more time for?",
        ),
        "meeting_bridge": (
            "We should pick a small gallery or market and wander with coffee.",
            "I’d love to hear what you’re into visually over a drink.",
            "Let’s trade ‘you have to see this’ spots sometime.",
        ),
    },
    "general": {
        "opener": (
            "Okay — what’s one thing you’re into lately that isn’t on your profile?",
            "What’s been the best tiny part of your week?",
            "Quick vibe check: are you more chaos-weekend or planned-weekend?",
        ),
        "playful": (
            "If we’re texting, I need to know: morning person or ‘please wait’? 😄",
            "What’s a small thing that made you smile recently?",
            "Important question: are you more ‘plans’ or ‘we’ll see’?",
        ),
        "deep": (
            "What are you genuinely curious about right now?",
            "What makes you feel most like yourself lately?",
            "What’s something you’re proud of that sounds small out loud?",
        ),
        "meeting_bridge": (
            "This is easy to talk to you — we should continue in person sometime.",
            "I like this energy — want a low-key coffee or walk soon?",
            "We should pick a tiny adventure and see if the chat holds up.",
        ),
    },
}


def _topic_seed_pack(topic_id: str) -> dict[str, tuple[str, ...]]:
    tid = topic_id if topic_id in TOPIC_SEEDS else "general"
    return TOPIC_SEEDS[tid]


def detect_conversation_topic(
    transcript_lines: list[tuple[str, str]],
) -> dict[str, Any]:
    """
    Heuristic topic + stage from recent text (role, text).
    Returns: topic, confidence, emotional_tone, flirt_level, conversation_stage
    """
    blob = " ".join((t or "").lower() for _, t in transcript_lines[-24:])
    if not blob.strip():
        return {
            "topic": "general",
            "confidence": 0.2,
            "emotional_tone": "neutral",
            "flirt_level": 0,
            "conversation_stage": "icebreaker",
        }

    scores: dict[str, int] = {}
    for tid, keys in TOPIC_KEYWORDS.items():
        c = sum(1 for k in keys if k in blob)
        if c:
            scores[tid] = c
    topic: TopicId = "general"
    confidence = 0.25
    if scores:
        topic = max(scores, key=lambda k: scores[k])  # type: ignore[assignment]
        top = scores[topic]
        confidence = min(0.95, 0.35 + top * 0.12)

    n = len(transcript_lines)
    if n <= 2:
        stage = "icebreaker"
    elif n <= 6:
        stage = "warming"
    elif n <= 14:
        stage = "connecting"
    else:
        stage = "deepening"

    tone = "neutral"
    if any(x in blob for x in ("lol", "haha", "😄", "😅", "lmao", "жарт", "смішн")):
        tone = "playful"
    elif any(x in blob for x in ("sad", "hard", "stress", "tired", "anxious", "важк", "втом")):
        tone = "tender"
    elif any(x in blob for x in ("love", "feel", "miss", "❤", "🥰", "кохан")):
        tone = "warm"

    flirt_level = 0
    if any(x in blob for x in ("😉", "😏", "cute", "attractive", "crush", "мил")):
        flirt_level = 2
    if topic in ("relationships", "nightlife") or "flirt" in blob:
        flirt_level = max(flirt_level, 1)
    if scores.get("humor") or tone == "playful":
        flirt_level = min(3, flirt_level + 1)

    return {
        "topic": topic,
        "confidence": round(confidence, 3),
        "emotional_tone": tone,
        "flirt_level": int(flirt_level),
        "conversation_stage": stage,
    }


def topic_context_for_prompt(meta: dict[str, Any], locale: str) -> str:
    """Short block for Gemini user prompt (English instructions; output still must be locale)."""
    topic = str(meta.get("topic") or "general")
    stage = str(meta.get("conversation_stage") or "")
    tone = str(meta.get("emotional_tone") or "")
    conf = float(meta.get("confidence") or 0)
    seeds = _topic_seed_pack(topic)
    ex_op = random.choice(seeds["opener"])
    ex_play = random.choice(seeds["playful"])
    ex_deep = random.choice(seeds["deep"])
    ex_br = random.choice(seeds["meeting_bridge"])
    base_header = (
        "TOPIC_INTELLIGENCE (use ideas, do NOT copy verbatim; translate to LANGUAGE; every variant needs a reply hook):\n"
        f"- detected_topic: {topic} (confidence ~{meta.get('confidence')})\n"
        f"- conversation_stage: {stage}\n"
        f"- emotional_tone: {tone}\n"
        f"- example_opener_seed: {ex_op}\n"
        f"- example_playful_seed: {ex_play}\n"
        f"- example_deep_seed: {ex_deep}\n"
        f"- example_meeting_bridge_seed: {ex_br}\n"
        f"- locale_hint: {locale}\n"
    )
    if conf < TOPIC_CONFIDENCE_LOW_THRESHOLD:
        return (
            base_header
            + "LOW_TOPIC_CONFIDENCE_MODE: thread may be shallow or off-topic — force specificity. "
            "Pick one angle (opener / playful / deep / soft plan) from the seeds above and make it feel human; "
            "avoid generic hobbies questions; end with something easy to answer.\n"
        )
    return base_header


def topic_fallback_variant(
    topic: str,
    variant: str,
    locale: str,
    *,
    last_partner_message: str | None = None,
) -> str:
    """Curated fallback line in English, or contextual UA (never English pools for ``uk``)."""
    loc = (locale or "en").strip().lower()
    if loc == "uk":
        from app.services.ai.conversation.contextual_fallback_triples import uk_reply_fallback_three_lines

        lines = uk_reply_fallback_three_lines(last_partner_message or "", continue_mode=True)
        v = (variant or "light").strip().lower()
        idx = 0 if v == "light" else 1 if v == "flirty" else 2
        return lines[idx]

    seeds = _topic_seed_pack(topic)
    v = (variant or "light").strip().lower()
    if v == "deep":
        pool = seeds["deep"]
    elif v == "flirty":
        pool = seeds["playful"]
    elif v == "light":
        pool = seeds["opener"]
    else:
        pool = seeds["playful"]

    return random.choice(pool)


def topic_anchor_line(
    topic: str, kind: Literal["opener", "playful", "deep", "meeting_bridge"], locale: str = "en"
) -> str:
    """Single curated line for low-confidence recovery or tooling."""
    seeds = _topic_seed_pack(topic)
    pool = seeds.get(kind) or seeds["opener"]
    line = random.choice(pool)
    if locale == "uk" and kind == "playful" and topic == "movies":
        if "thriller at night" in line:
            return "Важливе питання 😄 ти більше про трилер ввечері чи затишне кіно?"
    return line


def brain_line_quality_fail(
    text: str,
    *,
    variant: str,
    recent_lines: list[str],
    lang: str | None = None,
) -> str | None:
    """Return reason string if line should be rejected; None if ok (delegates to shared AI output rules)."""
    from app.services.ai.ai_output_validation import validate_chat_brain_line

    loc = (lang or "en").strip() or "en"
    salt = f"legacy_brain_fail:{variant}"
    return validate_chat_brain_line(text, variant=variant, recent_lines=recent_lines, lang=loc, salt=salt)
