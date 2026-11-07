"""/chu (/chuni /中二) commands on top of ChuniService — same Reply / Ctx model as /mai.

Servers: 国际服 (CHUNITHM-NET, clal), 日服 (CHUNITHM-NET JP, SEGA ID + 密码) and 国服 (水鱼 / 落雪). Constants for 查歌 / 定数 / 定数表 can be shown
for 国际服 / 日服 / 国服.
"""
from __future__ import annotations

import asyncio
import contextvars
import re
import time
from pathlib import Path

try:
    from ..mai.bot.commands import Ctx, Reply
    from ..mai.bot.guard import looks_like_clal
    from ..mai.data.fuzzy import COMMON_SLIPS, alias_pick, decide, split_glued, suggest
    from ..mai.calc.sample import THEORY_WORDS, is_sample
except ImportError:  # tests
    from mai.bot.commands import Ctx, Reply
    from mai.bot.guard import looks_like_clal
    from mai.data.fuzzy import COMMON_SLIPS, alias_pick, decide, split_glued, suggest
    from mai.calc.sample import THEORY_WORDS, is_sample

from .client import ChuniError

try:
    from ..core import cnupdate as CU
    from ..core.privsrv import PrivError, SERVERS as PRIV_SERVERS
    from ..core.privsrv import servers as _priv
    from ..core.privsrv.bind import bind as priv_bind
except ImportError:  # tests
    from core import cnupdate as CU
    from core.privsrv import PrivError, SERVERS as PRIV_SERVERS
    from core.privsrv import servers as _priv
    from core.privsrv.bind import bind as priv_bind
from .render import b50_text, profile_text, recent_text, song_text
from .service import ChuniService

# 私服（MuNET …）：成绩来自私服网站，曲库 / 定数表借日服的
PRIV_SERVERS_CHU = tuple(k for k in _priv.KEYS if _priv.supports(k, "chu"))
SERVER_NAMES = {"intl": "国际服", "jp": "日服", "cn": "国服", **{k: _priv.NAMES[k] for k in PRIV_SERVERS_CHU}}
SERVER_ALIASES = {
    "intl": "intl", "国际服": "intl", "国际": "intl", "int": "intl",
    "jp": "jp", "日服": "jp", "日本": "jp",
    "cn": "cn", "国服": "cn", "中国": "cn", "水鱼": "cn", "落雪": "cn", "lxns": "cn", "luoxue": "cn",
    **{a: k for a, k in _priv.ALIASES.items() if k in PRIV_SERVERS_CHU},
}
LX_WORDS = ("落雪", "lxns", "luoxue", "落雪查分器")
LX_HOWTO = ("绑定落雪：登录 maimai.lxns.net →「账号详情」→「个人 API 密钥」生成一个，"
            "然后私聊我发「/chu 绑定 落雪 <密钥>」。绑好后发 /chu b50 就是国服的 B30 + 新曲 N20")
BIND_SERVERS = ("intl", "jp", "cn", *PRIV_SERVERS_CHU)


def catalog_server(server: str | None) -> str | None:
    """查曲库 / 定数 / 理论值用哪个服：私服借日服。"""
    return "jp" if server in PRIV_SERVERS_CHU else server
_HINT: contextvars.ContextVar[str] = contextvars.ContextVar("chu_hint", default="")

BIND_HELP = """绑定中二节奏账号
最省事：发「/网页绑定」（群里私聊都行），拿链接用手机网页填（也能在电脑上打开）。下面是指令绑法：
【国际服】只能私聊我，两种任选：
· SEGA ID + 密码（手机方便，clal 过期会自动续登）：/chu 绑定 国际服 <SEGA ID> <密码>（发完我会撤回）
· clal：电脑浏览器打开 chunithm-net-eng.com/mobile/ 用 SEGA ID 登录（勾选保持登录）→ F12 → Application →
  Cookies → lng-tgk-aime-gw.am-all.net → 复制 clal（64 位），私聊发：/chu 绑定 <clal>
⚠ 这些都相当于登录凭据，会加密保存在机器人主人的电脑上。千万别发在群里！
【日服】SEGA ID + 密码，推荐网页绑定；也可以私聊一行发：/chu 绑定 日服 <SEGA ID> <密码>
【私服 MuNET】只要网站用户名（portal.mumur.net/u/<用户名>），群里也能绑：/chu 绑定 munet <用户名>
【私服 AquaDX】网站用户名（aquadx.net/u/<用户名>），群里也能绑：/chu 绑定 aqua <用户名>
【私服 RinNET】只能私聊：/chu 绑定 rin <账号或邮箱> <密码>（开了两步验证在最后加 6 位验证码；
  第三方登录没密码的发 /chu 绑定 rin token <refreshToken>）。只加密保存登录令牌，不存密码，发完撤回。
  私服都是舞萌中二共用一个绑定，绑一次两边都能查。
【国服】两种查分器任选：
· 落雪（推荐，能查全部成绩，B30 + 新曲 N20）：登录 maimai.lxns.net →「账号详情」→「个人 API 密钥」，
  私聊我发：/chu 绑定 落雪 <密钥>（密钥也是凭据，别发群里）
· 水鱼（不用密钥，群里也能绑，只有 B30 / R10）：/chu 绑定 国服 <水鱼用户名>（不填就用你的 QQ 去水鱼查）
不想用了发「/chu 解绑」。"""


def split_server(args: list[str]) -> tuple[str | None, list[str]]:
    server, rest = None, []
    for a in args:
        s = SERVER_ALIASES.get(a.lower())
        if s and server is None:
            server = s
        else:
            rest.append(a)
    return server, rest


