"""中二日服：SEGA ID 登录流程 + 路径前缀 + 存储（页面用 chuni-penguin 的测试素材，0BSD）。"""
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chuni.client import ChuniJpClient, LoginFailed, NoCards  # noqa: E402
from chuni.storage import JpBindingStore  # noqa: E402

FX = Path(__file__).parent / "fixtures"
PRE = "/chuni-mobile/html/mobile/"
LOGIN = f'<html><form action="{PRE}submit/" method="post"><input name="segaId"><input name="password" type="password">' \
        '<input type="hidden" name="token" value="tok123"></form></html>'


def jp_transport(log, *, good_pw="pw", cards=True):
    home = (FX / "chuni_home.html").read_text("utf-8")
    rec = (FX / "chuni_music_record.html").read_text("utf-8")
    state = {"in": False}

    def handler(req: httpx.Request):
        p = req.url.path
        log.append((req.method, p + (("?" + req.url.query.decode()) if req.url.query else "")))
        assert req.url.host == "new.chunithm-net.com"
        if req.method == "POST" and p == PRE + "submit/":
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            assert form["token"] == "tok123" and form["segaId"] == "me_1"
            if form["password"] != good_pw:
                return httpx.Response(302, headers={"location": PRE + "error/"})
            return httpx.Response(302, headers={"location": PRE + "aimeList/", "set-cookie": "_t=abc; Path=/"})
        if p == PRE + "error/":
            return httpx.Response(200, text="<html>error</html>")
        if p == PRE + "aimeList/":
            return httpx.Response(200, text="<html>aime list</html>")
        if p == PRE + "aimeList/submit/":
            if not cards:
                return httpx.Response(302, headers={"location": PRE + "error/"})
            state["in"] = True
            return httpx.Response(302, headers={"location": PRE + "home/"})
        logged = state["in"] and "_t=abc" in req.headers.get("cookie", "")
        if p in (PRE, PRE.rstrip("/")) or not logged:
            return httpx.Response(200, text=LOGIN)
        if p.startswith(PRE + "home"):
            return httpx.Response(200, text=home)
        if p.startswith(PRE + "record/musicGenre"):
            return httpx.Response(200, text=rec)
        return httpx.Response(404, text="nope")
    return httpx.MockTransport(handler)


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def test_jp_login_and_profile_uses_jp_prefix():
    log = []

    async def go():
        async with ChuniJpClient("me_1", "pw", transport=jp_transport(log), request_interval=0) as c:
            prof = await c.profile()
            return prof
    prof = run(go())
    assert prof.name and prof.rating > 0
    paths = [p for _, p in log]
    assert paths[:2] == [PRE, PRE + "submit/"]
    assert PRE + "aimeList/submit/?idx=0" in paths
    assert PRE + "home/playerData" in paths
    assert not any(p.startswith("/mobile/") for p in paths)


def test_jp_wrong_password_and_no_cards():
    with pytest.raises(LoginFailed):
        run(ChuniJpClient("me_1", "bad", transport=jp_transport([]), request_interval=0).login())
    with pytest.raises(NoCards):
        run(ChuniJpClient("me_1", "pw", transport=jp_transport([], cards=False), request_interval=0).login())


def test_jp_reauth_when_bounced_to_login():
    log = []

    async def go():
        c = ChuniJpClient("me_1", "pw", transport=jp_transport(log), request_interval=0)
        await c.login()
        c._http.cookies.clear()          # session lost: server shows the login form again → log in once more
        return await c.scores_by_difficulty(__import__("chuni.models", fromlist=["Difficulty"]).Difficulty.MASTER)
    run(go())
    paths = [p for _, p in log]
    assert paths.count(PRE + "submit/") == 2              # logged in again after being bounced
    assert paths[-1].startswith(PRE + "record/musicGenre/sendMaster")


def test_jp_store_encrypts(tmp_path):
    st = JpBindingStore(tmp_path)
    st.set_creds("10001", "me_1", "s3cret!", "NAME")
    raw = (tmp_path / "jp_bindings.json").read_text("utf-8")
    assert "s3cret" not in raw and "me_1" not in raw
    assert st.creds("10001") == {"sega_id": "me_1", "password": "s3cret!", "aime_idx": 0}
    assert "10001" in st and st.remove("10001") and st.creds("10001") is None
