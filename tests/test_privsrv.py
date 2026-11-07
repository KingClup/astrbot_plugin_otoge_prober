"""私服公共层（core/privsrv）：MuNET 解析、版本、隐私、客户端、绑定。离线，用 player_a 的真实数据。"""
from __future__ import annotations

import asyncio
import tempfile

import httpx
import pytest

from chuni.models import Difficulty, Score as ChuScoreModel
from chuni.rating import B50
from core import privsrv as P
from core.privsrv import munet, servers
from mai.calc.rating import chart_rating
from tests import munet_data as D


def mai_total(scores):
    return sum(chart_rating(s.const, s.achievement, s.fc) for s in scores)


# ---------------------------------------------------------------- 舞萌

def test_mai_rating_matches_server():
    best = munet.parse_mai_rating(D.rating_json(), "1.66.00")
    assert (len(best.old), len(best.new)) == (35, 15)
    assert mai_total(best.old) == D.B35_SUM and mai_total(best.new) == D.B15_SUM
    assert mai_total(best.old) + mai_total(best.new) == D.SERVER_RATING


def test_mai_fields():
    best = munet.parse_mai_rating(D.rating_json(), "1.66.00")
    s = best.old[0]
    assert (s.music_id, s.kind, s.level_index, s.achievement) == (11752, "dx", 3, 1005799)
    assert (s.title, s.const, s.fc, s.fs, s.dx_score) == ("雨露霜雪", 14.6, "", "sync", 3320)
    assert best.old[2].fc == "fcp" and best.new[4].level_index == 4 and best.new[-1].fs == "fs"


def test_mai_utage_ignored():
    gc = next(s for s in munet.parse_mai_rating(D.rating_json(), "1.66.00").old if s.music_id == 456)
    assert gc.kind == "std" and gc.const == 14.8


@pytest.mark.parametrize("rom,want", [("1.50.00", 23), ("1.60.00", 25), ("1.66.00", 26), ("1.70.01", 27),
                                      ("", None), ("2.50.00", None)])
def test_mai_const_version(rom, want):
    assert munet.mai_const_version(rom) == want


def test_mai_const_follows_client():
    js = D.rating_json(const_override={11752: (28, 15.0)})
    assert munet.parse_mai_rating(js, "1.66.00").old[0].const == 14.6
    assert munet.parse_mai_rating(js, "1.75.00").old[0].const == 15.0
    assert munet.parse_mai_rating(js, "").old[0].const == 15.0


def test_mai_playlog():
    plays = munet.parse_mai_playlog(D.playlog_json())
    assert len(plays) == 3 and plays[1].title == "テスト曲" and plays[1].achievement == 990432


# ---------------------------------------------------------------- 中二

def chu_b50(best):
    conv = lambda xs: [ChuScoreModel(song_id=s.music_id, title=s.title, difficulty=Difficulty(s.level_index),
                                     score=s.score, const=s.const) for s in xs]
    return B50(best=conv(best.best), new=conv(best.new))


def test_chu_rating_matches_server():
    best = munet.parse_chu_rating(D.chu_rating_json(), "2.50.00")
    assert (len(best.best), len(best.new)) == (30, 17)
    assert str(chu_b50(best).total) == D.CHU_RATING


def test_chu_const_follows_client():
    js = D.chu_rating_json(old_const={2967: 14.0})
    assert munet.parse_chu_rating(js, "2.50.00").best[0].const == 15.5
    assert munet.parse_chu_rating(js, "2.45.00").best[0].const == 14.0


@pytest.mark.parametrize("rom,want", [("2.50.00", 25000), ("2.45.01", 24500), ("1.66.00", 10000 + 6600), ("", None)])
def test_chu_const_version(rom, want):
    assert munet.chu_const_version(rom) == want


def test_chu_fields_and_playlog():
    best = munet.parse_chu_rating(D.chu_rating_json(), "2.50.00")
    s = best.new[4]
    assert (s.title, s.score, s.full_combo, s.all_justice) == ("ALLNIGHT_DANCER", 1009811, True, True)
    plays = munet.parse_chu_playlog(D.chu_playlog_json())
    assert [p.title for p in plays] == ["ZegalltA", "Ignis Danse"] and plays[1].new_record


# ---------------------------------------------------------------- 资料 / 隐私

def test_profiles_both_games():
    mp, _ = munet.parse_profile(D.profile_json("mai2"), "player_a", "mai2")
    cp, _ = munet.parse_profile(D.profile_json("chusan"), "player_a", "chusan")
    assert (mp.rating, mp.rom_version, mp.server_rank) == (16001, "1.66.00", 780)
    assert (cp.name, cp.rating, cp.rom_version) == ("☆ＫΣｌｕｐ†☆", 1601, "2.50.00")


