def score_account_risk(profile_data: dict) -> dict:
    risk = 0
    reasons = []
    if not profile_data.get("bio"):
        risk += 10
        reasons.append("Empty bio")
    if len(profile_data.get("photo_urls", "").split(",")) <= 1:
        risk += 10
        reasons.append("Too few photos")
    if profile_data.get("age") is None:
        risk += 5
        reasons.append("Missing age")
    if "telegram" in profile_data.get("bio", "").lower() or "whatsapp" in profile_data.get("bio", "").lower():
        risk += 20
        reasons.append("External contact too early")
    return {"risk_score": min(risk, 100), "reasons": reasons}
