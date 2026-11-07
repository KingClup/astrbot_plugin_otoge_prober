"""O.N.G.E.K.I. rating / constants / AquaDX parsing.

The AquaDX fixture is a public ranking player (name replaced) on client 1.51
(Re:Fresh); the server shows 21.202.
"""
import json
from pathlib import Path

import pytest
from ongeki.rating import fmt as rating_fmt

from ongeki import aquadx, rating, versions
from ongeki.models import GekiChart
from ongeki.music import OngekiMusicDB

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "tests" / "data_ongeki"


@pytest.fixture(scope="module")
def db():
    return OngekiMusicDB.load(ROOT / "ongeki" / "data" / "ongeki_consts.json")


def _lamp_rows():
    keys = ["musicId", "level", "isFullCombo", "isAllBreake", "isFullBell",
            "techScoreMax", "platinumScoreStar", "platinumScoreMax"]
    raw = (D / "aqua_ongeki_lamps.txt").read_text().strip().split(",")
    return [dict(zip(keys, map(int, x.split(":")))) for x in raw]


def _all_music():
    meta = {}
    for line in (D / "aqua_ongeki_music.txt").read_text(encoding="utf-8").splitlines():
        p = line.split("|")
        meta[p[0]] = dict(name=p[1], composer=p[2], ver=int(p[3]), lunatic=bool(int(p[4])),
                          notes=[{"lv": float(v)} for v in p[5].split("/")])
    return meta


@pytest.fixture(scope="module")
def summary():
    return json.loads((D / "aqua_ongeki_summary.json").read_text(encoding="utf-8"))


# ---------- rating math ----------

@pytest.mark.parametrize("score,offset", [
    (1_010_000, 2000), (1_007_500, 1750), (1_000_000, 1250), (990_000, 750),
    (970_000, 0), (900_000, -4000), (800_000, -6000),
])
def test_score_part_anchors(score, offset):
    assert rating.score_part(13.0, score) == 13000 + offset


def test_score_part_slopes():
    # SSS+..max: +0.001 per 10 points; SSS: per 15; SS: per 20
    assert rating.score_part(12.0, 1_007_510) == 12000 + 1751
    assert rating.score_part(12.0, 1_000_015) == 12000 + 1251
    assert rating.score_part(12.0, 990_020) == 12000 + 751
    assert rating.score_part(12.0, 1_000_014) == 12000 + 1250   # truncated


def test_score_part_low_scores():
    assert rating.score_part(12.0, 650_000) == (6000 * 150_000) // 300_000
    assert rating.score_part(12.0, 400_000) == 0
    assert rating.score_part(3.0, 820_000) == 0   # never negative


def test_wiki_example_no_limit_red_force():
    # wiki: const 12.4, 1,009,214, AB + FB -> 14.971
    assert rating.ts_rate(12.4, 1_009_214, fc=True, ab=True, fb=True) == 14971


def test_bonuses():
    assert rating.ts_rate(13.0, 1_010_000, fc=True, ab=True, fb=True) == 13000 + 2700
    # FC -> AB is +0.200, the score mark comes from the best score, not this one
    assert rating.ts_rate(13.0, 995_000, best_score=1_008_000, fc=True) == \
        rating.score_part(13.0, 995_000) + 300 + 100


def test_platinum():
    assert rating.ps_rate(12.0, 3) == 432        # wiki example: 0.432
    assert rating.ps_rate(12.7, 6) == rating.ps_rate(12.7, 5)
    assert rating.ps_rate(15.0, 0) == 0
    assert rating.stars_of(98, 100) == 5 and rating.stars_of(9399, 10000) == 0


def test_old_rate():
    assert rating.old_rate(13.0, 1_010_000) == 15000
    assert rating.old_rate(13.0, 970_000) == 13000
    assert rating.old_rate(13.0, 900_000) == 9000


def test_fmt():
    assert rating.fmt(21202) == "21.202" and rating.fmt(5) == "0.005"


# ---------- versions ----------

def test_versions():
    assert versions.parse_client("1.51.00") == 151
    assert versions.parse_client(1060) == 160
    assert versions.name(151) == "Re:Fresh"
    assert versions.name(160) == "Re:Fresh Act.2"
    assert versions.name(145) == "bright MEMORY Act.3"
    assert versions.const_table(151) == 150 and versions.const_table(160) == 160
    assert versions.const_table(130) == 145
    assert versions.is_new_song(160, 151) and versions.is_new_song(150, 160)
    assert not versions.is_new_song(145, 151)
    assert versions.is_new_song(145, 145) and not versions.is_new_song(140, 145)


