"""Command parsing + handlers, independent of AstrBot (main.py adapts events to this)."""
from __future__ import annotations

import asyncio
import contextvars
import re
import time
from dataclasses import dataclass, field

import httpx

from ..calc.rating import attach_charts, chart_rating, min_ach_for_rating
from ..calc.sample import THEORY_WORDS, is_sample, sample_best50
from ..data.fuzzy import COMMON_SLIPS, alias_pick, decide, split_glued, suggest
from ..consts import (API_REGIONS, DIFF_ALIASES, DIFF_LABEL, PRIV_REGIONS, REGION_ALIASES, REGION_NAMES,
                      catalog_region, fmt_ach)
from ..net.client import LoginFailed, NetLocked
from ..parse.html import NetLoggedOut, NetMaintenance, NetPageError
from ..render import text as T
from ..service import MaiService, NotBound, NotSupported
from .guard import CONSENT_TEXT, LX_CONSENT_TEXT, REDACTOR, FlowBook, looks_like_clal

try:
    from ...core import cnupdate as CU
    from ...core.privsrv import PrivError, SERVERS as PRIV_SERVERS
    from ...core.privsrv.bind import bind as priv_bind
    from ...core.privsrv.servers import parse_username as priv_username  # noqa: F401
except ImportError:  # tests import mai as a top-level package
    from core import cnupdate as CU
    from core.privsrv import PrivError, SERVERS as PRIV_SERVERS
    from core.privsrv.bind import bind as priv_bind
    from core.privsrv.servers import parse_username as priv_username  # noqa: F401  (re-exported for tests)

NET_TIMEOUT = 120
LX_WORDS = ("落雪", "lxns", "luoxue", "落雪查分器")
LX_HOWTO = ("绑定落雪：登录 maimai.lxns.net →「账号详情」→「个人 API 密钥」生成一个，"
            "然后私聊我发「/mai 绑定 落雪 <密钥>」。绑好后发 /mai b50 就是国服的 B50")

HELP = """舞萌 DX 查分（国际服 / 日服 / 国服）
/网页绑定 — 拿个人链接，用手机网页绑定（群里私聊都行，最省事）
/mai 绑定 [国际服|日服] — 私聊绑定（国际服可直接带 clal）
/mai 绑定 国服 [水鱼用户名] — 国服走水鱼（不填就用 QQ 查）
/mai 绑定 落雪 <个人API密钥> — 国服走落雪（私聊；能查全部成绩）
/mai 绑定 munet <网站用户名> — 私服 MuNET（舞萌中二共用，群里也能绑）
/mai 绑定 rin <账号> <密码> — 私服 RinNET（私聊；只存登录令牌）
/mai 绑定 aqua <网站用户名> — 私服 AquaDX（群里也能绑）
/mai 解绑 [区服]　/mai 切换 国际服|日服|国服|munet|rin|aqua
/mai b50 [区服] [文字]　/mai 理论 [区服]（理论 Rating）
/mai 刷新　/mai 我
/mai 最近 [条数]　/mai 详情 [第几条]
/mai 查歌 <歌名/别名/ID>（带曲绘的谱面详情图）
/mai 定数 14.9 [15.0]（定数查歌卡片）　/mai 定数表 14+
/mai 随歌 [dx|sd] [紫|白…] [13+]　/mai 分数线 <定数>
/mai 好友码 <好友码>　/mai 公开 开|关　/mai b50 @某人
/mai 曲库
谱面图（sdvx.in 没有舞萌）：/chu 谱面、/sdvx 谱面、/pjsk 谱面、/谱面 <歌名>"""


@dataclass
class Reply:
    texts: list[str] = field(default_factory=list)
    image: bytes | None = None
    recall: bool = False      # try to recall the user's message (contains a secret)
    stop: bool = True
    at: str | None = None     # @ this QQ at the start of the reply (group web-bind links)

    def say(self, t: str) -> "Reply":
        self.texts.append(t)
        return self


FLAG_TEXT = {"fc": "FC", "fcp": "FC+", "ap": "AP", "app": "AP+", "sync": "SYNC", "fs": "FS", "fsp": "FS+",
             "fsd": "FDX", "fsdp": "FDX+"}


@dataclass
class Ctx:
    uid: str
    private: bool
    admin: bool
    at_uid: str | None = None
    name: str = ""


def split_args(args: list[str]) -> tuple[str | None, list[str]]:
    region, rest = None, []
    for a in args:
        r = REGION_ALIASES.get(a.lower())
        if r and region is None:
            region = r
        else:
            rest.append(a)
    return region, rest


def friendly_error(e: BaseException) -> str:
    if isinstance(e, PrivError):          # 私服：消息本身就是给用户看的
        return str(e)
    if isinstance(e, NotBound):
        code = str(e.args[0]) if e.args else ""
        if code in PRIV_SERVERS:
            return f"你还没绑定 {REGION_NAMES[code]}，发「/mai 绑定 {code} <网站用户名>」"
        if code == "cn":
            why = (str(e.args[1]) + "。\n") if len(e.args) > 1 else ""
            return why + "你还没绑定舞萌国服，发「/mai 绑定 国服 <水鱼用户名>」或私聊「/mai 绑定 落雪 <个人API密钥>」"
        return f"你还没有绑定{REGION_NAMES.get(code, '')}，私聊我发 /mai 绑定（国服发 /mai 绑定 国服 <水鱼用户名>）"
    if isinstance(e, NotSupported):
        return str(e)
    if type(e).__name__ == "DivingFishError":
        return f"水鱼查分器：{e}"
    if type(e).__name__ == "LxnsError":
        return f"落雪查分器：{e}"
    if isinstance(e, LoginFailed):
        return f"登录 NET 失败：{e}。clal 可能过期了，私聊 /mai 绑定 重新绑一下"
    if isinstance(e, NetLocked):
        return f"NET 说请求太频繁（200001），先歇 {e.seconds_left // 60 + 1} 分钟再查"
    if isinstance(e, NetMaintenance):
        return "maimai DX NET 正在维护，等维护结束再查"
    if isinstance(e, NetPageError):
        if e.code == "200001":
            return "NET 说请求太频繁（200001），先歇 5 分钟再查"
        return f"NET 报错 {e.code}：{e.message}"
    if isinstance(e, NetLoggedOut):
        return "NET 登录状态丢了，再试一次；还不行就重新绑定"
    if isinstance(e, (httpx.TimeoutException, asyncio.TimeoutError)):
        return "NET 响应超时（SEGA 服务器可能不稳），晚点再试"
    if isinstance(e, httpx.HTTPError):
        return f"连不上 NET：{type(e).__name__}"
    return f"出错了：{type(e).__name__}: {e}"


