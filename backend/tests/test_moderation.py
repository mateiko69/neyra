from app.services.moderation import moderate_text

def test_moderation_blocks_banned_word():
    result = moderate_text("This is a scam")
    assert result["allowed"] is False
