"""落雪开发者 API：按 QQ 查国服（不用玩家的个人密钥）。离线 mock。"""
from __future__ import annotations

import httpx
import pytest

from core import lxns as LX
from mai.bot.commands import Commands, Ctx
from mai.bot.storage import UserStore
from mai.data.loader import CatalogStore
from mai.service import MaiService
from tests.test_cn import CHU_ROWS, MAI_PLAYER, MAI_ROWS, chu_fixture, mai_song_list

DEV = "DevToken0123456789abcdefghijklmnopqrstuvw="


def _mai_best_rows():
    rows = []
    for mid, title, typ, _ds, ver, ach, ra in MAI_ROWS:
        rows.append(({"id": mid % 10000, "song_name": title, "level": "14+", "level_index": 3, "achievements": ach,
                      "fc": None, "fs": None, "dx_score": 2500, "dx_star": 0, "dx_rating": ra,
                      "rate": "sss", "type": typ}, ver >= 25500))
    return {"standard_total": 0, "dx_total": 0,
            "standard": [r for r, new in rows if not new], "dx": [r for r, new in rows if new],
            "standard_selections": [], "dx_selections": []}


def _chu_bests():
    _songs, scores, _player = chu_fixture()
    new_ids = {i for i, *_x, v in CHU_ROWS if v >= 23000}
    rated = [s for s in scores if s["level_index"] < 5]
    return {"bests": [s for s in rated if s["id"] not in new_ids], "new_bests": [s for s in rated if s["id"] in new_ids],
            "selections": []}


def dev_handler(calls=None):
    songs, _scores, chu_player = chu_fixture()

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if calls is not None:
            calls.append(path)
        if path.endswith("/song/list"):
            if "/chunithm/" in path:
                return httpx.Response(200, json={"songs": songs, "versions": [{"title": "x", "version": 23000}]})
            return httpx.Response(200, json=mai_song_list())
        if req.headers.get("authorization") != DEV:
            return httpx.Response(401, json={"success": False, "code": 401, "message": "bad dev token"})
        game = "maimai" if "/maimai/" in path else "chunithm"
        player = MAI_PLAYER if game == "maimai" else {**chu_player, "upload_time": "2026-11-02T00:00:00Z"}
        if "/player/qq/" in path:
            qq = path.rsplit("/", 1)[1]
            if qq == "10003":
                return httpx.Response(403, json={"success": False, "code": 403, "message": "privacy"})
            if qq != "10001":
                return httpx.Response(404, json={"success": False, "code": 404, "message": "player not found"})
            return httpx.Response(200, json={"success": True, "code": 200, "data": player})
        fc = str(player["friend_code"])
        if path.endswith(f"/player/{fc}"):
            return httpx.Response(200, json={"success": True, "code": 200, "data": player})
        if path.endswith(f"/player/{fc}/bests"):
            data = _mai_best_rows() if game == "maimai" else _chu_bests()
            return httpx.Response(200, json={"success": True, "code": 200, "data": data})
        return httpx.Response(404, json={"success": False, "code": 404, "message": "nope"})
    return httpx.MockTransport(handler)


@pytest.fixture()
def mai_dev(tmp_path):
    store = UserStore(str(tmp_path / "mai"))
    catalog = CatalogStore(str(tmp_path / "mai"))
    catalog.load_local()
    svc = MaiService(store, catalog)
    calls: list = []
    t = dev_handler(calls)
    svc.lx_transport = t
    svc.lx_songs.transport = t
    svc.lx_dev = DEV
    return svc, Commands(svc, require_consent=True, cache_minutes=10), calls


@pytest.fixture()
def chu_dev(tmp_path):
    from chuni.commands import ChuCommands
    from chuni.service import ChuniService
    svc = ChuniService(tmp_path / "chu")
    t = dev_handler()
    svc.lx_transport = t
    svc.lx_songs.transport = t
    svc.lx_dev = DEV
    return svc, ChuCommands(svc, tmp_path / "chu", renderer=None, tz="Australia/Sydney")


def test_dev_token_from_file(tmp_path):
    assert LX.dev_token_from("  abc ", str(tmp_path)) == "abc"
    assert LX.dev_token_from("", str(tmp_path)) == ""
    (tmp_path / "lx_dev_token.txt").write_text("﻿fromfile\n", "utf-8")
    assert LX.dev_token_from("", str(tmp_path)) == "fromfile"


async def test_player_by_qq_errors():
    t = dev_handler()
    with pytest.raises(LX.NotFoundOnLxns) as e:
        await LX.player_by_qq("maimai", "10002", DEV, transport=t)
    assert "绑定这个 QQ" in str(e.value)
    with pytest.raises(LX.LxnsError) as e:
        await LX.player_by_qq("maimai", "10003", DEV, transport=t)
    assert "隐私设置" in str(e.value)
    with pytest.raises(LX.LxnsError) as e:
        await LX.player_by_qq("maimai", "10001", "wrong", transport=t)
    assert "开发者令牌无效" in str(e.value)


