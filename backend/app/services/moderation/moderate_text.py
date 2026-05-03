BANNED_WORDS = {"scam", "crypto guaranteed", "send nude", "escort"}


def moderate_text(text: str) -> dict:
    lowered = (text or "").lower()
    hits = [word for word in BANNED_WORDS if word in lowered]
    return {"allowed": len(hits) == 0, "flags": hits}

