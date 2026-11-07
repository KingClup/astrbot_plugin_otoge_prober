"""私服查分（MuNET、RinNET …）。

models    公共数据类型 + 错误
munet     MuNET 客户端（公开主页，按用户名）
rinnet    RinNET 客户端（要登录，只存加密 refreshToken）
servers   私服登记表：名字、别名、认证方式、版本名
bindings  QQ → 私服账号（舞萌中二共用）
bind      两个游戏共用的绑定逻辑
Hub       给游戏插件用的入口：发请求、按 key 拿客户端、查绑定
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .bindings import PrivBindings
from .models import PrivError, PrivHidden, PrivNotFound
from .servers import NAMES, SERVERS, is_priv, supports

__all__ = ["Hub", "PrivBindings", "PrivError", "PrivHidden", "PrivNotFound", "NAMES", "SERVERS", "is_priv",
           "supports", "NotBoundPriv"]

UA = {"User-Agent": "astrbot_plugin_otoge_prober"}


class NotBoundPriv(PrivError):
    def __init__(self, server: str, game: str):
        s = SERVERS.get(server)
        name = NAMES.get(server, server)
        cmd = "/mai" if game == "mai" else "/chu"
        if s is not None and s.auth == "login":
            how = f"私聊发「{cmd} 绑定 {server} <账号或邮箱> <密码>」（只存登录令牌，不存密码）"
        else:
            how = f"发「{cmd} 绑定 {server} <网站用户名>」（用户名是 {s.site if s else ''} 里那段）"
        super().__init__(f"你还没绑定 {name}，{how}；舞萌中二绑一次就都能查")


class Hub:
    """一个插件实例一个。transport 给测试注入假网络（httpx.MockTransport）。"""

    def __init__(self, root: str, *, timeout: float = 30, proxy: str | None = None, transport=None):
        self.bindings = PrivBindings(root)
        self.timeout = timeout
        self.proxy = proxy
        self.transport = transport
        self._clients: dict[str, Any] = {}
        self._http: httpx.AsyncClient | None = None

    def _conn(self) -> httpx.AsyncClient:
        """一个插件实例共用一条连接（TLS 握手只做一次；私服一次查分要连发 3～4 个请求）。"""
        loop = asyncio.get_running_loop()
        if self._http is None or self._http.is_closed or getattr(self._http, "_otoge_loop", None) is not loop:
            kw = {"proxy": self.proxy} if self.proxy else {}
            self._http = httpx.AsyncClient(timeout=self.timeout, headers=UA, transport=self.transport, **kw)
            self._http._otoge_loop = loop        # 换了事件循环（重载 / 测试）就重建，连接不能跨循环用
        return self._http

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    async def request(self, method: str, url: str, *, json: Any = None,
                      headers: dict | None = None) -> tuple[int, Any]:
        try:
            r = await self._conn().request(method, url, json=json, headers=headers)
        except httpx.TimeoutException as e:
            raise PrivError("私服响应超时，晚点再试") from e
        except httpx.HTTPError as e:
            raise PrivError(f"连不上私服（{type(e).__name__}）") from e
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None

    async def get_json(self, url: str) -> tuple[int, Any]:
        return await self.request("GET", url)

    def client(self, server: str):
        if server not in SERVERS:
            raise PrivError(f"不认识的私服：{server}")
        if server not in self._clients:
            self._clients[server] = SERVERS[server].make_client(self)
        return self._clients[server]

    def cred(self, qq: str, server: str, game: str) -> dict:
        """绑定记录（令牌已解密）；没绑定时抛 NotBoundPriv。"""
        c = self.bindings.cred(qq, server)
        if not c:
            raise NotBoundPriv(server, game)
        return c

    def username(self, qq: str, server: str, game: str) -> str:
        return self.cred(qq, server, game)["username"]