def _parse_range(arg: str) -> tuple[float, float, str] | None:
    arg = arg.replace("～", "-").replace("~", "-").replace("–", "-").strip()
    m1 = re.fullmatch(r"(\d{1,2})(\+?)", arg)
    m2 = re.fullmatch(r"(\d{1,2}(?:\.\d)?)\s*[- ]\s*(\d{1,2}(?:\.\d)?)", arg)
    m3 = re.fullmatch(r"\d{1,2}\.\d", arg)
    if m3:
        v = float(arg)
        return v, v, f"定数 {v:.1f}"
    if m1:
        n = int(m1.group(1))
        lo, hi = (n + 0.5, n + 0.9) if m1.group(2) else (float(n), n + 0.4)
        return lo, hi, f"Level {n}{m1.group(2)}"
    if m2:
        a, b = float(m2.group(1)), float(m2.group(2))
        lo, hi = min(a, b), max(a, b)
        if "." not in m2.group(2) and hi != lo:
            hi += 0.9
        return lo, hi, f"定数 {lo:g}–{hi:g}"
    return None


def pick_regular(choices):
    """「Aleph-0」= 普通谱和 WORLD'S END 同名：歌名完全一样、只有一首不是 WE 时就是它 → (普通, WE)。"""
    exact = [m for m in (choices or []) if m.score >= 100]
    if len(exact) < 2 or len({m.item.title for m in exact}) != 1:
        return None
    is_we = lambda it: "WORLD" in (getattr(it, "genre", "") or "").upper()  # noqa: E731
    regular = [m.item for m in exact if not is_we(m.item)]
    we = [m.item for m in exact if is_we(m.item)]
    return (regular[0], we[0]) if len(regular) == 1 and we else None


