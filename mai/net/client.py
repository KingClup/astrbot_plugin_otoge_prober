"""maimai DX NET client for International (maimaidx-eng.com) and JP (maimaidx.jp).

Login
  intl, clal:      GET aime login page with the clal cookie → 302 → redeem → NET session
  intl, password:  POST common_auth/login/sid (sid, password, retention=1) → 302 → redeem; the new
                   clal is taken from the cookie jar so later logins can skip the password
  jp, password:    GET /maimai-mobile/ (token) → POST /submit/ → aimeList/ → aimeList/submit/?idx=N → home

Behaviour borrowed from tomomai / DXRating (re-implemented, no code copied):
  * one httpx client per user; the NET session belongs to the connection that redeemed it;
  * all requests to a NET host go through one shared throttle (≤ RATE per second);
  * ERROR CODE 200001 = too many requests → the whole host cools down for LOCK_SECONDS;
  * NET serves an incomplete TLS chain, so GlobalSign's intermediates are bundled.
"""
from __future__ import annotations

import asyncio
import os
import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from ..consts import NET_BASE
from ..parse.html import NetLoggedOut, NetMaintenance, NetPageError, attr, check_page, parse

AIME_LOGIN = ("https://lng-tgk-aime-gw.am-all.net/common_auth/login?site_id=maimaidxex"
              "&redirect_url=https://maimaidx-eng.com/maimai-mobile/&back_url=https://maimai.sega.com/")
AIME_SID = "https://lng-tgk-aime-gw.am-all.net/common_auth/login/sid"
AIME_HOST = "lng-tgk-aime-gw.am-all.net"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja;q=0.9,en;q=0.8,zh-CN;q=0.7",
}
RATE = 2.0           # requests per second per NET host
LOCK_SECONDS = 300   # cool-down after ERROR CODE 200001
TIMEOUT = 20.0


class LoginFailed(Exception):
    """Wrong credentials / expired clal."""


class NetLocked(Exception):
    def __init__(self, seconds_left: int):
        super().__init__(f"NET rate-limit lock, {seconds_left}s left")
        self.seconds_left = seconds_left


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # pragma: no cover
        ctx = ssl.create_default_context()
    pem = os.path.join(os.path.dirname(__file__), "intermediates.pem")
    if os.path.exists(pem):
        ctx.load_verify_locations(pem)
    return ctx


