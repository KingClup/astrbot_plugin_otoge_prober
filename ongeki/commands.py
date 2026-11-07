"""/geki（音击 / オンゲキ）：私服查分 + sdvx.in 谱面。

查分只走私服（音击没有官方查分网站可用）：
  AquaDX   按网站用户名，公开接口，能查
  MuNET    第三方工具被挡（HTTP 418），暂时查不了
  RinNET   还没做音击
私服绑定跟舞萌中二共用一份（core/privsrv），绑一次三个游戏都能查。
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from . import fetch
from .music import OngekiMusicDB
from .text import render

try:
    from ..core.privsrv import PrivError
    from ..core.privsrv.servers import ALIASES, NAMES, parse_username
    from ..mai.bot.commands import Ctx, Reply
except ImportError:  # tests import packages top-level
    from core.privsrv import PrivError
    from core.privsrv.servers import ALIASES, NAMES, parse_username
    from mai.bot.commands import Ctx, Reply

log = logging.getLogger("astrbot")

CONSTS = os.path.join(os.path.dirname(__file__), "data", "ongeki_consts.json")
CHART_SUBS = ("谱面", "谱", "谱面确认", "chart", "查谱", "谱面图", "加别名", "添加别名")
BEST_SUBS = ("b50", "best", "best50", "b60", "ra", "rating", "成绩", "查分", "我", "info", "me", "资料")
ALL_WORDS = ("全", "全部", "all", "完整")
TEXT_WORDS = ("文字", "text", "txt", "文本")
MUSIC_TTL = 86400
BEST_TTL = 10 * 60             # 同一个人 10 分钟内再查 b50：直接用上次拉到的成绩（「/geki 刷新」强制重拉）
REFRESH_SUBS = ("刷新", "更新", "sync", "refresh")

HELP = """音击（オンゲキ）
/geki b50：私服成绩图（新曲 10 + 旧曲 50 + P 分 50，Re:Fresh 算法）；加「文字」发文字版，「文字 全」列全部
/geki 刷新：刚打完想马上看新成绩时用（平时 10 分钟内重复查用的是上次的数据）
/geki 绑定 aqua <用户名>：绑 AquaDX（跟舞萌中二共用，已经绑过就不用再绑）；/geki 网页绑定：在手机网页上填
/geki 谱面 <歌名> [红|紫|lun]：sdvx.in 谱面图（LUNATIC / Re:MASTER 写 lun）
现在能查分的私服：AquaDX。MuNET 不让第三方工具读数据，RinNET 的音击还没做
定数按你游戏客户端的版本取（1.45 bright MEMORY Act.3 / 1.5x Re:Fresh / 1.60 Re:Fresh Act.2）
也可以写 /音击、/ongeki"""


class GekiCommands:
    def __init__(self, hub, charts=None, bot_name: str = "AstrBot", font_path: str | None = None):
        self.hub = hub                  # core.privsrv.Hub：发请求 + 共用绑定
        self.charts = charts            # chart.commands.ChartCommands
        self.bot_name = bot_name
        self.font_path = font_path
        self._db: OngekiMusicDB | None = None
        self._music: tuple[float, dict] | None = None
        self._best_cache: dict[str, tuple[float, object]] = {}     # uid:username → (拉取时间, best)
        self._img_cache: dict[str, bytes] = {}

    @property
    def db(self) -> OngekiMusicDB:
        if self._db is None:
            self._db = OngekiMusicDB.load(CONSTS)
        return self._db

    # ---------- http (on the shared private-server client) ----------
    async def _get(self, url: str):
        return await self.hub.request("GET", url)

    async def _post(self, url: str, json=None):
        return await self.hub.request("POST", url, json=json)

    async def _all_music(self) -> dict | None:
        if self._music and time.time() - self._music[0] < MUSIC_TTL:
            return self._music[1]
        try:
            status, js = await self._get(fetch.AQUA_MUSIC)
        except PrivError:
            status, js = 0, None
        if status == 200 and isinstance(js, dict):
            self._music = (time.time(), js)
            return js
        return self._music[1] if self._music else None

    # ---------- entry ----------
    async def handle(self, ctx: Ctx, argline: str) -> Reply:
        words = argline.split()
        if not words or words[0] in ("帮助", "help", "?", "？"):
            return Reply().say(HELP)
        sub = words[0].lower()
        if sub in CHART_SUBS or sub in ("刷新谱面", "更新谱面"):
            if self.charts is None:
                return Reply().say("谱面查询没开")
            return await self.charts.handle(ctx, "刷新" if sub.endswith("谱面") and sub != "谱面" else argline, "geki")
        if sub in ("绑定", "bind"):
            return await self._bind(ctx, words[1:])
        if sub in ("解绑", "unbind"):
            return Reply().say("私服绑定是舞萌、中二、音击共用的：发「/查分 账号」看绑了哪些，"
                               "「/mai 解绑 aqua」解绑（三个游戏一起解）")
        if sub in ("最近", "recent"):
            return Reply().say("音击还只能查 b50（/geki b50）；最近游玩记录以后再做")
        if sub in BEST_SUBS or sub in ALL_WORDS or sub in TEXT_WORDS or sub in REFRESH_SUBS:
            full = any(w in ALL_WORDS for w in words)
            text = any(w in TEXT_WORDS for w in words) or (full and sub in ALL_WORDS)
            return await self._best(ctx, full, text, force=sub in REFRESH_SUBS or any(w in REFRESH_SUBS for w in words))
        # 不是子命令：当歌名查谱面
        if self.charts is not None:
            return await self.charts.handle(ctx, argline, "geki")
        return Reply().say(HELP)

    # ---------- bind ----------
    async def _bind(self, ctx: Ctx, args: list[str]) -> Reply:
        if not args:
            return Reply().say("用法：/geki 绑定 aqua <用户名>（aquadx.net/u/ 后面那段），或发「/geki 网页绑定」在网页上填。"
                               "舞萌中二已经绑过 AquaDX 的不用再绑")
        server = ALIASES.get(args[0].lower())
        if server is None:
            server, args = "aqua", ["aqua", *args]           # 「/geki 绑定 xwx」= AquaDX
        if server != "aqua":
            return Reply().say(f"{NAMES.get(server, server)} 的音击还查不了，现在只有 AquaDX 能查音击")
        username = parse_username(" ".join(args[1:]))
        if not username:
            return Reply().say("用法：/geki 绑定 aqua <用户名>（aquadx.net/u/ 后面那段）")
        try:
            status, _js = await self._post(
                f"https://aquadx.net/aqua/api/v2/card/user-games?username={quote(username, safe='')}")
        except PrivError as e:
            return Reply().say(f"绑定 AquaDX 失败：{e}")
        if status != 200:
            return Reply().say(f"AquaDX 上找不到用户「{username}」（用户名是 aquadx.net/u/ 后面那段）")
        self.hub.bindings.set(ctx.uid, "aqua", username, "")
        return Reply().say(f"AquaDX 绑定成功：{username}。发「/geki b50」查音击（舞萌中二也能直接查）")

    # ---------- best ----------
    def _server(self, uid: str) -> tuple[str, str]:
        for s in ("aqua", "munet", "rin"):
            u = self.hub.bindings.get(uid, s)
            if u:
                return s, u
        return "", ""

    async def _best(self, ctx: Ctx, full: bool, text_only: bool = False, force: bool = False) -> Reply:
        server, username = self._server(ctx.uid)
        if not server:
            return Reply().say("你还没绑定私服。音击现在能查 AquaDX：发「/geki 绑定 aqua <用户名>」"
                               "（跟舞萌中二共用，绑一次都能查）")
        if server == "munet":
            return Reply().say("你绑的是 MuNET：MuNET 现在不允许第三方查分工具读取数据（HTTP 418），"
                               "音击成绩去 portal.mumur.net 网站上看。有 AquaDX 号的话发「/geki 绑定 aqua <用户名>」")
        if server == "rin":
            return Reply().say("你绑的是 RinNET：RinNET 的音击查分还没做，现在只有 AquaDX 能查音击")
        ckey = f"{ctx.uid}:{username}"
        hit = self._best_cache.get(ckey)
        if hit and not force and time.time() - hit[0] < BEST_TTL:
            best = hit[1]
        else:
            hit = None
            try:
                best = await fetch.aquadx_best(self._post, self._get, username, self.db, await self._all_music())
            except fetch.GekiError as e:
                return Reply().say(str(e))
            except PrivError as e:
                return Reply().say(f"AquaDX：{e}")
            if len(self._best_cache) > 200:
                self._best_cache = {k: v for k, v in self._best_cache.items() if time.time() - v[0] < BEST_TTL}
            self._best_cache[ckey] = (time.time(), best)
        if not text_only:
            try:
                img = self._img_cache.get(ckey) if hit is not None else None      # 成绩没变：图也不用重画
                if img is None:
                    img = await self._image(best)
                    self._img_cache = {ckey: img}        # 只留最近一张（一张 1～3 MB）
                r = Reply(image=img)
                if best.calc is not None and best.shown is not None and best.calc != best.shown:
                    r.say("（图上「计算值」是按定数表重算的；跟服务器显示的差一点时以服务器为准）")
                return r
            except Exception as e:  # noqa: BLE001
                log.warning(f"[otoge] geki b50 image failed: {type(e).__name__}: {e}")
        text = render(best, best_limit=None if full else 15, plat_limit=None if full else 10)
        if not full:
            text += "\n（列全部发「/geki b50 文字 全」）"
        return Reply().say(text)

    async def _image(self, best) -> bytes:
        from .b50img import render as render_img
        titles = [c.title for c in (*best.new, *best.best, *best.plat, *best.recent)]
        jackets: dict = {}
        src = getattr(self.charts, "src", None)
        if src is not None:
            try:
                jackets = await src.geki_jackets(titles)
            except Exception as e:  # noqa: BLE001
                log.warning(f"[otoge] geki jackets failed: {type(e).__name__}: {e}")
        server = {"aqua": "AquaDX", "munet": "MuNET", "rin": "RinNET"}.get(best.server, best.server)
        label = f"{server} · {best.version_name}" + (f" · Ver.{best.client // 100}.{best.client % 100:02d}"
                                                     if best.client else "")
        out = Path(tempfile.gettempdir()) / f"otoge_geki_{time.time_ns()}.jpg"
        await asyncio.to_thread(render_img, best, out, jackets=jackets, font_path=self.font_path,
                                footer_left=f"Generated by {self.bot_name}", region_label=label)
        try:
            return out.read_bytes()
        finally:
            try:
                out.unlink()
            except OSError:
                pass
