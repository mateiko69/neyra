from app.services.antifraud import score_account_risk

def test_antifraud_flags_sparse_profile():
    result = score_account_risk({"bio": "", "photo_urls": "", "age": None})
    assert result["risk_score"] >= 20