class HostThrottle:
    """Shared per-host pacing + 200001 lock-out bookkeeping."""

    def __init__(self, rate: float = RATE):
        self.interval = 1.0 / rate
        self._next: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.locked_until: dict[str, float] = {}

    def _lock(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    def check(self, host: str) -> None:
        left = self.locked_until.get(host, 0) - time.monotonic()
        if left > 0:
            raise NetLocked(int(left) + 1)

    async def wait(self, host: str) -> None:
        self.check(host)
        async with self._lock(host):
            now = time.monotonic()
            t = self._next.get(host, 0.0)
            if t > now:
                await asyncio.sleep(t - now)
            self._next[host] = max(now, t) + self.interval

    def lock(self, host: str, seconds: int = LOCK_SECONDS) -> None:
        self.locked_until[host] = time.monotonic() + seconds

    def status(self) -> dict[str, int]:
        now = time.monotonic()
        return {h: int(t - now) for h, t in self.locked_until.items() if t > now}


THROTTLE = HostThrottle()


@dataclass
class Credentials:
    region: str
    clal: str = ""
    sega_id: str = ""
    password: str = ""
    aime_idx: int = 0

    def has_password(self) -> bool:
        return bool(self.sega_id and self.password)


@dataclass
class NetSession:
    creds: Credentials
    throttle: HostThrottle = field(default_factory=lambda: THROTTLE)
    transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport
    client: httpx.AsyncClient | None = None
    logged_in: bool = False
    clal_changed: bool = False   # True when a password login produced a fresh clal

    @property
    def base(self) -> str:
        return NET_BASE[self.creds.region]

    def _new_client(self) -> httpx.AsyncClient:
        kw = dict(headers=HEADERS, timeout=TIMEOUT, follow_redirects=False)
        if self.transport is not None:
            kw["transport"] = self.transport
        else:
            kw["verify"] = ssl_context()
        return httpx.AsyncClient(**kw)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
        self.client = None
        self.logged_in = False

    # ---------- low level ----------
    async def _req(self, method: str, url: str, **kw) -> httpx.Response:
        assert self.client is not None
        host = urlparse(url).hostname or ""
        if host.endswith(urlparse(self.base).hostname or "~"):
            await self.throttle.wait(host)
        r = await self.client.request(method, url, **kw)
        if r.status_code == 503 and host.endswith(urlparse(self.base).hostname or "~"):
            raise NetMaintenance()
        return r

    async def _follow(self, r: httpx.Response, limit: int = 8) -> httpx.Response:
        for _ in range(limit):
            if r.status_code not in (301, 302, 303, 307, 308):
                return r
            loc = urljoin(str(r.url), r.headers.get("location", ""))
            if urlparse(loc).path.rstrip("/").endswith("/maimai-mobile/error"):
                page = await self._req("GET", loc)
                self._raise_page(page.text)
                raise NetPageError("unknown", "redirected to error page")
            r = await self._req("GET", loc)
        return r

    def _raise_page(self, html: str) -> None:
        try:
            check_page(html)
        except NetPageError as e:
            if e.code == "200001":
                self.throttle.lock(urlparse(self.base).hostname or "")
            raise

    # ---------- login ----------
    async def login(self) -> None:
        await self.close()
        self.client = self._new_client()
        c = self.creds
        if c.region == "intl":
            if c.clal:
                try:
                    await self._login_intl_clal(c.clal)
                    self.logged_in = True
                    return
                except LoginFailed:
                    if not c.has_password():
                        raise
                    await self.close()
                    self.client = self._new_client()
            if c.has_password():
                await self._login_intl_password(c.sega_id, c.password)
                self.logged_in = True
                return
            raise LoginFailed("no usable credentials")
        if c.region == "jp":
            if not c.has_password():
                raise LoginFailed("JP needs SEGA ID + password")
            await self._login_jp(c.sega_id, c.password, c.aime_idx)
            self.logged_in = True
            return
        raise LoginFailed(f"unknown region {c.region}")

    async def _redeem_intl(self, r: httpx.Response) -> None:
        loc = r.headers.get("location", "")
        if r.status_code not in (301, 302, 303) or not loc:
            raise LoginFailed("aime gateway did not redirect")
        if AIME_HOST in loc and "common_auth/login" in loc:
            raise LoginFailed("aime gateway rejected the credentials")
        page = await self._follow(r)
        self._raise_page(page.text)

    async def _login_intl_clal(self, clal: str) -> None:
        assert self.client is not None
        self.client.cookies.set("clal", clal, domain=AIME_HOST)
        r = await self._req("GET", AIME_LOGIN)
        await self._redeem_intl(r)

    async def _login_intl_password(self, sid: str, password: str) -> None:
        assert self.client is not None
        await self._req("GET", AIME_LOGIN)
        r = await self._req("POST", AIME_SID, data={"sid": sid, "password": password, "retention": "1"})
        if r.status_code not in (301, 302, 303):
            raise LoginFailed("aime login did not redirect (wrong SEGA ID or password?)")
        new_clal = self._jar_clal()
        await self._redeem_intl(r)
        if new_clal and new_clal != self.creds.clal:
            self.creds.clal = new_clal
            self.clal_changed = True

    def _jar_clal(self) -> str:
        """Latest clal the aime gateway set (cookie domain may carry a leading dot)."""
        assert self.client is not None
        val = ""
        for c in self.client.cookies.jar:
            if c.name == "clal" and (c.domain or "").lstrip(".").endswith(AIME_HOST):
                val = c.value or val
        return val

    async def _login_jp(self, sega_id: str, password: str, aime_idx: int) -> None:
        top = await self._follow(await self._req("GET", f"{self.base}/maimai-mobile/"))
        self._raise_page_soft(top.text)
        token = attr(parse(top.text).css_first("input[name=token]"), "value")
        if not token:
            raise LoginFailed("JP login page had no token")
        r = await self._req("POST", f"{self.base}/maimai-mobile/submit/", data={
            "segaId": sega_id, "password": password, "save_cookie": "on", "token": token})
        loc = r.headers.get("location", "")
        if r.status_code not in (301, 302, 303) or "error" in loc:
            raise LoginFailed("JP login rejected (wrong SEGA ID or password?)")
        for url in (f"{self.base}/maimai-mobile/aimeList/",
                    f"{self.base}/maimai-mobile/aimeList/submit/?idx={int(aime_idx)}"):
            r = await self._req("GET", url)
            loc = r.headers.get("location", "")
            if "error" in loc:
                raise LoginFailed("JP login: no usable Aime card")
        home = await self._follow(await self._req("GET", f"{self.base}/maimai-mobile/home/"))
        self._raise_page(home.text)

    def _raise_page_soft(self, html: str) -> None:
        try:
            check_page(html)
        except NetLoggedOut:
            pass  # the JP top page *is* a login form

    # ---------- pages ----------
    async def get(self, path: str, *, retry_login: bool = True) -> str:
        if not self.logged_in:
            await self.login()
        url = path if path.startswith("http") else f"{self.base}{path}"
        r = await self._follow(await self._req("GET", url))
        try:
            self._raise_page(r.text)
        except NetLoggedOut:
            if not retry_login:
                raise
            self.logged_in = False
            await self.login()
            return await self.get(path, retry_login=False)
        if urlparse(str(r.url)).path.rstrip("/") in ("", "/maimai-mobile") and "name_block" not in r.text:
            if not retry_login:
                raise NetLoggedOut()
            self.logged_in = False
            await self.login()
            return await self.get(path, retry_login=False)
        return r.text

    async def get_bytes(self, url: str) -> bytes:
        if not self.logged_in:
            await self.login()
        r = await self._follow(await self._req("GET", url))
        r.raise_for_status()
        return r.content


# NET page paths
P_HOME = "/maimai-mobile/home/"
P_PLAYER = "/maimai-mobile/playerData/"
P_RECORD = "/maimai-mobile/record/"
P_TARGET = "/maimai-mobile/home/ratingTargetMusic/"


def p_scores(diff_index: int) -> str:
    return f"/maimai-mobile/record/musicGenre/search/?genre=99&diff={diff_index}"


def p_playlog(idx: str) -> str:
    from urllib.parse import quote
    return f"/maimai-mobile/record/playlogDetail/?idx={quote(idx, safe='')}"


def p_friend_search(code: str) -> str:
    return f"/maimai-mobile/friend/search/searchUser/?friendCode={int(code)}"
