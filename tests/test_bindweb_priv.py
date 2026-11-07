"""网页绑定的私服部分：真的舞萌 / 中二指令 + 假 MuNET / RinNET / AquaDX，走 HTTP 接口。"""
from __future__ import annotations

import json
import logging
import types

import httpx
import pytest
from aiohttp.test_utils import TestClient, TestServer

from chuni.commands import ChuCommands
from chuni.service import ChuniService
from core import privsrv as P
from core.bindweb import Binder, BindError, BindWeb, is_success
from mai.bot.commands import Commands as MaiCommands
from mai.bot.guard import REDACTOR
from mai.bot.storage import UserStore
from mai.data.loader import CatalogStore
from mai.service import MaiService
from tests import rinnet_data as RD
from tests.test_aquadx import transport as aqua_transport
from tests.test_privsrv_mai import munet_transport

QQ = "40001"


def all_servers():
    mu, rin, aq = munet_transport(), RD.server(), aqua_transport()

    async def handle(req):
        h = req.url.host
        t = rin if "naominet" in h else aq if "aquadx" in h else mu
        return await t.handle_async_request(req)
    return httpx.MockTransport(handle)


@pytest.fixture()
def plugin(tmp_path):
    store = UserStore(str(tmp_path / "mai"))
    catalog = CatalogStore(str(tmp_path / "mai"))
    catalog.load_local()
    svc = MaiService(store, catalog)
    chu_svc = ChuniService(tmp_path / "chu")
    hub = P.Hub(str(tmp_path / "privsrv"), transport=all_servers())
    svc.priv = chu_svc.priv = hub
    p = types.SimpleNamespace(store=store, service=svc, chu_svc=chu_svc, priv=hub,
                              cmd=MaiCommands(svc), chu=ChuCommands(chu_svc, tmp_path / "chu", renderer=None))
    return p


async def test_binder_priv_all_servers(plugin):
    b = Binder(plugin)
    msg = await b.bind(QQ, {"game": "mai", "server": "priv", "method": "munet",
                            "value": "https://portal.mumur.net/u/player_a/mai2"})
    assert is_success(msg) and "MuNET 绑定成功" in msg
    msg = await b.bind(QQ, {"game": "chu", "server": "priv", "method": "aqua", "value": "player_b"})
    assert is_success(msg) and "AquaDX 绑定成功" in msg
    msg = await b.bind(QQ, {"game": "chu", "server": "priv", "method": "rin", "account": "KCrump",
                            "password": RD.GOOD_PW, "agree": True})
    assert is_success(msg) and "14.86" in msg
    st = b.status(QQ)
    assert {"munet", "rin", "aqua"} <= set(st["mai"]) and {"munet", "rin", "aqua"} <= set(st["chu"])
    raw = json.dumps(plugin.priv.bindings.d)
    assert RD.REFRESH not in raw and RD.GOOD_PW not in raw
    assert RD.GOOD_PW not in REDACTOR._secrets                 # 密码用完就丢


@pytest.mark.parametrize("form,err", [
    ({"method": "munet", "value": "a b/c"}, "用户名格式不对"),
    ({"method": "rin", "account": "KCrump", "password": "x"}, "勾选"),
    ({"method": "rin", "account": "a b", "password": "x", "agree": True}, "账号格式不对"),
    ({"method": "rin", "account": "KCrump", "password": "x", "code": "12", "agree": True}, "6 位数字"),
    ({"method": "rin_token", "value": "short", "agree": True}, "refreshToken 格式不对"),
    ({"method": "nope"}, "方式不对"),
])
async def test_binder_priv_validation(plugin, form, err):
    with pytest.raises(BindError, match=err):
        await Binder(plugin).bind(QQ, {"game": "mai", "server": "priv", **form})


async def test_binder_rin_totp_and_token(plugin):
    b = Binder(plugin)
    msg = await b.bind(QQ, {"game": "mai", "server": "priv", "method": "rin", "account": "KCrump",
                            "password": RD.TOTP_PW, "agree": True})
    assert not is_success(msg) and "6 位验证码" in msg
    msg = await b.bind(QQ, {"game": "mai", "server": "priv", "method": "rin", "account": "KCrump",
                            "password": RD.TOTP_PW, "code": RD.TOTP_CODE, "agree": True})
    assert is_success(msg) and "还没有舞萌记录" in msg
    plugin.priv.bindings.remove(QQ)
    msg = await b.bind(QQ, {"game": "chu", "server": "priv", "method": "rin_token", "value": RD.REFRESH, "agree": True})
    assert is_success(msg)


async def test_http_priv_password_not_echoed_or_logged(plugin, caplog):
    web = BindWeb(Binder(plugin))
    c = TestClient(TestServer(web.app()))
    await c.start_server()
    try:
        page = await (await c.get("/")).text()
        assert 'data-for="rinlogin"' in page and "{{BOT}}" not in page
        js = await (await c.get("/app.js")).text()
        assert '"priv", "私服"' in js and "rin_token" in js
        tok = web.sessions.issue(QQ)
        h = {"X-Bind-Token": tok}
        st = await (await c.get("/api/session", headers=h)).json()
        assert "munet" not in st["bound"]["mai"]
        with caplog.at_level(logging.INFO):
            r = await c.post("/api/bind", headers=h, json={"game": "chu", "server": "priv", "method": "rin",
                                                           "account": "KCrump", "password": RD.GOOD_PW, "agree": True})
            body = await r.text()
        j = json.loads(body)
        assert j["ok"] and j["bound"]["chu"]["rin"] and j["bound"]["mai"]["rin"]     # 一个绑定两个游戏
        assert RD.GOOD_PW not in body and RD.REFRESH not in body
        assert RD.GOOD_PW not in caplog.text and RD.REFRESH not in caplog.text
    finally:
        await c.close()


async def test_binder_geki_aqua(plugin, tmp_path):
    """音击：网页上选「音击 → 私服 → AquaDX」，走 /geki 绑定 aqua 同一条路；绑完三个游戏共用。"""
    from ongeki.commands import GekiCommands
    plugin.geki = GekiCommands(plugin.priv)
    b = Binder(plugin)
    msg = await b.bind(QQ, {"game": "geki", "server": "priv", "method": "aqua", "value": "https://aquadx.net/u/player_b"})
    assert is_success(msg) and "AquaDX 绑定成功：player_b" in msg
    st = b.status(QQ)
    assert st["mai"]["aqua"] and st["chu"]["aqua"]
    with pytest.raises(BindError, match="用户名格式不对"):
        await b.bind(QQ, {"game": "geki", "server": "priv", "method": "aqua", "value": "a b"})
    for bad in ({"game": "geki", "server": "priv", "method": "munet", "value": "x"},
                {"game": "geki", "server": "cn", "method": "lx", "value": "x", "agree": True}):
        with pytest.raises(BindError, match="方式不对"):
            await b.bind(QQ, bad)
    web = BindWeb(Binder(plugin))
    c = TestClient(TestServer(web.app()))
    await c.start_server()
    try:
        page = await (await c.get("/")).text()
        assert 'data-game="geki"' in page
        js = await (await c.get("/app.js")).text()
        assert '"geki/priv"' in js and 'g === "geki"' in js
    finally:
        await c.close()
