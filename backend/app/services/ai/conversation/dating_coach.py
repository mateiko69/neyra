from __future__ import annotations

from app.services.ai.conversation.conversation_analyzer import ConversationAnalyzer


def coach_heuristic(messages: list[str]) -> dict:
    """Rule-based coach guidance when LLM is unavailable."""
    msgs = [m.strip() for m in (messages or []) if (m or "").strip()]
    if not msgs:
        return {
            "tone": "Теплий і спокійний. Почни з короткого привітання й одного конкретного питання про них.",
            "ask_next": "Запитай про щось з їхнього профілю або останньої репліки — щоб було видно, що ти слухаєш.",
            "avoid": "Довгі монологи, натискання на зустріч одразу й низка сухих «ок» підряд.",
        }

    a = ConversationAnalyzer.analyze_conversation(msgs)
    flags = set(a.flags or [])

    if a.energy_level == "high":
        tone = "Легкий і зацікавлений: підтримай темп, але не перехльостуй поверхневими компліментами."
    elif a.energy_level == "low":
        tone = "М’який і без тиску: покажи, що тобі комфортно чекати й слухати."
    else:
        tone = "Рівний і любопитний: одна коротка думка + одне відкрите питання."

    if "short_replies" in flags:
        ask_next = "Спрости питання: краще одне просте «що саме ти маєш на увазі під…?» ніж три питання в одному повідомленні."
    elif "dry_tone" in flags:
        ask_next = "Додай трохи людського контексту (одне речення) і запитай про їхній досвід, не про оцінку."
    else:
        ask_next = "Підхопи деталь з останнього повідомлення і запитай «чому» або «як це було» — глибше, але без допиту."

    avoid = "Не подвоюй повідомлення з нетерпінням, не перекладай розмову в інтерв’ю з чекліста."
    if a.risk_of_drop >= 60:
        avoid += " Уникай тиску «давай швидко» і великих ультиматумів у чаті."
    if "short_replies" in flags:
        avoid += " Не засипай серією коротких пінгів «ти тут?»."

    return {"tone": tone, "ask_next": ask_next, "avoid": avoid}
