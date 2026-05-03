from app.services.match_engine import MatchEngine

class Dummy:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

def test_match_engine_scores_common_interests():
    a = Dummy(interests="travel,coffee,music", lifestyle_tags="social,active", relationship_goal="relationship", city="Kyiv", min_preferred_age=20, max_preferred_age=35)
    b = Dummy(interests="travel,music,books", lifestyle_tags="social,creative", relationship_goal="relationship", city="Kyiv", age=27, bio="A strong profile bio with enough details to count.")
    score, reasons = MatchEngine.score(a, b)
    assert score > 0
    assert len(reasons) > 0