# ---------- constants ----------

def test_constants_follow_client_version(db):
    s = db.match("Λzure Vixen", "かめりあ")
    assert s.const(3, 151) == 15.1      # corrected Re:Fresh value
    assert s.const(3, 160) == 15.1
    old = db.match("World Vanquisher")
    # changed with Re:Fresh Act.2
    assert old.const(2, 151) != old.const(2, 160)


def test_lunatic_and_bonus(db):
    lun = db.match("MEGALOVANIA", lunatic=True)
    assert lun is not None and lun.lunatic and lun.const(10, 151) is not None
    assert db.match("MEGALOVANIA", lunatic=False) is None or not db.match("MEGALOVANIA").lunatic


def test_all_fixture_songs_match(db):
    for mid, m in _all_music().items():
        assert db.match(m["name"], m["composer"], lunatic=m["lunatic"]) is not None, m["name"]


# ---------- AquaDX ----------

def test_parse_items():
    assert aquadx.parse_items("1:3:1000000:5:2000,bad,,2:10:990000") == [
        (1, 3, 1000000, 5, 2000), (2, 10, 990000)]


def test_parse_lamps_caps_score():
    lp = aquadx.parse_lamps([{"musicId": 1, "level": 3, "techScoreMax": 1010002,
                              "isAllBreake": True, "isFullCombo": True}])
    assert lp[(1, 3)].best_score == 1_010_000 and lp[(1, 3)].ab


def test_music_ids(summary):
    ids = aquadx.music_ids(summary)
    assert 1097 in ids and 8169 in ids and len(ids) == len(set(ids))


def test_aquadx_public_player_matches_site(db, summary):
    b = aquadx.build_best(summary, _lamp_rows(), _all_music(), db)
    assert b.refresh and b.version_name == "Re:Fresh"
    assert (len(b.new), len(b.best), len(b.plat)) == (10, 50, 50)
    assert b.unknown == []
    assert b.shown == 21202
    assert b.calc == 21202


def test_aquadx_lamps_used(db, summary):
    b = aquadx.build_best(summary, _lamp_rows(), _all_music(), db)
    first = b.best[0]                       # 天狗の落とし文 LUNATIC 1,008,484, AB + FB
    assert first.diff_name == "LUN" and first.lamp == "AB" and first.fb
    assert first.rate == rating.ts_rate(first.const, 1_008_484, fc=True, ab=True, fb=True)


def test_aquadx_without_lamps_is_lower(db, summary):
    b = aquadx.build_best(summary, [], _all_music(), db)
    assert b.calc < 21202     # missing FB/FC/AB bonuses are not invented


def test_unknown_chart_not_counted(db):
    summ = {"name": "X", "rating": 15000, "lastVersion": "1.51.00",
            "ratingComposition": {"new10": "", "best50": "99999:3:1007500:0:0", "pscore50": ""}}
    b = aquadx.build_best(summ, [], {}, db)
    assert len(b.unknown) == 1 and b.calc == 0


def test_old_system(db):
    summ = {"name": "X", "rating": 15000, "lastVersion": "1.45.00",
            "ratingComposition": {"best30": "1097:3:1007500", "new15": "", "recent10": ""}}
    meta = {"1097": {"name": "Λzure Vixen", "composer": "かめりあ", "ver": 1050,
                     "notes": [{"lv": 6}, {"lv": 9.7}, {"lv": 13.7}, {"lv": 15.1}]}}
    b = aquadx.build_best(summ, [], meta, db)
    assert not b.refresh and b.calc is None
    assert b.best[0].rate == rating.old_rate(b.best[0].const, 1_007_500)


def test_chart_lamp_names():
    c = GekiChart(1, 3, "t", 1_010_000, const=13.0, ab=True, fc=True)
    assert c.lamp == "AB+" and c.rank == "SSS+"
    assert GekiChart(1, 3, "t", 990_000, const=13.0, fc=True).lamp == "FC"


