"""舞萌接入私服（MuNET）：绑定、b50、我、最近、成绩、解绑、切换、出图。离线（httpx.MockTransport），player_a 真实数据。"""
from __future__ import annotations

import io
import os

import httpx
import pytest
from PIL import Image

from core import privsrv as P
from core.privsrv import munet
from mai.bot.commands import Commands, Ctx, priv_username
from mai.bot.storage import UserStore
from mai.data.loader import CatalogStore
from mai.service import MaiService
from tests import munet_data as D

QQ = "10086"


def munet_transport(calls=None, privacy=0, routes=None):
    table = {"game=mai2": (200, D.profile_json("mai2", privacy=privacy)),
             "game=chusan": (200, D.profile_json("chusan", privacy=privacy)),
             "/mai2/rating": (200, D.rating_json()), "/mai2/playlog": (200, D.playlog_json()),
             "/chusan/rating": (200, D.chu_rating_json()), "/chusan/playlog": (200, D.chu_playlog_json()),
             **(routes or {})}

    def handler(req: httpx.Request):
        url = str(req.url)
        if calls is not None:
            calls.append(url)
        if "/u/nobody" in url:
            return httpx.Response(200, json={"error": 1, "message": "user not found"})
        for key, (status, body) in table.items():
            if key in url:
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


@pytest.fixture()
def env(tmp_path):
    store = UserStore(str(tmp_path / "mai"))
    catalog = CatalogStore(str(tmp_path / "mai"))
    catalog.load_local()
    svc = MaiService(store, catalog)
    calls: list = []
    svc.priv = P.Hub(str(tmp_path / "privsrv"), transport=munet_transport(calls))
    cmd = Commands(svc, require_consent=True, cache_minutes=10)
    return svc, cmd, calls


def text(r):
    return "\n".join(r.texts)


def test_username_parsing():
    assert priv_username("player_a") == "player_a"
    assert priv_username("@player_a") == "player_a"
    assert priv_username("https://portal.mumur.net/u/player_a/mai2") == "player_a"
    assert priv_username("") == "" and priv_username("a b") == "a"
    assert priv_username("<script>") == ""


async def test_bind_in_group_no_consent_needed(env):
    svc, cmd, calls = env
    r = await cmd.handle(Ctx(uid=QQ, private=False, admin=False), "绑定 munet @player_a")
    t = text(r)
    assert "MuNET 绑定成功" in t and "☆ＫΣｌｕｐ†☆" in t and "16001" in t and "/chu b50 munet" in t
    assert not r.recall                                     # 用户名不是凭据，不撤回
    assert svc.priv.bindings.get(QQ, "munet") == "player_a"
    assert svc.bound_regions(QQ) == ["munet"]
    assert svc.store.bound_regions(QQ) == []                # 没写进 NET 凭据库


async def test_bind_aliases_and_errors(env):
    _svc, cmd, _ = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    assert "MuNET 绑定成功" in text(await cmd.handle(ctx, "绑定 mu服 player_a"))
    assert "用法" in text(await cmd.handle(ctx, "绑定 munet"))
    assert "找不到用户「nobody」" in text(await cmd.handle(ctx, "绑定 munet nobody"))


async def test_b50_matches_server_and_uses_munet_split(env):
    svc, cmd, calls = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, "绑定 munet player_a")
    snap = await cmd._snapshot(QQ, "munet")
    b = snap.best50(svc.catalog)
    assert (len(b.old), len(b.new)) == (35, 15)
    assert (b.old_total, b.new_total, b.total) == (D.B35_SUM, D.B15_SUM, D.SERVER_RATING)
    assert b.region == "munet" and b.version == "CiRCLE PLUS"
    # 歌名用插件曲库的写法，能对上曲绘 / 查歌
    top = b.old[0]
    assert top.music_id == 11823 or top.song_id is not None
    assert all(s.song_id for s in b.old + b.new)
    # 文字版
    r = await cmd.handle(ctx, "b50 文字")
    t = text(r)
    assert "舞萌 MuNET B50 · CiRCLE PLUS" in t and "Rating 16001" in t and "计算值 16001" in t and "⚠" not in t


async def test_b50_cached_then_refresh(env):
    _svc, cmd, calls = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, "绑定 munet player_a")
    await cmd.handle(ctx, "b50 文字")
    n = len(calls)
    await cmd.handle(ctx, "b50 文字")
    assert len(calls) == n                                  # 10 分钟内用缓存
    r = await cmd.handle(ctx, "刷新")
    assert "已同步 MuNET：B35 + B15 共 50 条，Rating 16001（CiRCLE PLUS）" in text(r)
    assert len(calls) > n


