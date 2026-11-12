"""群友自助绑定网页（手机优先）。

插件只在本机开一个小 HTTP 服务（默认 127.0.0.1:36199；别用 6199，那是 AstrBot aiocqhttp 的端口），外面用 Cloudflare Tunnel / frp 等把公网 HTTPS 域名接进来；
换入口不用改这里。

流程：私聊发「/查分 网页绑定」→ 机器人回一个 10 分钟有效的链接 https://<域名>/#t=<一次性令牌>
     → 手机打开，选游戏 / 区服，填 clal、SEGA ID、落雪密钥、水鱼用户名，或私服（MuNET / AquaDX 用户名、
       RinNET 账号密码 / 令牌；音击只有私服 AquaDX）→ 直接 HTTPS 交给插件加密保存。
令牌放在 # 后面：浏览器不会把它发进任何请求行，Cloudflare / 代理日志里也看不到；页面脚本用请求头带给接口。
凭据不经过 QQ 聊天、不进日志（REDACTOR 打码）、不交给大模型；真正的绑定复用聊天绑定的同一套函数。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

try:
    from ..mai.bot.commands import Ctx
    from ..mai.bot.guard import CLAL_RE, CONSENT_TEXT, LX_CONSENT_TEXT, REDACTOR
    from .lxns import TOKEN_RE
    from .privsrv.servers import parse_username
except ImportError:  # tests import modules flat
    from mai.bot.commands import Ctx
    from mai.bot.guard import CLAL_RE, CONSENT_TEXT, LX_CONSENT_TEXT, REDACTOR
    from core.lxns import TOKEN_RE
    from core.privsrv.servers import parse_username

LX_OAUTH_CONSENT = ("1. 点下面的按钮会跳到落雪查分器的授权页，你在那里确认后，我只拿到「读取玩家数据」权限：资料和成绩，改不了任何东西。\n"
                    "2. 授权凭证加密保存在 bot 主人的电脑上，不会发进群聊、不会交给 AI、日志里也不会出现；我会每隔几周自动续期。\n"
                    "3. 一次授权舞萌、中二国服都能用。随时发 /mai 解绑 国服、/chu 解绑 国服，或者在落雪网站上取消授权。")
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "bind")
TTL = 600                    # 链接有效期（秒）
MAX_PENDING = 8              # 一条群链接最多让几个浏览器等确认（再多就不发确认码了）
MAX_CODE_TRIES = 5           # 确认码回错几次，这条链接作废
MAX_SUBMITS = 12             # 一个链接最多提交几次绑定
SEGA_ID_RE = re.compile(r"[A-Za-z0-9_.@\-]{3,64}")
DF_NAME_RE = re.compile(r"[^\s/\\]{1,64}")
RIN_ACCOUNT_RE = re.compile(r"\S{1,128}")
RIN_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-.~+/=]{20,200}")
# 私服：网页上「区服」选「私服」，「方式」就是哪个私服；rin_token 也是绑 RinNET
PRIV_METHODS = {"munet": "munet", "aqua": "aqua", "rin": "rin", "rin_token": "rin"}
IMG_RE = re.compile(r"[a-z0-9\-]{1,40}\.webp")
LOCAL = ("127.0.0.1", "::1", "localhost")

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
}


def mask_qq(uid: str) -> str:
    uid = str(uid)
    return uid if len(uid) <= 4 else uid[:2] + "*" * (len(uid) - 4) + uid[-2:]


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Session:
    uid: str
    umo: str = ""                 # 私聊会话（绑定成功后回一条 QQ 通知）
    name: str = ""
    exp: float = 0.0
    submits: int = 0
    group: bool = False           # 链接发在群里：谁都能点开，所以要发命令的人在 QQ 回网页上的确认码才认
    claim: str = ""               # 确认过的那个浏览器（X-Bind-Claim）
    pend: dict = field(default_factory=dict)      # 点开了还没确认的浏览器：claim → 4 位确认码
    tries: int = 0                # 确认码回错的次数
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Sessions:
    """令牌只存在内存里（存哈希）；同一个 QQ 再要一次链接，旧的立刻作废。"""

    def __init__(self, ttl: int = TTL):
        self.ttl = ttl
        self._by_hash: dict[str, Session] = {}

    def issue(self, uid: str, umo: str = "", name: str = "", group: bool = False) -> str:
        self._gc()
        for k in [k for k, s in self._by_hash.items() if s.uid == str(uid)]:
            del self._by_hash[k]
        token = secrets.token_urlsafe(24)
        self._by_hash[_h(token)] = Session(str(uid), umo, name, time.time() + self.ttl, group=group)
        return token

    def get(self, token: str) -> Session | None:
        if not token or len(token) > 100:
            return None
        s = self._by_hash.get(_h(token))
        if s is None:
            return None
        if time.time() > s.exp:
            self._by_hash.pop(_h(token), None)
            return None
        return s

    def confirm(self, uid: str, code: str) -> str:
        """发命令的人在 QQ 回确认码 → 认下显示这个码的那个浏览器。
        返回 ok / none（没有在等确认的链接）/ wrong（码不对）/ locked（错太多次，链接作废）。"""
        self._gc()
        mine = [(k, s) for k, s in self._by_hash.items() if s.uid == str(uid) and s.group and not s.claim]
        if not mine:
            return "none"
        code = "".join(ch for ch in str(code) if ch.isdigit())
        for k, s in mine:
            for claim, c in s.pend.items():
                if code and secrets.compare_digest(c, code):
                    s.claim = claim
                    s.pend = {}
                    return "ok"
        for k, s in mine:
            s.tries += 1
            if s.tries >= MAX_CODE_TRIES:
                del self._by_hash[k]
                return "locked"
        return "wrong"

    def revoke(self, token: str) -> None:
        self._by_hash.pop(_h(token), None)

    def _gc(self) -> None:
        now = time.time()
        for k in [k for k, s in self._by_hash.items() if now > s.exp]:
            del self._by_hash[k]


class RateLimit:
    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if len(hits) >= self.limit:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        if len(self._hits) > 5000:
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window}
        return True


class BindError(Exception):
    pass


class Binder:
    """把网页提交翻译成聊天绑定用的同一套函数。plugin 需要有 cmd / chu / store / service / chu_svc。"""

    def __init__(self, plugin):
        self.p = plugin

    # ---------- 状态 ----------
    def status(self, uid: str) -> dict:
        p = self.p
        mai = {r: True for r in p.service.bound_regions(uid)}       # 含私服（舞萌中二共用）
        if mai.get("cn"):
            src = (p.store.get_creds(uid, "cn") or {}).get("source")
            mai["cn"] = src if src in ("lx", "lxqq", "lxoauth") else "df"
        chu = {r: True for r in p.chu.bound(uid)}
        if chu.get("cn"):
            src = (p.chu_svc.cn.get(uid) or {}).get("source")
            chu["cn"] = src if src in ("lx", "lxqq", "lxoauth") else "df"
        off = getattr(p, "geki_official", None)
        geki = {"jp": bool(off is not None and off.bound(uid))}
        return {"mai": mai, "chu": chu, "geki": geki}

    def lx_options(self) -> dict:
        p = self.p
        oauth = getattr(p, "lx_oauth", None)
        return {"oauth": bool(oauth is not None and oauth.configured and p.lx_oauth_redirect()),
                "qq": bool(getattr(p.service, "lx_dev", ""))}

    async def lx_oauth_complete(self, uid: str) -> tuple[bool, list[str]]:
        """授权回来以后：用这个玩家的令牌分别看舞萌 / 中二国服有没有数据，有就绑上（一次授权两个游戏）。"""
        try:
            from . import lxns as LX
        except ImportError:
            from core import lxns as LX
        p = self.p
        access = await p.lx_oauth.access(uid)
        ok, lines = False, []
        for game, name in (("maimai", "舞萌"), ("chunithm", "中二")):
            try:
                kw = {"transport": p.service.lx_transport} if game == "maimai" else \
                     {"transport": p.chu_svc.lx_transport, "proxy": p.chu_svc.settings.proxy}
                d = await LX.player(game, access, **kw)
            except LX.LxnsError as e:
                lines.append(f"{name}国服：没绑上（{e}）")
                continue
            ok = True
            if game == "maimai":
                p.store.set_creds(uid, "cn", {"source": "lxoauth", "qq": str(uid)})
                p.cmd._drop_cn_snapshot(uid)
                lines.append(f"舞萌国服绑定成功（落雪授权）：{d.get('name') or ''}，Rating {d.get('rating') or 0}")
            else:
                p.chu_svc.cn.set(uid, {"source": "lxoauth"}, str(d.get("name") or ""))
                p.chu_svc._cache.pop((uid, "cn_b50"), None)
                lines.append(f"中二国服绑定成功（落雪授权）：{d.get('name') or ''}，Rating {float(d.get('rating') or 0):.2f}")
            if getattr(p, "prefs", None):
                p.prefs.set_last(uid, "mai" if game == "maimai" else "chu", "cn")
        if not ok:
            p.lx_oauth.forget(uid)
        return ok, lines

    def consent_needed(self, uid: str) -> bool:
        cmd = self.p.cmd
        return bool(getattr(cmd, "require_consent", True)) and not self.p.store.has_consent(uid)

    # ---------- 绑定 ----------
    async def bind(self, uid: str, form: dict) -> str:
        game = str(form.get("game") or "")
        server = str(form.get("server") or "")
        method = str(form.get("method") or "")
        agree = bool(form.get("agree"))
        value = str(form.get("value") or "").strip().strip("\"'“”‘’「」")
        sega_id = str(form.get("sega_id") or "").strip()
        password = str(form.get("password") or "")
        combo = (game, server, method)
        allowed = {("mai", "intl", "clal"), ("mai", "intl", "sega"), ("mai", "jp", "sega"),
                   ("mai", "cn", "df"), ("mai", "cn", "lx"), ("mai", "cn", "lxqq"), ("chu", "cn", "lxqq"),
                   ("chu", "intl", "clal"), ("chu", "intl", "sega"), ("chu", "jp", "sega"), ("chu", "cn", "df"), ("chu", "cn", "lx"),
                   *((g, "priv", m) for g in ("mai", "chu") for m in PRIV_METHODS),
                   ("geki", "priv", "aqua"),            # 音击私服只有 AquaDX 能查；绑定本身三个游戏共用
                   ("geki", "jp", "sega")}              # 音击官服：SEGA ID 登录 オンゲキ-NET（要 Standard）
        if combo not in allowed:
            raise BindError("游戏 / 区服 / 方式不对，刷新页面再试")
        if server == "priv":
            return await self._priv(uid, game, method, value, form, agree)
        secret = method in ("clal", "sega", "lx")
        if secret and not agree:
            raise BindError("要先勾选同意说明")
        if method == "clal":
            if not CLAL_RE.fullmatch(value):
                raise BindError("clal 应该是 64 位字母和数字（不要带「clal=」、引号或空格）")
        elif method == "sega":
            if not SEGA_ID_RE.fullmatch(sega_id):
                raise BindError("SEGA ID 格式不对（只填 ID 本身）")
            if not password or len(password) > 128:
                raise BindError("请填密码")
        elif method == "lx":
            if not TOKEN_RE.fullmatch(value):
                raise BindError("落雪密钥格式不对：在落雪网站「账号详情 → 个人 API 密钥」里复制完整的一串")
        elif method == "df" and value and not DF_NAME_RE.fullmatch(value):
            raise BindError("水鱼用户名格式不对（不能有空格）；不填就用你的 QQ 去水鱼查")

        ctx = Ctx(uid=str(uid), private=True, admin=False, name="")
        secrets_used = [s for s in (value if method in ("clal", "lx") else "", password) if s]
        for s in secrets_used:
            REDACTOR.remember(s)
        try:
            if game == "geki":
                return await self.p.geki_official.bind(ctx.uid, "", sega_id, password)
            if game == "mai":
                return await self._mai(ctx, server, method, value, sega_id, password, agree)
            return await self._chu(ctx, server, method, value, sega_id, password)
        finally:
            for s in secrets_used:
                REDACTOR.forget(s)

    async def _priv(self, uid: str, game: str, method: str, value: str, form: dict, agree: bool) -> str:
        """私服：走两个游戏共用的 core/privsrv/bind（和聊天里「/mai 绑定 munet …」同一条路）。"""
        if method in ("munet", "aqua"):
            name = parse_username(value)
            if not name or (re.search(r"\s", value) and "/u/" not in value):     # 网页是一个输入框：不收带空格的
                raise BindError("用户名格式不对：填网站个人主页 /u/ 后面那段（也可以直接粘贴主页链接）")
            args, secrets_used = [name], []
        else:
            if not agree:
                raise BindError("要先勾选同意说明")
            if method == "rin":
                account = str(form.get("account") or "").strip()
                password = str(form.get("password") or "")
                code = str(form.get("code") or "").strip()
                if not RIN_ACCOUNT_RE.fullmatch(account):
                    raise BindError("账号格式不对（账号或邮箱，不能有空格）")
                if not password or len(password) > 128:
                    raise BindError("请填密码")
                if code and not re.fullmatch(r"\d{6}", code):
                    raise BindError("两步验证码是 6 位数字；没开两步验证就不填")
                args, secrets_used = [account, password] + ([code] if code else []), [password]
            else:
                if not RIN_TOKEN_RE.fullmatch(value):
                    raise BindError("refreshToken 格式不对：复制 currentAccount 里 refreshToken 引号中的那一串")
                args, secrets_used = ["token", value], [value]
        ctx = Ctx(uid=str(uid), private=True, admin=False, name="")
        for x in secrets_used:
            REDACTOR.remember(x)
        try:
            if game == "geki":                      # /geki 绑定 aqua <用户名> 同一条路（验证用户存在后写进共用绑定）
                r = await self.p.geki._bind(ctx, ["aqua", *args])
            else:
                handler = self.p.cmd if game == "mai" else self.p.chu
                r = await handler._bind_priv(ctx, PRIV_METHODS[method], args)
        finally:
            for x in secrets_used:
                if x != value:            # refreshToken 绑定后一直打码；密码用完就丢
                    REDACTOR.forget(x)
        return "\n".join(r.texts)

    async def _mai(self, ctx: Ctx, server, method, value, sega_id, password, agree) -> str:
        cmd = self.p.cmd
        if method in ("clal", "sega", "lx") and agree and self.consent_needed(ctx.uid):
            self.p.store.give_consent(ctx.uid)
        if method == "clal":
            r = await cmd._finish_bind(ctx, "intl", {"clal": value})
        elif method == "sega":
            r = await cmd._finish_bind(ctx, server, {"sega_id": sega_id, "password": password})
        elif method == "lx":
            r = await cmd._finish_lx(ctx, value)
        elif method == "lxqq":
            r = await cmd._bind_lx_qq(ctx)
        else:
            r = await cmd._bind_cn(ctx, [value] if value else [])
        return "\n".join(r.texts)

    async def _chu(self, ctx: Ctx, server, method, value, sega_id="", password="") -> str:
        chu = self.p.chu
        if method == "sega":
            r = await chu._bind_sega(ctx, [sega_id, password], server)
        elif method == "clal":
            r = await chu.handle(ctx, "绑定 " + value)
        elif method == "lx":
            r = await chu.handle(ctx, "绑定 落雪 " + value)
        elif method == "lxqq":
            r = await chu.handle(ctx, "绑定 落雪")
        else:
            r = await chu.handle(ctx, "绑定 国服" + (" " + value if value else ""))
        return "\n".join(r.texts)


def is_success(text: str) -> bool:
    first = (text or "").split("\n", 1)[0]
    return "绑定成功" in first and "失败" not in first


class BindWeb:
    def __init__(self, binder: Binder, *, host: str = "127.0.0.1", port: int = 36199, bot_name: str = "AstrBot",
                 notify: Callable[..., Awaitable[Any]] | None = None, log: Callable[[str], Any] | None = None,
                 sessions: Sessions | None = None, extra: list | None = None):
        self.binder = binder
        self.extra = list(extra or [])        # 同一个服务上的别的页面（传分网站）：对象要有 add_routes(app)
        self.host, self.port = host, int(port)
        self.bot_name = bot_name
        self.notify = notify
        self.log = log or (lambda s: None)
        self.sessions = sessions or Sessions()
        self.ip_api = RateLimit(60, 60)
        self.ip_bind = RateLimit(8, 60)
        self._runner = None
        self.running = False
        self.error = ""

    # ---------- 生命周期 ----------
    def app(self):
        from aiohttp import web

        @web.middleware
        async def headers(request, handler):
            try:
                resp = await handler(request)
            except web.HTTPException as e:
                for k, v in SECURITY_HEADERS.items():
                    e.headers.setdefault(k, v)
                raise
            for k, v in SECURITY_HEADERS.items():
                resp.headers.setdefault(k, v)
            return resp

        app = web.Application(client_max_size=16 * 1024, middlewares=[headers])
        app.router.add_get("/", self.page)
        app.router.add_get("/app.js", self.static)
        app.router.add_get("/app.css", self.static)
        app.router.add_get("/img/{name}", self.image)
        app.router.add_get("/healthz", self.health)
        app.router.add_get("/api/session", self.api_session)
        app.router.add_post("/api/bind", self.api_bind)
        app.router.add_post("/api/lx/start", self.api_lx_start)
        app.router.add_get("/lxns/callback", self.lx_callback)
        for x in self.extra:
            if hasattr(x, "attach_bind"):
                x.attach_bind(self)
            x.add_routes(app)
        return app

    async def start(self, retries: int = 10) -> bool:
        from aiohttp import web
        runner = web.AppRunner(self.app(), access_log=None)
        await runner.setup()
        for i in range(retries):
            try:
                site = web.TCPSite(runner, self.host, self.port)
                await site.start()
                self._runner, self.running, self.error = runner, True, ""
                return True
            except OSError as e:          # 热重载时旧实例可能还没放开端口
                self.error = f"{type(e).__name__}: {e}"
                await asyncio.sleep(1.0)
        await runner.cleanup()
        return False

    async def stop(self) -> None:
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            finally:
                self._runner, self.running = None, False

    # ---------- 工具 ----------
    @staticmethod
    def client_ip(request) -> str:
        remote = request.remote or ""
        if remote in LOCAL:          # 隧道从本机进来：真实 IP 在 Cloudflare 的头里
            return (request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "")
                    .split(",")[0].strip() or remote)
        return remote

    def _json(self, data: dict, status: int = 200):
        from aiohttp import web
        return web.json_response(data, status=status, dumps=lambda o: json.dumps(o, ensure_ascii=False))

    def _session(self, request, claim_ok: bool = False) -> tuple[str, Session | None, str]:
        """→ (令牌, 会话, 错误)。群里发出的链接只认第一个打开它的浏览器（X-Bind-Claim）。"""
        token = request.headers.get("X-Bind-Token", "").strip()
        s = self.sessions.get(token)
        if s is None:
            return token, None, "expired"
        if s.group:
            if not s.claim:
                return token, None, "pending"         # 还没在 QQ 确认：除了 /api/session 什么都不给
            got = request.headers.get("X-Bind-Claim", "")
            if not got or not secrets.compare_digest(got, s.claim):
                return token, None, "claimed"
        return token, s, ""

    def _pending(self, request, s: Session):
        """群链接还没确认：给这个浏览器一个确认码（同一个浏览器再问还是同一个码）。满了返回 None。"""
        got = request.headers.get("X-Bind-Claim", "")
        if got and got in s.pend:
            return "", s.pend[got]
        if len(s.pend) >= MAX_PENDING:
            return None
        claim = secrets.token_urlsafe(18)
        code = f"{secrets.randbelow(10000):04d}"
        while code in s.pend.values():
            code = f"{secrets.randbelow(10000):04d}"
        s.pend[claim] = code
        return claim, code

    # ---------- 页面 ----------
    async def page(self, request):
        from aiohttp import web
        with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
            html = f.read().replace("{{BOT}}", _esc(self.bot_name))
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def static(self, request):
        from aiohttp import web
        name = request.path.lstrip("/")
        ctype = "application/javascript" if name.endswith(".js") else "text/css"
        with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type=ctype, charset="utf-8")

    async def image(self, request):
        """看板娘图片：只给 web/bind/img 里的 .webp，文件名只许小写字母、数字和连字符。"""
        from aiohttp import web
        name = request.match_info.get("name", "")
        if not IMG_RE.fullmatch(name):
            raise web.HTTPNotFound()
        path = os.path.join(WEB_DIR, "img", name)
        if not os.path.isfile(path):
            raise web.HTTPNotFound()
        with open(path, "rb") as f:
            # 图片里没有任何个人信息，可以缓存；页面和接口照旧 no-store
            return web.Response(body=f.read(), content_type="image/webp",
                                headers={"Cache-Control": "public, max-age=86400"})

    async def health(self, request):
        return self._json({"ok": True})

    # ---------- 接口 ----------
    async def api_session(self, request):
        if not self.ip_api.allow(self.client_ip(request)):
            return self._json({"error": "请求太频繁，稍等一分钟"}, 429)
        token, s, err = self._session(request)
        if s is None and err == "pending":
            ps = self.sessions.get(token)
            got = self._pending(request, ps) if ps is not None else None
            if got is None:
                return self._json({"error": "claimed"}, 409)
            return self._json({"pending": True, "claim": got[0], "code": got[1], "group": True, "bot": self.bot_name,
                               "expires_in": max(0, int(ps.exp - time.time()))})
        if s is None:
            return self._json({"error": err}, 409 if err == "claimed" else 401)
        claim = ""
        return self._json({
            "claim": claim, "group": s.group,
            "bot": self.bot_name, "qq": mask_qq(s.uid), "name": s.name,
            "expires_in": max(0, int(s.exp - time.time())),
            "bound": self.binder.status(s.uid),
            "consent": {"mai": CONSENT_TEXT.rsplit("\n", 1)[0], "lx": LX_CONSENT_TEXT.rsplit("\n", 1)[0],
                        "lxoauth": LX_OAUTH_CONSENT},
            "lx": self.binder.lx_options(),
        })

    async def api_lx_start(self, request):
        """网页上点「去落雪授权」→ 返回落雪授权页地址（state 绑定这个 QQ）。"""
        ip = self.client_ip(request)
        if not self.ip_api.allow(ip) or not self.ip_bind.allow(ip):
            return self._json({"ok": False, "message": "提交太频繁，稍等一分钟再试"}, 429)
        if request.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json({"ok": False, "message": "bad request"}, 415)
        token, s, err = self._session(request)
        if s is None:
            return self._json({"ok": False, "message": "链接已过期，重新发「/网页绑定」要一个新的"}, 409 if err == "claimed" else 401)
        try:
            form = await request.json()
        except Exception:  # noqa: BLE001
            form = {}
        if not self.binder.lx_options()["oauth"]:
            return self._json({"ok": False, "message": "bot 主人还没配置落雪授权"})
        if not (isinstance(form, dict) and form.get("agree")):
            return self._json({"ok": False, "message": "要先勾选「我看完了，同意」"})
        s.submits += 1
        if s.submits > MAX_SUBMITS:
            self.sessions.revoke(token)
            return self._json({"ok": False, "message": "这个链接提交次数太多，已作废；私聊我重新要一个"}, 429)
        p = self.binder.p
        if self.binder.consent_needed(s.uid):
            p.store.give_consent(s.uid)
        url = p.lx_oauth.begin(s.uid, p.lx_oauth_redirect(), extra={"umo": s.umo, "group": s.group})
        self.log(f"[otoge] web bind lxoauth start {mask_qq(s.uid)}")
        return self._json({"ok": True, "url": url})

    async def lx_callback(self, request):
        """落雪授权完跳回来：?code=&state=（拒绝时 ?error=access_denied）。"""
        if not self.ip_api.allow(self.client_ip(request)):
            return self._result_page(False, "请求太频繁，稍等一分钟再试")
        q = request.query
        if q.get("error"):
            return self._result_page(False, "你取消了授权，什么都没改。想绑的话回到绑定页再点一次。")
        state, code = q.get("state", ""), q.get("code", "")
        p = self.binder.p
        if not state or not code or p.lx_oauth.pending(state) is None:
            return self._result_page(False, "这个授权链接已经用过或过期了。回 QQ 重新发「/网页绑定」。")
        try:
            uid, extra = await asyncio.wait_for(p.lx_oauth.finish(state, code), 30)
            ok, lines = await asyncio.wait_for(self.binder.lx_oauth_complete(uid), 40)
        except Exception as e:  # noqa: BLE001
            self.log(f"[otoge] web bind lxoauth callback error {type(e).__name__}")
            msg = str(e) if type(e).__name__ in ("LxnsError", "OAuthExpired") else f"出错了：{type(e).__name__}"
            return self._result_page(False, msg)
        self.log(f"[otoge] web bind lxoauth {mask_qq(uid)} {'ok' if ok else 'failed'}")
        if ok and self.notify and extra.get("umo"):
            first = next((x for x in lines if "绑定成功" in x), lines[0] if lines else "")
            try:
                if extra.get("group"):
                    await self.notify(extra["umo"], f"网页绑定好了：{first}\n不是你本人操作的话，马上发「/mai 解绑 国服」「/chu 解绑 国服」",
                                      at=uid)
                else:
                    await self.notify(extra["umo"], "【网页绑定】" + "\n".join(lines)
                                      + "\n不是你本人操作的话，马上发「/mai 解绑 国服」「/chu 解绑 国服」。")
            except Exception:  # noqa: BLE001
                pass
        tail = "\n\n可以关掉这页，回 QQ 发 /mai b50 或 /chu b50。" if ok else ""
        return self._result_page(ok, "\n".join(lines) + tail)

    def _result_page(self, ok: bool, msg: str):
        from aiohttp import web
        body = "".join(f"<p>{_esc(x)}</p>" if x else "" for x in msg.split("\n"))
        pose = "ok" if ok else "gone"
        girl = (f'<img class="notice-girl" src="/img/yume-{pose}.webp" alt="" width="520" height="388">'
                if os.path.isfile(os.path.join(WEB_DIR, "img", f"yume-{pose}.webp")) else "")   # 公开版包里没有这张图
        html = (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>落雪授权 · {_esc(self.bot_name)}</title>'
                f'<link rel="stylesheet" href="/app.css"></head><body><main class="wrap">'
                f'<header class="top"><div class="bar"><span class="brand">{_esc(self.bot_name)} 音游查分</span></div>'
                f'<div class="rule" aria-hidden="true"><i></i><i></i></div>'
                f'<h1>{"授权成功" if ok else "没有绑上"}</h1></header>'
                f'{girl}'
                f'<div class="result {"ok" if ok else "bad"}">{body}</div></main></body></html>')
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def api_bind(self, request):
        ip = self.client_ip(request)
        if not self.ip_api.allow(ip) or not self.ip_bind.allow(ip):
            return self._json({"ok": False, "message": "提交太频繁，稍等一分钟再试"}, 429)
        if request.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json({"ok": False, "message": "bad request"}, 415)
        token, s, err = self._session(request)
        if s is None:
            if err == "claimed":
                return self._json({"ok": False, "message": "这个链接已经在别的设备上打开了。是你自己的话回那台设备上填；"
                                                           "不是的话重新发「/网页绑定」要一个新的"}, 409)
            return self._json({"ok": False, "message": "链接已过期，重新发「/网页绑定」要一个新的"}, 401)
        try:
            form = await request.json()
            if not isinstance(form, dict):
                raise ValueError
        except Exception:  # noqa: BLE001
            return self._json({"ok": False, "message": "bad request"}, 400)
        if s.lock.locked():
            return self._json({"ok": False, "message": "上一个还在处理，等一下"}, 409)
        async with s.lock:
            s.submits += 1
            if s.submits > MAX_SUBMITS:
                self.sessions.revoke(token)
                return self._json({"ok": False, "message": "这个链接提交次数太多，已作废；私聊我重新要一个"}, 429)
            tag = f"{form.get('game')}/{form.get('server')}/{form.get('method')}"
            try:
                msg = await asyncio.wait_for(self.binder.bind(s.uid, form), 60)
            except BindError as e:
                return self._json({"ok": False, "message": str(e)})
            except asyncio.TimeoutError:
                self.log(f"[otoge] web bind {tag} {mask_qq(s.uid)} timeout")
                return self._json({"ok": False, "message": "查分服务器太慢了，过一会儿再试"})
            except Exception as e:  # noqa: BLE001
                self.log(f"[otoge] web bind {tag} {mask_qq(s.uid)} error {type(e).__name__}")
                return self._json({"ok": False, "message": f"出错了：{type(e).__name__}"})
            ok = is_success(msg)
            self.log(f"[otoge] web bind {tag} {mask_qq(s.uid)} {'ok' if ok else 'failed'}")
            if ok and self.notify and s.umo:
                first = msg.split("\n", 1)[0]
                try:
                    if s.group:     # 群里只说一句结果，不带名字 / rating 以外的东西
                        await self.notify(s.umo, f"网页绑定好了：{first}\n不是你本人操作的话，马上发「/mai 解绑」「/chu 解绑」",
                                          at=s.uid)
                    else:
                        await self.notify(s.umo, f"【网页绑定】{first}\n不是你本人操作的话，马上发「/mai 解绑」「/chu 解绑」。")
                except Exception:  # noqa: BLE001
                    pass
            return self._json({"ok": ok, "message": msg, "bound": self.binder.status(s.uid)})


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
