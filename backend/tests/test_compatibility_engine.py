from app.domain.matching.compatibility_engine import CompatibilityEngine


class Dummy:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_shared_interests_increasing_score():
    engine = CompatibilityEngine()
    me = Dummy(interests="travel,coffee,music", lifestyle_tags="", relationship_goal="relationship", city="", min_preferred_age=None, max_preferred_age=None)
    other_no_overlap = Dummy(interests="books,art", lifestyle_tags="", relationship_goal="relationship", city="", age=28, bio="Bio with enough details to discuss.", photo_urls="", min_preferred_age=None, max_preferred_age=None)
    other_overlap = Dummy(interests="travel,music,books", lifestyle_tags="", relationship_goal="relationship", city="", age=28, bio="Bio with enough details to discuss.", photo_urls="", min_preferred_age=None, max_preferred_age=None)
    s1 = engine.evaluate(me, other_no_overlap).compatibility_score
    s2 = engine.evaluate(me, other_overlap).compatibility_score
    assert s2 > s1


def test_same_relationship_goal_increasing_score():
    engine = CompatibilityEngine()
    me = Dummy(interests="", lifestyle_tags="", relationship_goal="relationship", city="", min_preferred_age=None, max_preferred_age=None)
    other_same = Dummy(interests="", lifestyle_tags="", relationship_goal="relationship", city="", age=28, bio="Some bio content here.", photo_urls="")
    other_diff = Dummy(interests="", lifestyle_tags="", relationship_goal="casual", city="", age=28, bio="Some bio content here.", photo_urls="")
    s_same = engine.evaluate(me, other_same).score_breakdown["relationship_intent_score"]
    s_diff = engine.evaluate(me, other_diff).score_breakdown["relationship_intent_score"]
    assert s_same > s_diff


def test_incomplete_profiles_lowering_conversation_potential():
    engine = CompatibilityEngine()
    me = Dummy(interests="", lifestyle_tags="", relationship_goal="relationship", city="", min_preferred_age=None, max_preferred_age=None)
    other_rich = Dummy(
        interests="coffee,travel,music,climbing,films",
        lifestyle_tags="active,social",
        relationship_goal="relationship",
        city="Kyiv",
        age=28,
        bio="I love live music and weekend hikes. Ask me about my last trip! Favorite coffee spot in town?",
        photo_urls="a,b,c",
    )
    other_poor = Dummy(interests="", lifestyle_tags="", relationship_goal="", city="", age=28, bio="", photo_urls="")
    c_rich = engine.evaluate(me, other_rich).score_breakdown["conversation_potential_score"]
    c_poor = engine.evaluate(me, other_poor).score_breakdown["conversation_potential_score"]
    assert c_rich > c_poor


def test_age_outside_preference_reducing_score():
    engine = CompatibilityEngine()
    me = Dummy(interests="", lifestyle_tags="", relationship_goal="relationship", city="", min_preferred_age=25, max_preferred_age=30)
    other_in = Dummy(interests="", lifestyle_tags="", relationship_goal="relationship", city="", age=28, bio="Some bio content here.", photo_urls="a")
    other_out = Dummy(interests="", lifestyle_tags="", relationship_goal="relationship", city="", age=40, bio="Some bio content here.", photo_urls="a")
    s_in = engine.evaluate(me, other_in).score_breakdown["age_preference_score"]
    s_out = engine.evaluate(me, other_out).score_breakdown["age_preference_score"]
    assert s_in > s_out


def test_score_never_exceeding_bounds():
    engine = CompatibilityEngine()
    me = Dummy(interests="a,b,c,d,e,f", lifestyle_tags="x,y,z", relationship_goal="relationship", city="Kyiv", min_preferred_age=18, max_preferred_age=99)
    other = Dummy(interests="a,b,c,d,e,f", lifestyle_tags="x,y,z", relationship_goal="relationship", city="Kyiv", age=25, bio="A" * 500, photo_urls="1,2,3,4,5,6")
    res = engine.evaluate(me, other)
    assert 0 <= res.compatibility_score <= 100
    for v in res.score_breakdown.values():
        assert 0 <= v <= 100

