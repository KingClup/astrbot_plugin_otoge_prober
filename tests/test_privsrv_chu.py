"""中二接入私服（MuNET）：共用绑定、b50（B30 + N20）、我、最近、成绩、解绑、出图。离线，player_a 真实数据。"""
from __future__ import annotations

import os

import pytest

from chuni.commands import ChuCommands, split_server
from chuni.service import ChuniService
from core import privsrv as P
from mai.bot.commands import Commands as MaiCommands, Ctx
from mai.bot.storage import UserStore
from mai.data.loader import CatalogStore
from mai.service import MaiService
from tests import munet_data as D
from tests.test_privsrv_mai import munet_transport

QQ = "10086"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    svc = ChuniService(tmp_path / "chu")

    async def no_net(*a, **k):        # 曲库在测试里不下载：歌名、等级用私服给的
        raise RuntimeError("offline")
    monkeypatch.setattr(svc.songdb, "ensure_loaded", no_net)
    calls: list = []
    hub = P.Hub(str(tmp_path / "privsrv"), transport=munet_transport(calls))
    svc.priv = hub
    cmd = ChuCommands(svc, tmp_path / "chu", renderer=None, tz="Australia/Sydney", cooldown=0)
    return svc, cmd, hub, calls


def text(r):
    return "\n".join(r.texts)


def test_aliases():
    assert split_server(["b50", "munet"])[0] == "munet"
    assert split_server(["mu服"])[0] == "munet"


async def test_bind_and_b50_matches_server(env):
    svc, cmd, hub, _ = env
    ctx = Ctx(uid=QQ, private=False, admin=False)
    t = text(await cmd.handle(ctx, "绑定 munet player_a"))
    assert "MuNET 绑定成功" in t and "16.01" in t and "/mai b50 munet" in t
    assert hub.bindings.get(QQ, "munet") == "player_a" and cmd.bound(QQ) == ["munet"]
    prof, b = await svc.b50_priv(QQ, "munet")
    assert (len(b.best), len(b.new)) == (30, 17)
    assert str(b.total) == D.CHU_RATING and prof.rating == 16.01 and b.version == "Mate"
    aj = next(s for s in b.new if s.title == "ALLNIGHT_DANCER")
    assert aj.combo_lamp.value == "AJ"
    t = text(await cmd.handle(ctx, "b50 文字"))
    assert "MuNET 显示：16.01" in t and "计算 rating：16.01" in t


async def test_one_binding_serves_both_games(env, tmp_path):
    svc, cmd, hub, _ = env
    store = UserStore(str(tmp_path / "mai"))
    catalog = CatalogStore(str(tmp_path / "mai"))
    catalog.load_local()
    msvc = MaiService(store, catalog)
    msvc.priv = hub                                         # 和中二同一个 Hub，就像 main.py 里那样
    mcmd = MaiCommands(msvc)
    ctx = Ctx(uid=QQ, private=True, admin=False)
    assert "MuNET 绑定成功" in text(await mcmd.handle(ctx, "绑定 munet player_a"))
    assert cmd.bound(QQ) == ["munet"]                       # 舞萌绑的，中二直接能查
    assert "Rating 16.01" in text(await cmd.handle(ctx, "我"))
    t = text(await cmd.handle(ctx, "解绑 munet"))
    assert "三个游戏一起解了" in t and msvc.bound_regions(QQ) == []


async def test_me_recent_refresh_score(env):
    _svc, cmd, _hub, calls = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, "绑定 munet player_a")
    me = text(await cmd.handle(ctx, "我"))
    assert "☆ＫΣｌｕｐ†☆（MuNET · Mate）" in me and "Rating 16.01" in me
    rec = text(await cmd.handle(ctx, "最近"))
    assert rec.startswith("（MuNET）") and "ZegalltA" in rec and "1,007,480" in rec
    n = len(calls)
    assert "已刷新 MuNET" in text(await cmd.handle(ctx, "刷新")) and len(calls) > n


async def test_unbind_all_keeps_shared(env):
    _svc, cmd, hub, _ = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, "绑定 munet player_a")
    t = text(await cmd.handle(ctx, "解绑"))
    assert "没有可解绑的记录" in t and "/chu 解绑 munet" in t and hub.bindings.get(QQ, "munet") == "player_a"


async def test_hidden_and_not_bound(env, tmp_path):
    _svc, cmd, _hub, _ = env
    t = text(await cmd.handle(Ctx(uid=QQ, private=True, admin=False), "b50 munet"))
    assert "/chu 绑定 munet" in t
    from core.privsrv import munet
    svc2 = ChuniService(tmp_path / "chu2")
    svc2.priv = P.Hub(str(tmp_path / "p2"), transport=munet_transport(privacy=munet.CHU_HIDE_B30))
    cmd2 = ChuCommands(svc2, tmp_path / "chu2", renderer=None, cooldown=0)
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd2.handle(ctx, "绑定 munet player_a")
    assert "设成了隐藏" in text(await cmd2.handle(ctx, "b50"))


async def test_b50_image(env, tmp_path):
    from chuni.b50img import render_b50
    svc, cmd, _hub, _ = env
    await cmd.handle(Ctx(uid=QQ, private=True, admin=False), "绑定 munet player_a")
    prof, b = await svc.b50_priv(QQ, "munet")
    out = tmp_path / "chu_munet.jpg"
    render_b50(prof.name, b, out, {}, version=b.version, server="munet", region_label=f"MuNET · {b.version}")
    assert out.stat().st_size > 10_000
    if os.environ.get("MUNET_CHU_OUT"):
        out.replace(os.environ["MUNET_CHU_OUT"])