_HINT: contextvars.ContextVar[str] = contextvars.ContextVar("mai_hint", default="")


class Commands:
    GAME = "mai"

    def __init__(self, service: MaiService, *, require_consent: bool = True, cache_minutes: int = 10,
                 renderer=None, prefs=None):
        self.prefs = prefs         # core.prefs.Prefs: last-used server + catalog default server
        self.svc = service
        self.flows = FlowBook()
        self.require_consent = require_consent
        self.cache_seconds = cache_minutes * 60
        self.renderer = renderer   # callable(best50, profile, db, at) -> bytes | None
        self.cards = None          # render.cards.CardRenderer (查歌 / 定数 images); None → text
        self.aliases = None        # data.aliases.AliasStore (local 加别名 / 删别名)
        self._syncing: dict[tuple[str, str], asyncio.Task] = {}   # 同一个人同一个服同时发两条 b50 → 只同步一次
        self._img_memo: dict[str, tuple[tuple, bytes]] = {}        # uid → ((区服, 同步时间), 图)：成绩没变就不重画

    @property
    def db(self):
        return self.svc.catalog.db

    # ---------- entry ----------
    async def handle(self, ctx: Ctx, argline: str) -> Reply:
        args = argline.split()
        sub = (args[0].lower() if args else "帮助")
        rest = args[1:]
        table = {
            "帮助": self.c_help, "help": self.c_help,
            "绑定": self.c_bind, "bind": self.c_bind,
            "解绑": self.c_unbind, "unbind": self.c_unbind,
            "切换": self.c_switch,
            "b50": self.c_b50, "best50": self.c_b50,
            **{w: self.c_theory for w in THEORY_WORDS},
            "刷新": self.c_refresh, "更新": self.c_refresh, "sync": self.c_refresh,
            "我": self.c_me, "info": self.c_me, "资料": self.c_me,
            "最近": self.c_recent, "recent": self.c_recent,
            "详情": self.c_detail,
            "查歌": self.c_song, "查": self.c_song, "song": self.c_song,
            "定数": self.c_ds, "定数查歌": self.c_ds,
            "定数表": self.c_dstable, "id": self.c_song,
            "随歌": self.c_random, "随个": self.c_random,
            "分数线": self.c_line,
            "好友码": self.c_friend,
            "公开": self.c_public,
            "曲库": self.c_catalog,
            "别名": self.c_alias, "外号": self.c_alias, "alias": self.c_alias,
            "加别名": self.c_alias_add, "添加别名": self.c_alias_add,
            "删别名": self.c_alias_del, "删除别名": self.c_alias_del,
            "成绩": self.c_score, "单曲": self.c_score, "分数": self.c_score,
        }
        fn = table.get(sub)
        if fn is None and table.get(COMMON_SLIPS.get(sub, "")):      # 查曲 / 查谱 / b40 / 外号 … mean the same
            fn = table[COMMON_SLIPS[sub]]
        if fn is None and args and (sp := split_glued(args[0], table)):
            sub, glued = sp                    # 「/mai 查歌救护车」「/mai b50文字」
            fn, rest = table[sub], [glued, *rest]
        if fn is None:
            if args and (song := self._lone_song(argline)) is not None:
                fn, rest = self.c_song, [str(min(song.music_ids()) if song.music_ids() else song.title)]
            else:
                sug = suggest(sub, table)
                tip = f"，是不是想发「/mai {sug[0]}{(' ' + ' '.join(rest)) if rest else ''}」？" if sug else "。"
                return Reply().say(f"没有「{sub}」这个指令{tip}\n舞萌的指令发「/mai 帮助」看～")
        _HINT.set("")
        try:
            r = await fn(ctx, rest)
        except Exception as e:  # never leak a traceback with secrets into chat
            return Reply().say(friendly_error(e))
        if _HINT.get() and (r.texts or r.image):
            r.say(_HINT.get())
        return r

    def _catalog_region(self) -> str:
        return self.prefs.catalog_server("mai") if self.prefs else "intl"

    async def c_help(self, ctx, rest):
        return Reply().say(HELP)

    # ---------- binding ----------
    async def c_bind(self, ctx: Ctx, rest):
        if any(a.lower() in LX_WORDS for a in rest):
            return await self._bind_lx(ctx, rest)
        region, rest = split_args(rest)
        if region == "cn":
            return await self._bind_cn(ctx, rest)
        if region in PRIV_REGIONS:
            return await self._bind_priv(ctx, region, rest)
        secret_given = any(looks_like_clal(a) for a in rest) or len(rest) >= 2
        if not ctx.private:
            r = Reply().say(("刚才那条带了凭据，我试着撤回了；保险起见去 NET 重新登录一次让旧 clal 失效。\n" if secret_given else "")
                            + "国际服 / 日服要填凭据，别在群里发：发「/网页绑定」拿链接在网页上填（国服水鱼可以直接「/mai 绑定 国服 <水鱼用户名>」）")
            r.recall = secret_given
            return r
        region = region or "intl"
        clal = next((a for a in rest if looks_like_clal(a)), "")
        if self.require_consent and not ctx.admin and not self.svc.store.has_consent(ctx.uid):
            self.flows.start(ctx.uid, region, "consent", clal=clal)
            return Reply().say(CONSENT_TEXT)
        return await self._bind_next(ctx, region, clal)

    async def _bind_next(self, ctx: Ctx, region: str, clal: str = "") -> Reply:
        if region == "intl" and clal:
            return await self._finish_bind(ctx, region, {"clal": clal})
        if region == "intl":
            self.flows.start(ctx.uid, region, "method")
            return Reply().say("国际服两种绑法，直接回复：\n"
                               "① 发 clal（64 位，在 lng-tgk-aime-gw.am-all.net 的 Cookie 里）\n"
                               "② 回复「账号」用 SEGA ID + 密码（clal 过期时能自动续登）\n回复「取消」放弃")
        self.flows.start(ctx.uid, region, "sega_id")
        return Reply().say("日服只能用 SEGA ID 登录。请回复你的 SEGA ID（回复「取消」放弃）")

    async def on_flow_message(self, ctx: Ctx, text: str) -> Reply | None:
        """Called for every private message while a binding flow is open. None = not ours."""
        f = self.flows.get(ctx.uid)
        if f is None:
            if ctx.private and looks_like_clal(text) and not text.strip().startswith("/"):
                return Reply().say("这看起来像 clal。绑定舞萌国际服请发：/mai 绑定 国际服 <clal>（中二是 /chu 绑定 <clal>）")
            return None
        t = text.strip()
        if t in ("取消", "cancel", "/取消"):
            self.flows.end(ctx.uid)
            return Reply().say("已取消绑定")
        f.touch()
        if f.step == "consent":
            if t not in ("同意", "我同意", "yes"):
                return Reply().say("要继续请回复「同意」，放弃请回复「取消」")
            self.svc.store.give_consent(ctx.uid)
            clal = f.data.get("clal", "")
            self.flows.end(ctx.uid)
            if f.data.get("lx_token"):
                tok = f.data["lx_token"]
                r = await self._finish_lx(ctx, tok)
                REDACTOR.forget(tok)
                return r
            return await self._bind_next(ctx, f.region, clal)
        if f.step == "method":
            if looks_like_clal(t):
                self.flows.end(ctx.uid)
                return await self._finish_bind(ctx, f.region, {"clal": t.split()[0]})
            if t in ("账号", "②", "2", "sega", "segaid"):
                f.step = "sega_id"
                return Reply().say("请回复你的 SEGA ID")
            return Reply().say("没看懂，发 clal 或回复「账号」")
        if f.step == "sega_id":
            if not re.fullmatch(r"[A-Za-z0-9_.@\-]{3,64}", t):
                return Reply().say("SEGA ID 格式不对，再发一次（只要 ID 本身）")
            f.data["sega_id"] = t
            f.step = "password"
            return Reply().say("请回复密码。发完我会马上处理，也建议你随后删掉那条消息")
        if f.step == "password":
            REDACTOR.remember(t)
            f.data["password"] = t
            creds = {"sega_id": f.data["sega_id"], "password": t}
            self.flows.end(ctx.uid)
            r = await self._finish_bind(ctx, f.region, creds)
            r.recall = True
            REDACTOR.forget(t)
            return r
        return None

    async def _finish_bind(self, ctx: Ctx, region: str, creds: dict) -> Reply:
        try:
            prof = await asyncio.wait_for(self.svc.verify(region, creds), NET_TIMEOUT)
        except Exception as e:
            return Reply(recall=True).say("绑定失败：" + friendly_error(e))
        self.svc.store.set_creds(ctx.uid, region, creds)
        await self.svc.drop_session(ctx.uid, region)
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, region)
        others = [REGION_NAMES[r] for r in self.svc.bound_regions(ctx.uid) if r != region]
        tail = (f"\n你还绑了{'、'.join(others)}；现在默认查{REGION_NAMES[region]}，查别的服在指令后加区服" if others else "")
        return Reply(recall=True).say(
            f"绑定成功（{REGION_NAMES[region]}）：{prof.name}，Rating {prof.rating}\n"
            f"发 /mai b50 看看。凭据已加密保存，随时 /mai 解绑" + tail)

    async def _bind_lx(self, ctx: Ctx, rest) -> Reply:
        """国服 = 落雪查分器：个人 API 密钥（是凭据），只能私聊，加密保存。"""
        try:
            from ...core.lxns import find_token
        except ImportError:
            from core.lxns import find_token
        token = find_token(rest)
        if not token and self.svc.lx_dev:
            return await self._bind_lx_qq(ctx)
        if not token and getattr(self.svc.lx_oauth, "configured", False):
            return Reply().say("绑定落雪不用复制密钥了：发「/网页绑定」，选 国服 →「落雪授权」，在落雪页面点一下授权就好（舞萌中二一起绑）。")
        if not ctx.private:
            r = Reply().say(("刚才那条带了密钥，我试着撤回了；保险起见去落雪网站重新生成一个。\n" if token else "")
                            + "落雪密钥别在群里发：发「/网页绑定」拿链接在网页上填。水鱼不用密钥，群里也能绑：/mai 绑定 国服 <水鱼用户名>")
            r.recall = bool(token)
            return r
        if not token:
            return Reply().say(LX_HOWTO)
        REDACTOR.remember(token)
        if self.require_consent and not ctx.admin and not self.svc.store.has_consent(ctx.uid):
            self.flows.start(ctx.uid, "cn", "consent", lx_token=token)
            r = Reply().say(LX_CONSENT_TEXT)
            r.recall = True
            return r
        r = await self._finish_lx(ctx, token)
        REDACTOR.forget(token)
        return r

    async def _bind_lx_qq(self, ctx: Ctx) -> Reply:
        """不用密钥：bot 的落雪开发者令牌按 QQ 找账号。群里私聊都行。"""
        src = (self.svc.store.get_creds(ctx.uid, "cn") or {}).get("source")
        if src in ("lx", "lxoauth"):          # 已经能查全部成绩：别被「按 QQ」降级
            how = "个人密钥" if src == "lx" else "落雪授权"
            return Reply().say(f"你已经用{how}绑了落雪，能查全部成绩，不用再按 QQ 绑。要换方式先「/mai 解绑 国服」")
        try:
            prof = await asyncio.wait_for(self.svc.bind_cn_qq(ctx.uid), NET_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            return Reply().say("按 QQ 在落雪没找到你：" + friendly_error(e) + "\n"
                               "确认已在 maimai.lxns.net 绑定这个 QQ、同步过成绩，并在隐私设置里允许第三方查询。\n"
                               "也可以私聊「/mai 绑定 落雪 <个人API密钥>」")
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, "cn")
        self._drop_cn_snapshot(ctx.uid)
        return Reply().say(f"国服绑定成功（落雪 · 按 QQ）：{prof.name}，Rating {prof.rating}\n"
                           "发 /mai b50 看看。按 QQ 只能拿到 B50 范围的成绩。"
                           + ("\n" + "要查单曲 / 完成表 / 最近游玩等全部成绩：发「/网页绑定」选「落雪授权」点一下就行" if getattr(self.svc.lx_oauth, "configured", False)
                              else "要查单曲 / 完成表等全部成绩，私聊「/mai 绑定 落雪 <个人API密钥>」"))

    async def _finish_lx(self, ctx: Ctx, token: str) -> Reply:
        binding = {"source": "lx", "token": token}
        try:
            prof = await asyncio.wait_for(self.svc.verify("cn", binding), NET_TIMEOUT)
        except Exception as e:
            r = Reply().say("绑定落雪失败：" + friendly_error(e) + "\n" + LX_HOWTO)
            r.recall = True
            return r
        self.svc.store.set_creds(ctx.uid, "cn", binding)
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, "cn")
        self._drop_cn_snapshot(ctx.uid)
        others = [REGION_NAMES[r] for r in self.svc.bound_regions(ctx.uid) if r != "cn"]
        r = Reply(recall=True).say(
            f"国服绑定成功（落雪查分器）：{prof.name}，Rating {prof.rating}\n"
            "发 /mai b50 看看；密钥已加密保存，随时 /mai 解绑 国服。\n"
            "同一个密钥也能绑中二国服：私聊发「/chu 绑定 落雪 <密钥>」"
            + (f"\n你还绑了{'、'.join(others)}；现在默认查国服，查别的服在指令后加区服" if others else ""))
        return r

    def _drop_cn_snapshot(self, uid: str) -> None:
        """Switching 水鱼 ↔ 落雪: the cached 国服 scores came from the other source."""
        import os
        try:
            os.remove(self.svc.store._snap_path(uid, "cn"))
        except OSError:
            pass

    async def _bind_cn(self, ctx: Ctx, rest) -> Reply:
        """国服 = 水鱼查分器：用户名或 QQ，不涉及密码，群里也能绑。"""
        name = " ".join(rest).strip()
        binding = {"username": name} if name else {"qq": ctx.uid}
        try:
            prof = await asyncio.wait_for(self.svc.verify("cn", binding), NET_TIMEOUT)
        except Exception as e:
            return Reply().say("绑定国服失败：" + friendly_error(e) +
                               "\n用法：/mai 绑定 国服 <水鱼用户名>（不填就用你的 QQ 去水鱼查）")
        self.svc.store.set_creds(ctx.uid, "cn", binding)
        self._drop_cn_snapshot(ctx.uid)
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, "cn")
        others = [REGION_NAMES[r] for r in self.svc.bound_regions(ctx.uid) if r != "cn"]
        return Reply().say(f"国服绑定成功（水鱼查分器）：{prof.name}，Rating {prof.rating}\n"
                           + ("发 /mai b50 看看" if not others else
                              f"你还绑了{'、'.join(others)}；现在默认查国服，查别的服在指令后加区服"))

    async def _bind_priv(self, ctx: Ctx, region: str, rest) -> Reply:
        """私服绑定（逻辑在 core/privsrv/bind.py，两个游戏共用）；舞萌中二共用一份绑定。"""
        if self.svc.priv is None:
            return Reply().say("私服查分没有启用")
        out = await priv_bind(self.svc.priv, ctx.uid, region, list(rest), game="mai", private=ctx.private,
                              redactor=REDACTOR)
        if not out.ok:
            return Reply(recall=out.recall).say(out.text)
        self._drop_snapshot(ctx.uid, region)
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, region)
        name = REGION_NAMES[region]
        p = out.profile
        head = (f"{name} 绑定成功：{p.name}（{out.account}），舞萌 Rating {p.rating}" if p else
                f"{name} 绑定成功（{out.account}），不过这个号在 {name} 上还没有舞萌记录")
        if PRIV_SERVERS[region].auth == "login":
            head += "\n只加密保存了登录令牌，没存密码；随时「/mai 解绑 " + region + "」"
        others = [REGION_NAMES[r] for r in self.svc.bound_regions(ctx.uid) if r != region]
        return Reply(recall=out.recall).say(
            head + (f"（{out.text}）" if out.text else "") + f"\n中二也能直接查（/chu b50 {region}）。"
            + (f"你还绑了{'、'.join(others)}；现在默认查 {name}，查别的服在指令后加区服" if others else "发 /mai b50 看看"))

    def _drop_snapshot(self, uid: str, region: str) -> None:
        import os
        try:
            os.remove(self.svc.store._snap_path(uid, region))
        except OSError:
            pass

    async def c_unbind(self, ctx, rest):
        region, _ = split_args(rest)
        if region in PRIV_REGIONS:
            gone = self.svc.priv.bindings.remove(ctx.uid, region) if self.svc.priv else []
            self._drop_snapshot(ctx.uid, region)
            return Reply().say(f"已解绑 {REGION_NAMES[region]}（舞萌、中二、音击共用这一个绑定，三个游戏一起解了）" if gone
                               else f"你没绑定 {REGION_NAMES[region]}")
        removed = self.svc.store.unbind(ctx.uid, region)
        for r in removed:
            await self.svc.drop_session(ctx.uid, r)
        priv = [r for r in self.svc.bound_regions(ctx.uid) if r in PRIV_REGIONS] if not region else []
        keep = (f"\n{'、'.join(REGION_NAMES[r] for r in priv)} 是舞萌中二共用的绑定，没动；"
                f"要解绑发「/mai 解绑 {priv[0]}」" if priv else "")
        if not removed:
            return Reply().say("没有可解绑的记录" + keep)
        return Reply().say("已删除：" + "、".join(REGION_NAMES[r] for r in removed) + "（凭据和成绩缓存都删了）" + keep)

    async def c_switch(self, ctx, rest):
        region, _ = split_args(rest)
        if not region:
            return Reply().say("用法：/mai 切换 国际服|日服|国服|munet|rin|aqua")
        if region not in self.svc.bound_regions(ctx.uid):
            return Reply().say(f"你还没绑定{REGION_NAMES[region]}")
        self.svc.store.set_default_region(ctx.uid, region)
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, region)
        return Reply().say(f"之后默认查{REGION_NAMES[region]}（直接在指令后加区服也会自动切换）")

    def _region(self, uid: str, region: str | None, remember: bool = True) -> str:
        """Explicit server → use it and remember it; otherwise the server this user queried last."""
        bound = self.svc.bound_regions(uid)
        if region:
            if remember and self.prefs and region in bound:
                self.prefs.set_last(uid, self.GAME, region)
            return region
        last = self.prefs.last(uid, self.GAME) if self.prefs else ""
        r = last if last in bound else self.svc.default_region(uid)
        if not r and self.svc.lx_dev and str(uid).isdigit():
            r = "cn"            # 什么都没绑：先按 QQ 去落雪找（sync 里自动绑）
        if not r:
            raise NotBound("")
        others = [x for x in bound if x != r]
        if others and remember:
            ex = REGION_NAMES[others[0]]
            _HINT.set(f"（查的是{REGION_NAMES[r]}。要查{'/'.join(REGION_NAMES[o] for o in others)}就在指令后加区服，"
                      f"比如「/mai b50 {ex}」，之后会默认用你最后查的那个服）")
        return r

    # ---------- scores ----------
    async def _sync_once(self, uid: str, region: str):
        """Share one in-flight NET sync between concurrent commands for the same (user, server)."""
        key = (uid, region)
        task = self._syncing.get(key)
        if task is None or task.done():
            task = asyncio.ensure_future(asyncio.wait_for(self.svc.sync(uid, region), NET_TIMEOUT))
            self._syncing[key] = task
            task.add_done_callback(lambda t, k=key: self._syncing.pop(k, None) if self._syncing.get(k) is t else None)
        return await asyncio.shield(task)

    async def _snapshot(self, uid: str, region: str, *, force: bool = False):
        snap = None if force else self.svc.cached(uid, region)
        if snap is None or time.time() - snap.at > self.cache_seconds:
            try:
                snap = await self._sync_once(uid, region)
            except (NetMaintenance, NetLocked, httpx.HTTPError, asyncio.TimeoutError):
                old = self.svc.cached(uid, region)
                if old is None:
                    raise
                old.stale = True  # type: ignore[attr-defined]
                return old
        return snap

    async def c_b50(self, ctx: Ctx, rest):
        region, rest = split_args(rest)
        as_text = any(a in ("文字", "text", "txt") for a in rest)
        if is_sample(rest):
            return await self._b50_sample(catalog_region(region) or self._catalog_region(), as_text)
        uid = ctx.uid
        if ctx.at_uid and ctx.at_uid != ctx.uid:
            if not self.svc.store.is_public(ctx.at_uid):
                return Reply().say("对方没有开放查询（对方可以发 /mai 公开 开）")
            uid = ctx.at_uid
            region = self._region(uid, region, remember=False)
            snap = self.svc.cached(uid, region)
            if snap is None:
                return Reply().say("对方还没有同步过成绩")
        else:
            region = self._region(uid, region)
            snap = await self._snapshot(uid, region)
        b = snap.best50(self.svc.catalog)
        b.source = self._src_name(uid, region)
        b.show_dx = self.prefs.show(ctx.uid, "mai_dx") if self.prefs is not None and hasattr(self.prefs, "show") else True
        note = "（NET 暂时连不上，这是上次缓存的成绩）" if getattr(snap, "stale", False) else ""
        if region == "cn":              # 国服是查分器里存的那份：说明来源、上传时间、怎么更新
            note = (note + "\n" if note else "") + CU.b50_note(
                "mai", self.svc.cn_source(self.svc.store.get_creds(uid, "cn")),
                getattr(snap.profile, "uploaded_at", ""), getattr(self, "tz", None))
        if not as_text and self.renderer is not None:
            try:
                memo_key = (region, snap.at, b.source, getattr(snap, "stale", False), b.show_dx)
                memo = self._img_memo.get(uid)
                img = memo[1] if memo is not None and memo[0] == memo_key else None
                if img is None:
                    img = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: self.renderer(b, snap.profile, self.db, snap.at))
                    if img:
                        if len(self._img_memo) >= 8:
                            self._img_memo.pop(next(iter(self._img_memo)))
                        self._img_memo[uid] = (memo_key, img)
                if img:
                    r = Reply(image=img)
                    if note:
                        r.say(note)
                    return r
            except Exception as e:  # fall back to text
                note += f"（出图失败：{type(e).__name__}，先发文字版）"
        return Reply().say((note + "\n" if note else "") + T.best50_text(b, snap.profile, self.db, snap.at))

    def theory(self, region: str):
        """→ Best50：这个服当前版本全部 SSS+ AP+ 时的 B35 + B15。"""
        b, _prof = sample_best50(self.db, region)
        return b

    async def c_theory(self, ctx: Ctx, rest):
        """/mai 理论 [区服] [文字]：理论最高 Rating（不用绑定）。"""
        region, rest = split_args(rest)
        as_text = any(a in ("文字", "text", "txt") for a in rest)
        return await self._b50_sample(catalog_region(region) or self._catalog_region(), as_text)

    async def _b50_sample(self, region: str, as_text: bool) -> Reply:
        """理论最高 B50：当前版本每张谱面都 SSS+ AP+ 时的 B35 + B15（不需要绑定）。"""
        import time as _t
        b, prof = await asyncio.get_running_loop().run_in_executor(None, lambda: sample_best50(self.db, region))
        if not b.old and not b.new:
            return Reply().say("曲库还没加载好，稍后再试")
        head = f"{REGION_NAMES[region]}理论 Rating：{b.total}（B35 {b.old_total} + B15 {b.new_total}）"
        others = "、".join(f"/mai 理论 {REGION_NAMES[x]}" for x in ("intl", "jp", "cn") if x != region)
        if not as_text and self.renderer is not None:
            try:
                cache = getattr(self, "imgcache", None)
                img = cache.get("mai_sample", region, head) if cache else None
                if img is None:
                    img = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: self.renderer(b, prof, self.db, int(_t.time())))
                    if cache:
                        cache.put("mai_sample", img, region, head)
                if img:
                    return Reply(image=img).say(head + f"\n其他服：{others}")
            except Exception as e:  # noqa: BLE001
                head += f"（出图失败：{type(e).__name__}，先发文字版）"
        return Reply().say(head + "\n" + T.best50_text(b, prof, self.db, int(_t.time())))

    async def c_refresh(self, ctx, rest):
        region, _ = split_args(rest)
        region = self._region(ctx.uid, region)
        snap = await self._snapshot(ctx.uid, region, force=True)
        b = snap.best50(self.svc.catalog)
        net = snap.profile.rating if snap.profile else 0
        src = self._src_name(ctx.uid, region)
        if region in PRIV_REGIONS:
            msg = (f"已同步 {REGION_NAMES[region]}：B35 + B15 共 {len(snap.scores)} 条，Rating {net}"
                   + (f"（{snap.version}）" if snap.version else ""))
        else:
            msg = (f"已同步 {REGION_NAMES[region]}：{len(snap.scores)} 条成绩，NET Rating {net}，计算值 {b.total}" if not src
                   else f"已同步 {REGION_NAMES[region]}（{src}）：{len(snap.scores)} 条成绩，Rating {net}")
        if getattr(snap, "stale", False):
            msg = "NET 暂时连不上，没能刷新"
        return Reply().say(msg)

    def _src_name(self, uid: str, region: str) -> str:
        if region != "cn":
            return ""
        return "落雪查分器" if self.svc.cn_source(self.svc.store.get_creds(uid, "cn")) in ("lx", "lxqq") else "水鱼查分器"

    async def c_me(self, ctx, rest):
        region, _ = split_args(rest)
        region = self._region(ctx.uid, region)
        if region in API_REGIONS:
            snap = await self._snapshot(ctx.uid, region)
            b = snap.best50(self.svc.catalog)
            p = snap.profile
            where = " · ".join(x for x in (REGION_NAMES[region], self._src_name(ctx.uid, region), snap.version) if x)
            return Reply().say(f"{p.name if p else '-'}（{where}）\n"
                               f"Rating {p.rating if p else b.total}" + (f"　称号 {p.title}" if p and p.title else "")
                               + f"\nB35 {b.old_total} + B15 {b.new_total}　共 {len(snap.scores)} 条成绩")
        p = await asyncio.wait_for(self.svc.profile(ctx.uid, region), NET_TIMEOUT)
        return Reply().say(T.profile_text(p))

    async def c_recent(self, ctx, rest):
        region, rest = split_args(rest)
        region = self._region(ctx.uid, region)
        n = next((int(a) for a in rest if a.isdigit()), 10)
        if region in PRIV_REGIONS:
            plays = await asyncio.wait_for(self.svc.priv_recent(ctx.uid, region), NET_TIMEOUT)
            if not plays:
                return Reply().say(f"{REGION_NAMES[region]} 上还没有最近游玩记录")
            return Reply().say(f"最近游玩（{REGION_NAMES[region]}）\n" + T.recent_text(plays, max(1, min(n, 50))))
        if region == "cn":
            raw = await asyncio.wait_for(self.svc.cn_recent(ctx.uid), NET_TIMEOUT)
            if not raw:
                return Reply().say("落雪上还没有最近游玩记录")
            lines = ["最近游玩（国服 · 落雪查分器）"]
            for i, r in enumerate(raw[:max(1, min(n, 50))], 1):
                li = int(r.get("level_index") or 0)
                diff = DIFF_LABEL.get(("basic", "advanced", "expert", "master", "remaster")[li] if 0 <= li < 5 else "", "")
                typ = "DX" if str(r.get("type")) == "dx" else "SD"
                ach = int(round(float(r.get("achievements") or 0) * 10000))
                when = str(r.get("play_time") or "")[:16].replace("T", " ")
                flags = " ".join(FLAG_TEXT.get(x, x.upper()) for x in (r.get("fc"), r.get("fs")) if x)
                lines.append(f"{i}. {r.get('song_name') or '?'} [{typ} {diff}] {fmt_ach(ach)}"
                             + (f" {flags}" if flags else "") + (f"  {when}" if when else ""))
            return Reply().say("\n".join(lines))
        plays = await asyncio.wait_for(self.svc.recent(ctx.uid, region), NET_TIMEOUT)
        return Reply().say(T.recent_text(plays, max(1, min(n, 50))))

    async def c_detail(self, ctx, rest):
        region, rest = split_args(rest)
        region = self._region(ctx.uid, region)
        n = next((int(a) for a in rest if a.isdigit()), 1)
        plays = await asyncio.wait_for(self.svc.recent(ctx.uid, region), NET_TIMEOUT)
        if not plays or n < 1 or n > len(plays):
            return Reply().say("没有这一条记录")
        p = plays[n - 1]
        d = await asyncio.wait_for(self.svc.playlog(ctx.uid, region, p.idx), NET_TIMEOUT)
        return Reply().say(T.playlog_text(p, d))

    async def c_friend(self, ctx, rest):
        region, rest = split_args(rest)
        code = next((a for a in rest if a.isdigit() and len(a) >= 10), "")
        if not code:
            return Reply().say("用法：/mai 好友码 <好友码>（需要你自己已绑定同区服）")
        region = self._region(ctx.uid, region)
        p = await asyncio.wait_for(self.svc.friend_card(ctx.uid, region, code), NET_TIMEOUT)
        if p is None:
            return Reply().say("没找到这个好友码")
        return Reply().say(T.profile_text(p) + "\n（只凭好友码看不到成绩：需要互加好友并设为最爱）")

    async def c_public(self, ctx, rest):
        on = bool(rest) and rest[0] in ("开", "on", "开启", "是")
        off = bool(rest) and rest[0] in ("关", "off", "关闭", "否")
        if not (on or off):
            return Reply().say(f"现在是{'公开' if self.svc.store.is_public(ctx.uid) else '不公开'}。用法：/mai 公开 开|关")
        self.svc.store.set_public(ctx.uid, on)
        return Reply().say("已允许群友用 /mai b50 @你 查看你的缓存成绩" if on else "已关闭他人查询")

    # ---------- catalog-only ----------
    # ---------- song lookup by title / nickname / ID ----------
    def _lone_song(self, text: str):
        """「/mai 救护车」: a bare name that clearly means one song → treat as 查歌."""
        d = decide(self.db.search_ranked(text, 6), text)
        if d.item is not None and not d.note:
            return d.item
        return None

    def _song_choices(self, q: str, choices, cmd: str = "查歌") -> str:
        lines = [f"「{q}」可能是这几首，用 ID 再查一次："]
        for i, m in enumerate(choices, 1):
            s = m.item
            ids = "/".join(str(x) for x in sorted(s.music_ids())) or "-"
            why = f" ← 外号「{m.name}」" if m.by_alias else ""
            cat = f" · {s.category}" if s.category else ""
            lines.append(f"{i}. {s.title}（ID {ids}{cat}）{why}")
        first = min(choices[0].item.music_ids()) if choices[0].item.music_ids() else choices[0].item.title
        lines.append(f"例：/mai {cmd} {first}")
        return "\n".join(lines)

    def find_song(self, q: str, cmd: str = "查歌"):
        """(song, None, note) or (None, Reply, "")."""
        d = decide(self.db.search_ranked(q, 8), q)
        if d.item is not None:
            return d.item, None, d.note
        if (pk := alias_pick(d.choices)) is not None:      # 一个外号好几首：先出最难的
            song, others = pk
            sid = lambda s: (min(s.music_ids()) if s.music_ids() else s.title)  # noqa: E731
            return song, None, "\n".join([f"外号「{q}」还对应：", *(f"{o.title}（{sid(o)}）" for o in others[:4]),
                                           f"看别的发「/mai {cmd} ID」"])
        if d.choices:
            return None, Reply().say(self._song_choices(q, d.choices, cmd)), ""
        return None, Reply().say(f"没找到「{q}」。可以试试歌名的一部分、常用外号或曲目 ID；"
                                 f"知道是哪首但外号没收录的话，可以发「/mai 加别名 外号 歌名」教我。"), ""

    async def c_song(self, ctx, rest):
        region, rest = split_args(rest)
        region = catalog_region(region) or self._catalog_region()
        q = " ".join(rest)
        if not q:
            return Reply().say("用法：/mai 查歌 <歌名/外号/ID>，例：/mai 查歌 救护车")
        song, err, note = self.find_song(q)
        if err:
            return err
        img = await self._card(lambda: self.cards.song(song, self.db, region),
                               ("mai_song", song.id, region, sorted(song.aliases)))
        if img:
            r = Reply(image=img)
            if note:
                r.say(note if note.startswith("外号") else f"{note}：{song.title}")
            return r
        return Reply().say((f"{note}：\n" if note else "") + T.song_text(song, self.db, region))

    async def c_alias(self, ctx, rest):
        q = " ".join(rest)
        if not q:
            return Reply().say("用法：/mai 别名 <歌名/外号/ID>，看一首歌有哪些外号")
        song, err, _ = self.find_song(q, "别名")
        if err:
            return err
        names = [a for a in song.aliases if a.lower() != song.title.lower()]
        if not names:
            return Reply().say(f"{song.title} 还没有收录外号。可以发「/mai 加别名 外号 {song.title}」加一个")
        shown = "、".join(names[:60]) + (f" …（共 {len(names)} 个）" if len(names) > 60 else "")
        return Reply().say(f"{song.title} 的外号：\n{shown}\n（来源：落雪 / Yuzuchan 别名库 / DXRating / 本机添加）")

    async def c_alias_add(self, ctx, rest):
        if len(rest) < 2:
            return Reply().say("用法：/mai 加别名 <外号> <歌名或 ID>，例：/mai 加别名 救车 SUPER AMBULANCE")
        alias, q = rest[0], " ".join(rest[1:])
        if len(alias) > 20:
            return Reply().say("外号太长了（最多 20 个字）")
        song, err, _ = self.find_song(q, f"加别名 {alias}")
        if err:
            return err
        if self.aliases is None:
            return Reply().say("别名库没有加载，暂时加不了")
        base = min(m % 10000 for m in song.music_ids()) if song.music_ids() else None
        if base is None:
            return Reply().say("这首歌没有曲目 ID，加不了外号")
        self.aliases.add_local(alias, base)
        self.svc.catalog.set_aliases(self.aliases.merged())
        return Reply().say(f"记住了：「{alias}」= {song.title}（只在这个 bot 上生效）")

    async def c_alias_del(self, ctx, rest):
        if not ctx.admin:
            return Reply().say("只有机器人主人能删外号")
        if not rest or self.aliases is None:
            return Reply().say("用法：/mai 删别名 <外号>（只能删本机加的）")
        ok = self.aliases.remove_local(rest[0])
        if ok:
            self.svc.catalog.set_aliases(self.aliases.merged())
        return Reply().say("删掉了" if ok else "这个外号不是本机加的（别名库里的删不了）")

    async def c_score(self, ctx, rest):
        """/mai 成绩 <歌>: your own results on every chart of one song."""
        region, rest = split_args(rest)
        q = " ".join(rest)
        if not q:
            return Reply().say("用法：/mai 成绩 <歌名/外号/ID> [区服]，例：/mai 成绩 潘")
        song, err, note = self.find_song(q, "成绩")
        if err:
            return err
        region = self._region(ctx.uid, region)
        snap = await self._snapshot(ctx.uid, region)
        scores = attach_charts(list(snap.scores), self.db, catalog_region(region), keep_ds=(region in API_REGIONS))
        mine = [s for s in scores if s.song_id == song.id or (s.song_id is None and s.title == song.title)]
        head = f"{song.title}（{REGION_NAMES[region]}）" + (f"\n{note}" if note else "")
        if not mine:
            tip = ("\n（水鱼只给 B50 里的成绩；绑定落雪能查全部成绩）"
                   if self._src_name(ctx.uid, region) == "水鱼查分器" else
                   f"\n（{REGION_NAMES[region]} 只公开 B50 里的成绩）" if region in PRIV_REGIONS else "")
            return Reply().say(f"{head}\n还没有这首的成绩" + tip)
        order = {d: i for i, d in enumerate(("basic", "advanced", "expert", "master", "remaster", "utage"))}
        lines = [head]
        for s in sorted(mine, key=lambda s: (s.type != "dx", order.get(s.diff, 9))):
            ds = s.ds
            ra = chart_rating(ds, s.ach, s.fc) if ds else 0
            flags = " ".join(FLAG_TEXT.get(x, x.upper()) for x in (s.fc, s.fs) if x)
            typ = "DX" if s.type == "dx" else "标准" if s.type == "std" else "宴"
            lines.append(f"· {typ} {DIFF_LABEL.get(s.diff, s.diff)} {ds or s.level}：{fmt_ach(s.ach)}"
                         + (f" {flags}" if flags else "") + (f" → {ra}" if ra else ""))
        return Reply().say("\n".join(lines))

    async def _card(self, fn, key: tuple | None = None):
        if self.cards is None:
            return None
        cache = getattr(self, "imgcache", None)
        if key is not None and cache is not None and (hit := cache.get(*key)) is not None:
            return hit
        try:
            img = await asyncio.get_running_loop().run_in_executor(None, fn)
            if key is not None and cache is not None:
                cache.put(key[0], img, *key[1:])
            return img
        except Exception as e:  # pragma: no cover - fall back to text
            import logging
            logging.getLogger("astrbot").warning(f"[mai] card render failed: {type(e).__name__}: {e}")
            return None

    async def c_ds(self, ctx, rest):
        region, rest = split_args(rest)
        region = catalog_region(region) or self._catalog_region()
        nums = [float(a) for a in rest if re.fullmatch(r"\d+(\.\d)?", a)]
        if not nums:
            return Reply().say("用法：/mai 定数 14.0 或 /mai 定数 13.7 14.0")
        lo, hi = (nums[0], nums[0]) if len(nums) == 1 else (min(nums[:2]), max(nums[:2]))
        charts = self.db.charts_by_ds(lo, hi, region)
        if not charts:
            return Reply().say("这个范围没有谱面")
        rv = self.db.current_version.get(region)
        rng = f"{lo}" if lo == hi else f"{lo}–{hi}"
        sub = f"{REGION_NAMES[region]} {rv} · 定数 {rng} · 共 {len(charts)} 张"
        if len(charts) <= 40:
            img = await self._card(lambda: self.cards.ds_list(charts, self.db, region, "定数查歌", sub),
                                   ("mai_ds", lo, hi, region, sub))
        else:
            img = await self._card(lambda: self.cards.ds_table(charts, self.db, region, f"定数 {rng}", sub),
                                   ("mai_ds", lo, hi, region, sub))
        if img:
            return Reply(image=img)
        lines = [f"{c.ds_in(region, rv):.1f} {c.song.title} [{'DX' if c.type == 'dx' else 'SD'} "
                 f"{DIFF_LABEL[c.diff]}]" for c in charts[:60]]
        more = f"\n…共 {len(charts)} 张，只列前 60" if len(charts) > 60 else ""
        return Reply().say(f"{REGION_NAMES[region]} 定数 {lo}–{hi}：\n" + "\n".join(lines) + more)

    async def c_dstable(self, ctx, rest):
        region, rest = split_args(rest)
        region = catalog_region(region) or self._catalog_region()
        arg = " ".join(rest).replace("～", "-").replace("~", "-").replace("–", "-")
        m1 = re.fullmatch(r"\s*(\d{1,2})(\+?)\s*", arg)
        m2 = re.fullmatch(r"\s*(\d{1,2}(?:\.\d)?)\s*[- ]\s*(\d{1,2}(?:\.\d)?)\s*", arg)
        if m1:
            n = int(m1.group(1))
            lo, hi = (n + 0.6, n + 0.9) if m1.group(2) else (float(n), n + 0.5)
            name = f"Level {n}{m1.group(2)}"
        elif m2:
            a, b = float(m2.group(1)), float(m2.group(2))
            lo, hi = min(a, b), max(a, b)
            if hi == int(hi) and "." not in m2.group(2):
                hi += 0.9 if hi != lo else 0
            name = f"定数 {lo:g}–{hi:g}"
        else:
            return Reply().say("用法：/mai 定数表 14+　/mai 定数表 14　/mai 定数表 14.0-14.5")
        if hi - lo > 2.0:
            return Reply().say("范围太大了，一次最多 2.0（比如 13-14 或 14+）")
        charts = self.db.charts_by_ds(lo, hi, region)
        if not charts:
            return Reply().say("这个范围没有谱面")
        rv = self.db.current_version.get(region)
        sub = f"{REGION_NAMES[region]} {rv} · {lo:.1f}–{hi:.1f} · 共 {len(charts)} 张"
        img = await self._card(lambda: self.cards.ds_table(charts, self.db, region, f"{name} 定数表", sub),
                               ("mai_dstable", name, region, sub))
        if img:
            return Reply(image=img)
        return await self.c_ds(ctx, [region, f"{lo:.1f}", f"{hi:.1f}"])

    async def c_random(self, ctx, rest):
        region, rest = split_args(rest)
        region = catalog_region(region) or self._catalog_region()
        type_ = diff = level = None
        for a in rest:
            al = a.lower()
            if al in ("dx",):
                type_ = "dx"
            elif al in ("sd", "std", "标准"):
                type_ = "std"
            elif al in DIFF_ALIASES:
                diff = DIFF_ALIASES[al]
            elif re.fullmatch(r"\d{1,2}\+?", a):
                level = a
        c = self.db.random_chart(region, type_=type_, diff=diff, level=level)
        if c is None:
            return Reply().say("没有符合条件的谱面")
        rv = self.db.current_version.get(region)
        return Reply().say(f"{c.song.title} [{'DX' if c.type == 'dx' else 'SD'} {DIFF_LABEL[c.diff]} "
                           f"{c.level_in(region)} / {c.ds_in(region, rv)}]")

    async def c_line(self, ctx, rest):
        nums = [a for a in rest if re.fullmatch(r"\d+(\.\d)?", a)]
        if not nums:
            return Reply().say("用法：/mai 分数线 14.2  或  /mai 分数线 14.2 300（达到 300 分要多少）")
        ds = float(nums[0])
        if len(nums) >= 2:
            target = int(float(nums[1]))
            a = min_ach_for_rating(ds, target)
            if a is None:
                return Reply().say(f"定数 {ds} 最高只有 {chart_rating(ds, 1005000)}（AP 再 +1）")
            return Reply().say(f"定数 {ds} 拿 {target} 分需要 {fmt_ach(a)}")
        return Reply().say(f"定数 {ds}：\n" + T.line_text(ds))

    async def c_catalog(self, ctx, rest):
        st = self.db.stats()
        cat = self.svc.catalog
        return Reply().say(
            f"曲库：{st['songs']} 首 / {st['charts']} 张谱面（来源 {cat.source}，{st['updated_at'][:10]}）\n"
            f"国际服当前版本 {st['current_version']['intl']}，新曲 = {'/'.join(st['new_versions']['intl'])}\n"
            f"日服当前版本 {st['current_version']['jp']}，新曲 = {'/'.join(st['new_versions']['jp'])}\n"
            "Data from DXRating (dxrating.net)" + (f"\n上次刷新失败：{cat.last_error[:200]}" if cat.last_error else ""))