def _players_bc():
    keys = ["musicId", "level", "isFullCombo", "isAllBreake", "isFullBell",
            "techScoreMax", "platinumScoreStar", "platinumScoreMax"]
    out = {}
    for block in (D / "aqua_ongeki_players_bc.txt").read_text().split("@")[1:]:
        lines = block.strip().split("\n")
        tag, ver, shown = lines[0].split("|")
        f = dict(l.split("=", 1) for l in lines[1:])
        summ = {"name": tag, "rating": int(shown), "lastVersion": ver,
                "ratingComposition": {"new10": f["N"], "best50": f["B"], "pscore50": f["P"]}}
        rows = [dict(zip(keys, map(int, x.split(":")))) for x in f["L"].split(",")]
        out[tag] = (summ, rows)
    return out


def test_aquadx_player_on_152_matches_site(db):
    summ, rows = _players_bc()["C"]
    b = aquadx.build_best(summ, rows, _all_music(), db)
    assert b.version_name == "Re:Fresh" and b.unknown == []
    assert b.calc == b.shown == 19685


def test_aquadx_player_on_160_within_0_001(db):
    # Act.2 client: uses the newest constant table. Off by 0.001 (one bonus the
    # stored rating has not caught up with, most likely); the page shows both values.
    summ, rows = _players_bc()["B"]
    b = aquadx.build_best(summ, rows, _all_music(), db)
    assert b.version_name == "Re:Fresh Act.2" and b.unknown == []
    assert len(b.plat) == 30          # 20 padding entries dropped
    assert abs(b.calc - b.shown) <= 1


# ---------- MuNET (shape from the portal's front-end code; data re-shaped from the AquaDX fixture) ----------

from ongeki import munet


def _as_munet(summary, lamp_rows, meta):
    comp = summary["ratingComposition"]

    def items(s):
        return [{"musicId": t[0], "level": t[1], "score": t[2],
                 "platinumScoreStar": t[3] if len(t) > 3 else 0} for t in aquadx.parse_items(s)]
    rank = lambda s: 12 if s >= 1_007_500 else 11 if s >= 1_000_000 else 10 if s >= 990_000 else 9
    return {"data": {
        "bestOld": items(comp["best50"]), "bestNew": items(comp["new10"]), "hot": items(comp["pscore50"]),
        "musicDetails": [{"id": int(k), "name": v["name"], "artist": v["composer"]} for k, v in meta.items()],
        "userDetails": [{"musicId": r["musicId"], "level": r["level"], "isFullCombo": bool(r["isFullCombo"]),
                         "isAllBreake": bool(r["isAllBreake"]), "isFullBell": bool(r["isFullBell"]),
                         "techScoreRank": rank(r["techScoreMax"])} for r in lamp_rows],
    }}


def test_munet_shape_gives_same_rating(db, summary):
    resp = _as_munet(summary, _lamp_rows(), _all_music())
    b = munet.build_best(resp, db, refresh=True, client=151, player="P", shown=21202)
    assert (len(b.new), len(b.best), len(b.plat)) == (10, 50, 50)
    assert b.unknown == [] and b.calc == 21202


def test_munet_old_system_and_padding(db):
    resp = {"data": {"bestOld": [{"musicId": 1097, "level": 3, "score": 1007500}, {"musicId": 0}],
                     "bestNew": [], "hot": [{"musicId": 1097, "level": 3, "score": 1000000}],
                     "musicDetails": [{"id": 1097, "name": "Λzure Vixen"}], "userDetails": []}}
    b = munet.build_best(resp, db, refresh=False, client=145)
    assert not b.refresh and len(b.best) == 1 and len(b.recent) == 1
    assert b.best[0].rate == rating.old_rate(b.best[0].const, 1_007_500)


def test_munet_unknown_song(db):
    resp = {"data": {"bestOld": [{"musicId": 5, "level": 3, "score": 1000000}]}}
    b = munet.build_best(resp, db, refresh=True)
    assert len(b.unknown) == 1 and b.best[0].title == "#5"


def test_munet_client_version():
    assert munet.client_version({"data": {"ongeki": {"lastRomVersion": "1.60.00"}}}) == 160
    assert munet.client_version({}) is None


# ---------- text ----------

from ongeki import text


def test_text_refresh(db, summary):
    b = aquadx.build_best(summary, _lamp_rows(), _all_music(), db)
    out = text.render(b)
    assert out.splitlines()[0] == "音击 · AquaDX · Re:Fresh（1.51）"
    assert "Rating 21.202" in out and "计算" not in out.splitlines()[2]
    assert "── 新曲 10（均 " in out and "…还有 35 首" in out and "…还有 40 首" in out
    st = b.frame_stats()
    # 三段的贡献加起来就是 rating（各段分别截断，最多差 0.002）
    assert abs(sum(v["contrib"] for v in st.values()) - b.calc) <= 2
    assert st["new"]["avg"] == st["new"]["sum"] // st["new"]["n"]
    assert f"+{rating_fmt(st['plat']['contrib'])}" in out
    assert "天狗の落とし文 feat. ｙｔｒ [LUN 14.9] 1,008,484 SSS+ AB FB →" in out


