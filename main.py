"""AstrBot 插件：音游查分（舞萌 DX 国际服 / 日服 / 国服 + 中二节奏 国际服 / 日服 / 国服）。

  /mai …     舞萌 DX（别名 /maimai /舞萌）
  /chu …     中二节奏（别名 /chuni /中二）
  /查分 …    帮助图、我的账号、本群自然语言开关（别名 /score）
业务逻辑在 mai/、chuni/、core/ 里，这里只做 AstrBot 接入。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import sys
import tempfile
import time
from pathlib import Path

# 覆盖安装 / 热重载时 AstrBot 只卸载 main，子模块还留在 sys.modules → 先清掉，保证用的是新代码
for _m in [m for m in list(sys.modules) if __package__ and m.startswith(__package__ + ".") and m != __name__]:
    del sys.modules[_m]

from astrbot.api import AstrBotConfig, logger  # noqa: E402
from astrbot.api.event import AstrMessageEvent, filter  # noqa: E402
from astrbot.api.star import Context, Star, StarTools, register  # noqa: E402
import astrbot.api.message_components as Comp  # noqa: E402

from .core import nl as NL  # noqa: E402
from .core.help import help_text, render_full, render_help, render_topic, topic_key  # noqa: E402
from .core.bindguide import render_bind_guide  # noqa: E402
from .core import progress_img as PG  # noqa: E402
from .core.progress import CHU_VERSION_NUMBERS  # noqa: E402
from .core.progress import ProgressTracker  # noqa: E402
from .chuni.augment import apply_chu_consts, augment_songdb  # noqa: E402
from .core import consts_hub as CH  # noqa: E402
from .mai.data.consts_apply import apply_mai_consts  # noqa: E402
from .core.migrate import migrate  # noqa: E402
from .core.route import CHART_SUBS, SONG_SUBS, route  # noqa: E402
from .chart.commands import ChartCommands  # noqa: E402
from .chart.sdvxin import SdvxIn  # noqa: E402
from .ongeki.commands import GekiCommands  # noqa: E402
from .games.commands import GameCommands  # noqa: E402
from .games.sources import GameData  # noqa: E402
from .mai.data.fuzzy import alias_pick, decide  # noqa: E402
from .core.prefs import GAME_NAMES, SERVER_NAMES, Prefs  # noqa: E402
from .mai.calc.sample import THEORY_WORDS  # noqa: E402
from .mai.bot.commands import Commands as MaiCommands, Ctx, Reply  # noqa: E402
from .mai.bot.guard import install_redactor, looks_like_clal, looks_like_password_bind  # noqa: E402
from .core.lxns import looks_like_lxns_secret  # noqa: E402
from .mai.bot.storage import UserStore  # noqa: E402
from .mai.data.aliases import AliasStore  # noqa: E402
from .mai.data.loader import CatalogStore  # noqa: E402
from .mai.service import MaiService  # noqa: E402
from .mai.webui import ROUTES as MAI_ROUTES, Settings as MaiSettings, WebUI as MaiWebUI  # noqa: E402
from .chuni import redact as chu_redact  # noqa: E402
from .chuni.commands import ChuCommands, pick_regular  # noqa: E402
from .chuni.service import ChuniService, Settings as ChuSettings  # noqa: E402
from .chuni.webui import register_web_apis as chu_web_apis  # noqa: E402
from .core.webui import CoreWebUI, ROUTES as CORE_ROUTES  # noqa: E402
from .core.bindweb import Binder, BindWeb  # noqa: E402
from .core import cnupdate as CU  # noqa: E402
from .core import changelog as CL  # noqa: E402
from .mai.bot.commands import split_args as mai_split_args  # noqa: E402
from .chuni.commands import split_server as chu_split_server  # noqa: E402
from .core.imgcache import ImageCache  # noqa: E402
from .core.privsrv import Hub as PrivHub, NAMES as PRIV_NAMES  # noqa: E402
from .core.privsrv.servers import rom_label  # noqa: E402

PLUGIN = "astrbot_plugin_otoge_prober"
VERSION = "2.0.0"
MAI_NAMES = ("mai", "maimai", "舞萌")
CHU_NAMES = ("chu", "chuni", "中二")
CORE_NAMES = ("查分", "score", "otoge")
SDVX_NAMES = ("sdvx", "soundvoltex", "sv")
PJSK_NAMES = ("pjsk", "prsk", "烧烤", "啤酒烧烤", "世界计划")
GEKI_NAMES = ("geki", "ongeki", "音击", "オンゲキ")
CMD_NAME = {"mai": "mai", "chu": "chu", "core": "查分", "sdvx": "sdvx", "pjsk": "pjsk", "chart": "谱面", "geki": "geki"}
HELP_WORDS = ("", "帮助", "help", "?", "？")
def _is_we(song) -> bool:
    return "WORLD" in (getattr(song, "genre", "") or "").upper()


_PLAIN_AT = re.compile(r"^\s*(?:@[^\s/／@]+\s*)+(?=[/／])")
BIND_WEB_PORT = 36199
RESERVED_PORTS = (6185, 6195, 6196, 6199, 6099, 3000, 3001)   # AstrBot 面板 / 各平台适配器 / NapCat 常用端口
BIND_GUIDE_WORDS = ("绑定", "bind", "登录", "绑定教程", "bindhelp", "怎么绑", "怎么绑定")
WEB_BIND_WORDS = ("网页绑定", "网页", "web", "webbind", "绑定网页", "网页登录")


class _Host:
    """Attribute bag handed to the per-game WebUI modules (they were written for a plugin object)."""


@register(PLUGIN, "KingClup & Claude (vibe coding)", "音游查分：舞萌 DX（国际服/日服/国服）+ 中二节奏（国际服/日服/国服）", VERSION)
class OtogeScore(Star):
    VERSION = VERSION

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        root = str(StarTools.get_data_dir(PLUGIN))
        self.root = root
        self.migration = migrate(root)
        _old = os.path.join(os.path.dirname(root), "astrbot_plugin_otoge_score")
        if os.path.isdir(_old) and not any(n for n in os.listdir(root) if n not in ("prefs.json",)):
            import shutil as _sh
            _sh.copytree(_old, root, dirs_exist_ok=True,
                         ignore=lambda d, names: [n for n in names if n in ("__pycache__", "outbox", "render")])
            self.migration["renamed"] = "已从 astrbot_plugin_otoge_score 复制全部数据"
        self.prefs = Prefs(root)
        self.bot_name = str(self._cfg("bot_name", "AstrBot") or "AstrBot")
        self.next_refresh = None
        self._init_mai(os.path.join(root, "mai"))
        self._init_chu(Path(root) / "chu")
        # 私服（MuNET …）：一份绑定舞萌中二共用
        self.priv = PrivHub(os.path.join(root, "privsrv"), proxy=self._cfg("proxy", "") or None)
        self.service.priv = self.chu_svc.priv = self.priv
        # 落雪开发者令牌：配置 lx_dev_token，或数据目录 lx_dev_token.txt。有了就能按 QQ 查国服
        from .core.lxns import dev_token_from
        self.service.lx_dev = self.chu_svc.lx_dev = dev_token_from(str(self._cfg("lx_dev_token", "") or ""), root)
        if self.service.lx_dev:
            logger.info("[otoge] 落雪开发者令牌已配置：国服可以按 QQ 查")
        # 落雪 OAuth：网页上点授权。client_id / secret 来自配置或数据目录 lx_oauth.json
        from .core.lxoauth import LxOAuth, load_client
        cid, csec = load_client(str(self._cfg("lx_oauth_client_id", "") or ""),
                                str(self._cfg("lx_oauth_client_secret", "") or ""), root)
        self.lx_oauth = LxOAuth(root, self.store._fernet, cid, csec, proxy=self._cfg("proxy", "") or None)
        self.service.lx_oauth = self.chu_svc.lx_oauth = self.lx_oauth
        self.charts = ChartCommands(SdvxIn(os.path.join(root, "sdvxin"), proxy=self._cfg("proxy", "") or None),
                                    chu=self.chu)
        self.geki = GekiCommands(self.priv, self.charts, bot_name=self.bot_name,
                                 font_path=getattr(self.chu_svc.settings, "font_path", None))
        self.games = GameCommands(GameData(self), last_game=self.prefs.last_game,
                                  help=lambda: self._help_reply("games"))   # 开字母 / 猜曲绘 / 猜谱面
        self.imgcache = ImageCache(root, version=VERSION)
        self.cmd.imgcache = self.imgcache
        self.chu.imgcache = self.imgcache
        # 版本进度核实：官方曲目表 + otoge-db 比社区曲库快，用来定各服当前版本、给中二补新歌和日服定数
        self.progress = ProgressTracker(root, proxy=self._cfg("proxy", "") or None)
        self.progress.load_cached()
        self._chu_aug: dict = {}
        self._apply_progress()
        # 定数中心：多个定数表按游戏 / 区服合并（core/consts_hub），结果写回两边曲库
        self.consts_hub = CH.ConstsHub(root, proxy=self._cfg("proxy", "") or None)
        self._register_const_sources()
        self.consts_hub.load_cached()
        self._const_stats: dict = {}
        self.chu_svc.songdb.post_load.append(self._chu_augment)
        self.chu_svc.consts.post_load.append(lambda _c: self._apply_chu_consts())
        self.catalog.post_load.append(lambda db: self._apply_mai_consts(db))
        self._rebuild_consts()
        self.core_webui = CoreWebUI(self)
        self._register_web(context)
        install_redactor()
        if self._cfg("redact_logs", True):
            chu_redact.install()
        self.bindweb = self._init_bindweb()
        self._tasks = [asyncio.create_task(self._mai_refresh_loop()), asyncio.create_task(self._chu_refresh_loop()),
                       asyncio.create_task(self._sdvxin_warmup())]
        if self.bindweb is not None:
            self._tasks.append(asyncio.create_task(self._bindweb_start()))
        self._tasks.append(asyncio.create_task(self.imgcache.prune_async()))
        self._tasks.append(asyncio.create_task(self._lx_oauth_loop()))
        self._tasks.append(asyncio.create_task(asyncio.to_thread(self._sweep_old_temp)))
        logger.info(f"[otoge] v{VERSION} loaded · migration {self.migration} · mai {self.catalog.db.current_version}")

    # ---------- setup ----------
    def _cfg(self, key: str, default):
        v = self.config.get(key, default) if hasattr(self.config, "get") else default
        return default if v is None else v

    def _init_mai(self, data_dir: str) -> None:
        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir          # mai WebUI reads p.data_dir
        self.settings = MaiSettings(data_dir)
        override = {"intl": self._cfg("version_intl", "auto"), "jp": self._cfg("version_jp", "auto"),
                    "cn": self._cfg("version_cn", "auto")}
        override.update(self.settings.get("version_override") or {})
        self.catalog = CatalogStore(data_dir, override)
        self.mai_aliases = AliasStore(os.path.join(data_dir, "aliases"), "mai", proxy=self._cfg("proxy", "") or None)
        self.catalog.aliases = self.mai_aliases.merged()
        self.catalog.load_local()
        self.store = UserStore(data_dir)
        self.service = MaiService(self.store, self.catalog)
        mcfg = lambda k, d: self.settings.get(k, self._cfg(k, d))  # noqa: E731  WebUI value wins
        name = str(mcfg("bot_name", self.bot_name) or self.bot_name)
        self.bot_name = name
        images = bool(mcfg("b50_image", True))
        renderer = cards = None
        if images:
            try:
                from .mai.render.b50img import B50Renderer
                from .mai.render.cards import CardRenderer
                renderer, cards = B50Renderer(data_dir, name), CardRenderer(data_dir, name)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[otoge] mai image renderer unavailable: {e}")
        self.cmd = MaiCommands(self.service, require_consent=bool(mcfg("require_consent", True)),
                               cache_minutes=int(mcfg("cache_minutes", 10)), renderer=renderer, prefs=self.prefs)
        self.cmd.cards = cards
        self.cmd.aliases = self.mai_aliases
        self.cmd.tz = str(self._cfg("timezone", "Asia/Shanghai"))
        self.mai_webui = MaiWebUI(self)

    def _init_chu(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        c = self._cfg
        self.chu_svc = ChuniService(data_dir, ChuSettings(
            timeout=float(c("timeout", 20)), proxy=c("proxy", "") or None,
            profile_ttl=int(c("profile_cache_seconds", 300)), scores_ttl=int(c("scores_cache_seconds", 1800)),
            timezone=str(c("timezone", "Asia/Shanghai")), font_path=c("font_path", "") or None,
            b50_fetch_lamps=bool(c("b50_fetch_lamps", True)), theme_version=str(c("theme_version", "auto") or "auto"),
            cn_theme_version=str(c("chu_cn_version", "auto") or "auto"),
            songdb_primary=str(c("songdb_primary", "beerpsi") or "beerpsi"), auto_logo=bool(c("auto_logo", True)),
            b50_footer=f"Generated by {self.bot_name}", b50_max_kb=int(c("b50_max_kb", 3000) or 0),
        ))
        self.chu_svc.consts.load_files()
        self.chu_aliases = AliasStore(data_dir / "aliases", "chu", proxy=self.chu_svc.settings.proxy)
        self.chu_svc.songdb.apply_aliases(self.chu_aliases.merged())
        cards = None
        try:
            from .chuni.cards import ChuCards
            cards = ChuCards(data_dir, self.bot_name)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] chuni cards unavailable: {e}")
        self.chu = ChuCommands(self.chu_svc, data_dir, prefs=self.prefs, cards=cards, renderer=self._chu_render,
                               tz=self.chu_svc.settings.timezone, cooldown=float(c("b50_cooldown", 15)))
        self.chu.aliases = self.chu_aliases
        host = _Host()
        host.svc, host.config, host._cfg = self.chu_svc, self.config, self._cfg
        host.next_refresh = None
        host.version_str = VERSION
        host.recognize = self._chu_recognize
        self.chu_host = host

    def _chu_render(self, name, b50, out, jackets, server="intl"):
        from .chuni.b50img import render_b50
        from .chuni.logos import LogoStore
        svc = self.chu_svc
        ver, th = svc.current_version, svc.theme
        theory = server.endswith("_theory")          # 理论值图：区服标签末尾写「理论值」，不写数据来源
        server = server.removesuffix("_theory")
        logos = LogoStore(Path(self.root) / "chu")
        card_logos = {}
        for s in [*b50.best, *b50.new]:     # each card shows the version its song came from
            song = svc.songdb.get(s.song_id) if s.song_id is not None else None
            if song is not None and s.song_id not in card_logos and (lg := logos.fit(song.version, 150, 36)):
                card_logos[s.song_id] = lg
        if server in PRIV_NAMES:
            # 私服 runs the 日服 / 国际服 client: the player's client version (2.50 → Mate) picks the artwork
            pv = b50.version or svc.jp_version or ver

            def own(v, kind):
                p = th.dir_for(v) / f"{kind}.png"
                return p if p.exists() else None
            bg = own(pv, "bg") or th.asset(ver, "bg")
            header_logo = own(pv, "logo") or logos.path(pv) or th.asset(ver, "logo")
            label = pv
            region = f"{PRIV_NAMES[server]} · {pv}"
            if b50.rom and (rl := rom_label(b50.rom)) and rl != pv:
                region += f" · {rl}"      # 玩家客户端版本号：定数、新旧曲都按它算
        elif server in ("cn", "cn_lx"):
            # 国服 shares the 日服 / 国际服 artwork: the 日服 version its build is based on (e.g. X-VERSE-X) picks
            # the header logo; its background falls back to the 国际服 theme, then default/. No 「中二节奏 20xx」.
            cv = svc.cn_version

            def own(v, kind):
                p = th.dir_for(v) / f"{kind}.png"
                return p if p.exists() else None
            bg = own(cv, "bg") or th.asset(ver, "bg")
            header_logo = own(cv, "logo") or logos.path(cv)
            label = cv
            region = f"国服 · {cv} · " + ("落雪查分器" if server == "cn_lx" else "水鱼查分器")
        elif server == "jp":
            jv = svc.jp_version or ver

            def own(v, kind):
                p = th.dir_for(v) / f"{kind}.png"
                return p if p.exists() else None
            bg = own(jv, "bg") or th.asset(ver, "bg")
            header_logo = own(jv, "logo") or logos.path(jv) or th.asset(ver, "logo")
            label = jv
            region = "日服" + (f" · {jv}" if jv else "") + " · CHUNITHM-NET"
        else:
            bg = th.asset(ver, "bg")
            header_logo = th.asset(ver, "logo") or logos.path(ver)
            label = ver
            region = "国际服" + (f" · {ver}" if ver else "") + " · CHUNITHM-NET"
        if theory:
            region = region.rsplit(" · ", 1)[0] + " · 理论值"
        return render_b50(name, b50, out, jackets, font_path=svc.settings.font_path, tz=svc.settings.timezone,
                          version=label, bg_path=bg, logo_path=header_logo, digits=th.digits(),
                          footer_left=f"Generated by {self.bot_name}", max_kb=svc.settings.b50_max_kb,
                          server=server, card_logos=card_logos, region_label=region)

    async def _sdvxin_warmup(self) -> None:
        """Have the sdvx.in song lists ready (from the disk cache, or downloaded once a day)."""
        await asyncio.sleep(20)
        for game in ("chu", "sdvx", "pjsk", "geki"):
            try:
                n = await self.charts.src.ensure(game)
                logger.info(f"[otoge] sdvx.in {game}: {n} songs")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[otoge] sdvx.in {game} list failed: {type(e).__name__}: {e}")

    async def _chu_recognize(self, text: str, event=None):
        it = await NL.classify(text, await self._llm_call(event))
        return it

    # ---------- 网页绑定（群友自助，手机优先） ----------
    def _bindweb_file(self) -> dict:
        import json
        try:
            with open(os.path.join(self.root, "bindweb.json"), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def lx_oauth_redirect(self) -> str:
        base = self.bindweb_url()
        return (base + "/lxns/callback") if base else ""

    def lx_oauth_in_use(self, uid: str) -> bool:
        """这个 QQ 的舞萌 / 中二国服还在用落雪授权吗（都解绑了就删掉授权记录）。"""
        mai = (self.store.get_creds(uid, "cn") or {}).get("source") == "lxoauth"
        chu = (self.chu_svc.cn.get(uid) or {}).get("source") == "lxoauth"
        return mai or chu

    async def _lx_oauth_loop(self):
        """每 6 小时：落雪授权超过 20 天的续期（refresh_token 30 天过期），没人用的删掉。"""
        await asyncio.sleep(120)
        while True:
            try:
                if self.lx_oauth.configured and self.lx_oauth.users():
                    st = await self.lx_oauth.keepalive(self.lx_oauth_in_use)
                    if any(st.values()):
                        logger.info(f"[otoge] 落雪授权续期：{st}")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[otoge] 落雪授权续期失败：{type(e).__name__}")
            await asyncio.sleep(6 * 3600)

    def bindweb_url(self) -> str:
        url = str(self._cfg("bind_web_url", "") or "").strip() or str(self._bindweb_file().get("url") or "").strip()
        return url.rstrip("/")

    def _init_bindweb(self):
        if not self._cfg("bind_web_enabled", True):
            return None
        port = int(self._cfg("bind_web_port", 0) or self._bindweb_file().get("port") or BIND_WEB_PORT)
        if port in RESERVED_PORTS:      # 6199 = AstrBot aiocqhttp 反向 WebSocket（NapCat 连这个），绝不能占 / 暴露
            logger.warning(f"[otoge] 网页绑定端口 {port} 是 AstrBot 自己在用的，改用 {BIND_WEB_PORT}")
            port = BIND_WEB_PORT
        return BindWeb(Binder(self), host="127.0.0.1", port=port, bot_name=self.bot_name,
                       notify=self._notify_private, log=logger.info)

    async def _bindweb_start(self) -> None:
        if await self.bindweb.start():
            logger.info(f"[otoge] 网页绑定服务：http://127.0.0.1:{self.bindweb.port} → {self.bindweb_url() or '（还没配公网地址）'}")
        else:
            logger.warning(f"[otoge] 网页绑定服务没起来（端口 {self.bindweb.port}）：{self.bindweb.error}")

    async def _notify_private(self, umo: str, text: str, at: str = "") -> None:
        from astrbot.api.event import MessageChain
        chain = MessageChain()
        if at:
            chain = chain.at("", at).message(" ")
        await self.context.send_message(umo, chain.message(text))

    def bindweb_ready(self) -> bool:
        return self.bindweb is not None and bool(self.bindweb_url()) and self.bindweb.running

    async def _bind_guide_img(self) -> bytes | None:
        try:
            return await self.imgcache.cached("bindguide", (self.bot_name,),
                                              lambda: asyncio.to_thread(render_bind_guide, self.bot_name, None),
                                              daily=False)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] bind guide image failed: {e}")
            return None

    async def _web_bind_reply(self, event: AstrMessageEvent, ctx: Ctx, game: str = "") -> Reply:
        """绑定指南图 + 本人专用的绑定链接（链接发文字，点得开）。"""
        r = self._web_bind_text(event, ctx, game)
        if self.bindweb_ready() and (ctx.private or self._cfg("bind_web_group", True)):
            img = await self._bind_guide_img()
            if img:
                r.image = img
        return r

    def _web_bind_text(self, event: AstrMessageEvent, ctx: Ctx, game: str = "") -> Reply:
        if self.bindweb is None:
            return Reply().say("网页绑定没开（插件配置 bind_web_enabled）。可以直接私聊发指令绑定，见「/mai 绑定」「/chu 绑定教程」")
        url = self.bindweb_url()
        if not url or not self.bindweb.running:
            return Reply().say("网页绑定还没接好公网地址，先用私聊指令绑定：/mai 绑定、/chu 绑定教程")
        group = not ctx.private
        if group and not self._cfg("bind_web_group", True):
            return Reply().say("网页绑定链接是你个人专用的，私聊我发「/网页绑定」拿链接～")
        token = self.bindweb.sessions.issue(ctx.uid, event.unified_msg_origin, ctx.name, group=group)
        link = f"{url}/#t={token}" + (f"&g={game}" if game in ("mai", "chu", "geki") else "")
        if group:
            return Reply(at=ctx.uid).say(f"你的绑定链接（10 分钟内有效，请自己马上点开，绑好了我在群里说一声）：\n{link}")
        return Reply().say(f"你的绑定链接（10 分钟内有效，只给你自己用，别转发）：\n{link}")

    # ---------- 国服成绩怎么更新 ----------
    def _cn_update_links(self) -> dict:
        return {k: str(self._cfg(key, "") or "").strip() or CU.DEFAULT_LINKS[k]
                for k, key in (("lx", "lx_sync_url"), ("df_mai", "df_mai_url"), ("df_chu", "df_chu_url"))}

    async def _cn_update(self, ctx: Ctx, game: str, rest: str) -> Reply:
        """国服：数据来自落雪 / 水鱼、上传于什么时候、去哪里更新；别的服：这一步不需要，顺手刷新。"""
        words = rest.split()
        try:
            if game == "mai":
                region, _ = mai_split_args(words)
                region = self.cmd._region(ctx.uid, region, remember=False)
            else:
                region, _ = chu_split_server(words)
                region = self.chu._server(ctx.uid, region, remember=False)
        except Exception:  # noqa: BLE001  未绑定之类：交给原来的指令去回「你还没绑定…」
            handler = self.cmd if game == "mai" else self.chu
            return await handler.handle(ctx, "刷新 " + rest if rest else "刷新")
        handler = self.cmd if game == "mai" else self.chu
        if region != "cn":
            name = SERVER_NAMES.get(region) or PRIV_NAMES.get(region) or region
            r = await handler.handle(ctx, f"刷新 {name}")
            return Reply().say(CU.not_cn_note(game, name) + "\n\n" + "\n".join(r.texts))
        tz = str(self._cfg("timezone", "Asia/Shanghai"))
        if game == "mai":
            binding = self.store.get_creds(ctx.uid, "cn") or {}
            source = self.service.cn_source(binding)
            uploaded = self.service.cn_uploaded_at(ctx.uid)
            if source in ("lx", "lxqq") and not uploaded:   # 还没查过：拉一次资料拿上传时间（不拉成绩）
                try:
                    from .core import lxns as LX
                    prof = await asyncio.wait_for(
                        LX.player("maimai", await self.service.lx_bearer(binding), transport=self.service.lx_transport)
                        if source == "lx" else
                        LX.player_by_qq("maimai", ctx.uid, self.service.lx_dev, transport=self.service.lx_transport),
                        20)
                    uploaded = str(prof.get("upload_time") or "")
                    self.service.remember_cn_uploaded(ctx.uid, uploaded)
                except Exception:  # noqa: BLE001
                    uploaded = ""
            snap = self.service.cached(ctx.uid, "cn")
            name = snap.profile.name if snap and snap.profile else ""
        else:
            source = self.chu_svc.cn_source(ctx.uid)
            uploaded = self.chu_svc.cn_uploaded_at(ctx.uid)
            if source in ("lx", "lxqq") and not uploaded:
                try:
                    from .core import lxns as LX
                    kw = {"transport": self.chu_svc.lx_transport, "proxy": self.chu_svc.settings.proxy}
                    prof = await asyncio.wait_for(
                        LX.player("chunithm", await self.chu_svc.lx_bearer(ctx.uid), **kw) if source == "lx" else
                        LX.player_by_qq("chunithm", ctx.uid, self.chu_svc.lx_dev, **kw), 20)
                    uploaded = str(prof.get("upload_time") or "")
                    self.chu_svc.remember_cn_uploaded(ctx.uid, uploaded)
                except Exception:  # noqa: BLE001
                    uploaded = ""
            name = str((self.chu_svc.cn.get(ctx.uid) or {}).get("name") or "")
        return Reply().say(CU.update_card(game, source, uploaded, self._cn_update_links(), tz, name))

    # ---------- WebUI ----------
    def _register_web(self, context) -> None:
        reg = getattr(context, "register_web_api", None)
        if reg is None:
            return
        for name, (method, attr) in MAI_ROUTES.items():
            reg(f"/{PLUGIN}/mai/{name}", self._api(getattr(self.mai_webui, attr)), [method], f"otoge mai {name}")
        reg(f"/{PLUGIN}/mai/theme/upload/<kind>/<target>", self._mai_upload, ["POST"], "otoge mai theme upload")
        reg(f"/{PLUGIN}/core/assets/upload/<key>", self._assets_upload, ["POST"], "otoge asset upload")
        for name, (method, attr) in CORE_ROUTES.items():
            reg(f"/{PLUGIN}/core/{name}", self._api(getattr(self.core_webui, attr)), [method], f"otoge core {name}")
        try:
            chu_web_apis(self.chu_host, context, f"{PLUGIN}/chu")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] chuni webui routes failed: {e}")

    def _api(self, fn):
        async def handler(**_):
            from astrbot.api.web import request
            params = {k: request.query.get(k) for k in request.query.keys()}
            if request.method != "GET":
                body = await request.json(default={}) or {}
                if isinstance(body, dict):
                    params.update(body)
            try:
                return {"status": "ok", "data": await fn(params)}
            except Exception as e:  # noqa: BLE001
                logger.info(f"[otoge] webui {fn.__name__}: {type(e).__name__}: {e}")
                return {"status": "error", "message": str(e) or type(e).__name__, "data": None}
        return handler

    async def _mai_upload(self, kind: str = "", target: str = "", **_):
        from astrbot.api.web import request
        params = {"kind": kind, "version" if kind in ("bg", "logo") else "name": target}
        try:
            f = (await request.files()).get("file")
            if f is None:
                raise ValueError("没有收到文件")
            data = await f.read()
            return {"status": "ok", "data": await self.mai_webui.theme_upload(params, getattr(f, "filename", ""), data)}
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": str(e), "data": None}

    async def _assets_upload(self, key: str = "", **_):
        """WebUI「素材」上传：key = auto（按文件名放）或某个素材位（如 mai_rank_sssp）。一次一个文件，页面逐个发。"""
        from astrbot.api.web import request
        try:
            f = (await request.files()).get("file")
            if f is None:
                raise ValueError("没有收到文件")
            data = await f.read()
            return {"status": "ok", "data": await self.core_webui.assets_upload(getattr(f, "filename", "") or "", data, key)}
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": str(e), "data": None}

    async def terminate(self):
        for t in self._tasks:
            t.cancel()
        if self.bindweb is not None:
            await self.bindweb.stop()
        chu_redact.uninstall()
        await self.chu_svc.close()
        await self.priv.close()

    # ---------- message helpers ----------
    def _ctx(self, event: AstrMessageEvent) -> Ctx:
        at = None
        for comp in event.get_messages():
            if isinstance(comp, Comp.At) and str(comp.qq) != str(event.get_self_id()):
                at = str(comp.qq)
        return Ctx(uid=str(event.get_sender_id()), private=event.is_private_chat(), admin=event.is_admin(),
                   at_uid=at, name=event.get_sender_name())

    async def _recall(self, event: AstrMessageEvent) -> None:
        try:
            bot = getattr(event, "bot", None)
            mid = getattr(event.message_obj, "message_id", None)
            if bot is not None and mid:
                await bot.call_action("delete_msg", message_id=int(mid))
        except Exception as e:  # noqa: BLE001
            logger.info(f"[otoge] recall failed: {type(e).__name__}")

    @staticmethod
    def _sweep_old_temp() -> None:
        """v1.14 及以前把发送用的图片写在系统临时目录里从不删：启动时把超过 1 小时的清掉。"""
        try:
            d = tempfile.gettempdir()
            now = time.time()
            n = 0
            for name in os.listdir(d):
                if name.startswith("otoge_") and name.endswith((".png", ".jpg")):
                    fp = os.path.join(d, name)
                    try:
                        if now - os.path.getmtime(fp) > 3600:
                            os.remove(fp)
                            n += 1
                    except OSError:
                        pass
            if n:
                logger.info(f"[otoge] 清理了临时目录里 {n} 张旧图片")
        except Exception:  # noqa: BLE001
            pass

    OUTBOX_KEEP = 10 * 60      # 发出去的图片文件留 10 分钟（适配器异步读文件），之后清掉

    def _outbox_file(self, uid: str, data: bytes) -> str:
        """待发送的图片：放在插件自己的 outbox/ 里并定期清理（以前写进系统临时目录，从不删，会一直堆）。"""
        d = os.path.join(self.root, "outbox")
        os.makedirs(d, exist_ok=True)
        now = time.time()
        if now - getattr(self, "_outbox_pruned", 0) > 60:
            self._outbox_pruned = now
            for name in os.listdir(d):
                fp = os.path.join(d, name)
                try:
                    if now - os.path.getmtime(fp) > self.OUTBOX_KEEP:
                        os.remove(fp)
                except OSError:
                    pass
        path = os.path.join(d, f"otoge_{uid}_{time.time_ns()}.png")
        with open(path, "wb") as f:
            f.write(data)
        return path

    async def _emit(self, event: AstrMessageEvent, r: Reply):
        if r.recall:
            await self._recall(event)
        if r.image:
            path = await asyncio.to_thread(self._outbox_file, str(event.get_sender_id()), r.image)
            chain = ([Comp.At(qq=r.at), Comp.Plain(" ")] if r.at else []) + [Comp.Image.fromFileSystem(path)]
            if r.texts:
                chain.append(Comp.Plain("\n".join(r.texts)))
            yield event.chain_result(chain)
        elif r.texts and r.at:
            yield event.chain_result([Comp.At(qq=r.at), Comp.Plain(" " + "\n".join(r.texts))])
        elif r.texts:
            yield event.plain_result("\n".join(r.texts))

    @staticmethod
    def _which(text: str) -> tuple[str, str] | None:
        """'/mai b50' → ('mai', 'b50'); '/chu 查 x' → ('chu', '查 x'); None if not ours."""
        t = text.strip()
        body = t[1:] if t.startswith("/") else t
        for game, names in (("mai", MAI_NAMES), ("chu", CHU_NAMES), ("core", CORE_NAMES), ("sdvx", SDVX_NAMES),
                            ("pjsk", PJSK_NAMES), ("geki", GEKI_NAMES)):
            for n in sorted(names, key=len, reverse=True):
                if body.lower() == n.lower() or body.lower().startswith(n.lower() + " "):
                    return game, body[len(n):].strip()
        return None

    def _help_versions(self) -> tuple:
        """帮助图上「现在的版本」：[(游戏, 区服, 版本名, 版本号)]。出错就不画这一条。"""
        try:
            out = []
            for title, rows in self._progress_data().games:
                g = "mai" if "舞萌" in title else "chu" if "中二" in title else ""
                out += [(g, r.region, r.version, r.number) for r in rows if g and r.version and r.version != "?"]
            return tuple(out)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] help versions failed: {e}")
            return ()

    async def _help_reply(self, topic: str | None = None) -> Reply:
        """topic：None = 总览；mai / chu / geki / chart / games / more = 那一页；all = 全部拼一张。"""
        try:
            if topic == "all":
                img = await self.imgcache.cached("help_all", (self.bot_name,),
                                                 lambda: asyncio.to_thread(render_full, self.bot_name), daily=False)
            elif topic:
                img = await self.imgcache.cached(f"help_{topic}", (self.bot_name,),
                                                 lambda: asyncio.to_thread(render_topic, topic, self.bot_name), daily=False)
            else:
                vers = self._help_versions()
                img = await self.imgcache.cached("help", (self.bot_name, vers),
                                                 lambda: asyncio.to_thread(render_help, self.bot_name, None, vers),
                                                 daily=False)
            return Reply(image=img)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] help image failed: {e}")
            return Reply().say(help_text(topic, self.bot_name))

    def _help_topic(self, game: str, argline: str) -> str | None:
        """「/mai 帮助」「/chu」「/sdvx 帮助」「/查分 帮助 舞萌」→ 要发哪一页；不是在要帮助就返回 False。"""
        words = argline.split()
        if words and words[0].lower() not in HELP_WORDS:
            return False
        if game == "core":
            return topic_key(words[1]) if len(words) > 1 else None
        if len(words) > 1 and topic_key(words[1]):
            return topic_key(words[1])
        return game                                     # sdvx / pjsk 各自一页；/谱面 帮助（game=chart）才是 sdvx.in 那页

    async def _dispatch(self, event: AstrMessageEvent, game: str, argline: str) -> Reply:
        ctx = self._ctx(event)
        topic = self._help_topic(game, argline)
        if topic is not False:                          # 「/mai 帮助」「/geki」「/sdvx 帮助」「/查分 帮助 舞萌」
            return await self._help_reply(topic)
        first, _, rest = argline.strip().partition(" ")
        if game == "geki":                              # 音击：私服查分 + sdvx.in 谱面
            # 「/geki 网页绑定」「/geki 绑定」不带参数 → 绑定指南图 + 链接（网页上预选音击）
            if first.lower() in WEB_BIND_WORDS or (first.lower() in BIND_GUIDE_WORDS and not rest.strip()
                                                   and self.bindweb_ready()):
                return await self._web_bind_reply(event, ctx, game)
            return await self.geki.handle(ctx, argline)
        if game == "core":
            return await self._core(event, ctx, argline)
        if game in ("sdvx", "pjsk", "chart"):           # sdvx.in chart views (no scores for these)
            return await self.charts.handle(ctx, argline, game)
        if first.lower() in WEB_BIND_WORDS:
            return await self._web_bind_reply(event, ctx, game)
        if first.lower() in CU.UPDATE_WORDS:            # 「/mai 更新」「/chu 更新 国服」：国服成绩怎么更新
            return await self._cn_update(ctx, game, rest)
        # 「/mai 绑定」「/chu 绑定」「/chu 绑定教程」不带参数 → 绑定指南图 + 链接（写了区服 / 凭据的照旧走指令绑定）
        if first.lower() in BIND_GUIDE_WORDS and not rest.strip() and self.bindweb_ready():
            return await self._web_bind_reply(event, ctx, game)
        if first.lower() in CHART_SUBS:
            if game == "chu":
                return await self.charts.handle(ctx, rest, "chu")
            return Reply().say("sdvx.in 没有舞萌的谱面确认。可以查：/chu 谱面 <歌>、/geki 谱面 <歌>、/sdvx 谱面 <歌>、/pjsk 谱面 <歌>")
        self.prefs.set_last_game(ctx.uid, game)
        handler = self.cmd if game == "mai" else self.chu
        return await handler.handle(ctx, argline)

    # ---------- 版本进度核实 ----------
    def _chu_augment(self, db) -> None:
        self._chu_aug = augment_songdb(db, self.progress)
        if self._chu_aug.get("added") or self._chu_aug.get("intl"):
            logger.info(f"[otoge] chu 曲库补充：{self._chu_aug}")
        self._apply_chu_consts()

    # ---------- 定数中心 ----------
    def _register_const_sources(self) -> None:
        from .chuni.cn import DF_MUSIC
        from .core.progress import OTOGE_DB
        from .chuni.songdb import TACHI_CHARTS
        H, S = self.consts_hub, CH.Source
        chu = os.path.join(self.root, "chu", "songdb")
        prog = os.path.join(self.root, "progress")
        zeta = "https://dp4p6x0xfi5o9.cloudfront.net"
        lx = "https://maimai.lxns.net/api/v0"

        def otoge_ids():
            return {CH.norm_title(x.get("title")): int(x["id"]) for x in self.progress.otoge.get("chu") or []
                    if str(x.get("id", "")).isdigit()}
        for src in (
            S("reiwa", "chu", "jp", "https://reiwa.f5.si/chunithm_record.json", CH.parse_reiwa_chu, "reiwa_chu.json"),
            S("otoge-db 中二", "chu", "jp", OTOGE_DB["chu"], CH.parse_otoge_chu, "otogedb_chu.json",
              os.path.join(prog, "otogedb_chu.json")),
            S("beerpsi", "chu", "jp", "https://chunithm.beerpsi.cc/songs", CH.parse_beerpsi_chu, "beerpsi_chu.json",
              os.path.join(chu, "beerpsi-songs.json")),
            S("zetaraku 中二", "chu", "jp", f"{zeta}/chunithm/data.json", CH.make_zeta_parser("chu", "jp", otoge_ids),
              "zeta_chu.json"),
            S("Tachi 日服", "chu", "jp", TACHI_CHARTS, CH.make_tachi_parser("jp"), "tachi_chu.json",
              os.path.join(chu, "tachi-charts.json")),
            S("Tachi 国际服", "chu", "intl", TACHI_CHARTS, CH.make_tachi_parser("intl"), "tachi_chu.json",
              os.path.join(chu, "tachi-charts.json")),
            S("落雪 中二", "chu", "cn", f"{lx}/chunithm/song/list?notes=false", CH.parse_lx_chu, "lx_chu.json",
              os.path.join(chu, "lxns-chunithm-songs.json")),
            S("水鱼 中二", "chu", "cn", DF_MUSIC, CH.parse_df_chu, "df_chu.json", os.path.join(chu, "df-chu-music.json")),
            S("otoge-db 舞萌", "mai", "jp", OTOGE_DB["mai"], CH.parse_otoge_mai, "otogedb_mai.json",
              os.path.join(prog, "otogedb_mai.json")),
            S("zetaraku 舞萌", "mai", "jp", f"{zeta}/maimai/data.json", CH.make_zeta_parser("mai", "jp"), "zeta_mai.json"),
            S("落雪 舞萌", "mai", "cn", f"{lx}/maimai/song/list?notes=false", CH.parse_lx_mai, "lx_mai.json",
              self.service.lx_songs.path),
            S("水鱼 舞萌", "mai", "cn", "https://www.diving-fish.com/api/maimaidxprober/music_data", CH.parse_df_mai,
              "df_mai.json"),
        ):
            H.register(src)

    def _consts_plan(self) -> dict:
        """每个游戏 / 区服的来源优先顺序（前面的说了算，后面的只补缺）。"""
        st = self.progress.state
        ci, cj = st.get("chu", "intl"), st.get("chu", "jp")
        same = bool(ci and cj and ci.current and ci.current == cj.current)
        chu_jp = ["reiwa", "otoge-db 中二", "beerpsi", "zetaraku 中二", "Tachi 日服"]
        return {
            ("chu", "jp"): chu_jp,
            # 国际服跟日服同版本时定数一样 → 用日服最新的；国际服落后时只信 Tachi 的国际服标签
            ("chu", "intl"): (chu_jp + ["Tachi 国际服"]) if same else ["Tachi 国际服"],
            ("chu", "cn"): ["落雪 中二", "水鱼 中二"],
            ("mai", "jp"): ["otoge-db 舞萌", "zetaraku 舞萌"],
            ("mai", "cn"): ["落雪 舞萌", "水鱼 舞萌"],
        }

    def _apply_chu_consts(self) -> None:
        if self.__dict__.get("consts_hub") is not None and self.consts_hub.merged:
            self._const_stats["chu"] = apply_chu_consts(self.chu_svc, self.consts_hub.merged)

    def _apply_mai_consts(self, db) -> None:
        if self.__dict__.get("consts_hub") is not None and self.consts_hub.merged:
            self._const_stats["mai"] = apply_mai_consts(db, self.consts_hub.merged)
            if db is not None and self._const_stats["mai"].get("cn_new"):
                db.set_version_override(self.catalog.effective_versions())   # 国服可玩曲变了 → 重新判断国服版本

    def _rebuild_consts(self) -> None:
        self.consts_hub.build(self._consts_plan())
        self._apply_chu_consts()
        self._apply_mai_consts(self.catalog.db)

    def _apply_progress(self) -> None:
        st = self.progress.state
        mai_auto = {r: rp.current for r in ("jp", "intl") if (rp := st.get("mai", r)) and rp.current}
        self.catalog.set_auto_versions(mai_auto)
        for r in ("jp", "intl"):
            if (rp := st.get("chu", r)) and rp.current:
                self.chu_svc.version_hint[r] = rp.current

    def _catalog_versions(self) -> dict:
        from .chuni.songdb import TACHI_VERSION_NAMES
        cat = {}
        if self.catalog.db is not None:
            for r in ("jp", "intl"):
                cat[("mai", r)] = self.catalog.db.detected_version(r)
        cat[("chu", "intl")] = self.chu_svc.songdb.current_version or ""
        tag = self.chu_svc.consts.jp_version or ""
        cat[("chu", "jp")] = TACHI_VERSION_NAMES.get(tag, tag.upper() if tag else "")
        return cat

    STARTUP_MAX_AGE_H = 6      # 启动时：6 小时内下载过的曲库 / 曲目表 / 定数表直接用，不重新下载

    async def _progress_check(self, download: bool = True, notify: bool = True, max_age_hours: float | None = None):
        st = await self.progress.refresh(self._catalog_versions(),
                                         mai_versions=self.catalog.db.versions if self.catalog.db else None,
                                         download=download, max_age_hours=max_age_hours)
        self._apply_progress()
        if self.chu_svc.songdb.songs:            # 新下载的 otoge-db / 官方曲目表 → 马上补进已加载的曲库
            self._chu_augment(self.chu_svc.songdb)
            self.chu_svc.songdb.reindex()
        if download:
            await self.consts_hub.download(max_age_hours)
        self._rebuild_consts()
        logger.info(f"[otoge] 定数合并：{self._const_stats}")
        logger.info("[otoge] 版本进度：" + "；".join(f"{k} {v.current}" for k, v in st.regions.items()))
        if notify and st.changes:
            await self._notify_owners("【版本进度更新】\n" + "\n".join(st.changes)
                                      + "\n曲库和定数已经按新版本处理了；发「/查分 进度」看详情")
        return st

    def _remember_owner_chat(self, event: AstrMessageEvent) -> None:
        """主人私聊过我：记下私聊会话，版本有变化时私聊通知。"""
        try:
            umo = str(event.unified_msg_origin)
        except Exception:  # noqa: BLE001
            return
        d = self.prefs.d
        if d.get("owner_umo", {}).get(str(event.get_sender_id())) != umo:
            d.setdefault("owner_umo", {})[str(event.get_sender_id())] = umo
            self.prefs._save()

    async def _notify_owners(self, text: str) -> None:
        for qq, umo in (self.prefs.d.get("owner_umo") or {}).items():
            if qq not in self._owner_ids():
                continue
            try:
                await self._notify_private(umo, text)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[otoge] 通知主人失败：{e}")

    def _progress_data(self) -> PG.ProgressView:
        """版本进度：文字版和图片版共用的一份数据。"""
        st = self.progress.state
        names = {"jp": "日服", "intl": "国际服"}
        when = time.strftime("%m-%d %H:%M", time.localtime(st.at)) if st.at else "还没核实过"
        v = PG.ProgressView(when=when, hour=int(self._cfg("daily_refresh_hour", 12)), changes=list(st.changes or []))
        for game, title in (("mai", "舞萌 DX"), ("chu", "中二节奏")):
            rows: list[PG.ProgressRow] = []
            for r in ("jp", "intl"):
                rp = st.get(game, r)
                if rp is None:
                    continue
                ev, warn = [], ""
                if rp.official:
                    ev.append(f"官方曲目表 {rp.official_new} 首 {rp.official}")
                if rp.timeline:
                    ev.append(f"公告 {rp.timeline}")
                if rp.catalog:
                    ev.append(f"曲库 {rp.catalog}")
                    if rp.catalog != rp.current:
                        warn = "曲库还停在 " + rp.catalog + ("，新歌已从 otoge-db 补上" if game == "chu" else "")
                num = getattr(rp, "code", "") if game == "mai" else CHU_VERSION_NUMBERS.get(rp.current, "")
                rows.append(PG.ProgressRow(names[r], rp.current or "?", num, " · ".join(ev) or "没有资料", warn))
            if game == "mai" and self.catalog.db is not None:
                lx = self.service.lx_songs
                if not lx.newest:
                    lx.load_cached()
                rows.append(PG.ProgressRow("国服", self.catalog.db.current_version.get("cn") or "?",
                                           str(lx.newest) if lx.newest else "", "DXRating 曲库 · 落雪曲目表"))
            if game == "chu":
                lx = self.chu_svc.lx_songs
                if not lx.newest:
                    lx.load_cached()
                rows.append(PG.ProgressRow("国服", self.chu_svc.cn_version or "?",
                                           str(lx.newest) if lx.newest else "", "落雪 / 水鱼"))
            v.games.append((title, rows))
        v.games.append(("私服（MuNET / RinNET / AquaDX）", [PG.ProgressRow(
            "私服", "跟着玩家自己的客户端版本", "",
            "定数、新旧曲、AP 加分都按玩家最后上机用的客户端版本算，B50 图页头会标 Ver.x.xx")]))
        a = self._chu_aug or {}
        if a:
            v.sections.append(("中二曲库补充", [f"曲库里有 {a.get('total', a.get('added', 0))} 首是从 otoge-db 补进来的"
                                               + (f"，这次标国际服 {a['intl']} 首" if a.get("intl") else "")]))
        cl = []
        for (g, r), title in ((("chu", "jp"), "中二日服"), (("chu", "intl"), "中二国际服"), (("chu", "cn"), "中二国服"),
                              (("mai", "jp"), "舞萌日服（补缺）"), (("mai", "cn"), "舞萌国服")):
            if (sm := self.consts_hub.summary(g, r)):
                cl.append(f"· {title}：{sm}")
        if cl:
            cs, ms = self._const_stats.get("chu") or {}, self._const_stats.get("mai") or {}
            cl.append(f"本次写回：中二日服 {cs.get('jp', 0)} / 国际服 {cs.get('intl', 0)} / 国服 {cs.get('cn', 0)} 张，"
                      f"舞萌国服 {ms.get('cn', 0)} / 日服补 {ms.get('jp', 0)} 张"
                      + (f"；舞萌 {ms['cn_new']} 张谱面按落雪 / 水鱼补标为国服已上线" if ms.get("cn_new") else ""))
            v.sections.append(("定数（多来源合并，前面的来源优先）", cl))
        v.sources = [f"{k} {val}" for k, val in (st.sources or {}).items()]
        if self.catalog.db is not None and self.catalog.db.updated_at:
            v.sources.append(f"DXRating 曲库 {str(self.catalog.db.updated_at)[:16].replace('T', ' ')}（UTC）")
        return v

    def _progress_text(self) -> str:
        return PG.text(self._progress_data())

    async def _progress_reply(self, prefix: str = "") -> Reply:
        """版本进度图；画不出来就发文字版。"""
        v = self._progress_data()
        try:
            img = await asyncio.to_thread(PG.render, v, self.bot_name, None)
            r = Reply(image=img)
            if prefix:
                r.say(prefix)
            return r
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] progress image failed: {e}")
            return Reply().say((prefix + "\n" if prefix else "") + PG.text(v))

    # ---------- /查分 ----------
    def _owner_ids(self) -> set[str]:
        """机器人主人：AstrBot 全局「管理员 ID」(admins_id) + 本插件配置 owner_qq（备用）。"""
        ids: set[str] = set()
        try:
            ids |= {str(x).strip() for x in (self.context.get_config().get("admins_id") or []) if str(x).strip()}
        except Exception:  # noqa: BLE001
            pass
        extra = self._cfg("owner_qq", "") or ""
        if isinstance(extra, (list, tuple)):
            ids |= {str(x).strip() for x in extra if str(x).strip()}
        else:
            ids |= {x for x in re.split(r"[\s,，;；]+", str(extra)) if x}
        ids.discard("astrbot")      # AstrBot 的默认占位值
        return ids

    async def _theory_overview(self) -> Reply:
        """/查分 理论：舞萌、中二三个服的理论最高 Rating 一起列出来（当前版本每张都满分，不用绑定）。"""
        names = {"intl": "国际服", "jp": "日服", "cn": "国服"}
        lines = ["理论 Rating（当前版本每张谱面都满分，不用绑定）", "", "舞萌 DX（全部 SSS+ · AP+，B35 + B15）"]
        for r in ("intl", "jp", "cn"):
            try:
                b = await asyncio.to_thread(self.cmd.theory, r)
                if not b.old and not b.new:
                    raise LookupError("曲库还没加载好")
                v = self.cmd.db.current_version.get(r) or ""
                lines.append(f"· {names[r]}{' ' + v if v else ''}：{b.total}（B35 {b.old_total} + B15 {b.new_total}）")
            except Exception as e:  # noqa: BLE001
                lines.append(f"· {names[r]}：暂时算不出（{e or type(e).__name__}）")
        lines += ["", "中二节奏（全部 1,010,000 · AJC，旧曲 B30 + 新曲 N20）"]
        for sv in ("intl", "jp", "cn"):
            try:
                b, cur = await asyncio.wait_for(self.chu.theory(sv), 90)
                if not b.best and not b.new:
                    raise LookupError("曲库还没加载好")
                lines.append(f"· {names[sv]}{' ' + cur if cur else ''}：{b.total}"
                             f"（旧曲平均 {b.best_avg} · 新曲平均 {b.new_avg}）")
            except Exception as e:  # noqa: BLE001
                lines.append(f"· {names[sv]}：暂时算不出（{e or type(e).__name__}）")
        lines += ["", "看图：/mai 理论 日服　/chu 理论 国服（不写区服 = 国际服）"]
        return Reply().say("\n".join(lines))

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        return event.is_admin() or str(event.get_sender_id()) in self._owner_ids()

    async def _core(self, event: AstrMessageEvent, ctx: Ctx, argline: str) -> Reply:
        args = argline.split()
        sub = args[0].lower() if args else ""
        if sub in WEB_BIND_WORDS:
            return await self._web_bind_reply(event, ctx)
        if sub in ("账号", "我的账号", "account", "绑定"):
            return Reply().say(self.accounts_text(ctx.uid))
        if sub in CL.WORDS:                                  # /查分 更新记录 [全]
            full = len(args) > 1 and args[1] in ("全", "全部", "all", "完整")
            return Reply().say(CL.text(CL.load(), None if full else 3))
        if sub in ("llm", "自然语言", "ai"):
            gid = event.get_group_id() or None
            where = f"本群（{gid}）" if gid else "私聊"
            if len(args) < 2 or args[1] in ("状态", "status"):
                on = self.prefs.llm_enabled(gid)
                return Reply().say(f"{where}自然语言查分：{'开' if on else '关'}\n机器人主人可以发「/查分 llm 开」或「/查分 llm 关」")
            if not self._is_owner(event):
                if not self._owner_ids():
                    return Reply().say("只有机器人主人能改这个开关，但 AstrBot 还没设置主人：在 WebUI「配置文件 → 其他配置 → "
                                       "管理员 ID」里加上主人的 QQ（或者填本插件配置里的 owner_qq）")
                return Reply().say("只有机器人主人能改这个开关")
            on = args[1] in ("开", "on", "开启", "1", "true")
            self.prefs.set_llm(gid, on)
            return Reply().say(f"{where}自然语言查分已{'开启' if on else '关闭'}"
                               + ("：@我 说「帮我看下舞萌 b50」就行（会用到大模型）" if on else "，只响应指令"))
        if sub in THEORY_WORDS:
            return await self._theory_overview()
        if sub in ("进度", "版本", "版本进度", "曲库", "数据", "progress"):
            if len(args) > 1 and args[1] in ("文字", "text", "txt"):
                return Reply().say(self._progress_text())
            return await self._progress_reply()
        if sub in ("更新曲库", "刷新曲库", "更新数据", "核实进度", "update"):
            if not self._is_owner(event):
                return Reply().say("只有机器人主人能手动更新曲库（每天会自动更新）。看进度发「/查分 进度」")
            await self._refresh_all_data()
            return await self._progress_reply("已经重新下载曲库、定数和官方曲目表")
        if sub in ("区服", "server"):
            return Reply().say("区服写在指令最后：国际服 / 日服 / 国服 / munet / rin / aqua（私服）。\n"
                               "例：/mai b50 日服　/chu b50 国服　/mai b50 munet　/chu b50 rin　/mai 查歌 救护车 日服\n"
                               "不写时默认查你上一次查的那个服；定数默认按国际服显示。")
        return await self._help_reply()

    def accounts_text(self, uid: str) -> str:
        lines = ["你的账号："]
        mai_bound = self.service.bound_regions(uid)
        chu_bound = self.chu.bound(uid)
        for game, bound in (("mai", mai_bound), ("chu", chu_bound)):
            if not bound:
                lines.append(f"· {GAME_NAMES[game]}：没绑定")
                continue
            last = self.prefs.last(uid, game)
            default = last if last in bound else bound[0]
            def label(s, game=game):
                if s in PRIV_NAMES:
                    return f"{PRIV_NAMES[s]}（{self.priv.bindings.get(uid, s)}）"
                if s != "cn":
                    return SERVER_NAMES[s]
                src = (self.service.cn_source(self.store.get_creds(uid, "cn")) if game == "mai"
                       else self.chu_svc.cn_source(uid))
                lx = src in ("lx", "lxqq")
                if not lx:
                    return "国服（水鱼）"
                up = self.service.cn_uploaded_at(uid) if game == "mai" else self.chu_svc.cn_uploaded_at(uid)
                when, _stale = CU.age_text(up, str(self._cfg("timezone", "Asia/Shanghai")))
                return "国服（落雪" + (" · 按 QQ" if src == "lxqq" else "") + (f" · {when}" if when else "") + "）"
            lines.append(f"· {GAME_NAMES[game]}：" + "、".join(label(s) + ("（默认）" if s == default else "")
                                                         for s in bound))
        lines.append("查别的服在指令后加区服，例如「/mai b50 日服」；绑定发「/网页绑定」")
        if any("国服" in ln for ln in lines):
            lines.append("国服成绩是查分器里存的那份，要自己传上去：发「/mai 更新」「/chu 更新」看怎么传")
        return "\n".join(lines)

    # ---------- guard: before everything (chat history, memory, LLM) ----------
    def _other_plugin_command(self, event: AstrMessageEvent) -> bool:
        """Another plugin registered this exact command (e.g. someone else's /b50) → leave it alone."""
        try:
            handlers = event.get_extra("activated_handlers") or ()
        except Exception:  # noqa: BLE001
            return False
        for h in handlers:
            mod = str(getattr(h, "handler_module_path", "") or "")
            if mod.startswith(PLUGIN) or mod.startswith(__name__.rsplit(".", 1)[0]):
                continue
            if any("Command" in type(f).__name__ for f in getattr(h, "event_filters", ()) or ()):
                return True
        return False

    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize)
    async def guard(self, event: AstrMessageEvent):
        text = event.get_message_str() or ""
        raw = str(getattr(event.message_obj, "message_str", "") or text)
        # 「@机器人 /查分 llm 开」里的 @ 有时只是打出来 / 复制来的文字（不是真 @）：后面紧跟指令就照样认
        text, raw = _PLAIN_AT.sub("", text, count=1), _PLAIN_AT.sub("", raw, count=1)
        slash = raw.lstrip()[:1] in ("/", "／")
        ctx = self._ctx(event)
        if ctx.private and self._is_owner(event):
            self._remember_owner_chat(event)
        lx_secret = looks_like_lxns_secret(text)
        pw_secret = looks_like_password_bind(text)
        secret = looks_like_clal(text) or chu_redact.contains_clal(text) or lx_secret or pw_secret
        if not ctx.private and secret and (self._which(text) or not slash):
            event.should_call_llm(True)
            event.stop_event()
            await self._recall(event)
            if pw_secret:
                yield event.plain_result("群里别发密码！我试着撤回了；保险起见去改一下那个账号的密码。"
                                         "绑定发「/网页绑定」在网页上填；RinNET 私聊我发「/mai 绑定 rin」看用法。")
            elif lx_secret and not (looks_like_clal(text) or chu_redact.contains_clal(text)):
                yield event.plain_result("群里别发落雪密钥！我试着撤回了；保险起见去落雪网站重新生成一个。"
                                         "绑定发「/网页绑定」，拿链接在网页上填。")
            else:
                yield event.plain_result("群里别发 clal！我试着撤回了；保险起见去 NET 退出登录一次让它失效。"
                                         "绑定发「/网页绑定」，拿链接在网页上填。")
            return
        r = await self.cmd.on_flow_message(ctx, text) if ctx.private else None   # mai SEGA ID / password steps
        if r is None and self._cfg("games_enabled", True):
            # 猜歌小游戏：开局要像别的指令一样带「/」（或 @ / 私聊）；局里的「开 a」「提示」和猜对的歌名不用
            try:
                r = await self.games.handle(event.unified_msg_origin, ctx, text,
                                            command=ctx.private or slash or bool(event.is_at_or_wake_command))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[otoge] game message failed: {type(e).__name__}: {e}")
                r = None
        if r is None:
            body = text.lstrip().lstrip("/／")         # AstrBot already strips the wake prefix; tests may not
            rt = route(("/" + body) if slash else body, last_game=self.prefs.last_game(ctx.uid))
            if rt is not None and rt.how == "bare" and self._other_plugin_command(event):
                rt = None
            if rt is not None and not ctx.private and not (slash or event.is_at_or_wake_command):
                rt = None
            if rt is not None and rt.how == "plain" and not await self._plain_song_ok(rt):
                rt = None          # 「舞萌 查 一下吧」: no slash and no real song → it was chat
            if rt is not None:
                r = await self._dispatch(event, rt.game, rt.argline)
                if rt.how == "typo":
                    r.texts.insert(0, f"（按「/{CMD_NAME[rt.game]}」理解了）")
                elif rt.how == "bare" and rt.game in ("mai", "chu"):
                    other = "chu" if rt.game == "mai" else "mai"
                    r.say(f"（按你上次查的{GAME_NAMES[rt.game]}查的；查{GAME_NAMES[other]}发「/{CMD_NAME[other]} "
                          f"{rt.argline}」）")
        if r is None and ctx.private and pw_secret:
            r = Reply(recall=True).say("这条好像带着账号密码，我没处理也没记下来。绑定发「/网页绑定」在网页上填最安全")
        if r is None and ctx.private and lx_secret:
            # a 落雪 key that is not a clean bind command must still never reach the chat model / memory
            r = Reply().say("这看起来像落雪的个人 API 密钥。绑定请发「/mai 绑定 落雪 <密钥>」或「/chu 绑定 落雪 <密钥>」")
        if r is not None:
            event.should_call_llm(True)      # commands never reach the chat model …
            event.stop_event()               # … nor the companion / memory plugins below us
            async for out in self._emit(event, r):
                yield out

    # ---------- commands ----------
    async def _run_cmd(self, event: AstrMessageEvent, game: str):
        event.should_call_llm(True)
        which = self._which(event.get_message_str() or "")
        r = await self._dispatch(event, game, which[1] if which else "")
        async for out in self._emit(event, r):
            yield out
        event.stop_event()

    # Entry points kept for tests / internal use. They are deliberately NOT registered as AstrBot commands:
    # the guard above answers every real command at the highest priority, and a registered command filter
    # would also claim chat like 「中二 我 打不过」, so the companion plugin would stay silent on it.
    async def mai(self, event: AstrMessageEvent):
        async for out in self._run_cmd(event, "mai"):
            yield out

    async def chuni(self, event: AstrMessageEvent):
        async for out in self._run_cmd(event, "chu"):
            yield out

    async def score(self, event: AstrMessageEvent):
        async for out in self._run_cmd(event, "core"):
            yield out

    # ---------- natural language (per-group switch, default off) ----------
    async def _llm_call(self, event: AstrMessageEvent | None):
        provider_id = str(self._cfg("nl_provider_id", "") or "").strip()
        if not provider_id:
            try:
                if event is not None:
                    provider_id = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
                else:
                    prov = self.context.get_using_provider()
                    provider_id = prov.meta().id if prov else ""
            except Exception:  # noqa: BLE001
                return None
        if not provider_id:
            return None
        timeout = float(self._cfg("nl_timeout", 15))

        async def call(system: str, text: str) -> str:
            resp = await asyncio.wait_for(self.context.llm_generate(
                chat_provider_id=provider_id, system_prompt=system, prompt=text), timeout=timeout)
            return resp.completion_text or ""
        return call

    @filter.event_message_type(filter.EventMessageType.ALL, priority=9000)
    async def natural_language(self, event: AstrMessageEvent):
        text = (event.get_message_str() or "").strip()
        if (not text or self._which(text) or looks_like_clal(text) or chu_redact.contains_clal(text)
                or looks_like_lxns_secret(text) or looks_like_password_bind(text)):
            return
        gid = event.get_group_id() or None
        if not self.prefs.llm_enabled(gid):
            return                                  # 默认关闭：不调用大模型，交给别的插件 / 正常聊天
        if self._cfg("nl_require_wake", True) and gid and not event.is_at_or_wake_command:
            return
        it = await NL.classify(text, await self._llm_call(event), addressed=True,
                               rules_first=bool(self._cfg("nl_rules_first", True)))
        if it.action == "none" or it.game == "other":
            logger.info(f"[otoge] NL 没当成查询：{text[:40]!r} → {it.action}/{it.game}（{it.source}）")
            return
        if it.action == "theory" and it.game == "unknown":
            it.game = "core"            # 没说游戏：舞萌、中二六个服一起列
        uid = str(event.get_sender_id())
        game, extra = it.game, ""
        if game == "unknown" and it.action == "song":
            game, extra = await self._song_game(uid, it.query)   # nicknames decide: 6A景区 → 舞萌, 反叛 → 中二
        if it.action == "song" and not it.explicit:
            # the model thought this was about a song; only answer if the name clearly is one, never guess
            if game not in ("mai", "chu") or self._confident_song(game, it.query) is None:
                logger.info(f"[otoge] NL song {it.query!r} not clear enough, left to chat")
                return
        if game == "unknown" and it.action != "theory":
            game = self.prefs.last_game(uid) or ("chu" if self.chu.bound(uid) and not self.store.bound_regions(uid)
                                                 else "mai")
        logger.info(f"[otoge] NL → {game} {it.action} {it.query!r} {it.server}（{it.source}）")
        event.should_call_llm(True)
        event.stop_event()
        if it.action == "help":
            r = await self._help_reply()
        elif game == "none":
            r = Reply().say(f"舞萌和中二的曲库里都没找到「{it.query}」😵 试试歌名的一部分或者别的外号；"
                            f"知道是哪首的话可以发「/mai 加别名 {it.query} 歌名」教我")
        else:
            r = await self._dispatch(event, game, NL.to_command(it))
            if extra:
                r.say(extra)
        async for out in self._emit(event, r):
            yield out

    async def _plain_song_ok(self, rt) -> bool:
        """No-slash 「中二 查 xx」 only counts when xx clearly names one song."""
        words = rt.argline.split()
        if rt.game == "geki" and words and words[0].lower() not in SONG_SUBS:
            return True                       # 「音击 b50」
        if rt.game in ("sdvx", "pjsk", "geki"):
            if words and words[0].lower() in SONG_SUBS:
                words = words[1:]
            return self._confident_chart(rt.game, " ".join(words))
        if not words or words[0].lower() not in SONG_SUBS:
            return True
        q = " ".join(w for w in words[1:] if w not in ("国际服", "日服", "国服"))
        return self._confident_song(rt.game, q) is not None

    def _confident_chart(self, game: str, query: str) -> bool:
        """No-slash 「sdvx 谱面 xx」: only when the cached sdvx.in list clearly has xx (never a guess)."""
        from .chart.commands import split_diff
        _k, rest = split_diff(game, query.split())
        q = " ".join(rest)
        if not q or not self.charts.src.entries.get(game):
            return False
        ms = self.charts.src.index(game).search(q, 4)
        d = decide(ms, q)
        return d.item is not None and not d.note and bool(ms) and ms[0].score >= 80

    def _confident_song(self, game: str, query: str):
        """The song a name / nickname clearly means (exact or prefix match, no guessing), else None."""
        if not query.strip():
            return None
        db = self.catalog.db if game == "mai" else self.chu_svc.songdb
        ms = db.search_ranked(query, 6)
        d = decide(ms, query)
        if game == "chu" and d.item is None and (reg := pick_regular(d.choices)) is not None:
            return reg[0]
        if d.item is None and (pk := alias_pick(d.choices, skip=_is_we if game == "chu" else None)) is not None:
            return pk[0]          # one nickname, several songs → the hardest (same as the commands)
        if d.item is None or d.note or not ms or ms[0].score < 80:
            return None
        return d.item

    async def _song_game(self, uid: str, query: str) -> tuple[str, str]:
        """Which game a bare song name / nickname belongs to → (game | "none", hint about the other game)."""
        try:
            await self.chu._ensure_catalog()
        except Exception:  # noqa: BLE001
            pass
        tops, lists = {}, {}
        for g, ms in (("mai", self.catalog.db.search_ranked(query, 6)), ("chu", self.chu_svc.songdb.search_ranked(query, 6))):
            if ms:
                tops[g], lists[g] = ms[0], ms
        if not tops:
            return "none", ""
        last = self.prefs.last_game(uid)
        # a nickname that clearly means ONE song in a game beats one that is ambiguous there
        clear = {g: self._confident_song(g, query) is not None for g in tops}
        game = max(tops, key=lambda g: (clear[g], tops[g].score, g == last))
        other = "chu" if game == "mai" else "mai"
        hint = ""
        if other in tops and tops[other].score >= 80:
            cmd = f"/{CMD_NAME[other]} {'查' if other == 'chu' else '查歌'} {query}"
            strong = [m for m in lists[other] if m.score >= 80]
            if clear[other]:
                hint = f"（{GAME_NAMES[other]}里「{query}」是 {tops[other].item.title}，发「{cmd}」）"
            elif strong:
                names = " / ".join(m.item.title for m in strong[:3])
                hint = f"（{GAME_NAMES[other]}里「{query}」也可能是：{names}，发「{cmd}」看）"
        return game, hint

    # ---------- daily refresh ----------
    async def _refresh_aliases(self, force: bool = False) -> None:
        """Nickname lists (落雪 / Yuzuchan) for both games; a failed download keeps the old list."""
        for store, apply in ((self.mai_aliases, self.catalog.set_aliases),
                             (self.chu_aliases, self.chu_svc.songdb.apply_aliases)):
            try:
                await store.refresh(force=force)
                apply(store.merged())
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[otoge] alias refresh ({store.game}) failed: {e}")
        logger.info(f"[otoge] aliases mai {self.mai_aliases.status} · chu {self.chu_aliases.status}")

    async def _refresh_all_data(self) -> None:
        for name, coro in (("mai", self.catalog.refresh()), ("chu", self.chu_svc.refresh_data())):
            try:
                await coro
                logger.info(f"[otoge] {name} data refresh ok")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[otoge] {name} data refresh failed: {e}")
        try:
            await self._progress_check()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] 版本进度核实失败：{e}")

    async def _mai_refresh_loop(self):
        await asyncio.sleep(5)
        await self._refresh_aliases()
        try:
            await self.catalog.refresh(max_age_hours=self.STARTUP_MAX_AGE_H)
            logger.info(f"[otoge] mai catalog ready from {self.catalog.source}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] mai catalog refresh failed: {e}")
        try:
            await self._progress_check(max_age_hours=self.STARTUP_MAX_AGE_H)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] 版本进度核实失败：{e}")
        hour = int(self._cfg("daily_refresh_hour", 12))
        while True:
            now = dt.datetime.now()
            nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if nxt <= now:
                nxt += dt.timedelta(days=1)
            self.next_refresh = nxt
            self.chu_host.next_refresh = nxt
            await asyncio.sleep((nxt - now).total_seconds())
            try:
                await self._refresh_aliases(force=True)
                await self._refresh_all_data()
            except Exception as e:  # noqa: BLE001   任何一次失败都不能让每日刷新循环停掉
                logger.warning(f"[otoge] 每日刷新出错：{type(e).__name__}: {e}")

    async def _chu_refresh_loop(self):
        await asyncio.sleep(8)
        if self._cfg("auto_font", True):
            try:
                from .chuni.fonts import ensure_cjk_font
                await ensure_cjk_font(Path(self.root) / "chu", font_override=self.chu_svc.settings.font_path,
                                      proxy=self.chu_svc.settings.proxy)
            except Exception as e:  # noqa: BLE001
                logger.info(f"[otoge] chuni font check: {e}")
        try:
            await self.chu_svc.songdb.ensure_loaded()
            await self.chu_svc.consts.ensure_loaded()
            if self.chu_svc.settings.auto_logo:
                await self.chu_svc.theme.auto_logo(self.chu_svc.current_version)
            logger.info(f"[otoge] chuni catalog {self.chu_svc.songdb.source}, jp {len(self.chu_svc.consts.jp)}, "
                        f"cn {len(self.chu_svc.consts.cn)}")
        except Exception as e:  # noqa: BLE001
            logger.info(f"[otoge] chuni catalog load failed (retry on query): {e}")
