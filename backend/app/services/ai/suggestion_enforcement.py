from __future__ import annotations

from app.services.ai.ai_output_validation import pack_question_quota_met, validate_improve_reply_line
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.locale_rewrite import batch_translate_lines, enforce_text_locale
from app.services.ai.safety import safe_output_or_none

_IMPROVE_FALLBACK_EN = [
    "What part of that matters most to you right now?",
    "How would you want them to read between the lines here?",
    "If you simplified it to one sentence, what would you say?",
]


async def post_process_assist_openers(data: dict, locale: str | None) -> dict:
    loc = normalize_ai_request_locale(locale)
    by_type: dict[str, str] = {}
    for s in (data.get("suggestions") or [])[:8]:
        ot = str(s.get("type") or "").strip().lower()
        raw = safe_output_or_none(str(s.get("text") or "")) or ""
        text = (await enforce_text_locale(raw, loc)).strip()[:220]
        if ot in {"safe", "flirty", "smart"} and text:
            by_type.setdefault(ot, text)
    order = ("safe", "flirty", "smart")
    padded = [{"type": t, "text": by_type.get(t, "")} for t in order]
    if any(not x["text"] for x in padded):
        en_lines = [
            "Coffee or wine—what feels more like you today?",
            "Are you more of a planner or a ‘see what happens’ person?",
            "What’s been the best tiny moment of your week so far?",
        ]
        filled = await batch_translate_lines(en_lines, loc)
        for i, t in enumerate(order):
            if not padded[i]["text"]:
                padded[i]["text"] = (filled[i] if i < len(filled) else en_lines[i])[:220]
    try:
        rec = int(data.get("recommended_index") if data.get("recommended_index") is not None else 1)
    except (TypeError, ValueError):
        rec = 1
    rec = max(0, min(2, rec))
    return {"suggestions": padded, "recommended_index": rec}


async def post_process_wingman_replies(data: dict, locale: str | None) -> dict:
    loc = normalize_ai_request_locale(locale)
    salt = f"wingman_reply:{loc}"
    out: list[dict[str, str]] = []
    for s in (data.get("suggestions") or [])[:3]:
        st = str(s.get("style") or "safe").strip().lower()
        raw = safe_output_or_none(str(s.get("text") or "")) or ""
        text = (await enforce_text_locale(raw, loc)).strip()
        if st not in {"safe", "engaging", "slightly_bold"}:
            st = "safe"
        out.append({"text": text[:220], "style": st})
    while len(out) < 3:
        out.append({"text": "", "style": "safe"})
    filled_fb = await batch_translate_lines(_IMPROVE_FALLBACK_EN, loc)
    if any(not x["text"] for x in out):
        for i in range(3):
            if not out[i]["text"]:
                out[i]["text"] = (filled_fb[i] if i < len(filled_fb) else _IMPROVE_FALLBACK_EN[i])[:220]

    async def _swap_if_invalid(idx: int) -> None:
        peers = [out[j]["text"] for j in range(3) if j != idx]
        t = out[idx]["text"]
        if validate_improve_reply_line(t, lang=loc, index=idx, peer_texts=peers, salt=salt) is None:
            return
        for offset in (0, 1, 2):
            alt = _IMPROVE_FALLBACK_EN[(idx + offset) % 3]
            tr = await batch_translate_lines([alt], loc)
            cand = ((tr[0] if tr else alt) or alt)[:220]
            if validate_improve_reply_line(cand, lang=loc, index=idx, peer_texts=peers, salt=salt) is None:
                out[idx]["text"] = cand
                return

    for i in range(3):
        await _swap_if_invalid(i)

    pack = {"light": out[0]["text"], "flirty": out[1]["text"], "deep": out[2]["text"]}
    if not pack_question_quota_met(pack):
        for i in range(3):
            t = out[i]["text"]
            if "?" in t or "？" in t:
                continue
            alt = _IMPROVE_FALLBACK_EN[i]
            tr = await batch_translate_lines([alt], loc)
            cand = ((tr[0] if tr else alt) or alt)[:220]
            peers = [out[j]["text"] for j in range(3) if j != i]
            if validate_improve_reply_line(cand, lang=loc, index=i, peer_texts=peers, salt=salt) is None:
                out[i]["text"] = cand
                break
    return {"suggestions": out[:3]}


async def post_process_wingman_openers(data: dict, locale: str | None) -> dict:
    loc = normalize_ai_request_locale(locale)
    out: list[dict[str, str]] = []
    for s in (data.get("suggestions") or [])[:5]:
        raw = safe_output_or_none(str(s.get("text") or "")) or ""
        text = (await enforce_text_locale(raw, loc)).strip()
        out.append(
            {
                "text": text[:220],
                "style": str(s.get("style") or "fallback_safe"),
                "reason": str(s.get("reason") or "profile-based")[:140],
            }
        )
    while len(out) < 3:
        out.append({"text": "", "style": "fallback_safe", "reason": "safe fallback"})
    if any(not x["text"] for x in out[:3]):
        en_lines = [
            "I don’t want to start generic—what’s actually interesting in your life lately?",
            "Quick vibe check: are you more calm mornings or busy city energy?",
            "What’s one thing you’re into that you could talk about for way too long?",
        ]
        filled = await batch_translate_lines(en_lines, loc)
        for i in range(min(5, len(out))):
            if not out[i]["text"]:
                out[i]["text"] = (filled[i] if i < len(filled) else en_lines[min(i, 2)])[:220]
    return {"suggestions": out[:5]}
