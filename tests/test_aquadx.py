"""私服 AquaDX：公开接口按用户名；舞萌定数按玩家客户端版本取（含 AP 加分规则）；中二用 AquaDX 定数；未知谱面。
数据来自 aquadx.net 公开排行榜（名字已换掉）。离线（假服务器）。"""
from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest

from chuni.commands import ChuCommands
from chuni.service import ChuniService
from core import privsrv as P
from core.privsrv import aquadx
from mai.bot.commands import Commands as MaiCommands, Ctx
from mai.bot.storage import UserStore
from mai.data.loader import CatalogStore
from mai.privsrv import to_scores
from mai.service import MaiService
from tests import aquadx_data as A

QQ = "30001"
MORE = json.load(open(os.path.join(os.path.dirname(__file__), "aquadx_mai_more.json"), encoding="utf-8"))


def transport(calls=None, mai_summary=None, chu_summary=None, chu_rating=None):
    def handler(req: httpx.Request):
        url = str(req.url)
        if calls is not None:
            calls.append((req.method, req.url.path))
        if "username=nobody" in url:
            return httpx.Response(404, text="User not found")
        p = req.url.path
        if p.endswith("/card/user-games"):
            return httpx.Response(200, json={"mai2": {}, "chu3": {}, "ongeki": {}})
        if p.endswith("/mai2/user-summary"):
            return httpx.Response(200, json=mai_summary or A.mai_summary())
        if p.endswith("/mai2/user-rating"):
            return httpx.Response(200, json=A.mai_rating())
        if p.endswith("/chu3/user-summary"):
            return httpx.Response(200, json=chu_summary or A.chu_summary())
        if p.endswith("/chu3/user-rating"):
            r = A.chu_rating() if chu_rating is None else chu_rating
            return httpx.Response(200, json=r) if r else httpx.Response(400, text="No rating found")
        if p == "/d/mai2/00/all-music.json":
            return httpx.Response(200, json=A.mai_music())
        if p == "/d/chu3/00/all-music.json":
            return httpx.Response(200, json=A.chu_music())
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture(scope="module")
def db():
    import tempfile
    c = CatalogStore(tempfile.mkdtemp())
    c.load_local()
    return c.db


def best_of(rows):
    from core.privsrv.models import MaiBest, MaiScore
    from core.privsrv.models import MAI_FC
    conv = lambda r: MaiScore(music_id=r[0], level_index=r[1], achievement=r[3], fc=MAI_FC.get(r[4], ""),  # noqa: E731
                              rom_version=r[2])
    return MaiBest(old=[conv(r) for r in rows["b35"]], new=[conv(r) for r in rows["b15"]])


# ---------------------------------------------------------------- 舞萌：版本定数 + AP 加分规则

def test_mai_old_client_exact_without_ap_bonus(db):
    """排行榜第 13 名，客户端 1.55（PRiSM PLUS）：用 PRiSM PLUS 的定数、不加 AP 分 → 16551 = 显示值。"""
    p = MORE["rank13"]
    scores, _ = to_scores(best_of(p), db, "PRiSM PLUS")
    assert sum(s.rating for s in scores) == p["rating"] == 16551


def test_mai_ap_bonus_from_circle(db):
    from mai.privsrv import ap_bonus_on
    assert not ap_bonus_on(db, "PRiSM PLUS") and ap_bonus_on(db, "CiRCLE") and ap_bonus_on(db, "")


def test_mai_unknown_charts_listed(db):
    """第 1 名的 B50 里有 9 张官方曲库和 AQUA 曲目表都没有的谱：定数空着、rating 0、标「未知谱面」。"""
    best = aquadx.parse_mai_rating(A.mai_rating(), A.mai_music())
    scores, split = to_scores(best, db, "CiRCLE")
    unknown = [s for s in scores if s.ds is None]
    assert len(unknown) == 8 and all(s.title.startswith("未知谱面") and s.rating == 0 for s in unknown)
    hinted = next(s for s in scores if s.music_id == 15025)       # AQUA 曲目表有 → 用它的定数
    assert hinted.ds == 14.9 and hinted.rating > 0
    assert len(split["old"]) == 35 and len(split["new"]) == 15


def test_mai_lamps_from_music_list():
    best = aquadx.parse_mai_rating(A.mai_rating())
    s = best.old[3]                       # 803 Re:MASTER comboStatus 4
    assert (s.music_id, s.fc, s.dx_score, s.rom_version) == (803, "app", 2421, 19993)


# ---------------------------------------------------------------- 中二

