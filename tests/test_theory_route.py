from core.route import route


def r(t):
    x = route(t)
    return (x.game, x.argline) if x else None


def test_theory_phrases():
    assert r("国服中二理论ra") == ("chu", "理论 国服")
    assert r("中二日服理论值") == ("chu", "理论 日服")
    assert r("舞萌理论rating多少") == ("mai", "理论")
    assert r("查一下mai国际服的理论ra") == ("mai", "理论 国际服")
    assert r("国服舞萌理论ra是多少") == ("mai", "理论 国服")
    assert r("理论ra") == ("core", "理论")
    assert r("/理论ra") == ("core", "理论")
    assert r("/chu 理论 国服") == ("chu", "理论 国服")


def test_theory_chat_not_routed():
    assert r("理论上我能推分") is None
    assert r("我chovy") is None
    assert r("这个理论好像不对吧") is None
