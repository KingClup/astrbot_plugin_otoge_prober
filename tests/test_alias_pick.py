import os
import sys
from types import SimpleNamespace as N

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mai.data.fuzzy import Match, alias_pick, hardness  # noqa: E402


def mai_song(title, *ds):
    return N(title=title, charts=[N(ds=d, level="") for d in ds])


def chu_song(title, genre, *consts):
    return N(title=title, genre=genre, charts={i: N(const=c, level="") for i, c in enumerate(consts)})


def M(item, score=100, alias=True, name="我有抑郁症"):
    return Match(item=item, score=score, name=name, by_alias=alias)


def test_hardest_first_for_shared_nickname():
    a, b, c = mai_song("PANDORA PARADOXXX", 12.5, 14.9), mai_song("サヨナラフリーウェイ", 9.7, 12.6), \
        mai_song("INTERNET OVERDOSE", 13.0, 13.8)
    pick, others = alias_pick([M(b), M(c), M(a)])
    assert pick is a and others == [c, b]


def test_fuzzy_or_title_matches_still_ask():
    a, b = mai_song("A", 14.0), mai_song("B", 13.0)
    assert alias_pick([M(a, 90), M(b, 88)]) is None              # partial matches → let the user choose
    assert alias_pick([M(a, alias=False), M(b)]) is None          # one is the real title → not a pure nickname
    assert alias_pick([M(a)]) is None


def test_world_end_skipped_and_level_fallback():
    reg, we = chu_song("X", "VARIETY", 13.5), chu_song("X", "WORLD'S END", None)
    hard = chu_song("Y", "ORIGINAL", 15.2)
    is_we = lambda it: "WORLD" in it.genre  # noqa: E731
    pick, others = alias_pick([M(we), M(reg), M(hard)], skip=is_we)
    assert pick is hard and others == [reg]
    assert hardness(N(charts=[N(ds=None, level="14+")])) == 14.7