class ChuCommands:
    GAME = "chu"

    def __init__(self, svc: ChuniService, data_dir: Path, *, prefs=None, cards=None, renderer=None,
                 tz: str = "Asia/Shanghai", cooldown: float = 15):
        self.svc = svc
        self.data_dir = Path(data_dir)
        self.prefs = prefs
        self.cards = cards          # chuni.cards.ChuCards or None (text only)
        self.renderer = renderer    # callable(name, b50, out, jackets, server=...) or None
        self.tz = tz
        self.cooldown = cooldown
        self._last_b50: dict[str, float] = {}
        self._img_memo: dict[str, tuple[object, str, bytes]] = {}   # uid → (成绩对象, 区服, 图)：成绩没变就不重画
        self.aliases = None         # mai.data.aliases.AliasStore("chu") for 加别名 / 删别名
        self.imgcache = None        # core.imgcache.ImageCache (cards / tables that don't depend on the user)

    async def _cached_img(self, key: tuple, make):
        """make: async () → bytes (fetches jackets, renders). Cached on disk by key, so a hit skips both."""
        c = self.imgcache
        if c is not None and (hit := c.get(*key)) is not None:
            return hit
        img = await make()
        if c is not None:
            c.put(key[0], img, *key[1:])
        return img

    # ---------- entry ----------
    async def handle(self, ctx: Ctx, argline: str) -> Reply:
        args = argline.split()
        sub = (args[0].lower() if args else "帮助")
        rest = args[1:]
        table = {
            "帮助": self.c_help, "help": self.c_help,
            "绑定": self.c_bind, "bind": self.c_bind, "登录": self.c_bind,
            "绑定教程": self.c_bindhelp, "bindhelp": self.c_bindhelp,
            "解绑": self.c_unbind, "unbind": self.c_unbind,
            "切换": self.c_switch,
            "我": self.c_me, "资料": self.c_me, "me": self.c_me, "profile": self.c_me,
            "最近": self.c_recent, "recent": self.c_recent,
            "b50": self.c_b50, "b30": self.c_b50, "best": self.c_b50,
            **{w: self.c_theory for w in THEORY_WORDS},
            "查": self.c_song, "查歌": self.c_song, "song": self.c_song, "info": self.c_song, "id": self.c_song,
            "定数": self.c_ds, "定数查歌": self.c_ds,
            "定数表": self.c_dstable,
            "刷新": self.c_refresh, "refresh": self.c_refresh,
            "别名": self.c_alias, "外号": self.c_alias, "alias": self.c_alias,
            "加别名": self.c_alias_add, "添加别名": self.c_alias_add,
            "删别名": self.c_alias_del, "删除别名": self.c_alias_del,
            "成绩": self.c_score, "单曲": self.c_score, "分数": self.c_score,
        }
        fn = table.get(sub)
        if fn is None and table.get(COMMON_SLIPS.get(sub, "")):      # 查曲 / 查谱 / b40 / 外号 … mean the same
            fn = table[COMMON_SLIPS[sub]]
        if fn is None and args and (sp := split_glued(args[0], table)):
            sub, glued = sp                        # 「/chu 查Aleph-0」「/chu b30文字」
            fn, rest = table[sub], [glued, *rest]
        if fn is None:
            if args and _parse_range(args[0]):     # /chu 15.0 → 定数查歌
                fn, rest = self.c_ds, args
            elif args and (song := await self._lone_song(argline)) is not None:
                fn, rest = self.c_song, [str(song.id)]   # /chu Aleph-0 → 查歌
            else:
                sug = suggest(sub, table)
                tip = f"，是不是想发「/chu {sug[0]}{(' ' + ' '.join(rest)) if rest else ''}」？" if sug else "。"
                return Reply().say(f"没有「{sub}」这个指令{tip}\n中二的指令发「/chu 帮助」看～")
        _HINT.set("")
        try:
            r = await fn(ctx, rest)
        except (ChuniError, PrivError) as e:
            return Reply().say(str(e))
        except Exception as e:  # noqa: BLE001
            return Reply().say(f"出错了：{type(e).__name__}: {e}")
        if _HINT.get() and (r.texts or r.image):
            r.say(_HINT.get())
        return r

    # ---------- servers ----------
    def bound(self, uid: str) -> list[str]:
        out = []
        if uid in self.svc.store:
            out.append("intl")
        if uid in self.svc.jp:
            out.append("jp")
        if uid in self.svc.cn:
            out.append("cn")
        out += [x for x in self.svc.priv_bound(uid) if x not in out]
        return out

    def _server(self, uid: str, server: str | None, remember: bool = True) -> str:
        bound = self.bound(uid)
        if server:
            if server not in BIND_SERVERS:
                raise ChuniError(f"中二{SERVER_NAMES.get(server, server)}还查不了成绩（目前支持国际服、日服、国服、MuNET、RinNET、AquaDX）")
            if remember and self.prefs and server in bound:
                self.prefs.set_last(uid, self.GAME, server)
            return server
        last = self.prefs.last(uid, self.GAME) if self.prefs else ""
        s = last if last in bound else (bound[0] if bound else "")
        if not s and self.svc.lx_dev and str(uid).isdigit():
            s = "cn"            # 什么都没绑：先按 QQ 去落雪找（b50_cn 里自动绑）
        if not s:
            raise ChuniError("你还没有绑定中二账号～发「/网页绑定」用网页绑最省事，或者发「/chu 绑定教程」看指令绑法")
        others = [x for x in bound if x != s]
        if others and remember:
            _HINT.set(f"（查的是{SERVER_NAMES[s]}。要查{SERVER_NAMES[others[0]]}就在指令后加区服，"
                      f"比如「/chu b50 {SERVER_NAMES[others[0]]}」，之后会默认用你最后查的那个服）")
        return s

    def _catalog_server(self, server: str | None) -> str:
        return catalog_server(server) or (self.prefs.catalog_server("chu") if self.prefs else "intl")

    # ---------- help / bind ----------
    async def c_help(self, ctx, rest):
        return Reply().say("发「/查分 帮助」看图片版帮助。\n/chu b50 [文字] [区服]　/chu 我　/chu 最近\n"
                           "/chu 查 <歌名>　/chu 定数 15.0 [15.4]　/chu 定数表 15+\n"
                           "/chu 谱面 <歌名> [紫|红|黑|we]（sdvx.in 谱面图）\n/chu 绑定教程　/chu 解绑\n"
                           "/chu 绑定 munet|aqua <网站用户名>　/chu 绑定 rin（私服，舞萌中二共用）")

    async def c_bindhelp(self, ctx, rest):
        return Reply().say(BIND_HELP)

    async def c_bind(self, ctx: Ctx, rest):
        if any(a.lower() in LX_WORDS for a in rest):
            return await self._bind_lx(ctx, rest)
        server, rest = split_server(rest)
        if server in PRIV_SERVERS_CHU:
            return await self._bind_priv(ctx, server, rest)
        if server == "cn":
            name = " ".join(rest).strip()
            binding = {"username": name} if name else {"qq": ctx.uid}
            try:
                prof = await asyncio.wait_for(self.svc.bind_cn(ctx.uid, binding), 30)
            except Exception as e:  # noqa: BLE001
                return Reply().say(f"绑定国服失败：{e}\n用法：/chu 绑定 国服 <水鱼用户名>")
            if self.prefs:
                self.prefs.set_last(ctx.uid, self.GAME, "cn")
            tail = "\n你还绑了国际服；现在默认查国服，查国际服在指令后加「国际服」" if ctx.uid in self.svc.store else ""
            return Reply().say(f"国服绑定成功（水鱼查分器）：{prof.name}，Rating {prof.rating:.2f}" + tail)
        if server == "jp":
            return await self._bind_sega(ctx, rest, "jp")
        clal = next((a for a in rest if looks_like_clal(a)), "")
        if not clal and len(rest) >= 2:          # /chu 绑定 国际服 <SEGA ID> <密码>
            return await self._bind_sega(ctx, rest, "intl")
        if not ctx.private:
            r = Reply().say(("刚才那条带了 clal，我试着撤回了；建议去 CHUNITHM-NET 退出登录一次让它失效。\n" if clal else "")
                            + "国际服要填 clal 或 SEGA ID + 密码，别在群里发：发「/网页绑定」拿链接在网页上填"
                              "（国服水鱼可以直接「/chu 绑定 国服 <水鱼用户名>」）")
            r.recall = bool(clal)
            return r
        if not clal:
            return Reply().say(BIND_HELP)
        prof = await self.svc.bind(ctx.uid, clal)
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, "intl")
        tail = "\n你还绑了国服；现在默认查国际服，查国服在指令后加「国服」" if ctx.uid in self.svc.cn else ""
        r = Reply(recall=True).say(f"绑定成功：{prof.name}（Rating {prof.rating:.2f}）\n发「/chu b50」看看" + tail)
        return r

    async def _bind_priv(self, ctx: Ctx, server: str, rest) -> Reply:
        """私服绑定（逻辑在 core/privsrv/bind.py，两个游戏共用）；舞萌中二共用一份绑定。"""
        try:
            from ..mai.bot.guard import REDACTOR
        except ImportError:
            from mai.bot.guard import REDACTOR
        if self.svc.priv is None:
            return Reply().say("私服查分没有启用")
        out = await priv_bind(self.svc.priv, ctx.uid, server, list(rest), game="chu", private=ctx.private,
                              redactor=REDACTOR)
        if not out.ok:
            return Reply(recall=out.recall).say(out.text)
        self.svc.clear_cache(ctx.uid)
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, server)
        name = SERVER_NAMES[server]
        p = out.profile
        head = (f"{name} 绑定成功：{p.name}（{out.account}），中二 Rating {p.rating / 100:.2f}" if p else
                f"{name} 绑定成功（{out.account}），不过这个号在 {name} 上还没有中二记录")
        if PRIV_SERVERS[server].auth == "login":
            head += f"\n只加密保存了登录令牌，没存密码；随时「/chu 解绑 {server}」"
        others = [SERVER_NAMES[x] for x in self.bound(ctx.uid) if x != server]
        return Reply(recall=out.recall).say(
            head + (f"（{out.text}）" if out.text else "") + f"\n舞萌也能直接查（/mai b50 {server}）。"
            + (f"你还绑了{'、'.join(others)}；现在默认查 {name}，查别的服在指令后加区服" if others else "发「/chu b50」看看"))

    async def _bind_lx(self, ctx: Ctx, rest) -> Reply:
        try:
            from ..core.lxns import find_token
        except ImportError:
            from core.lxns import find_token
        token = find_token(rest)
        if not token and not self.svc.lx_dev and getattr(self.svc.lx_oauth, "configured", False):
            return Reply().say("绑定落雪不用复制密钥了：发「/网页绑定」，选 国服 →「落雪授权」，在落雪页面点一下授权就好（舞萌中二一起绑）。")
        if not token and self.svc.lx_dev:      # 不用密钥：按 QQ 找
            src = (self.svc.cn.get(ctx.uid) or {}).get("source")
            if src in ("lx", "lxoauth"):       # 已经能查全部成绩：别被「按 QQ」降级
                how = "个人密钥" if src == "lx" else "落雪授权"
                return Reply().say(f"你已经用{how}绑了落雪，能查全部成绩，不用再按 QQ 绑。要换方式先「/chu 解绑 国服」")
            try:
                prof = await asyncio.wait_for(self.svc.bind_cn_qq(ctx.uid), 30)
            except Exception as e:  # noqa: BLE001
                return Reply().say(f"按 QQ 在落雪没找到你：{e}\n确认已在 maimai.lxns.net 绑定这个 QQ、同步过成绩，"
                                   "并在隐私设置里允许第三方查询。也可以私聊「/chu 绑定 落雪 <个人API密钥>」")
            if self.prefs:
                self.prefs.set_last(ctx.uid, self.GAME, "cn")
            return Reply().say(f"国服绑定成功（落雪 · 按 QQ）：{prof.name}，Rating {prof.rating:.2f}\n"
                               "发「/chu b50」看看。按 QQ 只能拿到 B30 / N20；要查单曲等全部成绩，"
                               "发「/网页绑定」选「落雪授权」（或私聊绑个人密钥）")
        if not ctx.private:
            r = Reply().say(("刚才那条带了密钥，我试着撤回了；保险起见去落雪网站重新生成一个。\n" if token else "")
                            + "落雪密钥别在群里发：发「/网页绑定」拿链接在网页上填。水鱼不用密钥，群里也能绑：/chu 绑定 国服 <水鱼用户名>")
            r.recall = bool(token)
            return r
        if not token:
            return Reply().say(LX_HOWTO)
        try:
            prof = await asyncio.wait_for(self.svc.bind_cn_lx(ctx.uid, token), 30)
        except Exception as e:  # noqa: BLE001
            r = Reply().say(f"绑定落雪失败：{e}\n{LX_HOWTO}")
            r.recall = True
            return r
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, "cn")
        tail = "\n你还绑了国际服；现在默认查国服，查国际服在指令后加「国际服」" if ctx.uid in self.svc.store else ""
        return Reply(recall=True).say(f"国服绑定成功（落雪查分器）：{prof.name}，Rating {prof.rating:.2f}\n"
                                      "发「/chu b50」看看；密钥已加密保存，随时「/chu 解绑 国服」。\n"
                                      "同一个密钥也能绑舞萌国服：私聊发「/mai 绑定 落雪 <密钥>」" + tail)

    async def _bind_sega(self, ctx: Ctx, rest, server: str) -> Reply:
        """国际服 / 日服：SEGA ID + 密码。推荐网页绑定；私聊也可以一行发完（发完撤回）。"""
        try:
            from ..mai.bot.guard import REDACTOR
        except ImportError:
            from mai.bot.guard import REDACTOR
        sname = SERVER_NAMES[server]
        if not ctx.private:
            r = Reply().say(("刚才那条带了密码，我试着撤回了；保险起见去改一下 SEGA ID 的密码。\n" if len(rest) >= 2 else "")
                            + f"{sname}的 SEGA ID 和密码别在群里发：发「/网页绑定」拿链接在网页上填")
            r.recall = len(rest) >= 2
            return r
        if len(rest) < 2:
            return Reply().say(f"中二{sname}用 SEGA ID + 密码绑定。最省事：发「/网页绑定」拿链接在网页上填。\n"
                               f"也可以私聊一行发完：/chu 绑定 {sname} <SEGA ID> <密码>（发完我会撤回）")
        sega_id, password = rest[0], " ".join(rest[1:])
        REDACTOR.remember(password)
        bind = self.svc.bind_jp if server == "jp" else self.svc.bind_intl_sega
        try:
            prof = await asyncio.wait_for(bind(ctx.uid, sega_id, password), 60)
        except asyncio.TimeoutError:
            return Reply(recall=True).say(f"{sname} CHUNITHM-NET 太慢了，过一会儿再试")
        except ChuniError as e:
            return Reply(recall=True).say(f"绑定{sname}失败：{e}")
        finally:
            REDACTOR.forget(password)
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, server)
        others = [SERVER_NAMES[x] for x in self.bound(ctx.uid) if x != server]
        tail = (f"\n你还绑了{'、'.join(others)}；现在默认查{sname}，查别的服在指令后加区服" if others else "")
        b50 = "/chu b50" + (" 日服" if server == "jp" else "")
        unb = "/chu 解绑" + (" 日服" if server == "jp" else "")
        return Reply(recall=True).say(f"{sname}绑定成功：{prof.name}（Rating {prof.rating:.2f}）\n"
                                      f"发「{b50}」看看；密码已加密保存，随时「{unb}」" + tail)

    async def _bind_jp(self, ctx: Ctx, rest) -> Reply:       # 网页绑定还在用这个名字
        return await self._bind_sega(ctx, rest, "jp")

    async def _bind_intl_sega(self, ctx: Ctx, rest) -> Reply:
        return await self._bind_sega(ctx, rest, "intl")

    async def c_unbind(self, ctx, rest):
        server, _ = split_server(rest)
        if server in PRIV_SERVERS_CHU:
            gone = self.svc.priv.bindings.remove(ctx.uid, server) if self.svc.priv else []
            self.svc.clear_cache(ctx.uid)
            return Reply().say(f"已解绑 {SERVER_NAMES[server]}（舞萌、中二、音击共用这一个绑定，三个游戏一起解了）" if gone
                               else f"你没绑定 {SERVER_NAMES[server]}")
        done = []
        if server in (None, "intl") and await self.svc.unbind(ctx.uid):
            done.append("国际服")
        if server in (None, "jp") and await self.svc.unbind_jp(ctx.uid):
            done.append("日服")
        if server in (None, "cn") and self.svc.cn.remove(ctx.uid):
            done.append("国服")
        priv = self.svc.priv_bound(ctx.uid) if server is None else []
        keep = (f"\n{'、'.join(SERVER_NAMES[x] for x in priv)} 是舞萌中二共用的绑定，没动；"
                f"要解绑发「/chu 解绑 {priv[0]}」" if priv else "")
        return Reply().say((f"已解绑：{'、'.join(done)}（凭据和缓存都删了）" if done else "没有可解绑的记录") + keep)

    async def c_switch(self, ctx, rest):
        server, _ = split_server(rest)
        if server not in self.bound(ctx.uid):
            return Reply().say("用法：/chu 切换 国际服|日服|国服|munet|rin|aqua（要先绑定那个服）")
        if self.prefs:
            self.prefs.set_last(ctx.uid, self.GAME, server)
        return Reply().say(f"之后默认查{SERVER_NAMES[server]}")

    # ---------- scores ----------
    async def c_me(self, ctx, rest):
        server, _ = split_server(rest)
        s = self._server(ctx.uid, server)
        if s in PRIV_SERVERS_CHU:
            prof, b = await self.svc.b50_priv(ctx.uid, s)
            where = " · ".join(x for x in (SERVER_NAMES[s], b.version) if x)
            return Reply().say(f"{prof.name}（{where}）\nRating {prof.rating:.2f}"
                               + (f"　累计游玩 {prof.play_count}" if prof.play_count else "")
                               + f"\n旧曲 B30 平均 {b.best_avg} / 新曲 N20 平均 {b.new_avg}")
        if s == "cn":
            prof, b = await self.svc.b50_cn(ctx.uid)
            if self.svc.cn_source(ctx.uid) in ("lx", "lxqq"):
                return Reply().say(f"{prof.name}（国服 · 落雪查分器）\nRating {prof.rating:.2f}　Lv.{prof.level}\n"
                                   f"B30 平均 {b.best_avg} / 新曲 N20 平均 {b.new_avg}")
            r10 = b._avg(b._sum(b.new), 10)
            return Reply().say(f"{prof.name}（国服 · 水鱼查分器）\nRating {prof.rating:.2f}\n"
                               f"B30 平均 {b.best_avg} / R10 平均 {r10}")
        p = await self.svc.profile(ctx.uid, server=s)
        txt = profile_text(p, self.tz)
        return Reply().say(txt.replace("\n", "（日服）\n", 1) if s == "jp" else txt)

    async def c_recent(self, ctx, rest):
        server, _ = split_server(rest)
        s = self._server(ctx.uid, server)
        if s in PRIV_SERVERS_CHU:
            plays = await asyncio.wait_for(self.svc.recent_priv(ctx.uid, s), 60)
            return Reply().say(f"（{SERVER_NAMES[s]}）\n" + recent_text(plays, self.tz, 10))
        if s == "cn":
            if not self.svc.cn.get(ctx.uid):
                return Reply().say("你还没绑定中二国服：发「/网页绑定」，或者先发「/chu b50」试试按 QQ 自动找")
            if self.svc.cn_source(ctx.uid) == "lxqq":
                return Reply().say("按 QQ 查落雪拿不到最近游玩；发「/网页绑定」选「落雪授权」（或私聊绑个人密钥）就能看")
            if self.svc.cn_source(ctx.uid) != "lx":
                return Reply().say("水鱼查分器只有 B30 / R10，没有最近游玩；绑定落雪可以试试（发「/网页绑定」）")
            raw = await asyncio.wait_for(self.svc.cn_recent_lx(ctx.uid), 30)
            if not raw:
                return Reply().say("落雪上还没有最近游玩记录")
            names = ("BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA", "WORLD'S END")
            lines = ["最近游玩（国服 · 落雪查分器）"]
            for i, r in enumerate(raw[:10], 1):
                li = int(r.get("level_index") or 0)
                when = str(r.get("play_time") or "")[:16].replace("T", " ")
                lamp = str(r.get("full_combo") or "").replace("alljusticecritical", "AJC").replace(
                    "alljustice", "AJ").replace("fullcombo", "FC")
                lines.append(f"{i}. {r.get('song_name') or '?'} [{names[li] if 0 <= li < 6 else '?'}] "
                             f"{int(r.get('score') or 0):,}" + (f" {lamp}" if lamp else "") + (f"  {when}" if when else ""))
            return Reply().say("\n".join(lines))
        txt = recent_text(await self.svc.recent(ctx.uid, server=s), self.tz, 10)
        return Reply().say(("（日服）\n" + txt) if s == "jp" else txt)

    async def c_b50(self, ctx: Ctx, rest):
        server, rest = split_server(rest)
        as_text = any(a in ("文字", "text", "txt") for a in rest)
        if is_sample(rest):
            return await self._b50_sample(catalog_server(server) or "intl", as_text)
        s = self._server(ctx.uid, server)
        wait = self.cooldown - (time.time() - self._last_b50.get(ctx.uid, 0))
        if wait > 0:
            return Reply().say(f"查得太快啦，{wait:.0f} 秒后再试")
        self._last_b50[ctx.uid] = time.time()
        rs = s
        if s in PRIV_SERVERS_CHU:
            prof, b = await self.svc.b50_priv(ctx.uid, s)
        elif s == "cn":
            prof, b = await self.svc.b50_cn(ctx.uid)
            rs = "cn_lx" if self.svc.cn_source(ctx.uid) in ("lx", "lxqq") else "cn"
        else:
            prof, b = await self.svc.b50(ctx.uid, server=s)
        src = SERVER_NAMES[s] if s in PRIV_SERVERS_CHU else "CHUNITHM-NET"
        note = ""
        if s == "cn":                   # 国服是查分器里存的那份：说明来源、上传时间、怎么更新
            note = CU.b50_note("chu", "lx" if rs == "cn_lx" else "df", getattr(prof, "uploaded_at", ""), self.tz)
        if as_text or self.renderer is None:
            return Reply().say(b50_text(prof.name, b, src) + ("\n" + note if note else ""))
        memo = self._img_memo.get(ctx.uid)
        if memo is not None and memo[0] is b and memo[1] == rs:
            return Reply(image=memo[2]).say(note) if note else Reply(image=memo[2])   # 同一份缓存成绩：直接发上次画好的图
        try:
            jackets = await self.svc.jackets_for(b.best + b.new)
            out = self.data_dir / "render" / f"b50_{ctx.uid}_{int(time.time())}.jpg"
            await asyncio.to_thread(self.renderer, prof.name, b, out, jackets, rs)
            data = out.read_bytes()
            try:
                out.unlink()
            except OSError:
                pass
            if len(self._img_memo) >= 8:
                self._img_memo.pop(next(iter(self._img_memo)))
            self._img_memo[ctx.uid] = (b, rs, data)
            return Reply(image=data).say(note) if note else Reply(image=data)
        except Exception as e:  # noqa: BLE001
            return Reply().say(f"（出图失败：{type(e).__name__}，先发文字版）\n" + b50_text(prof.name, b, src)
                               + ("\n" + note if note else ""))

    async def theory(self, server: str):
        """→ (B50, 版本名)：这个服当前版本全部 1,010,000 + AJC 时的旧曲 B30 + 新曲 N20。"""
        from .sample import sample_b50
        await self._ensure_catalog()
        if server in ("jp", "cn"):
            try:
                await asyncio.wait_for(self.svc.consts.ensure_loaded(), 60)
            except Exception:  # noqa: BLE001
                pass
        if server == "cn":
            try:
                await self.svc.lx_songs.ensure()
            except Exception:  # noqa: BLE001
                pass
        _name, b, cur = await asyncio.to_thread(sample_b50, self.svc, server)
        return b, cur

    async def c_theory(self, ctx, rest):
        """/chu 理论 [区服] [文字]：理论最高 Rating（不用绑定）。"""
        server, rest = split_server(rest)
        as_text = any(a in ("文字", "text", "txt") for a in rest)
        return await self._b50_sample(catalog_server(server) or "intl", as_text)

    async def _b50_sample(self, server: str, as_text: bool) -> Reply:
        """理论最高 B50：当前版本每张谱面都 1,010,000 时的旧曲 B30 + 新曲 N20（不需要绑定）。"""
        b, cur = await self.theory(server)
        name = "理论 Rating"
        if not b.best and not b.new:
            return Reply().say("曲库还没加载好，稍后再试")
        head = (f"中二{SERVER_NAMES[server]}理论 Rating：{b.total}"
                f"（旧曲 B30 平均 {b.best_avg} / 新曲 N20 平均 {b.new_avg}{' · ' + cur if cur else ''}）")
        others = "、".join(f"/chu 理论 {SERVER_NAMES[x]}" for x in ("intl", "jp", "cn") if x != server)
        if as_text or self.renderer is None:
            return Reply().say(head + "\n" + b50_text(name, b))
        try:
            async def make():
                jackets = await self.svc.jackets_for(b.best + b.new)
                out = self.data_dir / "render" / f"b50_sample_{server}_{int(time.time())}.jpg"
                await asyncio.to_thread(self.renderer, name, b, out, jackets, ("cn_lx" if server == "cn" else server) + "_theory")
                data = out.read_bytes()
                try:
                    out.unlink()
                except OSError:
                    pass
                return data
            return Reply(image=await self._cached_img(("chu_sample", server, head), make)).say(
                head + f"\n其他服：{others}")
        except Exception as e:  # noqa: BLE001
            return Reply().say(head + f"（出图失败：{type(e).__name__}，先发文字版）\n" + b50_text(name, b))

    async def c_refresh(self, ctx, rest):
        server, _ = split_server(rest)
        s = self._server(ctx.uid, server)
        self.svc.clear_cache(ctx.uid)
        if s in PRIV_SERVERS_CHU:
            prof, b = await self.svc.b50_priv(ctx.uid, s, force=True)
            return Reply().say(f"已刷新 {SERVER_NAMES[s]}：{prof.name}  Rating {prof.rating:.2f}"
                               + (f"（{b.version}）" if b.version else ""))
        if s == "cn":
            prof, _b = await self.svc.b50_cn(ctx.uid, force=True)
            return Reply().say(f"已刷新国服（{self._cn_src(ctx.uid)}）：{prof.name}  Rating {prof.rating:.2f}")
        p = await self.svc.profile(ctx.uid, force=True, server=s)
        return Reply().say(f"已刷新{SERVER_NAMES[s]}：{p.name}  Rating {p.rating:.2f}")

    # ---------- catalog ----------
    async def _jackets(self, songs) -> dict:
        ids = [s.id for s in songs]
        fb = {s.id: s.jacket_url for s in songs if s.jacket_url}
        try:
            return await asyncio.wait_for(self.svc.jackets.get_many(ids, fb), 60)
        except Exception:  # noqa: BLE001
            return {}

    async def _ensure_catalog(self):
        await self.svc.songdb.ensure_loaded()
        c = self.svc.consts
        if not c.loaded_at:
            c.load_files()                      # use whatever is cached right away
        if not c.cn or not c.fetched_at or time.time() - c.fetched_at > 24 * 3600:
            try:                                # 水鱼 is small: worth a short wait; Tachi continues in background
                await asyncio.wait_for(asyncio.shield(self._consts_task()), 20)
            except Exception:  # noqa: BLE001
                pass

    def _consts_task(self):
        t = getattr(self, "_consts_bg", None)
        if t is None or t.done():
            t = self._consts_bg = asyncio.ensure_future(self.svc.consts.ensure_loaded())
        return t

    async def c_song(self, ctx: Ctx, rest):
        server, rest = split_server(rest)
        server = self._catalog_server(server)
        q = " ".join(rest).strip()
        if not q:
            return Reply().say("用法：/chu 查 <歌名/别名/ID> [国际服|日服|国服]")
        await self._ensure_catalog()
        song, err, note = self.find_song(q)
        if err:
            return err
        if not song.bpm and (b := getattr(self.svc.consts, "bpm", {}).get(song.id)):
            song.bpm = b          # chuni-penguin has no BPM for some songs; 水鱼 does
        consts = self.svc.consts_for(song)
        r = Reply()
        if self.cards is not None:
            ver = f" {self.svc.current_version}" if server == "intl" and self.svc.current_version else ""
            aliases = self.svc.songdb.aliases_of(song)

            async def make():
                jk = await self._jackets([song])
                return await asyncio.to_thread(self.cards.song, song, server, consts, jk.get(song.id), ver, aliases)
            r.image = await self._cached_img(("chu_song", song.id, server, ver, sorted(aliases), consts), make)
            if note:
                r.say(note if note.startswith(("WORLD", "外号")) else f"{note}：{song.title}")
        else:
            lines = [f"{song.title}（{song.id}）"]
            for d, c in sorted(song.charts.items()):
                v = consts.get(d, {})
                lines.append(f"[{d.short} {c.level}] " + " / ".join(f"{SERVER_NAMES[s]} {x:.1f}" for s, x in v.items()))
            r.say("\n".join(lines))
        mine = ("jp" if server == "jp" and ctx.uid in self.svc.jp else
                "intl" if ctx.uid in self.svc.store else "jp" if ctx.uid in self.svc.jp else "")
        if mine:  # 绑定了国际服 / 日服就顺便附上自己的成绩（NET 不通就算了）
            try:
                _song, scores = await asyncio.wait_for(self.svc.song(ctx.uid, str(song.id), mine), 15)
                txt = song_text(song.title, scores, {d: c.const for d, c in song.charts.items()})
                r.say("你的成绩：\n" + "\n".join(txt.split("\n")[1:]))
            except Exception:  # noqa: BLE001
                pass
        return r

    # ---------- song lookup by title / nickname / ID ----------
    async def _lone_song(self, text: str):
        await self._ensure_catalog()
        d = decide(self.svc.songdb.search_ranked(text, 6), text)
        return d.item if d.item is not None and not d.note else None

    def find_song(self, q: str, cmd: str = "查"):
        d = decide(self.svc.songdb.search_ranked(q, 8), q)
        if d.item is not None:
            return d.item, None, d.note
        if (reg := pick_regular(d.choices)) is not None:
            song, we = reg
            return song, None, f"WORLD'S END 版发「/chu {cmd} {we.id}」"
        is_we = lambda it: "WORLD" in (getattr(it, "genre", "") or "").upper()  # noqa: E731
        if (pk := alias_pick(d.choices, skip=is_we)) is not None:     # 一个外号好几首：先出最难的
            song, others = pk
            return song, None, "\n".join([f"外号「{q}」还对应：", *(f"{o.title}（{o.id}）" for o in others[:4]),
                                           f"看别的发「/chu {cmd} ID」"])
        if d.choices:
            lines = [f"「{q}」可能是这几首，用 ID 再查一次："]
            for i, m in enumerate(d.choices, 1):
                why = f" ← 外号「{m.name}」" if m.by_alias else ""
                lines.append(f"{i}. {m.item.title}（ID {m.item.id}{' · ' + m.item.genre if m.item.genre else ''}）{why}")
            lines.append(f"例：/chu {cmd} {d.choices[0].item.id}")
            return None, Reply().say("\n".join(lines)), ""
        return None, Reply().say(f"没找到「{q}」。可以试试歌名的一部分、常用外号或曲目 ID；"
                                 f"外号没收录的话可以发「/chu 加别名 外号 歌名」教我。"), ""

    async def c_alias(self, ctx, rest):
        q = " ".join(rest)
        if not q:
            return Reply().say("用法：/chu 别名 <歌名/外号/ID>")
        await self._ensure_catalog()
        song, err, _ = self.find_song(q, "别名")
        if err:
            return err
        names = self.svc.songdb.aliases_of(song)
        if not names:
            return Reply().say(f"{song.title} 还没有收录外号。可以发「/chu 加别名 外号 {song.title}」加一个")
        shown = "、".join(names[:60]) + (f" …（共 {len(names)} 个）" if len(names) > 60 else "")
        return Reply().say(f"{song.title} 的外号：\n{shown}\n（来源：落雪 / Yuzuchan 别名库 / 本机添加）")

    async def c_alias_add(self, ctx, rest):
        if len(rest) < 2:
            return Reply().say("用法：/chu 加别名 <外号> <歌名或 ID>，例：/chu 加别名 阿列夫 Aleph-0")
        alias, q = rest[0], " ".join(rest[1:])
        if len(alias) > 20:
            return Reply().say("外号太长了（最多 20 个字）")
        await self._ensure_catalog()
        song, err, _ = self.find_song(q, f"加别名 {alias}")
        if err:
            return err
        if self.aliases is None:
            return Reply().say("别名库没有加载，暂时加不了")
        self.aliases.add_local(alias, song.id)
        self.svc.songdb.apply_aliases(self.aliases.merged())
        return Reply().say(f"记住了：「{alias}」= {song.title}（只在这个 bot 上生效）")

    async def c_alias_del(self, ctx, rest):
        if not ctx.admin:
            return Reply().say("只有机器人主人能删外号")
        if not rest or self.aliases is None:
            return Reply().say("用法：/chu 删别名 <外号>（只能删本机加的）")
        ok = self.aliases.remove_local(rest[0])
        if ok:
            self.svc.songdb.apply_aliases(self.aliases.merged())
        return Reply().say("删掉了" if ok else "这个外号不是本机加的（别名库里的删不了）")

    async def c_score(self, ctx, rest):
        """/chu 成绩 <歌>: 国际服 reads the song page on CHUNITHM-NET; 国服 only knows the B30 / R10."""
        server, rest = split_server(rest)
        q = " ".join(rest).strip()
        if not q:
            return Reply().say("用法：/chu 成绩 <歌名/外号/ID> [国际服|日服|国服]")
        await self._ensure_catalog()
        song, err, note = self.find_song(q, "成绩")
        if err:
            return err
        server = self._server(ctx.uid, server)
        if server in PRIV_SERVERS_CHU:
            _prof, b = await self.svc.b50_priv(ctx.uid, server)
            mine = [s for s in [*b.best, *b.new] if s.song_id == song.id]
            if not mine:
                return Reply().say(f"{song.title}（{SERVER_NAMES[server]}）\n这首不在你的 B30 / N20 里"
                                   f"（{SERVER_NAMES[server]} 只公开这部分成绩）")
            return Reply().say(song_text(f"{song.title}（{SERVER_NAMES[server]}）", mine, {})
                               + (f"\n{note}" if note else ""))
        consts = {d: self.svc.const_of(song, c, server) for d, c in song.charts.items()}
        if server in ("intl", "jp"):
            _song, scores = await asyncio.wait_for(self.svc.song(ctx.uid, str(song.id), server), 30)
            if not scores:
                return Reply().say(f"{song.title}（{SERVER_NAMES[server]}）\n还没有这首的成绩")
            return Reply().say(song_text(song.title, scores, consts) + (f"\n{note}" if note else ""))
        if self.svc.cn_source(ctx.uid) == "lx":
            _prof, all_scores = await asyncio.wait_for(self.svc.cn_scores_lx(ctx.uid), 30)
            mine = [s for s in all_scores if s.song_id == song.id]
            if not mine:
                return Reply().say(f"{song.title}（国服）\n落雪上还没有这首的成绩")
            return Reply().say(song_text(song.title, mine, consts) + (f"\n{note}" if note else ""))
        _prof, b = await self.svc.b50_cn(ctx.uid)
        mine = [s for s in [*b.best, *b.new] if s.song_id == song.id or s.title == song.title]
        if not mine:
            if self.svc.cn_source(ctx.uid) == "lxqq":
                return Reply().say(f"{song.title}（国服）\n这首不在你的 B30 / N20 里（按 QQ 只能拿到这部分；"
                                   "发「/网页绑定」选「落雪授权」能查全部）")
            return Reply().say(f"{song.title}（国服）\n这首不在你的 B30 / R10 里（水鱼只给这部分成绩；绑定落雪能查全部）")
        return Reply().say(song_text(song.title, mine, consts))

    def _entries(self, lo: float, hi: float, server: str):
        out = []
        for song, chart, v in self.svc.songdb.charts_by_const(
                lo, hi, lambda s, c: self.svc.const_of(s, c, server)):
            out.append((song, chart, v, self.svc.consts_for(song).get(chart.difficulty, {})))
        return out

    async def c_ds(self, ctx, rest):
        server, rest = split_server(rest)
        server = self._catalog_server(server)
        nums = [float(a) for a in rest if re.fullmatch(r"\d+(\.\d)?", a)]
        if not nums:
            return Reply().say("用法：/chu 定数 15.0 [15.4] [国际服|日服|国服]")
        lo, hi = (nums[0], nums[0]) if len(nums) == 1 else (min(nums[:2]), max(nums[:2]))
        if hi - lo > 2.0:
            return Reply().say("范围太大了，一次最多 2.0")
        await self._ensure_catalog()
        entries = self._entries(lo, hi, server)
        if not entries:
            return Reply().say("这个范围没有谱面")
        rng = f"{lo}" if lo == hi else f"{lo}–{hi}"
        sub = f"{SERVER_NAMES[server]} · 定数 {rng} · 共 {len(entries)} 张"
        if self.cards is not None:
            async def make():
                jk = await self._jackets(list({e[0].id: e[0] for e in entries}.values()))
                if len(entries) <= 40:
                    return await asyncio.to_thread(self.cards.ds_list, entries, server, "定数查歌", sub, jk)
                return await asyncio.to_thread(self.cards.ds_table, entries, server, f"定数 {rng}", sub, jk)
            return Reply(image=await self._cached_img(("chu_ds", lo, hi, server, sub), make))
        lines = [f"{v:.1f} {s.title} [{c.difficulty.short}]" for s, c, v, _ in entries[:60]]
        return Reply().say(f"中二{SERVER_NAMES[server]} 定数 {rng}：\n" + "\n".join(lines))

    async def c_dstable(self, ctx, rest):
        server, rest = split_server(rest)
        server = self._catalog_server(server)
        rng = _parse_range(" ".join(rest))
        if rng is None:
            return Reply().say("用法：/chu 定数表 15+　/chu 定数表 14　/chu 定数表 14.5-15.0")
        lo, hi, name = rng
        if hi - lo > 2.0:
            return Reply().say("范围太大了，一次最多 2.0")
        await self._ensure_catalog()
        entries = self._entries(lo, hi, server)
        if not entries:
            return Reply().say("这个范围没有谱面")
        sub = f"{SERVER_NAMES[server]} · {lo:.1f}–{hi:.1f} · 共 {len(entries)} 张"
        if self.cards is None:
            return await self.c_ds(ctx, [server, f"{lo:.1f}", f"{hi:.1f}"])
        async def make():
            jk = await self._jackets(list({e[0].id: e[0] for e in entries}.values()))
            return await asyncio.to_thread(self.cards.ds_table, entries, server, f"{name} 定数表", sub, jk)
        return Reply(image=await self._cached_img(("chu_dstable", name, server, sub), make))