def test_profile_errors():
    with pytest.raises(P.PrivNotFound):
        munet.parse_profile({"error": 1}, "nobody", "mai2")
    js = D.profile_json()
    js["data"]["mai2"] = js["homepage"]["mai2"] = None
    with pytest.raises(P.PrivNotFound, match="还没有舞萌记录"):
        munet.parse_profile(js, "player_a", "mai2")
    with pytest.raises(P.PrivHidden):
        munet.parse_profile(D.profile_json(privacy=munet.HIDE["mai2"]), "player_a", "mai2")
    munet.parse_profile(D.profile_json("chusan", privacy=munet.HIDE["mai2"]), "player_a", "chusan")  # 只藏了舞萌


# ---------------------------------------------------------------- 版本名 / 登记表

def test_version_names():
    assert servers.mai_version_name("1.66.00") == "CiRCLE PLUS"
    assert servers.mai_version_name("1.70.00") == "MAGiCAL"
    assert servers.chu_version_name("2.50.00") == "Mate"
    assert servers.chu_version_name("2.45.00") == "" and servers.rom_label("2.45.00") == "Ver.2.45"
    assert servers.ALIASES["mu服"] == "munet" and servers.ALIASES["munet"] == "munet"


# ---------------------------------------------------------------- 客户端（httpx 假网络）

def make_hub(routes, tmp=None):
    calls = []

    def handler(req: httpx.Request):
        calls.append(str(req.url))
        for key, (status, body) in routes.items():
            if key in str(req.url):
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"error": 1})
    hub = P.Hub(tmp or tempfile.mkdtemp(), transport=httpx.MockTransport(handler))
    return hub, calls


def test_client_mai_and_chu():
    hub, calls = make_hub({"game=mai2": (200, D.profile_json("mai2")), "game=chusan": (200, D.profile_json("chusan")),
                           "/mai2/rating": (200, D.rating_json()), "/chusan/rating": (200, D.chu_rating_json())})
    c = hub.client("munet")
    prof, best = asyncio.run(c.mai_best("@player_a"))
    assert prof.rating == 16001 and mai_total(best.old + best.new) == 16001
    assert calls[0] == "https://apidashboard3-cf.mumur.net/api/v3/public/u/player_a?game=mai2"
    _p, cb = asyncio.run(c.chu_best("player_a"))
    assert str(chu_b50(cb).total) == "16.01"


@pytest.mark.parametrize("game,flag,what", [("mai2", munet.MAI2_HIDE_B35, "B35"), ("mai2", munet.MAI2_HIDE_RATING, "Rating"),
                                           ("chusan", munet.CHU_HIDE_N20, "N20")])
def test_client_hidden_skips_request(game, flag, what):
    hub, calls = make_hub({f"game={game}": (200, D.profile_json(game, privacy=flag))})
    c = hub.client("munet")
    with pytest.raises(P.PrivHidden, match=what):
        asyncio.run(c.mai_best("player_a") if game == "mai2" else c.chu_best("player_a"))
    assert len(calls) == 1


def test_client_http_errors():
    hub, _ = make_hub({"game=mai2": (502, {})})
    with pytest.raises(P.PrivError, match="HTTP 502"):
        asyncio.run(hub.client("munet").mai_best("player_a"))
    hub, calls = make_hub({})
    with pytest.raises(P.PrivNotFound):
        asyncio.run(hub.client("munet").profile("a/../b?x", "mai2"))
    assert "/u/a%2F..%2Fb%3Fx?game=mai2" in calls[0]


# ---------------------------------------------------------------- 绑定（舞萌中二共用）

def test_bindings_shared_and_persisted():
    root = tempfile.mkdtemp()
    hub = P.Hub(root)
    with pytest.raises(P.NotBoundPriv, match="/chu 绑定 munet"):
        hub.username("10001", "munet", "chu")
    hub.bindings.set("10001", "munet", "player_a", "☆ＫΣｌｕｐ†☆")
    again = P.Hub(root)
    assert again.username("10001", "munet", "mai") == "player_a" == again.username("10001", "munet", "chu")
    assert again.bindings.bound("10001") == ["munet"]
    assert again.bindings.remove("10001") == ["munet"] and again.bindings.bound("10001") == []


def test_munet_418_says_bots_not_allowed():
    """2026-11-07 实测：MuNET 对机器人发的请求一律 418。提示要说清楚，而不是「稍后再试」。"""
    import asyncio
    import pytest
    from core.privsrv.models import PrivError

    async def get(url):
        return 418, None
    c = munet.MunetClient(get)
    with pytest.raises(PrivError, match="不允许第三方查分工具"):
        asyncio.run(c.profile({"username": "player_a"}, "mai2"))