async def test_me_recent_score(env):
    _svc, cmd, _ = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, "绑定 munet player_a")
    me = text(await cmd.handle(ctx, "我"))
    assert "☆ＫΣｌｕｐ†☆（MuNET · CiRCLE PLUS）" in me and "Rating 16001" in me and "B35 11255 + B15 4746" in me
    rec = text(await cmd.handle(ctx, "最近 2"))
    assert rec.startswith("最近游玩（MuNET）") and "99.0432" in rec
    sc = text(await cmd.handle(ctx, "成绩 11752"))
    assert "雨露霜雪" in sc and "100.5799" in sc
    miss = text(await cmd.handle(ctx, "成绩 834"))           # 不在 B50 里
    assert "只公开 B50 里的成绩" in miss


async def test_net_only_features_explain(env):
    _svc, cmd, _ = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, "绑定 munet player_a")
    assert "MuNET 只提供 B50 和最近 50 条记录" in text(await cmd.handle(ctx, "详情 1"))
    assert "MuNET 只提供" in text(await cmd.handle(ctx, "好友码 123456789012345"))


async def test_privacy_hidden_message(tmp_path):
    store = UserStore(str(tmp_path / "mai"))
    catalog = CatalogStore(str(tmp_path / "mai"))
    catalog.load_local()
    svc = MaiService(store, catalog)
    svc.priv = P.Hub(str(tmp_path / "p"), transport=munet_transport(privacy=munet.MAI2_HIDE_B35))
    cmd = Commands(svc, require_consent=True)
    ctx = Ctx(uid=QQ, private=True, admin=False)
    assert "绑定成功" in text(await cmd.handle(ctx, "绑定 munet player_a"))   # 资料没藏，能绑
    assert "设成了隐藏" in text(await cmd.handle(ctx, "b50"))


async def test_not_bound_message(env):
    _svc, cmd, _ = env
    t = text(await cmd.handle(Ctx(uid=QQ, private=True, admin=False), "b50 munet"))
    assert "/mai 绑定 munet" in t


async def test_unbind_keeps_shared_unless_named(env):
    svc, cmd, _ = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, "绑定 munet player_a")
    t = text(await cmd.handle(ctx, "解绑"))
    assert "没有可解绑的记录" in t and "/mai 解绑 munet" in t
    assert svc.priv.bindings.get(QQ, "munet") == "player_a"
    t = text(await cmd.handle(ctx, "解绑 munet"))
    assert "已解绑 MuNET" in t and "三个游戏一起解了" in t
    assert svc.bound_regions(QQ) == []


async def test_switch_between_cn_and_munet(env):
    svc, cmd, _ = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, "绑定 munet player_a")
    svc.store.set_creds(QQ, "cn", {"username": "someone"})       # 再绑个国服
    assert set(svc.bound_regions(QQ)) == {"munet", "cn"}
    assert "之后默认查MuNET" in text(await cmd.handle(ctx, "切换 munet"))
    assert cmd._region(QQ, None) == "munet"


async def test_theory_and_catalog_commands_borrow_jp(env):
    _svc, cmd, _ = env
    ctx = Ctx(uid=QQ, private=True, admin=False)
    r = await cmd.handle(ctx, "理论 munet 文字")
    assert text(r).startswith("日服理论 Rating")
    r = await cmd.handle(ctx, "查歌 11752 munet")
    assert "雨露霜雪" in text(r)


async def test_b50_image_uses_client_version(env, tmp_path):
    from mai.render import b50img as R
    svc, cmd, _ = env
    root = tmp_path / "render"
    (root / "themes" / "CiRCLE PLUS").mkdir(parents=True)
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, "绑定 munet player_a")
    snap = await cmd._snapshot(QQ, "munet")
    b = snap.best50(svc.catalog)
    R.share_versions(svc.catalog.db)
    png = R.B50Renderer(str(root), "Bot")(b, snap.profile, svc.catalog.db, snap.at)
    im = Image.open(io.BytesIO(png))
    assert im.width == R.W and im.height > 1000
    im.save(os.environ.get("MUNET_B50_OUT") or (tmp_path / "munet_b50.png"))


@pytest.mark.parametrize("t,want", [("舞萌munet b50", ("mai", "b50", "munet", "b50 munet")),
                                    ("中二b30mu服", ("chu", "b50", "munet", "b50 munet")),
                                    ("查一下我mu服中二最近", ("chu", "recent", "munet", "最近 munet")),
                                    ("国服中二b30", ("chu", "b50", "cn", "b50 国服"))])
def test_natural_language_server(t, want):
    from core import nl
    it = nl.rules(t)
    assert (it.game, it.action, it.server, nl.to_command(it)) == want
