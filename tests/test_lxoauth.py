"""落雪 OAuth：授权地址、换令牌、15 分钟过期自动刷新、refresh_token 轮换、续期 / 清理、服务层走 Bearer。离线 mock。"""
from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet

from core import lxns as LX
from core.lxoauth import LxOAuth, OAuthExpired, load_client, save_client
from tests.test_cn import MAI_PLAYER, mai_scores, mai_song_list

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"


class FakeLx:
    """token 端点 + 个人 API；refresh_token 每次换新、旧的作废。"""

    def __init__(self):
        self.n = 0
        self.valid_rt = set()
        self.bodies = []

    def issue(self):
        self.n += 1
        rt = f"rt{self.n}"
        self.valid_rt.add(rt)
        return {"access_token": f"{JWT}{self.n}", "token_type": "Bearer", "expires_in": 900,
                "refresh_token": rt, "scope": "read_player"}

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/oauth/token"):
            body = json.loads(req.content)
            self.bodies.append(body)
            if body.get("client_id") != "cid":
                return httpx.Response(401, json={"error": "invalid_client"})
            if body["grant_type"] == "authorization_code":
                if body.get("code") != "good" or not body.get("code_verifier"):
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json=self.issue())
            if body["grant_type"] == "refresh_token":
                rt = body.get("refresh_token")
                if rt not in self.valid_rt:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.valid_rt.discard(rt)
                return httpx.Response(200, json={"success": True, "code": 200, "data": self.issue()})
        if path.endswith("/song/list"):
            return httpx.Response(200, json=mai_song_list())
        if "/user/" in path:
            auth = req.headers.get("authorization", "")
            if not auth.startswith("Bearer " + JWT):
                return httpx.Response(401, json={"success": False, "code": 401, "message": "bad"})
            if path.endswith("/maimai/player"):
                return httpx.Response(200, json={"success": True, "code": 200, "data": MAI_PLAYER})
            if path.endswith("/maimai/player/scores"):
                return httpx.Response(200, json={"success": True, "code": 200, "data": mai_scores()})
            return httpx.Response(404, json={"success": False, "code": 404, "message": "no data"})
        return httpx.Response(404, json={})


@pytest.fixture()
def oa(tmp_path):
    fake = FakeLx()
    o = LxOAuth(str(tmp_path), Fernet(Fernet.generate_key()), "cid", "sec", transport=httpx.MockTransport(fake.handler))
    return o, fake, tmp_path


def test_client_file_roundtrip(tmp_path):
    assert load_client("", "", str(tmp_path)) == ("", "")
    save_client(str(tmp_path), "id1", "s1")
    assert load_client("", "", str(tmp_path)) == ("id1", "s1")
    assert load_client("cfgid", "cfgsec", str(tmp_path)) == ("cfgid", "cfgsec")


def test_begin_url_has_pkce_and_scope(oa):
    o, _fake, _ = oa
    url = o.begin("10001", "https://bind.example.com/lxns/callback")
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://maimai.lxns.net/oauth/authorize?")
    assert q["client_id"] == ["cid"] and q["scope"] == ["read_player"] and q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"] and len(q["code_challenge"][0]) >= 43
    assert o.pending(q["state"][0])["uid"] == "10001"


async def test_finish_store_encrypted_and_refresh_rotates(oa):
    o, fake, tmp = oa
    url = o.begin("10001", "https://x/lxns/callback", extra={"umo": "u"})
    state = parse_qs(urlparse(url).query)["state"][0]
    uid, extra = await o.finish(state, "good")
    assert uid == "10001" and extra == {"umo": "u"}
    raw = (tmp / "lx_oauth_tokens.json").read_text("utf-8")
    assert "rt1" not in raw and JWT not in raw              # 只存加密后的 refresh_token
    assert fake.bodies[0]["client_secret"] == "sec" and fake.bodies[0]["redirect_uri"] == "https://x/lxns/callback"
    assert await o.access("10001") == JWT + "1"             # 还没过期：不刷新
    o._access["10001"] = ("old", time.time() - 1)           # 模拟 15 分钟过了
    assert await o.access("10001") == JWT + "2"
    assert "rt1" not in fake.valid_rt and "rt2" in fake.valid_rt
    with pytest.raises(LX.LxnsError):
        await o.finish(state, "good")                       # state 一次性


async def test_revoked_grant_forgets_user(oa):
    o, fake, _ = oa
    state = parse_qs(urlparse(o.begin("10001", "https://x/cb")).query)["state"][0]
    await o.finish(state, "good")
    fake.valid_rt.clear()                                    # 玩家在落雪取消了授权
    o._access.clear()
    with pytest.raises(OAuthExpired):
        await o.access("10001")
    assert not o.has("10001")


async def test_keepalive_refreshes_old_and_drops_unused(oa):
    o, _fake, _ = oa
    for uid in ("1", "2"):
        state = parse_qs(urlparse(o.begin(uid, "https://x/cb")).query)["state"][0]
        await o.finish(state, "good")
    o.d["1"]["rt_at"] = time.time() - 25 * 86400
    st = await o.keepalive(lambda u: u == "1")
    assert st == {"refreshed": 1, "dropped": 1, "failed": 0}
    assert o.has("1") and not o.has("2")
    assert time.time() - o.d["1"]["rt_at"] < 60


