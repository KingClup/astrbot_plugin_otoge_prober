import json
import os

import pytest

from arcaea.calc import (B50, Play, build_b50, fmt_ptt, parse_diff, play_rating,
                         score_for, score_modifier)
from arcaea.songdb import SongDB, build

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "arcaea_mini.json")


@pytest.mark.parametrize("score,mod", [
    (10_002_000, 2.0), (10_000_000, 2.0), (9_950_000, 1.75), (9_900_000, 1.5),
    (9_800_000, 1.0), (9_500_000, 0.0), (9_200_000, -1.0), (8_900_000, -2.0),
])
def test_modifier_matches_wiki_table(score, mod):
    assert score_modifier(score) == pytest.approx(mod)


def test_clear_bonus_and_track_lost():
    # 维基表：9,950,000 TC = 定数+1.95，TL = 定数+1.75
    assert play_rating(10.0, 9_950_000) == pytest.approx(11.95)
    assert play_rating(10.0, 9_950_000, cleared=False) == pytest.approx(11.75)
    assert play_rating(10.0, 9_950_000, legacy=True) == pytest.approx(11.75)
    assert play_rating(1.0, 5_000_000) == 0.0


def test_b50_formula_and_dedup():
    plays = [Play(f"s{i}", 2, 10_000_000, 10.0) for i in range(60)]
    plays.append(Play("s0", 2, 9_000_000, 10.0))           # 同谱面低分不顶掉高分
    b = build_b50(plays)
    assert len(b.plays) == 50
    # 全是 12.2：(50×12.2 + 10×12.2) / 60 = 12.2
    assert b.total == pytest.approx(12.2)
    assert b.floor == pytest.approx(12.2)


def test_b50_partial_and_gain():
    b = build_b50([Play("a", 2, 10_000_000, 11.0)])        # 13.2
    assert b.total == pytest.approx(13.2 * 2 / 60)
    g = b.gain_if(Play("b", 2, 10_000_000, 10.0))           # 12.2 进前 10 → ×2
    assert g == pytest.approx(12.2 * 2 / 60)
    assert b.gain_if(Play("a", 2, 9_000_000, 11.0)) == 0.0


def test_score_for_roundtrip():
    s = score_for(10.5, 12.0)
    assert play_rating(10.5, s) >= 12.0 - 1e-9
    assert play_rating(10.5, s - 1) < 12.0
    assert score_for(9.0, 12.0) is None


def test_misc():
    assert parse_diff("FTR") == 2 and parse_diff("byd") == 3 and parse_diff("x") is None
    assert fmt_ptt(12.999) == "12.99"


def test_songdb_build_and_find(tmp_path):
    d = json.load(open(FIX, encoding="utf-8"))
    songs = build(d["songlist"], d["consts"], d["alias"])
    t = songs["testify"]
    assert t.charts[3].level.endswith("+") or t.charts[3].const >= 12.0
    db = SongDB(str(tmp_path))
    db.load(d["songlist"], d["consts"], d["alias"],
            patch={"testify": [None, None, None, {"constant": 12.3, "old": False}, None]})
    assert db.const("testify", 3) == 12.3                   # 补丁优先
    assert db.find("Testify")[0].sid == "testify"
    assert db.find("grievous")[0].sid == "grievouslady"
    assert any(s.sid == "tempestissimo" for s, _ in db.charts_in(11.0, 12.5))
