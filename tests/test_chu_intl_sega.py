"""中二国际服：SEGA ID + 密码登录（aime 网关 /common_auth/login/sid），clal 过期自动续登，新 clal 会被存下来。"""
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chuni.client import AIME_HOST, ChuniError, ChuniNetClient, InvalidToken  # noqa: E402

FX = Path(__file__).parent / "fixtures"
GOOD_CLAL = "A" * 64
NEW_CLAL = "B" * 64


def intl_transport(log, *, good_pw="pw", valid_clals=(GOOD_CLAL,)):
    home = (FX / "chuni_home.html").read_text("utf-8")
    valid = set(valid_clals)

    def handler(req: httpx.Request):
        p, host = req.url.path, req.url.host
        cookie = req.headers.get("cookie", "")
        log.append((req.method, host, p))
        if host == AIME_HOST:
            if req.method == "GET" and p == "/common_auth/login":
                clal = next((c.split("=", 1)[1] for c in cookie.split("; ") if c.startswith("clal=")), "")
                if clal in valid:
                    return httpx.Response(302, headers={"location": "https://chunithm-net-eng.com/mobile/home/"})
                return httpx.Response(200, text="<html>SEGA ID login</html>", headers={"set-cookie": "JSESSIONID=x; Path=/"})
            if req.method == "POST" and p == "/common_auth/login/sid":
                form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
                assert form["sid"] == "me_1" and form["retention"] == "1"
                if form["password"] != good_pw:
                    return httpx.Response(200, text="<html>SEGA ID login (error)</html>")
                valid.add(NEW_CLAL)
                return httpx.Response(302, headers={
                    "location": "https://chunithm-net-eng.com/mobile/home/",
                    "set-cookie": f"clal={NEW_CLAL}; Domain={AIME_HOST}; Path=/common_auth"})
        if host == "chunithm-net-eng.com":
            if p == "/mobile/home/":
                return httpx.Response(200, text="<html>home</html>", headers={"set-cookie": "_t=tok; Path=/"})
            if p.startswith("/mobile/home/playerData"):
                return httpx.Response(200, text=home)
        return httpx.Response(404, text="nope")
    return httpx.MockTransport(handler)


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def test_password_only_login_gets_clal():
    log = []

    async def go():
        async with ChuniNetClient("", sega_id="me_1", password="pw", transport=intl_transport(log),
                                  request_interval=0) as c:
            prof = await c.profile()
            return prof, c.clal, c.clal_changed
    prof, clal, changed = run(go())
    assert prof.name and prof.rating > 0
    assert clal == NEW_CLAL and changed
    assert ("POST", AIME_HOST, "/common_auth/login/sid") in log


def test_expired_clal_falls_back_to_password():
    log = []

    async def go():
        async with ChuniNetClient("C" * 64, sega_id="me_1", password="pw", transport=intl_transport(log),
                                  request_interval=0) as c:
            await c.profile()
            return c.clal
    assert run(go()) == NEW_CLAL
    gets = [x for x in log if x[2] == "/common_auth/login"]
    assert len(gets) >= 2               # clal try, then the password path


def test_good_clal_skips_password():
    log = []

    async def go():
        async with ChuniNetClient(GOOD_CLAL, sega_id="me_1", password="pw", transport=intl_transport(log),
                                  request_interval=0) as c:
            await c.profile()
            return c.clal_changed
    assert run(go()) is False
    assert not any(x[2] == "/common_auth/login/sid" for x in log)


def test_wrong_password_and_clal_only_still_invalid():
    with pytest.raises(ChuniError, match="SEGA ID 或密码不对"):
        run(ChuniNetClient("", sega_id="me_1", password="bad", transport=intl_transport([]), request_interval=0).login())
    with pytest.raises(InvalidToken):
        run(ChuniNetClient("C" * 64, transport=intl_transport([]), request_interval=0).login())


def test_service_bind_intl_sega_stores_clal_and_creds(tmp_path):
    from chuni.service import ChuniService, Settings
    svc = ChuniService(tmp_path, Settings())
    t = intl_transport([])
    orig = svc._new_client
    svc._new_client = lambda clal, creds=None: (lambda c: (setattr(c, "_interval", 0), c)[1])(
        ChuniNetClient(clal, sega_id=(creds or {}).get("sega_id", ""), password=(creds or {}).get("password", ""),
                       transport=t))
    prof = run(svc.bind_intl_sega("12345", "me_1", "pw"))
    assert prof.name
    assert svc.store.get("12345") == NEW_CLAL
    assert svc.intl_creds.creds("12345")["sega_id"] == "me_1"
    assert run(svc.unbind("12345")) and svc.intl_creds.creds("12345") is None
    svc._new_client = orig