async def test_mai_b50_without_binding_uses_qq(mai_dev):
    svc, cmd, calls = mai_dev
    ctx = Ctx(uid="10001", private=False, admin=False)
    r = await cmd.handle(ctx, "b50 文字")
    text = "\n".join(r.texts)
    assert "PANDORA PARADOXXX" in text and "Zitronectar" in text, text
    creds = svc.store.get_creds("10001", "cn")
    assert creds["source"] == "lxqq" and str(creds["friend_code"]) == str(MAI_PLAYER["friend_code"])
    assert "token" not in creds
    snap = svc.cached("10001", "cn")
    b = snap.best50(svc.catalog)
    assert {s.title for s in b.new} == {"Zitronectar", "Fraq"}
    assert any("/player/qq/10001" in c for c in calls)
    assert "落雪" in text


async def test_mai_bind_lx_without_key_binds_by_qq_in_group(mai_dev):
    svc, cmd, _ = mai_dev
    r = await cmd.handle(Ctx(uid="10001", private=False, admin=False), "绑定 落雪")
    assert "按 QQ" in r.texts[0] and not r.recall
    r = await cmd.handle(Ctx(uid="10002", private=False, admin=False), "绑定 落雪")
    assert "没找到" in r.texts[0]
    assert svc.store.get_creds("10002", "cn") is None


async def test_mai_recent_with_qq_binding_explains(mai_dev):
    svc, cmd, _ = mai_dev
    await svc.bind_cn_qq("10001")
    with pytest.raises(Exception) as e:
        await svc.cn_recent("10001")
    assert "按 QQ" in str(e.value)


async def test_mai_no_dev_token_keeps_old_behaviour(mai_dev):
    svc, cmd, _ = mai_dev
    svc.lx_dev = ""
    r = await cmd.handle(Ctx(uid="10001", private=False, admin=False), "b50 文字")
    assert "绑定" in "\n".join(r.texts)
    assert svc.store.get_creds("10001", "cn") is None


async def test_chu_b50_by_qq(chu_dev):
    svc, cmd = chu_dev
    from chuni.commands import Ctx as CCtx
    ctx = CCtx(uid="10001", private=False, admin=False) if "admin" in CCtx.__dataclass_fields__ else CCtx(uid="10001", private=False, admin=False)
    r = await cmd.handle(ctx, "b50 文字")
    text = "\n".join(r.texts)
    assert "新曲A" in text and "旧曲A" in text, text
    assert svc.cn_source("10001") == "lxqq"
    prof, b = await svc.b50_cn("10001")
    assert [s.title for s in b.new] == ["新曲A", "新曲B"]
    assert all(s.const is not None for s in b.best + b.new)
    r = await cmd.handle(ctx, "最近")
    assert "按 QQ" in r.texts[0]


async def test_chu_bind_lx_without_key(chu_dev):
    svc, cmd = chu_dev
    from chuni.commands import Ctx as CCtx
    ctx = CCtx(uid="10002", private=True, admin=False) if "admin" in CCtx.__dataclass_fields__ else CCtx(uid="10002", private=True)
    r = await cmd.handle(ctx, "绑定 落雪")
    assert "没找到" in r.texts[0]


async def test_no_downgrade_from_full_access(mai_dev):
    svc, cmd, calls = mai_dev
    svc.store.set_creds("10001", "cn", {"source": "lxoauth", "qq": "10001"})
    r = await cmd.handle(Ctx(uid="10001", private=False, admin=False), "绑定 落雪")
    assert "已经用落雪授权" in r.texts[0]
    assert svc.store.get_creds("10001", "cn")["source"] == "lxoauth"
    assert not any("/player/qq/" in c for c in calls)


async def test_qq_miss_is_cached(mai_dev):
    svc, cmd, calls = mai_dev
    ctx = Ctx(uid="10002", private=False, admin=False)
    r1 = await cmd.handle(ctx, "b50 文字")
    r2 = await cmd.handle(ctx, "b50 文字")
    assert "没找到" in "\n".join(r1.texts) and "没找到" in "\n".join(r2.texts)
    assert sum("/player/qq/10002" in c for c in calls) == 1


async def test_chu_no_downgrade_and_recent_unbound(chu_dev):
    svc, cmd = chu_dev
    from chuni.commands import Ctx as CCtx
    mk = (lambda u: CCtx(uid=u, private=True, admin=False)) if "admin" in CCtx.__dataclass_fields__ else (lambda u: CCtx(uid=u, private=True))
    svc.cn.set("10001", {"source": "lxoauth"}, "X")
    r = await cmd.handle(mk("10001"), "绑定 落雪")
    assert "已经用落雪授权" in r.texts[0] and svc.cn.get("10001")["source"] == "lxoauth"
    r = await cmd.handle(mk("10009"), "最近 国服")
    assert "还没绑定中二国服" in r.texts[0]