def test_text_shows_difference_and_unknown(db):
    summ = {"name": "X", "rating": 15000, "lastVersion": "1.51.00",
            "ratingComposition": {"new10": "", "best50": "99999:3:1007500:0:0", "pscore50": ""}}
    out = text.render(aquadx.build_best(summ, [], {}, db))
    assert "Rating 15.000（计算 0.000，-15.000）" in out
    assert "有 1 张谱没有定数" in out and "（未知谱面）" in out


def test_text_old_system(db):
    summ = {"name": "X", "rating": 15000, "lastVersion": "1.45.00",
            "ratingComposition": {"best30": "1097:3:1007500", "new15": "", "recent10": "1097:3:1000000"}}
    out = text.render(aquadx.build_best(summ, [], {"1097": {"name": "Λzure Vixen", "notes": [{"lv": 6}, {"lv": 9.7}, {"lv": 13.7}, {"lv": 15.1}]}}, db))
    assert "bright MEMORY Act.3（1.45）" in out and "旧版规则" in out and "── 最近 10 ──" in out


# ---------- fetch (fake HTTP) ----------

import asyncio
from ongeki import fetch


def _fake(routes):
    calls = []

    async def http(url, json=None):
        calls.append((url, json))
        for prefix, resp in routes.items():
            if url.startswith(prefix):
                return resp
        return 404, None
    return http, calls


def test_fetch_aquadx(db, summary):
    post, calls = _fake({
        fetch.AQUA_API + "/user-summary": (200, summary),
        fetch.AQUA_API + "/user-music-from-list": (200, _lamp_rows()),
    })
    get, _ = _fake({fetch.AQUA_MUSIC: (200, _all_music())})
    b = asyncio.run(fetch.aquadx_best(post, get, "player a", db))
    assert b.calc == 21202
    assert "username=player%20a" in calls[0][0] and 1097 in calls[1][1]


def test_fetch_aquadx_errors(db):
    post, _ = _fake({})
    with pytest.raises(fetch.NotFound):
        asyncio.run(fetch.aquadx_best(post, post, "x", db))
    post, _ = _fake({fetch.AQUA_API + "/user-summary": (200, {"ratingComposition": {}})})
    with pytest.raises(fetch.NoData, match="打一局再查"):
        asyncio.run(fetch.aquadx_best(post, post, "x", db))
    post, _ = _fake({fetch.AQUA_API + "/user-summary": (503, None)})
    with pytest.raises(fetch.ServerDown):
        asyncio.run(fetch.aquadx_best(post, post, "x", db))


def test_fetch_aquadx_without_lamps_still_works(db, summary):
    post, _ = _fake({fetch.AQUA_API + "/user-summary": (200, summary)})
    get, _ = _fake({fetch.AQUA_MUSIC: (200, _all_music())})
    b = asyncio.run(fetch.aquadx_best(post, get, "a", db))
    assert len(b.best) == 50 and b.calc < 21202


def test_fetch_munet(db, summary):
    resp = _as_munet(summary, _lamp_rows(), _all_music())
    get, calls = _fake({
        fetch.MUNET_API + "/p/ongeki/rating/new": (200, resp),
        fetch.MUNET_API + "/p": (200, {"data": {"ongeki": {"lastRomVersion": "1.51.00", "rating": 21.202}}}),
    })
    b = asyncio.run(fetch.munet_best(get, "p", db))
    assert b.calc == b.shown == 21202 and calls[1][0].endswith("/ongeki/rating/new")


def test_fetch_munet_hidden_or_empty(db):
    get, _ = _fake({fetch.MUNET_API + "/p": (403, None)})
    with pytest.raises(fetch.Hidden):
        asyncio.run(fetch.munet_best(get, "p", db))
    get, _ = _fake({fetch.MUNET_API + "/p/ongeki/rating/new": (200, {"data": {}}),
                    fetch.MUNET_API + "/p": (200, {"data": {}})})
    with pytest.raises(fetch.NoData):
        asyncio.run(fetch.munet_best(get, "p", db))
