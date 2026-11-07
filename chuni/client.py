"""CHUNITHM-NET 国际服 HTTP 客户端。

登录流程（参考 beer-psi/chuni-penguin，0BSD 许可）：
  带 clal Cookie 访问 aime 网关 common_auth/login → 跟随重定向到 chunithm-net-eng.com/mobile/
  → 服务器写入 _t / userId 会话 Cookie → 后续页面都用这组 Cookie。
会话失效（错误码 200002/200004，或被踢回 /mobile/ 首页）时自动用 clal 重新登录一次。

所有对国际服的网络请求只在这个文件里发；以后加国服就在旁边并列一个客户端。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from selectolax.lexbor import LexborHTMLParser

from . import parser as P
from .models import Difficulty, Profile, RecentScore, Score

log = logging.getLogger("chuni_intl.client")

BASE = "https://chunithm-net-eng.com"
AIME_HOST = "lng-tgk-aime-gw.am-all.net"
AUTH_URL = (
    f"https://{AIME_HOST}/common_auth/login"
    "?site_id=chuniex"
    "&redirect_url=https://chunithm-net-eng.com/mobile/"
    "&back_url=https://chunithm.sega.com/"
)
AUTH_SID_URL = f"https://{AIME_HOST}/common_auth/login/sid"     # SEGA ID + 密码（跟舞萌国际服同一个网关）
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# 错误码（来自 chuni-penguin）
ERR_CONNECTION_EXPIRED = 200002
ERR_INVALID_SESSION = 200004
ERR_RATE_LIMIT = 200001
ERR_MESSAGES = {
    100001: "CHUNITHM-NET 通用错误（可能在维护）",
    100101: "登录失败",
    100106: "游戏数据是旧版本：需要先在当前版本的机台上玩一次",
    120202: "无效访问",
    200001: "请求太频繁，被限流了，请稍后再试",
    200002: "会话已过期",
    200004: "会话无效",
    200012: "该账号被封禁",
    200020: "页面不存在",
}


class ChuniError(Exception):
    """所有可展示给用户的错误。str(e) 就是给用户看的中文提示。"""


class InvalidToken(ChuniError):
    def __init__(self) -> None:
        super().__init__("国际服登录凭据失效了（clal 过期或 SEGA ID 密码改了），发「/网页绑定」重新绑一下")


class NoCards(ChuniError):
    def __init__(self) -> None:
        super().__init__("这个 SEGA ID 下没有绑定 Aime 卡，请先到 my-aime.net 绑卡")


class Maintenance(ChuniError):
    def __init__(self) -> None:
        super().__init__("CHUNITHM-NET 正在维护或服务器异常，稍后再试吧")


class NetError(ChuniError):
    def __init__(self, code: int, desc: str = "") -> None:
        self.code = code
        msg = ERR_MESSAGES.get(code) or desc or "未知错误"
        super().__init__(f"CHUNITHM-NET 错误 {code}：{msg}")


class _NeedReauth(Exception):
    pass


def normalize_clal(raw: str) -> str:
    raw = raw.strip().strip('"').strip("'")
    if raw.startswith("clal="):
        raw = raw[5:]
    return raw.split(";", 1)[0].strip()


def is_valid_clal(clal: str) -> bool:
    return len(clal) == 64 and clal.isascii() and clal.isalnum()


class ChuniNetClient:
    BASE = BASE
    HOST = "chunithm-net-eng.com"
    PREFIX = "/mobile/"
    REGION = "intl"

    def __init__(
        self,
        clal: str,
        *,
        timeout: float = 20.0,
        user_agent: str = DEFAULT_UA,
        request_interval: float = 0.3,
        transport: httpx.AsyncBaseTransport | None = None,
        proxy: str | None = None,
        sega_id: str = "",
        password: str = "",
    ) -> None:
        self._clal = normalize_clal(clal or "")
        self._sega_id, self._password = (sega_id or "").strip(), password or ""
        self.clal_changed = False          # 用账号密码重新登录拿到了新 clal → 服务那边要存下来
        self._interval = request_interval
        kwargs: dict[str, Any] = {}
        if transport is not None:
            kwargs["transport"] = transport
        if proxy:
            kwargs["proxy"] = proxy
        self._http = httpx.AsyncClient(
            base_url=self.BASE,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
            headers={
                "user-agent": user_agent,
                "accept-language": "en-US,en;q=0.5",
                "upgrade-insecure-requests": "1",
                "referer": f"{self.BASE}/",
            },
            **kwargs,
        )
        self._reset_cookies()
        self._logged_in = False
        self._lock = asyncio.Lock()

    def _reset_cookies(self) -> None:
        self._http.cookies.clear()
        if self._clal:
            self._http.cookies.set("clal", self._clal, domain=AIME_HOST, path="/common_auth")

    @property
    def clal(self) -> str:
        return self._clal

    @property
    def has_password(self) -> bool:
        return bool(self._sega_id and self._password)

    def _jar_clal(self) -> str:
        val = ""
        for c in self._http.cookies.jar:
            if c.name == "clal" and (c.domain or "").lstrip(".").endswith(AIME_HOST):
                val = c.value or val
        return val

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "ChuniNetClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ---------- 底层 ----------

    @property
    def _token(self) -> str | None:
        for c in self._http.cookies.jar:
            if c.name == "_t" and c.domain.lstrip(".").endswith(self.HOST):
                return c.value
        return None

    @staticmethod
    def _check_common(resp: httpx.Response) -> None:
        if resp.status_code == 503:
            raise Maintenance()
        if resp.status_code >= 500:
            raise ChuniError(f"CHUNITHM-NET 服务器错误 HTTP {resp.status_code}")

    def _looks_like_auth_redirect(self, resp: httpx.Response) -> bool:
        """CHUNITHM-NET 有时用一段 JS 跳回登录网关，而不是 HTTP 重定向。"""
        if resp.url.host != self.HOST:
            return False
        if resp.url.path == self.PREFIX:
            return True
        body = resp.text[:2000] if len(resp.content) < 4000 else ""
        return "location.href" in body and "common_auth/login" in body

    async def login(self) -> None:
        """先用 clal；clal 没有 / 失效且存了 SEGA ID + 密码时，用账号密码登录并换上新 clal。"""
        if self._clal:
            try:
                await self._login_clal()
                return
            except InvalidToken:
                if not self.has_password:
                    raise
        if not self.has_password:
            raise InvalidToken()
        await self._login_password()

    async def _login_password(self) -> None:
        self._http.cookies.clear()
        try:
            await self._http.get(AUTH_URL)                 # 网关先发会话 Cookie
            resp = await self._http.post(AUTH_SID_URL, data={"sid": self._sega_id, "password": self._password,
                                                             "retention": "1"})
        except httpx.TimeoutException as e:
            raise ChuniError("连接 SEGA 登录网关超时") from e
        except httpx.HTTPError as e:
            raise ChuniError(f"连接 SEGA 登录网关失败：{type(e).__name__}") from e
        self._check_common(resp)
        if resp.url.host == AIME_HOST:
            if resp.url.path.startswith("/common_auth/redirect"):
                form = P.soup_of(resp.content).css_first("form")
                if form is not None and "access/code/add" in str(form.attrs.get("action", "")):
                    raise NoCards()
            raise ChuniError("SEGA ID 或密码不对（国际服 SEGA ID 登录失败）")
        self._finish_login(resp)
        new = normalize_clal(self._jar_clal())
        if new and new != self._clal:
            self._clal, self.clal_changed = new, True

    async def _login_clal(self) -> None:
        self._reset_cookies()
        try:
            resp = await self._http.get(AUTH_URL)
        except httpx.TimeoutException as e:
            raise ChuniError("连接 SEGA 登录网关超时") from e
        except httpx.HTTPError as e:
            raise ChuniError(f"连接 SEGA 登录网关失败：{type(e).__name__}") from e
        self._check_common(resp)

        url = resp.url
        if url.host == AIME_HOST:
            if url.path.startswith("/common_auth/redirect"):
                form = P.soup_of(resp.content).css_first("form")
                if form is not None and "access/code/add" in str(form.attrs.get("action", "")):
                    raise NoCards()
            # 停在登录页 = clal 无效
            raise InvalidToken()
        self._finish_login(resp)

    def _finish_login(self, resp: httpx.Response) -> None:
        url = resp.url
        if url.host != "chunithm-net-eng.com":
            raise ChuniError(f"登录后跳到了意外的地址：{url.host}")
        if url.path.startswith(self.PREFIX + "error"):
            err = P.parse_error_page(P.soup_of(resp.content))
            raise NetError(*(err or (0, "登录时出错")))
        if self._looks_like_auth_redirect(resp) and self._token is None:
            raise InvalidToken()
        self._logged_in = True
        log.debug("CHUNITHM-NET 登录成功")

    async def _request_once(self, method: str, path: str, data: dict | None) -> LexborHTMLParser:
        if data is not None and "token" in data:
            data = {**data, "token": self._token or ""}
        try:
            resp = await self._http.request(method, path, data=data)
        except httpx.TimeoutException as e:
            raise ChuniError("CHUNITHM-NET 响应超时") from e
        except httpx.HTTPError as e:
            raise ChuniError(f"连接 CHUNITHM-NET 失败：{type(e).__name__}") from e
        self._check_common(resp)

        if resp.url.host == AIME_HOST or self._looks_like_auth_redirect(resp):
            raise _NeedReauth()
        soup = P.soup_of(resp.content)
        if resp.url.path.startswith(self.PREFIX + "error"):
            err = P.parse_error_page(soup)
            code, desc = err or (0, "")
            if code in (ERR_CONNECTION_EXPIRED, ERR_INVALID_SESSION):
                raise _NeedReauth()
            raise NetError(code, desc)
        return soup

    def _path(self, path: str) -> str:
        """页面路径统一写成国际服的 /mobile/...，日服换成 /chuni-mobile/html/mobile/..."""
        return self.PREFIX + path[len("/mobile/"):] if path.startswith("/mobile/") else path

    async def request(self, method: str, path: str, data: dict | None = None) -> LexborHTMLParser:
        path = self._path(path)
        async with self._lock:
            if not self._logged_in:
                await self.login()
            try:
                soup = await self._request_once(method, path, data)
            except _NeedReauth:
                await self.login()
                try:
                    soup = await self._request_once(method, path, data)
                except _NeedReauth:
                    raise InvalidToken() from None
            if self._interval:
                await asyncio.sleep(self._interval)
            return soup

    # ---------- 页面 ----------

    async def profile(self) -> Profile:
        return P.parse_profile(await self.request("GET", "/mobile/home/playerData"))

    async def recent(self) -> list[RecentScore]:
        return P.parse_recent(await self.request("GET", "/mobile/record/playlog"))

    async def best30(self) -> list[Score]:
        return P.parse_score_list(await self.request("GET", "/mobile/home/playerData/ratingDetailBest/"))

    async def new20(self) -> list[Score]:
        return P.parse_score_list(await self.request("GET", "/mobile/home/playerData/ratingDetailRecent/"))

    async def scores_by_difficulty(self, diff: Difficulty) -> list[Score]:
        if diff == Difficulty.WORLDS_END:
            soup = await self.request("GET", "/mobile/record/worldsEndList")
        else:
            soup = await self.request(
                "POST",
                f"/mobile/record/musicGenre/send{diff.page_name}",
                {"genre": "99", "token": ""},
            )
        return P.parse_score_list(soup)

    async def music_detail(self, song_id: int) -> list[Score]:
        soup = await self.request(
            "POST",
            "/mobile/record/musicGenre/sendMusicDetail/",
            {"idx": str(song_id), "token": ""},
        )
        return P.parse_music_detail(soup, song_id)


# ---------------------------------------------------------------------------
# 日服：new.chunithm-net.com，SEGA ID + 密码登录（流程和 maimai DX NET 日服一样）
#   GET  /chuni-mobile/html/mobile/            登录页（带 token）
#   POST /chuni-mobile/html/mobile/submit/     segaId / password / save_cookie / token
#   GET  /chuni-mobile/html/mobile/aimeList/submit/?idx=N   选 Aime
#   之后各页面路径和国际服 /mobile/... 一样，只是前缀不同。
# ---------------------------------------------------------------------------
JP_BASE = "https://new.chunithm-net.com"


class LoginFailed(ChuniError):
    pass


class ChuniJpClient(ChuniNetClient):
    BASE = JP_BASE
    HOST = "new.chunithm-net.com"
    PREFIX = "/chuni-mobile/html/mobile/"
    REGION = "jp"

    def __init__(self, sega_id: str, password: str, *, aime_idx: int = 0, **kw) -> None:
        self._aime_idx = int(aime_idx)
        super().__init__("", sega_id=sega_id, password=password, **kw)
        self._http.headers["accept-language"] = "ja,en;q=0.5"

    def _reset_cookies(self) -> None:
        self._http.cookies.clear()

    def _looks_like_auth_redirect(self, resp: httpx.Response) -> bool:
        """日服首页就是登录表单：被带回首页 = 会话没了。"""
        if resp.url.host != self.HOST:
            return False
        path = resp.url.path.rstrip("/") + "/"
        if path == self.PREFIX:
            return True
        return 'name="segaId"' in resp.text[:20000] and 'name="password"' in resp.text[:20000]

    async def _get(self, path: str) -> httpx.Response:
        try:
            resp = await self._http.get(path)
        except httpx.TimeoutException as e:
            raise ChuniError("连接 CHUNITHM-NET（日服）超时") from e
        except httpx.HTTPError as e:
            raise ChuniError(f"连接 CHUNITHM-NET（日服）失败：{type(e).__name__}") from e
        self._check_common(resp)
        return resp

    def _raise_error_page(self, resp: httpx.Response, default: str) -> None:
        if resp.url.path.startswith(self.PREFIX + "error"):
            err = P.parse_error_page(P.soup_of(resp.content))
            code, desc = err or (0, default)
            if code == 100101 or (not err and "login" in default):
                raise LoginFailed("日服登录失败：SEGA ID 或密码不对")
            raise NetError(code, desc)

    async def login(self) -> None:
        self._reset_cookies()
        if not self._sega_id or not self._password:
            raise LoginFailed("日服要用 SEGA ID + 密码绑定")
        top = await self._get(self.PREFIX)
        self._raise_error_page(top, "打开登录页时出错")
        inp = P.soup_of(top.content).css_first("input[name=token]")
        token = str(inp.attrs.get("value") or "") if inp is not None else ""
        if not token:
            raise ChuniError("日服登录页格式变了（没找到 token），等插件更新")
        try:
            resp = await self._http.post(self.PREFIX + "submit/", data={
                "segaId": self._sega_id, "password": self._password, "save_cookie": "on", "token": token})
        except httpx.HTTPError as e:
            raise ChuniError(f"连接 CHUNITHM-NET（日服）失败：{type(e).__name__}") from e
        self._check_common(resp)
        self._raise_error_page(resp, "login")
        if self._looks_like_auth_redirect(resp):
            raise LoginFailed("日服登录失败：SEGA ID 或密码不对")
        sel = await self._get(f"{self.PREFIX}aimeList/submit/?idx={self._aime_idx}")
        if sel.url.path.startswith(self.PREFIX + "error"):
            err = P.parse_error_page(P.soup_of(sel.content))
            if err and err[0] in (100106,):
                raise NetError(*err)
            raise NoCards()
        home = await self._get(self.PREFIX + "home/")
        self._raise_error_page(home, "进入首页时出错")
        if self._looks_like_auth_redirect(home):
            raise LoginFailed("日服登录失败：登录后没能进入首页")
        self._logged_in = True
        log.debug("CHUNITHM-NET（日服）登录成功")