def test_chu_matches_display():
    from chuni.models import Difficulty, Score
    from chuni.rating import B50
    best = aquadx.parse_chu_best(A.chu_summary(), A.chu_rating(), A.chu_music())
    assert (len(best.best), len(best.new)) == (30, 20)
    conv = lambda xs: [Score(song_id=s.music_id, title=s.title, difficulty=Difficulty(s.level_index), score=s.score,  # noqa: E731
                             const=s.const) for s in xs]
    assert str(B50(best=conv(best.best), new=conv(best.new)).total) == "17.42"
    assert best.best[0].full_combo and best.best[0].const == 15.7


def test_chu_no_composition():
    empty = {**A.chu_summary(), "ratingComposition": {"best30": "", "new": "", "recent10": "1:3:1000000"}}
    with pytest.raises(P.PrivNotFound, match="还没有你的中二 rating 构成"):
        aquadx.parse_chu_best(empty, None, {})
    old = aquadx.parse_chu_best(empty, {"best30": [["982", "3", "1009205"]], "recent10": [["1086", "3", "1009222"]]}, {})
    assert [s.music_id for s in old.best] == [982] and [s.music_id for s in old.new] == [1086]


def test_profile_and_recent():
    p = aquadx.parse_profile(A.chu_summary(), "chusan", "player_b")
    assert (p.name, p.rating, p.rom_version, p.server_rank) == ("玩家乙", 1742, "2.45.00", 1)
    plays = aquadx.parse_mai_recent(A.mai_summary())
    assert plays[0].played_at == "2026-08-08T13:56:41" and plays[0].new_record
    assert aquadx.parse_chu_recent(A.chu_summary())[0].score == 1009486


def test_not_found(tmp_path):
    hub = P.Hub(str(tmp_path), transport=transport())
    with pytest.raises(P.PrivNotFound, match="找不到用户"):
        asyncio.run(hub.client("aqua").profile("nobody", "mai2"))


# ---------------------------------------------------------------- 指令

async def test_commands_both_games(tmp_path, monkeypatch):
    store = UserStore(str(tmp_path / "mai"))
    catalog = CatalogStore(str(tmp_path / "mai"))
    catalog.load_local()
    msvc = MaiService(store, catalog)
    hub = P.Hub(str(tmp_path / "privsrv"), transport=transport())
    msvc.priv = hub
    mcmd = MaiCommands(msvc)
    ctx = Ctx(uid=QQ, private=False, admin=False)          # 用户名不是凭据：群里也能绑
    t = "\n".join((await mcmd.handle(ctx, "绑定 aqua player_a")).texts)
    assert "AquaDX 绑定成功：玩家甲（player_a），舞萌 Rating 16756" in t
    t = "\n".join((await mcmd.handle(ctx, "b50 aqua 文字")).texts)
    assert "舞萌 AquaDX B50 · CiRCLE" in t and "未知谱面" in t and "Rating 16756" in t
    csvc = ChuniService(tmp_path / "chu")

    async def no_net(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(csvc.songdb, "ensure_loaded", no_net)
    csvc.priv = hub
    ccmd = ChuCommands(csvc, tmp_path / "chu", renderer=None, cooldown=0)
    t = "\n".join((await ccmd.handle(ctx, "b50 aqua 文字")).texts)     # 舞萌绑的，中二直接查
    assert "计算 rating：17.42" in t and "AquaDX 显示：17.42" in t
    assert "（AquaDX · Ver.2.45）" in "\n".join((await ccmd.handle(ctx, "我")).texts)


# ---------------------------------------------------------------- 404：没这个人 vs 这个人没玩过这个游戏

def test_404_user_exists_but_no_game_data():
    def handler(req: httpx.Request):
        if req.url.path.endswith("/card/user-games"):
            return httpx.Response(200, json={"mai2": {"name": "X"}})
        return httpx.Response(404, text="User not found")
    import tempfile
    hub = P.Hub(tempfile.mkdtemp(), transport=httpx.MockTransport(handler))
    c = aquadx.AquadxClient(hub)
    with pytest.raises(P.PrivNotFound, match="还没有中二记录"):
        asyncio.run(c.chu_best({"username": "maionly"}))


def test_404_no_such_user():
    import tempfile
    hub = P.Hub(tempfile.mkdtemp(), transport=httpx.MockTransport(lambda req: httpx.Response(404, text="User not found")))
    c = aquadx.AquadxClient(hub)
    with pytest.raises(P.PrivNotFound, match="找不到用户"):
        asyncio.run(c.chu_best({"username": "nobody"}))
