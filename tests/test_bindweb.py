import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from core.bindweb import Binder, BindError, BindWeb, Sessions, is_success  # noqa: E402
from mai.bot.commands import Reply  # noqa: E402

CLAL = "A1b2" * 16
LX = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG="


class FakeStore:
    def __init__(self):
        self.consent = set()
        self.regions = {}

    def bound_regions(self, uid):
        return list(self.regions.get(uid, {}))

    def get_creds(self, uid, r):
        return self.regions.get(uid, {}).get(r)

    def has_consent(self, uid):
        return uid in self.consent

    def give_consent(self, uid):
        self.consent.add(uid)


class FakeMaiCmd:
    require_consent = True

    def __init__(self, store):
        self.store, self.calls = store, []

    async def _finish_bind(self, ctx, region, creds):
        self.calls.append(("bind", region, creds))
        logging.getLogger("astrbot").info("verifying %s", creds)
        if creds.get("password") == "bad":
            return Reply().say("绑定失败：密码不对")
        self.store.regions.setdefault(ctx.uid, {})[region] = creds
        return Reply().say(f"绑定成功（{region}）：PLAYER，Rating 15000\n发 /mai b50 看看")

    async def _finish_lx(self, ctx, token):
        self.calls.append(("lx", token))
        self.store.regions.setdefault(ctx.uid, {})["cn"] = {"source": "lx", "token": token}
        return Reply().say("国服绑定成功（落雪查分器）：P，Rating 1")

    async def _bind_cn(self, ctx, rest):
        self.calls.append(("df", rest))
        return Reply().say("绑定国服失败：水鱼说没这个人")


class FakeChu:
    def __init__(self):
        self.calls = []

    async def _bind_sega(self, ctx, rest, server):
        self.calls.append((server, rest))
        return Reply().say(("日服" if server == "jp" else "国际服") + "绑定成功：J（Rating 16.00）")

    def bound(self, uid):
        return []

    async def handle(self, ctx, argline):
        self.calls.append(argline)
        return Reply().say("绑定成功：C（Rating 17.00）")


class FakeService:
    def __init__(self, store=None):
        self.store = store

    def bound_regions(self, uid):          # real MaiService: NET / 国服 + 私服
        return self.store.bound_regions(uid) if self.store else []

    def cn_source(self, b):
        return "lx" if (b or {}).get("source") == "lx" else "df"


class FakeChuSvc:
    def cn_source(self, uid):
        return "df"


class FakePlugin:
    def __init__(self):
        self.store = FakeStore()
        self.cmd = FakeMaiCmd(self.store)
        self.chu = FakeChu()
        self.service = FakeService(self.store)
        self.chu_svc = FakeChuSvc()


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _client(web):
    c = TestClient(TestServer(web.app()))
    await c.start_server()
    return c


def test_sessions_latest_only_and_expiry():
    s = Sessions(ttl=600)
    a = s.issue("10001")
    b = s.issue("10001")
    assert s.get(a) is None and s.get(b).uid == "10001"
    s.get(b).exp = time.time() - 1
    assert s.get(b) is None
    assert s.get("") is None and s.get("x" * 200) is None


def test_is_success():
    assert is_success("绑定成功（intl）：x")
    assert is_success("国服绑定成功（水鱼查分器）：x")
    assert not is_success("绑定国服失败：x")
    assert not is_success("要继续请回复「同意」")


def test_binder_validation_and_consent():
    p = FakePlugin()
    b = Binder(p)

    async def go():
        for form, msg in [({"game": "mai", "server": "jp", "method": "clal"}, "方式不对"),
                          ({"game": "chu", "server": "jp", "method": "clal"}, "方式不对"),
                          ({"game": "mai", "server": "intl", "method": "clal", "value": CLAL}, "勾选"),
                          ({"game": "mai", "server": "intl", "method": "clal", "value": "x", "agree": 1}, "64"),
                          ({"game": "mai", "server": "jp", "method": "sega", "sega_id": "a b", "password": "p",
                            "agree": 1}, "SEGA ID"),
                          ({"game": "mai", "server": "cn", "method": "lx", "value": "short", "agree": 1}, "落雪"),
                          ({"game": "mai", "server": "cn", "method": "df", "value": "a b"}, "水鱼")]:
            try:
                await b.bind("10001", form)
            except BindError as e:
                assert msg in str(e), (form, e)
            else:
                raise AssertionError(form)
        assert p.cmd.calls == []
        msg = await b.bind("10001", {"game": "mai", "server": "jp", "method": "sega", "sega_id": "me_1",
                                     "password": "pw", "agree": True})
        assert is_success(msg) and "10001" in p.store.consent
        assert p.cmd.calls[-1] == ("bind", "jp", {"sega_id": "me_1", "password": "pw"})
        await b.bind("10001", {"game": "mai", "server": "cn", "method": "df", "value": ""})
        assert p.cmd.calls[-1] == ("df", [])
        await b.bind("10001", {"game": "chu", "server": "intl", "method": "clal", "value": "'" + CLAL + "'",
                               "agree": True})
        await b.bind("10001", {"game": "chu", "server": "cn", "method": "lx", "value": LX, "agree": True})
        await b.bind("10001", {"game": "chu", "server": "cn", "method": "df", "value": "fishname"})
        assert p.chu.calls == ["绑定 " + CLAL, "绑定 落雪 " + LX, "绑定 国服 fishname"]
        msg = await b.bind("10001", {"game": "chu", "server": "jp", "method": "sega", "sega_id": "me_1",
                                     "password": "p w", "agree": True})
        assert is_success(msg) and p.chu.calls[-1] == ("jp", ["me_1", "p w"])
        msg = await b.bind("10001", {"game": "chu", "server": "intl", "method": "sega", "sega_id": "me_1",
                                     "password": "pw", "agree": True})
        assert is_success(msg) and p.chu.calls[-1] == ("intl", ["me_1", "pw"])
        st = b.status("10001")
        assert st["mai"] == {"jp": True}
    run(go())