async def test_mai_service_uses_bearer_from_oauth(oa, tmp_path):
    from mai.bot.storage import UserStore
    from mai.data.loader import CatalogStore
    from mai.service import MaiService
    o, fake, _ = oa
    state = parse_qs(urlparse(o.begin("10001", "https://x/cb")).query)["state"][0]
    await o.finish(state, "good")
    store = UserStore(str(tmp_path / "mai"))
    catalog = CatalogStore(str(tmp_path / "mai"))
    catalog.load_local()
    svc = MaiService(store, catalog)
    t = httpx.MockTransport(fake.handler)
    svc.lx_transport = t
    svc.lx_songs.transport = t
    svc.lx_oauth = o
    store.set_creds("10001", "cn", {"source": "lxoauth", "qq": "10001"})
    assert svc.cn_source(store.get_creds("10001", "cn")) == "lx"
    snap = await svc.sync("10001", "cn")
    assert snap.profile.name == MAI_PLAYER["name"] and len(snap.scores) >= 6


async def test_bad_client_message(oa):
    o, _fake, _ = oa
    o.client_id = "wrong"
    state = parse_qs(urlparse(o.begin("10001", "https://x/cb")).query)["state"][0]
    with pytest.raises(LX.LxnsError) as e:
        await o.finish(state, "good")
    assert "client_id" in str(e.value)


# ---------------- 网页：开始授权 → 落雪回调 → 两个游戏绑定 ----------------
async def test_web_oauth_flow(oa):
    from types import SimpleNamespace

    from aiohttp.test_utils import TestClient, TestServer

    from core.bindweb import Binder, BindWeb
    o, fake, _ = oa
    t = httpx.MockTransport(fake.handler)
    creds, chu_cn, sent = {}, {}, []

    class Store:
        def set_creds(self, uid, r, c): creds[(uid, r)] = c
        def get_creds(self, uid, r): return creds.get((uid, r))
        def bound_regions(self, uid): return [r for (u, r) in creds if u == uid]
        def has_consent(self, uid): return True
        def give_consent(self, uid): pass

    class ChuCn:
        def set(self, uid, b, name=""): chu_cn[uid] = {**b, "name": name}
        def get(self, uid): return chu_cn.get(uid)

    store = Store()
    p = SimpleNamespace(
        store=store, lx_oauth=o, lx_oauth_redirect=lambda: "https://bind.example.com/lxns/callback",
        service=SimpleNamespace(lx_transport=t, lx_dev="", bound_regions=store.bound_regions,
                                cn_source=lambda b: "lx"),
        chu_svc=SimpleNamespace(lx_transport=t, settings=SimpleNamespace(proxy=None), cn=ChuCn(), _cache={},
                                cn_source=lambda u: "lx"),
        cmd=SimpleNamespace(require_consent=False, _drop_cn_snapshot=lambda uid: None),
        chu=SimpleNamespace(bound=lambda uid: ["cn"] if uid in chu_cn else []),
        prefs=SimpleNamespace(set_last=lambda *a: None))

    async def notify(umo, text, at=None):
        sent.append((umo, text))

    web = BindWeb(Binder(p), notify=notify)
    c = TestClient(TestServer(web.app()))
    await c.start_server()
    try:
        tok = web.sessions.issue("10001", "aiocqhttp:FriendMessage:10001")
        h = {"X-Bind-Token": tok}
        j = await (await c.get("/api/session", headers=h)).json()
        assert j["lx"] == {"oauth": True, "qq": False} and "读取玩家数据" in j["consent"]["lxoauth"]
        j = await (await c.post("/api/lx/start", json={}, headers=h)).json()
        assert not j["ok"] and "同意" in j["message"]
        j = await (await c.post("/api/lx/start", json={"agree": True}, headers=h)).json()
        assert j["ok"] and j["url"].startswith("https://maimai.lxns.net/oauth/authorize?")
        state = parse_qs(urlparse(j["url"]).query)["state"][0]
        r = await c.get("/lxns/callback", params={"state": state, "code": "good"})
        html = await r.text()
        assert r.status == 200 and "授权成功" in html and "舞萌国服绑定成功" in html
        assert "中二国服：没绑上" in html                       # 这个玩家落雪上没有中二数据
        assert creds[("10001", "cn")] == {"source": "lxoauth", "qq": "10001"} and "10001" not in chu_cn
        assert sent and "落雪授权" in sent[0][1]
        r = await c.get("/lxns/callback", params={"state": state, "code": "good"})
        assert "用过或过期" in await r.text()
        r = await c.get("/lxns/callback", params={"error": "access_denied", "state": "x"})
        assert "取消了授权" in await r.text()
        assert "Content-Security-Policy" in r.headers
    finally:
        await c.close()
