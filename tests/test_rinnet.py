"""私服 RinNET：登录 / 两步验证 / 令牌续期 / 只存加密令牌 / 中二真实数据核对 / 两个游戏的指令。离线（假服务器）。"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import pytest

from chuni.commands import ChuCommands
from chuni.models import Difficulty, Score as ChuScoreModel
from chuni.rating import B50, song_rating
from chuni.service import ChuniService
from core import privsrv as P
from core.privsrv import rinnet
from mai.bot.commands import Commands as MaiCommands, Ctx
from mai.bot.guard import REDACTOR, looks_like_password_bind
from mai.bot.storage import UserStore
from mai.data.loader import CatalogStore
from mai.service import MaiService
from tests import rinnet_data as R

QQ = "20001"


def hub(tmp_path, calls=None, **kw):
    return P.Hub(str(tmp_path / "privsrv"), transport=R.server(calls, **kw))


def text(r):
    return "\n".join(r.texts)


# ---------------------------------------------------------------- 真实数据：公式和 rating

def test_every_song_rating_matches_rinnet():
    """45 首都和 RinNET 算的一样（包括 S 以下那首，v1.10.0 修了分段公式）。"""
    for mid, lv, score, base, ra, name in R.CHU_OLD + R.CHU_NEW:
        assert int(song_rating(score, base / 100) * 100) == ra, name


def test_verse_parse_and_total():
    best = rinnet.parse_chu_verse(R.verse_json())
    assert (len(best.best), len(best.new)) == (30, 15)
    conv = lambda xs: [ChuScoreModel(song_id=s.music_id, title=s.title, difficulty=Difficulty(s.level_index),  # noqa: E731
                                     score=s.score, const=s.const) for s in xs]
    assert str(B50(best=conv(best.best), new=conv(best.new)).total) == R.CHU_COMPUTED
    assert best.new[-1].const == 15.1 and best.best[4].level_index == 4


def test_profile_and_recent_parse():
    p = rinnet.parse_profile(R.CHU_PROFILE, "chusan", "KCrump")
    assert (p.name, p.rating, p.rom_version, p.plays) == ("ＫΣｌｕｐＱωＱ", 1486, "2.45.00", 72)
    with pytest.raises(P.PrivNotFound, match="还没有中二记录"):
        rinnet.parse_profile(None, "chusan")
    plays = rinnet.parse_chu_recent(R.CHU_RECENT)
    assert [p.music_id for p in plays] == [2647, 393, 2199] and plays[2].full_combo


def test_mai_rating_string():
    rows = rinnet.parse_mai_rating_string({"data": R.MAI_OLD + ",bad,1:2"})
    assert [(r.music_id, r.level_index, r.achievement, r.rom_version) for r in rows] == \
        [(11752, 3, 1005799, 25015), (11315, 3, 1007373, 22011)]
    assert rinnet.parse_mai_rating_string({"data": ""}) == []


# ---------------------------------------------------------------- 登录

def test_login_password_and_token(tmp_path):
    c = hub(tmp_path).client("rin")
    cred = asyncio.run(c.login("KCrump", R.GOOD_PW))
    assert cred == {"username": "KCrump", "secret": R.REFRESH, "aime": str(R.CARD), "games": ["chusan"]}
    assert asyncio.run(c.login_token(R.REFRESH))["aime"] == str(R.CARD)


@pytest.mark.parametrize("pw,code,err", [("nope", "", "账号或密码不对"), (R.TOTP_PW, "", "两步验证"),
                                        (R.TOTP_PW, "000000", "账号或密码不对"), ("banned", "", "封禁")])
def test_login_errors(tmp_path, pw, code, err):
    with pytest.raises(P.PrivError, match=err):
        asyncio.run(hub(tmp_path).client("rin").login("KCrump", pw, code))


def test_login_totp_ok(tmp_path):
    cred = asyncio.run(hub(tmp_path).client("rin").login("KCrump", R.TOTP_PW, R.TOTP_CODE))
    assert cred["secret"] == R.REFRESH


def test_no_card(tmp_path):
    with pytest.raises(P.PrivError, match="还没有绑卡"):
        asyncio.run(hub(tmp_path, card=False).client("rin").login("KCrump", R.GOOD_PW))


def test_access_token_cached_and_expiry(tmp_path):
    calls = []
    h = hub(tmp_path, calls)
    c = h.client("rin")
    cred = {"username": "KCrump", "secret": R.REFRESH, "aime": str(R.CARD)}
    asyncio.run(c.chu_best(cred))
    asyncio.run(c.chu_recent(cred))
    assert sum(1 for m, p in calls if p == "/api/auth/refresh") == 1      # 4 分钟内复用 accessToken
    c._access.clear()
    h.transport.state["refresh_ok"] = False                               # 玩家在网站上退出登录了
    with pytest.raises(rinnet.RinLoginExpired, match="登录失效"):
        asyncio.run(c.chu_best(cred))


# ---------------------------------------------------------------- 中二指令

@pytest.fixture()
def chu(tmp_path, monkeypatch):
    svc = ChuniService(tmp_path / "chu")

    async def no_net(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(svc.songdb, "ensure_loaded", no_net)
    calls: list = []
    svc.priv = hub(tmp_path, calls)
    return svc, ChuCommands(svc, tmp_path / "chu", renderer=None, cooldown=0), calls


async def test_group_bind_refused_without_network(chu):
    svc, cmd, calls = chu
    r = await cmd.handle(Ctx(uid=QQ, private=False, admin=False), f"绑定 rin KCrump {R.GOOD_PW}")
    assert r.recall and "别在群里发" in text(r) and calls == []
    assert svc.priv.bindings.bound(QQ) == []
    assert looks_like_password_bind(f"/chu 绑定 rin KCrump {R.GOOD_PW}")       # main.py 的守卫也会先拦


async def test_private_bind_stores_only_encrypted_token(chu, tmp_path):
    svc, cmd, _ = chu
    r = await cmd.handle(Ctx(uid=QQ, private=True, admin=False), f"绑定 rin KCrump {R.GOOD_PW}")
    t = text(r)
    assert r.recall and "RinNET 绑定成功：ＫΣｌｕｐＱωＱ（KCrump），中二 Rating 14.86" in t and "没存密码" in t
    raw = (tmp_path / "privsrv" / "privsrv_bindings.json").read_text(encoding="utf-8")
    assert R.REFRESH not in raw and R.GOOD_PW not in raw and "secret_enc" in raw
    assert svc.priv.cred(QQ, "rin", "chu")["secret"] == R.REFRESH


async def test_bind_usage_totp_and_token(chu):
    svc, cmd, _ = chu
    ctx = Ctx(uid=QQ, private=True, admin=False)
    assert "两步验证" in text(await cmd.handle(ctx, "绑定 rin"))
    r = await cmd.handle(ctx, f"绑定 rin KCrump {R.TOTP_PW}")
    assert "6 位验证码" in text(r) and r.recall
    assert "绑定成功" in text(await cmd.handle(ctx, f"绑定 rin KCrump {R.TOTP_PW} {R.TOTP_CODE}"))
    svc.priv.bindings.remove(QQ)
    assert "绑定成功" in text(await cmd.handle(ctx, f"绑定 rin token {R.REFRESH}"))


async def test_b50_me_recent_unbind(chu):
    svc, cmd, _ = chu
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, f"绑定 rin KCrump {R.GOOD_PW}")
    prof, b = await svc.b50_priv(QQ, "rin")
    assert str(b.total) == R.CHU_COMPUTED and prof.rating == 14.86 and b.version == "Ver.2.45"
    t = text(await cmd.handle(ctx, "b50 文字"))
    assert "计算 rating：15.19" in t and "RinNET 显示：14.86" in t
    assert "（RinNET · Ver.2.45）" in text(await cmd.handle(ctx, "我"))
    rec = text(await cmd.handle(ctx, "最近"))
    assert rec.startswith("（RinNET）") and "1,002,956" in rec
    t = text(await cmd.handle(ctx, "解绑 rin"))
    assert "已解绑 RinNET" in t and svc.priv.bindings.cred(QQ, "rin") is None


async def test_expired_token_message(chu):
    svc, cmd, _ = chu
    ctx = Ctx(uid=QQ, private=True, admin=False)
    await cmd.handle(ctx, f"绑定 rin KCrump {R.GOOD_PW}")
    svc.priv.client("rin")._access.clear()
    svc.priv.transport.state["refresh_ok"] = False
    svc.clear_cache(QQ)
    assert "登录失效了" in text(await cmd.handle(ctx, "b50"))


async def test_secrets_never_logged(chu):
    """绑定时密码进打码表、用完就删；令牌绑定后一直打码。"""
    _svc, cmd, _ = chu
    await cmd.handle(Ctx(uid=QQ, private=True, admin=False), f"绑定 rin KCrump {R.GOOD_PW}")
    rec = logging.LogRecord("astrbot", logging.INFO, __file__, 1, f"refresh {R.REFRESH}", None, None)
    REDACTOR.filter(rec)
    assert R.REFRESH not in rec.getMessage()
    assert R.GOOD_PW not in REDACTOR._secrets                 # 密码用完就从内存里丢掉


# ---------------------------------------------------------------- 舞萌（同一个绑定）

@pytest.fixture()
def mai(tmp_path):
    store = UserStore(str(tmp_path / "mai"))
    catalog = CatalogStore(str(tmp_path / "mai"))
    catalog.load_local()
    svc = MaiService(store, catalog)
    return svc, catalog


async def test_mai_bind_without_mai_data(mai, tmp_path):
    svc, _ = mai
    svc.priv = hub(tmp_path)
    t = text(await MaiCommands(svc).handle(Ctx(uid=QQ, private=True, admin=False), f"绑定 rin KCrump {R.GOOD_PW}"))
    assert "RinNET 绑定成功（KCrump），不过这个号在 RinNET 上还没有舞萌记录" in t


async def test_mai_b50_uses_catalog_constants_for_client_version(mai, tmp_path):
    svc, catalog = mai
    svc.priv = hub(tmp_path, with_mai=True)
    cmd = MaiCommands(svc)
    ctx = Ctx(uid=QQ, private=True, admin=False)
    assert "舞萌 Rating 1200" in text(await cmd.handle(ctx, f"绑定 rin KCrump {R.GOOD_PW}"))
    snap = await cmd._snapshot(QQ, "rin")
    b = snap.best50(catalog)
    assert (len(b.old), len(b.new)) == (2, 2) and b.version == "PRiSM PLUS"
    db = catalog.db
    for s in b.old + b.new:
        song = db.by_music_id(s.music_id)
        assert s.ds == song.chart(s.type, s.diff).ds_in("jp", "PRiSM PLUS") and s.rating > 0
    assert "最近游玩（RinNET）" in text(await cmd.handle(ctx, "最近"))


def test_naive_play_time_shown_as_recorded():
    from chuni import privsrv as CPV
    from chuni.render import recent_text
    from zoneinfo import ZoneInfo
    plays = CPV.to_recent(rinnet.parse_chu_recent(R.CHU_RECENT), None, lambda m, d: 15.0, ZoneInfo("Asia/Shanghai"))
    assert recent_text(plays, "Asia/Shanghai", 1).startswith("06-12 00:21")