def test_http_flow(caplog):
    p = FakePlugin()
    sent = []

    async def notify(umo, text):
        sent.append((umo, text))

    web = BindWeb(Binder(p), notify=notify, bot_name="Bot<x>")

    async def go():
        c = await _client(web)
        try:
            r = await c.get("/")
            html = await r.text()
            assert r.status == 200 and "Bot&lt;x&gt;" in html and "<script src=\"/app.js\">" in html
            assert "script-src 'self'" in r.headers["Content-Security-Policy"]
            assert r.headers["X-Frame-Options"] == "DENY" and r.headers["Cache-Control"] == "no-store"
            assert (await c.get("/app.js")).status == 200 and (await c.get("/app.css")).status == 200
            assert (await c.get("/../main.py")).status == 404
            assert (await c.get("/api/session")).status == 401
            tok = web.sessions.issue("123456789", "aiocqhttp:FriendMessage:123456789")
            h = {"X-Bind-Token": tok}
            j = await (await c.get("/api/session", headers=h)).json()
            assert j["qq"] == "12*****89" and j["expires_in"] > 500 and "同意" not in j["consent"]["mai"][-6:]
            r = await c.post("/api/bind", data="game=mai", headers={**h, "Content-Type": "application/x-www-form-urlencoded"})
            assert r.status == 415
            from mai.bot.guard import REDACTOR
            caplog.handler.addFilter(REDACTOR)
            with caplog.at_level(logging.INFO):
                r = await c.post("/api/bind", json={"game": "mai", "server": "intl", "method": "sega",
                                                    "sega_id": "me_1", "password": "s3cretPW!", "agree": True},
                                 headers=h)
            j = await r.json()
            assert j["ok"] and j["bound"]["mai"] == {"intl": True}
            assert "s3cretPW!" not in caplog.text
            assert sent and sent[0][0].endswith("123456789") and "网页绑定" in sent[0][1]
            j = await (await c.post("/api/bind", json={"game": "mai", "server": "intl", "method": "sega",
                                                         "sega_id": "me_1", "password": "bad", "agree": True},
                                    headers=h)).json()
            assert not j["ok"] and "失败" in j["message"] and len(sent) == 1
            # old link dies when a new one is issued
            tok2 = web.sessions.issue("123456789")
            assert (await c.get("/api/session", headers=h)).status == 401
            assert (await c.get("/api/session", headers={"X-Bind-Token": tok2})).status == 200
        finally:
            await c.close()
    run(go())


def test_rate_limit_and_submit_cap():
    p = FakePlugin()
    web = BindWeb(Binder(p))

    async def go():
        c = await _client(web)
        try:
            tok = web.sessions.issue("1")
            h = {"X-Bind-Token": tok}
            codes = []
            for _ in range(10):
                r = await c.post("/api/bind", json={"game": "mai", "server": "cn", "method": "df"}, headers=h)
                codes.append(r.status)
            assert codes[:8] == [200] * 8 and 429 in codes[8:]
            # cap per link
            web.ip_bind.limit = 999
            for _ in range(10):
                r = await c.post("/api/bind", json={"game": "mai", "server": "cn", "method": "df"}, headers=h)
            assert r.status in (401, 429)
            assert web.sessions.get(tok) is None
        finally:
            await c.close()
    run(go())


def test_cf_ip_only_trusted_from_localhost():
    class R:
        def __init__(self, remote, headers):
            self.remote, self.headers = remote, headers
    assert BindWeb.client_ip(R("127.0.0.1", {"CF-Connecting-IP": "1.2.3.4"})) == "1.2.3.4"
    assert BindWeb.client_ip(R("8.8.8.8", {"CF-Connecting-IP": "1.2.3.4"})) == "8.8.8.8"


def test_group_link_is_claimed_by_first_device():
    p = FakePlugin()
    sent = []

    async def notify(umo, text, at=""):
        sent.append((umo, text, at))

    web = BindWeb(Binder(p), notify=notify)

    async def go():
        c = await _client(web)
        try:
            tok = web.sessions.issue("123456", "aiocqhttp:GroupMessage:555", group=True)
            h = {"X-Bind-Token": tok}
            j = await (await c.get("/api/session", headers=h)).json()
            claim = j["claim"]
            assert claim and j["group"]
            # someone else opening the same link afterwards is locked out
            r = await c.get("/api/session", headers=h)
            assert r.status == 409 and (await r.json())["error"] == "claimed"
            r = await c.post("/api/bind", json={"game": "mai", "server": "jp", "method": "sega", "sega_id": "x_1",
                                                "password": "pw", "agree": True}, headers=h)
            assert r.status == 409 and not p.cmd.calls
            # the first device keeps working
            h2 = {**h, "X-Bind-Claim": claim}
            assert (await c.get("/api/session", headers=h2)).status == 200
            j = await (await c.post("/api/bind", json={"game": "mai", "server": "jp", "method": "sega",
                                                         "sega_id": "me_1", "password": "pw", "agree": True},
                                    headers=h2)).json()
            assert j["ok"] and sent and sent[0][0].endswith(":555") and sent[0][2] == "123456"
            # private links are not claimed (opening in QQ, then in Safari, still works)
            tok2 = web.sessions.issue("777")
            j = await (await c.get("/api/session", headers={"X-Bind-Token": tok2})).json()
            assert j["claim"] == "" and (await c.get("/api/session", headers={"X-Bind-Token": tok2})).status == 200
        finally:
            await c.close()
    run(go())
