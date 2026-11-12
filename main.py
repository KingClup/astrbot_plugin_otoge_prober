"""AstrBot 插件：音游查分（舞萌 DX 国际服 / 日服 / 国服 + 中二节奏 国际服 / 日服 / 国服）。

  /mai …     舞萌 DX（别名 /maimai /舞萌）
  /chu …     中二节奏（别名 /chuni /中二）
  /查分 …    帮助图、我的账号、本群自然语言开关（别名 /score）
业务逻辑在 mai/、chuni/、core/ 里，这里只做 AstrBot 接入。
"""
from __future__ import annotations

import asyncio
import io
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
from .games import aliasvote as AV  # noqa: E402
from .games.invite import InviteWatcher, clamp_settings as invite_settings  # noqa: E402
from .core import aliaslib as AL  # noqa: E402
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
from .scorebook import service as SBS  # noqa: E402
from .scorebook.service import ScoreBook  # noqa: E402
from .scorebook.web import ScoreWeb  # noqa: E402
from .core import cnupdate as CU  # noqa: E402
from .core import changelog as CL  # noqa: E402
from .mai.bot.commands import split_args as mai_split_args  # noqa: E402
from .chuni.commands import split_server as chu_split_server  # noqa: E402
from .core.imgcache import ImageCache  # noqa: E402
from .core.privsrv import Hub as PrivHub, NAMES as PRIV_NAMES  # noqa: E402
from .core.privsrv.servers import rom_label  # noqa: E402

PLUGIN = "astrbot_plugin_otoge_prober"
VERSION = "2.4.5"
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
LX_BIND_WORDS = ("落雪", "lxns", "luoxue", "落雪查分器", "水鱼", "divingfish", "df")
UNBOUND_MARKS = ("你还没绑定", "你还没有绑定", "还没绑定", "还没有绑定")


def bind_without_creds(game: str, rest: str) -> bool:
    """「/mai 绑定 国服」「/chu 绑定 日服」「/mai 绑定 落雪」「/geki 绑定 aqua」：只写了区服 / 方式、没给用户名或凭据。"""
    words = [w for w in rest.split() if w.lower() not in LX_BIND_WORDS]
    if game == "geki":
        return all(w.lower() in ("aqua", "aquadx", "munet", "rin", "rinnet", "私服") for w in words)
    try:
        _, left = (mai_split_args if game == "mai" else chu_split_server)(words)
    except Exception:  # noqa: BLE001
        return False
    return not left


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
        # 传分本（SDVX / 音击官服手动传分 + 传分网站）
        self.scorebook = ScoreBook(root, proxy=self._cfg("proxy", "") or None, geki_db=self.geki.db)
        self.scorebook.sdvxin = self.charts.src
        from .ongeki.official import GekiOfficial
        self.scorebook.prefs = self.prefs
        self.geki.prefs = self.prefs
        self.geki_official = GekiOfficial(os.path.join(root, "geki_official"), self.scorebook,
                                          proxy=self._cfg("proxy", "") or None)          # 音击官服 SEGA ID 自动查
        self.games = GameCommands(GameData(self), last_game=self.prefs.last_game,
                                  help=lambda: self._help_reply("games"))   # 开字母 / 猜曲绘 / 猜谱面
        # 别名收集：有人用原名猜中 → 回看这局没猜中的短消息 → 大模型挑像外号的 → 群里投票
        self._alias_live = self._alias_live_load(root)        # WebUI 里改的别名设置（不用重载，马上生效）
        self.alias_votes = AV.AliasVotes(root, yes=int(self._acfg("alias_vote_yes", 3) or 3),
                                         no=int(self._acfg("alias_vote_no", 2) or 2),
                                         minutes=float(self._acfg("alias_vote_minutes", 10) or 10))
        self._alias_checks: dict[str, list[float]] = {}
        self.games.on_message_log = self._alias_log
        self.invite = InviteWatcher()                  # 群里热闹时问一句要不要玩小游戏（每个群单独开，默认关）
        self._group_names_at = 0.0
        self.games.on_title_solve = self._alias_solved
        self.games.on_alias_solve = self._alias_solved_by_alias
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
        self._tasks.append(asyncio.create_task(self._scorebook_loop()))
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
        self.scorebook.sync_aliases()                   # sdvx.in 的外号也给传分网站搜歌用

    async def _scorebook_loop(self) -> None:
        """传分本曲库：SDVX 从 Tachi、音击从 otoge-db，每天拉一次（失败就用旧的 / 插件自带的）。"""
        await asyncio.sleep(90)
        while True:
            for game in ("sdvx", "geki"):
                try:
                    n = await self.scorebook.refresh(game)
                    logger.info(f"[otoge] 传分本曲库 {game}: {n} 首")
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[otoge] 传分本曲库 {game} 更新失败（继续用旧的）：{type(e).__name__}: {e}")
            await asyncio.sleep(3 * 3600)

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
        self.scoreweb = ScoreWeb(self.scorebook, bot_name=self.bot_name, log=logger.info)
        return BindWeb(Binder(self), host="127.0.0.1", port=port, bot_name=self.bot_name,
                       notify=self._notify_private, log=logger.info, extra=[self.scoreweb])

    async def _bindweb_start(self) -> None:
        if await self.bindweb.start():
            logger.info(f"[otoge] 网页绑定服务：http://127.0.0.1:{self.bindweb.port} → {self.bindweb_url() or '（还没配公网地址）'}")
        else:
            logger.warning(f"[otoge] 网页绑定服务没起来（端口 {self.bindweb.port}）：{self.bindweb.error}")

    # ---------- 热闹时邀请小游戏 ----------
    def _games_on(self) -> bool:
        v = self.prefs.games_enabled()
        return bool(self._cfg("games_enabled", True)) if v is None else v

    def _invite_cfg(self) -> dict:
        return invite_settings(self.prefs.invite_settings())

    def _invite_watch(self, event: AstrMessageEvent, ctx: Ctx, text: str) -> None:
        try:
            gid = str(event.get_group_id() or "")
            if not gid or not self.prefs.invite_enabled(gid) or not self._games_on():
                return
            umo = event.unified_msg_origin
            from datetime import datetime
            from zoneinfo import ZoneInfo
            try:
                local = datetime.now(ZoneInfo(str(self._cfg("timezone", "Asia/Shanghai"))))
            except Exception:  # noqa: BLE001
                local = datetime.now()
            line = self.invite.on_message(gid, ctx.uid, text, local, self._invite_cfg(),
                                          playing=umo in self.games.sessions, busy=self.alias_votes.busy(umo))
            if line:
                asyncio.create_task(self._invite_send(umo, line))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] invite check failed: {type(e).__name__}: {e}")

    async def _invite_send(self, umo: str, line: str) -> None:
        import random
        await asyncio.sleep(random.uniform(2, 6))     # 别紧贴着上一条，像是看了一眼才说
        if umo in self.games.sessions:
            return                                   # 这几秒里已经有人开局了
        try:
            await self._notify_private(umo, line)
            logger.info(f"[otoge] invited group {umo.rsplit(':', 1)[-1]} to a mini game")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] invite send failed: {type(e).__name__}: {e}")

    async def _refresh_group_names(self, force: bool = False) -> dict[str, str]:
        """从 QQ（OneBot get_group_list）读群名，10 分钟最多读一次；读不到就用上次存的。"""
        import time as _t
        if force or _t.time() - self._group_names_at > 600:
            self._group_names_at = _t.time()
            try:
                for inst in getattr(self.context.platform_manager, "platform_insts", []) or []:
                    get_client = getattr(inst, "get_client", None)
                    client = get_client() if callable(get_client) else None
                    if client is None or not hasattr(client, "call_action"):
                        continue
                    rows = await asyncio.wait_for(client.call_action("get_group_list"), timeout=8)
                    if isinstance(rows, dict):
                        rows = rows.get("data") or []
                    self.prefs.set_group_names({str(r.get("group_id")): str(r.get("group_name") or "")
                                                for r in rows or [] if isinstance(r, dict) and r.get("group_id")})
            except Exception as e:  # noqa: BLE001
                logger.info(f"[otoge] group names unavailable: {type(e).__name__}: {e}")
        return self.prefs.group_names()

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

    def _web_bind_confirm(self, ctx: Ctx, code: str) -> Reply:
        """「/网页绑定 确认 1234」：群里要的绑定链接，本人回网页上显示的确认码。"""
        if self.bindweb is None:
            return Reply().say("网页绑定没开。")
        if not "".join(ch for ch in code if ch.isdigit()):
            return Reply().say("把网页上的 4 位码带上：/网页绑定 确认 1234")
        st = self.bindweb.sessions.confirm(ctx.uid, code)
        return Reply().say({
            "ok": "确认好了，回到那个网页，几秒内就能往下填。网页被关掉 / 刷新了的话：用同一个浏览器再点一次那条链接。",
            "none": "你现在没有等确认的绑定链接（可能过期了，或者已经确认过）。重新发「/网页绑定」拿链接。",
            "wrong": "这个码不对。看一下你自己网页上显示的 4 位码再发一次（别人报给你的码不要发）。",
            "locked": "码错太多次，这条链接我作废了。重新发「/网页绑定」拿新的。",
        }[st])

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
        link = f"{url}/#t={token}" + (f"&g={game}" if game in ("mai", "chu", "geki", "sdvx") else "")
        if group:
            return Reply(at=ctx.uid).say(
                f"你的绑定链接（10 分钟内有效）：\n{link}"
                "\n点开后网页会显示一个 4 位确认码，你自己在 QQ 回「/网页绑定 确认 码」才能往下填"
                "（群里的链接谁都点得开，这一步是防别人替你绑）。只确认你自己屏幕上看到的码。"
                "嫌麻烦就私聊我发 /网页绑定，私聊的链接不用确认。")
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
        try:                                             # 重载 / 更新前：在玩的群先说一声、公布答案再走
            await asyncio.wait_for(self._announce_shutdown(), 15)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] shutdown notice failed: {type(e).__name__}: {e}")
        for t in self._tasks:
            t.cancel()
        if self.bindweb is not None:
            await self.bindweb.stop()
        chu_redact.uninstall()
        await self.chu_svc.close()
        await self.priv.close()

    # ---------- 重载前的告别 ----------
    SHUTDOWN_LINES = ("我要更新一下，马上回来～这局先停在这里，下次再玩！",
                      "要重启一下下，这局只能先到这里了，等我回来再开～",
                      "更新时间到！这局先暂停，重启完再来一局吧～")

    STICKER_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    STICKER_BYE = ("溜", "跑", "走了", "拜拜", "再见", "告辞", "下线", "睡", "晚安", "bye", "wave", "sorry",
                   "抱歉", "对不起", "离开", "撤", "润", "88")

    def _meme_roots(self) -> list[str]:
        """表情包管理器（meme_manager）的图库：新版在它自己的 plugin_data/…/packs/，旧版在数据目录的 memes/。"""
        data = os.path.dirname(os.path.dirname(os.path.abspath(getattr(self, "root", "") or ".")))
        return [p for p in (os.path.join(data, "memes"), os.path.join(data, "plugin_data", "meme_manager"),
                            os.path.join(data, "plugin_data", "astrbot_plugin_meme_manager")) if os.path.isdir(p)]

    def _pick_sticker_file(self) -> str | None:
        """从表情包管理器里挑一张：路径里带「溜了 / 再见 / 睡觉」这类再优先；
        都没有就随便一张；表情包管理器没装就返回 None（用看板娘那张）。"""
        import random
        fish: list[tuple[str, str]] = []
        other: list[tuple[str, str]] = []
        for root in self._meme_roots():
            for d, dirs, files in os.walk(root):
                dirs[:] = [x for x in dirs if x.lower() not in ("backup", "temp", "tmp", "semantic_indexes", "cache")]
                for f in files:
                    if f.lower().endswith(self.STICKER_EXT):
                        path = os.path.join(d, f)
                        rel = os.path.relpath(path, root).lower()
                        (fish if ("bye" in rel) else other).append((path, rel))
                if len(fish) + len(other) > 5000:
                    break
        pool = fish or other
        if not pool:
            return None
        bye = [p for p, rel in pool if any(w in rel for w in self.STICKER_BYE)]
        return random.choice(bye or [p for p, _ in pool])

    def _shutdown_sticker(self) -> tuple[str, str] | None:
        """(base64, 来源) —— 优先表情包管理器里的图，没有就用看板娘「溜了」那张（自用版才有）。"""
        import base64
        from PIL import Image
        pick = None
        try:
            pick = self._pick_sticker_file()
        except Exception as e:  # noqa: BLE001
            logger.info(f"[otoge] meme lookup failed: {type(e).__name__}: {e}")
        if pick:
            try:
                with open(pick, "rb") as f:
                    raw = f.read()
                if len(raw) <= 2 * 1024 * 1024:            # 表情包原样发（gif 也能动）
                    return base64.b64encode(raw).decode(), pick
            except OSError:
                pass
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "bind", "img", "yume-gone.webp")
        if not os.path.exists(p):
            return None
        with Image.open(p) as im:
            im = im.convert("RGBA")
            im.thumbnail((240, 240))
            buf = io.BytesIO()
            im.save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode(), "yume-gone"

    async def _announce_shutdown(self) -> None:
        """插件被重载（更新）或 AstrBot 关掉之前：正在玩小游戏、在投别名票的群，先发一句说明 + 表情包，
        再公布这局答案，然后才真正退出（局面只在内存里，重载后本来就没了）。"""
        import base64
        import random
        from astrbot.api.event import MessageChain
        sessions = dict(getattr(self.games, "sessions", {}) or {})
        av = getattr(self, "alias_votes", None)
        voting = {o for o in list(getattr(av, "active", {}) or {}) + list(getattr(av, "asks", {}) or {})} if av else set()
        origins = list(dict.fromkeys(list(sessions) + [o for o in voting if o not in sessions]))
        if not origins:
            return
        got = await asyncio.to_thread(self._shutdown_sticker)
        sticker = got[0] if got else None
        if got:
            logger.info(f"[otoge] shutdown sticker: {os.path.basename(got[1])}")

        async def one(origin: str) -> None:
            head = random.choice(self.SHUTDOWN_LINES)
            if origin not in sessions:
                head = "我要更新一下，马上回来～正在投的别名票先作废，重启后可以再提。"
            first = MessageChain().message(head)
            if sticker:
                first = first.base64_image(sticker)
            await self.context.send_message(origin, first)
            s = sessions.get(origin)
            if s is None:
                return
            r = self.games.finish(origin, s)
            chain = MessageChain().message("\n".join(r.texts))
            if r.image:
                chain = chain.base64_image(base64.b64encode(r.image).decode())
            await asyncio.sleep(0.8)
            await self.context.send_message(origin, chain)

        results = await asyncio.gather(*(asyncio.wait_for(one(o), 10) for o in origins), return_exceptions=True)
        bad = [r for r in results if isinstance(r, Exception)]
        logger.info(f"[otoge] shutdown notice sent to {len(origins) - len(bad)}/{len(origins)} chats")

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

    SHOW_WORDS = {
        "sdvx": ("sdvx_ex", ("ex", "exscore", "ex分", "ex分数", "ex score")),
        "mai": ("mai_dx", ("dx分", "dx分数", "dxscore", "dx score")),
        "geki": ("geki_plat", ("白金分", "白金", "p分", "白金分数", "platinum", "plat")),
    }

    def _show_switch(self, ctx: Ctx, game: str, first: str, rest: str) -> Reply | None:
        """「/sdvx ex 开|关」等：图上 / 传分网站上要不要显示这个附加分数。只认「词 + 开/关/状态」，别的照常走。"""
        spec = self.SHOW_WORDS.get(game)
        if spec is None:
            return None
        key, words = spec
        w = first.lower()
        tail = rest.strip().lower()
        if w + " " + tail.partition(" ")[0] in words:          # 「ex score 关」
            w, tail = w + " " + tail.partition(" ")[0], tail.partition(" ")[2].strip()
        if w not in words:
            return None
        on = {"开": True, "开启": True, "显示": True, "on": True, "关": False, "关闭": False, "隐藏": False,
              "不显示": False, "off": False}.get(tail)
        if on is None and tail not in ("", "状态", "?", "？"):
            return None
        name = self.prefs.SHOW_KEYS[key]
        where = {"sdvx_ex": "VF 50 图和传分网站", "mai_dx": "B50 图", "geki_plat": "B50 图和传分网站"}[key]
        if on is None:
            cur = self.prefs.show(ctx.uid, key)
            return Reply().say(f"{name}：现在{'显示' if cur else '不显示'}（{where}）。"
                               f"改：/{game} {words[0]} {'关' if cur else '开'}")
        self.prefs.set_show(ctx.uid, key, on)
        return Reply().say(f"好，{where}上{'会显示' if on else '不再显示'}{name}。" + (f"改回来：/{game} {words[0]} {'关' if on else '开'}"))

    async def _dispatch(self, event: AstrMessageEvent, game: str, argline: str) -> Reply:
        ctx = self._ctx(event)
        topic = self._help_topic(game, argline)
        if topic is not False:                          # 「/mai 帮助」「/geki」「/sdvx 帮助」「/查分 帮助 舞萌」
            return await self._help_reply(topic)
        first, _, rest = argline.strip().partition(" ")
        if "\n" in first:                               # 「/sdvx 批量传⏎第一行…」：换行也算分隔
            first = first.partition("\n")[0]
            rest = argline.strip()[len(first):].lstrip(" \t")
        sw = self._show_switch(ctx, game, first, rest)   # /sdvx ex 关、/mai dx分 开、/geki 白金分 关
        if sw is not None:
            return sw
        if game in ("sdvx", "geki"):                    # 传分本：传分网站 / 聊天传分 / 手动成绩 b50
            r = await self._scorebook_dispatch(event, ctx, game, first.lower(), rest)
            if r is not None:
                return r
        if game == "geki":                              # 音击：私服查分 + sdvx.in 谱面
            # 「/geki 网页绑定」「/geki 绑定」不带参数 → 绑定指南图 + 链接（网页上预选音击）
            if first.lower() in WEB_BIND_WORDS or (first.lower() in BIND_GUIDE_WORDS and self.bindweb_ready()
                                                   and bind_without_creds(game, rest)):
                return await self._web_bind_reply(event, ctx, game)
            r = await self._unbound_to_web(event, ctx, game, await self.geki.handle(ctx, argline))
            if first.lower() in ("加别名", "添加别名"):
                await asyncio.to_thread(self.alias_library)
            return r
        if game == "core":
            return await self._core(event, ctx, argline)
        if game == "sdvx" and first.lower() in WEB_BIND_WORDS:   # 「/sdvx 网页绑定」→ 绑定页预选 SDVX（官服 → 传分）
            return await self._web_bind_reply(event, ctx, "sdvx")
        if game in ("sdvx", "pjsk", "chart"):           # sdvx.in chart views (no scores for these)
            r = await self.charts.handle(ctx, argline, game)
            if first.lower() in ("加别名", "添加别名"):
                await asyncio.to_thread(self.alias_library)
            return r
        if first.lower() in WEB_BIND_WORDS:
            ws = rest.split()
            if ws and ws[0].lower() in ("确认", "confirm"):
                return self._web_bind_confirm(ctx, " ".join(ws[1:]))
            return await self._web_bind_reply(event, ctx, game)
        if first.lower() in CU.UPDATE_WORDS:            # 「/mai 更新」「/chu 更新 国服」：国服成绩怎么更新
            return await self._cn_update(ctx, game, rest)
        # 「/mai 绑定」「/chu 绑定 国服」「/mai 绑定 落雪」这种没给用户名 / 凭据的 → 一律引到网页绑定
        # （图 + 本人专用链接，网页上预选这个游戏）；把用户名 / 凭据写全了的照旧走指令绑定。
        if first.lower() in BIND_GUIDE_WORDS and self.bindweb_ready() and bind_without_creds(game, rest):
            return await self._web_bind_reply(event, ctx, game)
        if first.lower() in CHART_SUBS:
            if game == "chu":
                return await self.charts.handle(ctx, rest, "chu")
            return Reply().say("sdvx.in 没有舞萌的谱面确认。可以查：/chu 谱面 <歌>、/geki 谱面 <歌>、/sdvx 谱面 <歌>、/pjsk 谱面 <歌>")
        self.prefs.set_last_game(ctx.uid, game)
        handler = self.cmd if game == "mai" else self.chu
        r = await self._unbound_to_web(event, ctx, game, await handler.handle(ctx, argline))
        if first.lower() in ("加别名", "添加别名", "删别名"):
            await asyncio.to_thread(self.alias_library)
        return r

    # ---------- 传分本（SDVX / 音击官服：手动传分） ----------
    def _scorebook_link(self, event: AstrMessageEvent, ctx: Ctx, game: str = "", rest: str = "",
                        force: bool = False) -> Reply:
        url = self.bindweb_url()
        if self.bindweb is None or not url or not self.bindweb.running:
            return Reply().say("传分网站要用网页绑定那个公网地址，bot 主人还没配好。先用聊天传分：/sdvx 传 <歌> <难度> <分数> [灯]")
        from urllib.parse import urlencode
        n_sess = self.scorebook.sessions.active(ctx.uid)
        # 已经在某台设备上登录着：群里只给网址（不刷登录链接）；私聊照样带登录链接——
        # 不然换个浏览器 / 设备点开是只读模式，bot 却说「已经登录着」，人会以为坏了（v2.3.9）。
        if n_sess and not force and not ctx.private:
            nav = self.scorebook.deep_link(game, rest)
            direct = f"{url}/scores" + ("#" + urlencode(nav) if nav else "")
            what = ""
            if nav.get("k") or nav.get("q"):
                song = self.scorebook.cat(game).songs.get(nav["k"]) if nav.get("k") else None
                what = "（点开直接到：" + (song.title if song else f"搜「{nav['q']}」") + \
                       (f" {nav['d']}" if nav.get("d") else "") + "）"
            return Reply().say(f"传分网站{what}：\n{direct}\n你已经在 {n_sess} 个设备上登录过，在那台设备上直接打开就行。"
                               "\n这台设备没登录过的话点开是只读模式：发「/传分 登录」要登录链接（私聊发更省事，不用确认码）。")
        tok = self.scorebook.sessions.issue_login(ctx.uid, ctx.name, game, confirm=not ctx.private)
        nav = self.scorebook.deep_link(game, rest)
        link = f"{url}/scores#" + urlencode({"t": tok, **nav})
        if nav.get("k") or nav.get("q"):
            song = self.scorebook.cat(game).songs.get(nav["k"]) if nav.get("k") else None
            what = (song.title if song else f"搜「{nav['q']}」") + (f" {nav['d']}" if nav.get("d") else "")
            direct = f"{url}/scores#" + urlencode(nav)
            tail = (f"\n点开直接到：{what}。"
                    f"\n已经登传过的话，用这个不占登录次数：{direct}")
        else:
            tail = ("\n点开就登录了，之后 30 天在这台设备上直接打开 " + f"{url}/scores" + " 就行。"
                    "\n能找歌（歌名 / 外号 / 读音）、按等级 / 版本 / 分类翻，点难度就能传分；SDVX 和音击都在里面。"
                    f"\n想直接跳到某首：/{game or 'sdvx'} 传分 歌名 [难度]")
        if not ctx.private:
            return Reply(at=ctx.uid).say(f"你的传分网站登录链接（15 分钟内有效、只能用一次）：\n{link}{tail}"
                                         "\n群里发的链接点开后会显示一个 4 位确认码，你自己在 QQ 回「/传分 确认 码」才会登录，别人点开也登不上你的号。"
                                         "\n只确认你自己屏幕上看到的码，别人报给你的码不要发。私聊发 /传分 的链接不用确认")
        return Reply().say(f"你的传分网站登录链接（15 分钟内有效、只能用一次，别转发）：\n{link}{tail}")

    async def _scorebook_dispatch(self, event: AstrMessageEvent, ctx: Ctx, game: str, first: str, rest: str) -> Reply | None:
        sb = self.scorebook
        if game:
            sb._last_game[ctx.uid] = game
        if first in SBS.LOGIN_WORDS:
            w0, _, w1 = rest.strip().partition(" ")
            if w0 in ("确认", "confirm"):
                code = w1.strip()
                if not code:
                    return Reply().say("把网页上的 4 位码带上：/传分 确认 1234")
                res = sb.sessions.confirm(ctx.uid, code)
                return Reply().say({
                    "ok": "确认好了，回到那个网页，几秒内就会登录。网页已经被关掉 / 刷新了的话：用同一个浏览器重新打开 " + (self.bindweb_url() or "") + "/scores ，会接着登上。",
                    "none": "你现在没有等确认的登录（可能已经过期了，码只有 5 分钟）。重新发「/传分」拿链接。",
                    "wrong": "码不对。要回你自己点开的网页上显示的那 4 位。",
                    "locked": "输错太多次，这次的登录已经作废。重新发「/传分」拿链接。",
                }[res])
            if rest.strip() in ("登出", "退出", "logout", "下线"):
                n = sb.sessions.drop_user(ctx.uid)
                return Reply().say(f"传分网站已登出（{n} 个设备）。要再登录发「/传分」")
            if not game:                                 # /传分 sdvx VICTIM、/传分 音击 xxx
                g0, _, r0 = rest.strip().partition(" ")
                gm = {"sdvx": "sdvx", "sdvx∇": "sdvx", "sdvxnabla": "sdvx", "geki": "geki", "音击": "geki",
                      "ongeki": "geki", "オンゲキ": "geki"}.get(g0.lower())
                if gm:
                    game, rest = gm, r0
            f0, _, f1 = rest.strip().partition(" ")
            force = f0.lower() in ("登录", "登陆", "login", "新链接", "换设备", "登录链接")
            if force:
                rest = f1.strip()
            return self._scorebook_link(event, ctx, game, rest, force)
        r = await sb.handle(ctx, game, first, rest)
        if r is not None:
            return r
        words = rest.split()
        if game == "sdvx" and first in SBS.BEST_WORDS:
            text = any(w in ("文字", "text", "txt", "文本") for w in words)
            full = any(w in ("全", "全部", "all", "完整") for w in words)
            if not sb.store.has_any(ctx.uid, "sdvx"):
                return Reply().say(sb.sdvx_text(ctx.uid))
            if not text:
                try:
                    img = await sb.sdvx_image(ctx.uid, sb.store.user(ctx.uid).get("name") or ctx.name or "",
                                              self.bot_name, getattr(self.chu_svc.settings, "font_path", None),
                                              getattr(self.chu_svc.settings, "timezone", None) or "Australia/Sydney")
                    if img:
                        return Reply(image=img)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[otoge] sdvx vf50 image failed: {type(e).__name__}: {e}")
            return Reply().say(sb.sdvx_text(ctx.uid, full))
        off = self.geki_official
        if game == "geki" and (first in ("同步", "sync", "官服同步") or (first in ("刷新", "更新") and "官服" in rest)):
            return Reply().say(await off.sync(ctx.uid, force=True))
        if game == "geki" and first in ("绑定", "bind", "登录") and rest.strip().startswith(("官服", "sega", "日服")):
            r = await self._web_bind_reply(event, ctx, "geki")
            r.texts.insert(0, "音击官服用 SEGA ID + 密码绑（要账号开着 オンゲキ-NET Standard），只能在网页上填：打开下面的链接 → 音击 → 官服 → SEGA ID")
            return r
        if game == "geki" and first in ("解绑", "unbind") and "官服" in rest:
            return Reply().say("音击官服已解绑（之前同步进来的成绩还在，在传分网站上删）" if off.unbind(ctx.uid)
                               else "你没绑音击官服")
        if game == "geki" and first in ("b50", "best", "best50", "ra", "rating", "成绩", "我", "me", "资料", "文字", "text"):
            manual = any(w in ("手动", "官服", "manual", "传分", "录分", "日服") for w in words)
            bound = bool(self.geki._server(ctx.uid)[0])
            official = off.bound(ctx.uid)
            if official and (manual or not bound):
                note = await off.sync(ctx.uid)          # 5 分钟内拉过就不再拉
                r = await self._geki_manual_best(ctx, words + ([first] if first in ("文字", "text") else []))
                if "失败" in note or "没开" in note:
                    r.texts.insert(0, note)
                return r
            if manual or (not bound and sb.store.has_any(ctx.uid, "geki")):
                return await self._geki_manual_best(ctx, words + ([first] if first in ("文字", "text") else []))
        return None

    async def _geki_manual_best(self, ctx: Ctx, words: list[str]) -> Reply:
        from .scorebook import calc as SBK
        sb = self.scorebook
        if not sb.store.has_any(ctx.uid, "geki"):
            return Reply().say("你还没传过音击成绩。发「/geki 传分」打开传分网站，或者 /geki 传 <歌> <难度> <技术分> [fc|ab]")
        name = sb.store.user(ctx.uid).get("name") or ctx.name or ""
        best = SBK.geki_best(sb.cat("geki"), sb.store.scores(ctx.uid, "geki"), name)
        best.show_plat = self.prefs.show(ctx.uid, "geki_plat")
        text = any(w in ("文字", "text", "txt", "文本") for w in words)
        full = any(w in ("全", "全部", "all", "完整") for w in words)
        if not text:
            try:
                import tempfile
                from pathlib import Path
                from .ongeki.b50img import render as geki_render
                titles = [c.title for c in (*best.new, *best.best, *best.plat)]
                jackets = {}
                try:
                    jackets = await self.charts.src.geki_jackets(titles)
                except Exception:  # noqa: BLE001
                    pass
                out = Path(tempfile.gettempdir()) / f"otoge_gekim_{time.time_ns()}.jpg"
                await asyncio.to_thread(geki_render, best, out, jackets=jackets,
                                        font_path=getattr(self.chu_svc.settings, "font_path", None),
                                        footer_left=f"Generated by {self.bot_name}",
                                        region_label=("官服同步 + 手动传分" if self.geki_official.bound(ctx.uid)
                                                      else "手动传分") + " · Re:Fresh 规则",
                                        tz=getattr(self.chu_svc.settings, "timezone", None) or "Australia/Sydney")
                try:
                    return Reply(image=out.read_bytes())
                finally:
                    try:
                        out.unlink()
                    except OSError:
                        pass
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[otoge] geki manual b50 image failed: {type(e).__name__}: {e}")
        from .ongeki.text import render as geki_text
        t = geki_text(best, best_limit=None if full else 15, plat_limit=None if full else 10)
        return Reply().say("（手动传分的成绩）\n" + t)

    async def _unbound_to_web(self, event: AstrMessageEvent, ctx: Ctx, game: str, r: Reply) -> Reply:
        """查分时回「你还没绑定…（发某某指令）」→ 换成网页绑定（说明为什么 + 本人链接），指令写法留在最后一行。"""
        if r is None or r.image or not self.bindweb_ready():
            return r
        text = "\n".join(r.texts)
        cut = min((text.find(m) for m in UNBOUND_MARKS if m in text), default=-1)
        if cut < 0:
            return r
        why = text[:cut].strip()
        head = re.split(r"[，,：:。]", text[cut:], 1)[0]
        w = await self._web_bind_reply(event, ctx, game)
        if not w.texts or "http" not in w.texts[-1]:      # 没公网地址 / 群里不发链接：原样回
            return r
        w.texts[-1] = (why + "\n" if why else "") + head + "，点链接在网页上绑定（最简单，凭据不进聊天记录）👇\n" + w.texts[-1]
        return w

    # ---------- 别名收集（猜歌） ----------
    ALIAS_KEYS = {"alias_collect_enabled": bool, "alias_vote_yes": int, "alias_vote_no": int, "alias_vote_minutes": int,
                  "alias_checks_per_hour": int, "alias_llm_threshold": float, "alias_provider_id": str,
                  "alias_ask_enabled": bool, "alias_ask_cooldown_minutes": int, "alias_ask_max_known": int}

    @staticmethod
    def _alias_live_load(root: str) -> dict:
        try:
            import json
            with open(os.path.join(root, "alias_settings.json"), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _acfg(self, key: str, default=None):
        """别名设置：WebUI 里改过的优先（存在 alias_settings.json，改了马上生效、不重载插件），否则用插件配置。"""
        live = getattr(self, "_alias_live", None) or {}
        return live[key] if key in live else self._cfg(key, default)

    def alias_settings(self) -> dict:
        return {k: self._acfg(k, d) for k, d in (("alias_collect_enabled", True), ("alias_vote_yes", 3), ("alias_vote_no", 2),
                                                ("alias_vote_minutes", 10), ("alias_checks_per_hour", 0),
                                                ("alias_llm_threshold", 0.75), ("alias_provider_id", ""),
                                                ("alias_ask_enabled", True), ("alias_ask_cooldown_minutes", 0),
                                                ("alias_ask_max_known", 5))}

    def set_alias_settings(self, changes: dict) -> dict:
        import json
        live = dict(getattr(self, "_alias_live", None) or {})
        for k, v in (changes or {}).items():
            if k not in self.ALIAS_KEYS:
                continue
            try:
                v = self.ALIAS_KEYS[k](v) if self.ALIAS_KEYS[k] is not bool else bool(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} 填得不对") from None
            if k in ("alias_vote_yes", "alias_vote_no", "alias_vote_minutes") and v < 1:
                raise ValueError("票数和分钟至少是 1")
            if k == "alias_checks_per_hour" and v < 0:
                raise ValueError("次数不能是负数（0 = 不限）")
            if k == "alias_ask_max_known" and v < 0:
                raise ValueError("外号个数不能是负数（0 = 不管有几个都问）")
            if k == "alias_ask_cooldown_minutes" and v < 0:
                raise ValueError("冷却不能是负数（0 = 不冷却）")
            if k == "alias_llm_threshold" and not 0 <= v <= 1:
                raise ValueError("把握要在 0 到 1 之间")
            live[k] = v
        self._alias_live = live
        tmp = os.path.join(self.root, "alias_settings.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(live, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(self.root, "alias_settings.json"))
        av = self.alias_votes
        av.need_yes, av.need_no = int(self._acfg("alias_vote_yes", 3)), int(self._acfg("alias_vote_no", 2))
        av.minutes = float(self._acfg("alias_vote_minutes", 10))
        return self.alias_settings()

    def alias_remove(self, game: str, space: str, sid: str, alias: str) -> bool:
        """WebUI 删一条本机外号。"""
        ok = False
        if space == "mai" and self.cmd.aliases is not None:
            ok = self.cmd.aliases.remove_local(alias)
            if ok:
                self.service.catalog.set_aliases(self.cmd.aliases.merged())
        elif space == "chu" and self.chu.aliases is not None:
            ok = self.chu.aliases.remove_local(alias)
            if ok:
                self.chu_svc.songdb.apply_aliases(self.chu.aliases.merged())
        elif space == "sdvxin":
            ok = self.charts.src.remove_alias(game, alias, str(sid))
        if ok:
            try:
                self.games.data._cache.clear()
            except Exception:  # noqa: BLE001
                pass
            self.alias_library()
        return ok

    def _alias_on(self) -> bool:
        return bool(self._acfg("alias_collect_enabled", True)) and self._games_on()

    def _alias_log(self, origin: str, ctx: Ctx, text: str) -> None:
        if not ctx.private and self._alias_on():
            self.alias_votes.log(origin, ctx.uid, getattr(ctx, "name", "") or "", text)

    ALIAS_BATCH_SECONDS = 15        # 开字母一局能连中好几首：攒 15 秒一起问一次模型

    def _alias_catalog(self, game: str, kind: str) -> set[str]:
        """这个游戏所有歌的名字 + 已有外号（标准化后）：候选已经是别的歌的叫法，就不用问模型了。缓存 1 小时。"""
        cache = self.__dict__.setdefault("_alias_cat", {})
        hit = cache.get((game, kind))
        if hit and time.time() - hit[0] < 3600:
            return hit[1]
        keys: set[str] = set()
        try:
            songs = self.games.data.chart_songs(game) if kind == "chart" else self.games.data.songs(game)
            for x in songs:
                keys |= x.answers()
        except Exception:  # noqa: BLE001
            pass
        cache[(game, kind)] = (time.time(), keys)
        return keys

    def _alias_solved(self, origin: str, s, i: int, ctx, guess: str) -> None:
        if ctx is None or ctx.private or not self._alias_on():
            return
        now = time.time()
        song = s.picks[i].song
        others = [p.song for j, p in enumerate(s.picks) if j != i]
        known = self.alias_votes.known_keys(song.game, s.kind, song.sid)
        cands = AV.candidates(self.alias_votes.lines(origin), s.started, now, song, known, others,
                              solver=str(ctx.uid), catalog_keys=self._alias_catalog(song.game, s.kind))
        if not cands and not self._ask_worth(song):
            return
        pend = self.__dict__.setdefault("_alias_pending", {})
        first = origin not in pend
        pend.setdefault(origin, []).append((s.kind, song, cands))
        if first:
            self._tasks.append(asyncio.create_task(self._alias_flush(origin)))

    def _alias_solved_by_alias(self, origin: str, s, i: int, ctx, guess: str) -> None:
        """用已有外号猜中：聊天里不用找了，外号还少（默认 < 5 个）就排进去，跟别的一起问「还有别的叫法吗」。"""
        if ctx is None or ctx.private or not self._alias_on():
            return
        song = s.picks[i].song
        if not self._ask_worth(song):
            return
        pend = self.__dict__.setdefault("_alias_pending", {})
        first = origin not in pend
        pend.setdefault(origin, []).append((s.kind, song, []))
        if first:
            self._tasks.append(asyncio.create_task(self._alias_flush(origin)))

    async def _alias_flush(self, origin: str, delay: float | None = None) -> None:
        await asyncio.sleep(self.ALIAS_BATCH_SECONDS if delay is None else delay)
        batch = (self.__dict__.get("_alias_pending") or {}).pop(origin, [])
        if not batch:
            return
        found: set[int] = set()
        try:
            found = await self._alias_llm_batch(origin, batch)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] alias check failed: {type(e).__name__}: {e}")
            return                                   # 模型出错时不追问（可能只是没连上）
        await self._alias_ask(origin, [(kind, song) for n, (kind, song, _) in enumerate(batch) if n not in found])

    async def _alias_llm_batch(self, origin: str, batch: list) -> set[int]:
        """有候选的几首一起问模型；模型说像的直接发起投票。返回找到外号的那几首的序号。"""
        idxs = [n for n, (_, _, c) in enumerate(batch) if c]
        if not idxs:
            return set()
        now = time.time()
        recent = [t for t in self._alias_checks.get(origin, []) if now - t < 3600]
        try:
            cap = int(self._acfg("alias_checks_per_hour", 0) or 0)        # 0 = 不限
        except (TypeError, ValueError):
            cap = 0
        if cap > 0 and len(recent) >= cap:
            return set(range(len(batch)))           # 超了次数：这几首这次就不问模型也不追问
        recent.append(now)
        self._alias_checks[origin] = recent
        items = [(GAME_NAMES.get(batch[n][1].game, batch[n][1].game), batch[n][1], batch[n][2]) for n in idxs]
        call = await self._alias_llm_call()
        if call is None:
            return set(range(len(batch)))
        text = await call(AV.SYSTEM, AV.prompt(items))
        got = AV.parse_reply(text, items, float(self._acfg("alias_llm_threshold", 0.75) or 0.75))
        logger.info(f"[otoge] alias check {[(s.title, c) for _, s, c in items]} → {got}")
        av = self.alias_votes
        for j, n in enumerate(idxs):
            kind, song, cands = batch[n]
            for c in cands:
                if got.get(j, ("",))[0] != c:
                    av.remember_no(song.game, kind, song.sid, song.title, c)
        av.flush()
        for j, (alias, reason) in got.items():
            kind, song, _ = batch[idxs[j]]
            intro = av.propose(AV.Vote(origin, song.game, kind, song.sid, song.title, alias, reason, ref=song.ref))
            if intro:
                await self._notify_private(origin, intro)
        return {idxs[j] for j in got}

    def _ask_on(self) -> bool:
        return bool(self._acfg("alias_ask_enabled", True))

    def _ask_worth(self, song) -> bool:
        """外号已经很多的歌就不追问了（默认已有 5 个及以上不问；0 = 不管有几个都问）。"""
        if not self._ask_on():
            return False
        try:
            lim = int(self._acfg("alias_ask_max_known", 5) or 0)
        except (TypeError, ValueError):
            lim = 5
        return lim <= 0 or len(getattr(song, "aliases", None) or []) < lim

    async def _alias_ask(self, origin: str, items: list) -> None:
        """模型没从聊天里找到外号：问一句「这首大家叫它什么」。有冷却、群里正在投票 / 在问就不问，免得刷屏。"""
        items = [(k, sg) for k, sg in items if self._ask_worth(sg)]
        if not items or not self._alias_on():
            return
        try:
            cd = float(self._acfg("alias_ask_cooldown_minutes", 0) or 0)
        except (TypeError, ValueError):
            cd = 0.0
        if not self.alias_votes.can_ask(origin, cd):
            return
        text = self.alias_votes.open_ask(origin, items, GAME_NAMES)
        if text:
            await self._notify_private(origin, text)

    def _alias_ask_reply(self, origin: str, ctx: Ctx, text: str) -> Reply | None:
        """回「别名 xxx」：本地检查（不花 token），没问题就发起投票，靠群友投票把关。"""
        av = self.alias_votes
        a = av.ask_current(origin)
        if a is None:
            return None
        got = AV.parse_ask_reply(text, len(a.items))
        if got is None:
            return None
        idx, alias = got
        if idx < 0:
            return Reply().say(AV.which_song_hint(a.items, alias))
        kind, song = a.items[idx]
        alias = alias.replace(" ", "") if AV._CJK.search(alias) else alias.strip()
        why = AV.check_alias(alias, song, av.voted_keys(song.game, kind, song.sid), self._alias_catalog(song.game, kind))
        if why:
            return Reply().say(why)
        a.taken += 1
        who = (getattr(ctx, "name", "") or "").strip()
        v = AV.Vote(origin, song.game, kind, song.sid, song.title, alias, f"{who}提议" if who else "群友提议", ref=song.ref)
        intro = av.propose(v)
        if intro:
            return Reply().say(intro)
        cur = av._current(origin)
        if cur is None:
            return Reply().say(f"收到「{alias}」=《{song.title}》，排上了，前面的投完就轮到它")
        return Reply().say(f"收到「{alias}」=《{song.title}》，排在后面。\n"
                           f"⚠ 现在在投的是「{cur.alias}」=《{cur.title}》（{av.status(cur)}），"
                           f"这时候回 y / n 算给「{cur.alias}」，等它投完才轮到「{alias}」")

    def _alias_provider_id(self) -> str:
        """别名判断用便宜的模型：配置 alias_provider_id；没填就找名字里带 flash 的；再没有就用「自然语言」那个。"""
        pid = str(self._acfg("alias_provider_id", "") or "").strip()
        if pid:
            return pid
        try:
            for prov in self.context.get_all_providers():
                meta = prov.meta()
                model = str(getattr(meta, "model", "") or (prov.get_model() if hasattr(prov, "get_model") else ""))
                if "flash" in model.lower() or "flash" in str(meta.id).lower():
                    return str(meta.id)
        except Exception:  # noqa: BLE001
            pass
        return ""

    async def _alias_llm_call(self):
        pid = self._alias_provider_id()
        if not pid:
            return await self._llm_call(None)
        timeout = float(self._cfg("nl_timeout", 15))

        async def call(system: str, text: str) -> str:
            resp = await asyncio.wait_for(self.context.llm_generate(
                chat_provider_id=pid, system_prompt=system, prompt=text), timeout=timeout)
            return resp.completion_text or ""
        return call

    def alias_library(self) -> dict[str, int]:
        """本机别名按游戏导出到 alias_library/（mai/chu/geki/sdvx/pjsk.json + README.md）。"""
        try:
            self.scorebook.sync_aliases()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] scorebook alias sync failed: {type(e).__name__}: {e}")
        try:
            return AL.write(AL.collect(self), os.path.join(self.root, "alias_library"))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[otoge] alias library export failed: {type(e).__name__}: {e}")
            return {}

    def _alias_apply(self, v) -> str:
        """投票通过 → 写进本机别名库（舞萌 / 中二用各自的别名库，猜谱面和音击 / SDVX / PJSK 用 sdvx.in 那份）。"""
        alias = v.alias.replace(" ", "")
        if v.kind != "chart" and v.game == "mai" and self.cmd.aliases is not None:
            ref = v.ref
            ids = list(ref.music_ids()) if ref is not None and hasattr(ref, "music_ids") else \
                [int(v.sid)] if v.sid.isdigit() else []
            if not ids:
                return "没找到这首歌的曲目 ID，没加上"
            self.cmd.aliases.add_local(alias, min(m % 10000 for m in ids))
            self.service.catalog.set_aliases(self.cmd.aliases.merged())
        elif v.kind != "chart" and v.game == "chu" and self.chu.aliases is not None and v.sid.isdigit():
            self.chu.aliases.add_local(alias, int(v.sid))
            self.chu_svc.songdb.apply_aliases(self.chu.aliases.merged())
        else:
            self.charts.src.add_alias(v.game, alias, v.sid)
        try:
            self.games.data._cache.clear()                  # 猜歌的曲目列表带着外号，清掉重建
        except Exception:  # noqa: BLE001
            pass
        self.alias_library()
        return ""

    def _alias_vote(self, origin: str, ctx: Ctx, text: str) -> Reply | None:
        if ctx.private or not self._alias_on():
            return None
        r = self._alias_ask_reply(origin, ctx, text)
        if r is not None:
            return r
        res = self.alias_votes.on_message(origin, ctx.uid, text)
        if res is None:
            return None
        what, v = res
        if what == "counted":
            w = "y" if ctx.uid in v.yes else "n"
            return Reply().say(f"收到 {w}：「{v.alias}」=《{v.title}》（{self.alias_votes.status(v)}）")
        if what == "pass":
            err = self._alias_apply(v)
            line = (f"✓ 投票通过（{len(v.yes)} 票 y）：以后「{v.alias}」就是《{v.title}》了" if not err
                    else f"投票通过了，但{err}")
        else:
            line = f"✗ 没通过（{len(v.no)} 票 n）：「{v.alias}」不算《{v.title}》的外号"
        nxt = self.alias_votes.next_intro(origin)
        return Reply().say(line + (f"\n\n{nxt}" if nxt else ""))

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
            if len(args) > 1 and args[1].lower() in ("确认", "confirm"):
                return self._web_bind_confirm(ctx, " ".join(args[2:]))
            return await self._web_bind_reply(event, ctx)
        if sub in SBS.LOGIN_WORDS:                      # /传分、/查分 传分 → 传分网站
            return await self._scorebook_dispatch(event, ctx, "", sub, " ".join(args[1:])) or Reply()
        if sub in SBS.RECORD_WORDS or sub in SBS.BATCH_WORDS:   # /传、/批量传（不带游戏 → 上次传分的游戏）
            raw = argline.strip()
            rest = raw[len(args[0]):].lstrip(" \t") if args else ""
            g0 = re.match(r"(\S+)", rest)
            game = SBS.GAME_WORDS.get(g0.group(1).lower()) if g0 else None
            explicit = game is not None
            if explicit:
                rest = rest[len(g0.group(1)):].lstrip(" \t")
            else:
                game = self.scorebook.last_game(ctx.uid)
            r = await self.scorebook.handle(ctx, game, sub, rest)
            if r is None:
                return Reply()
            if not explicit and rest.strip():
                other = "geki" if game == "sdvx" else "sdvx"
                r.texts[0] = f"（按 {'SDVX' if game == 'sdvx' else '音击'} 传的；要传{'音击' if other == 'geki' else ' SDVX'}写 /{sub} {other} …）\n" + r.texts[0]
            return r
        if sub in ("账号", "我的账号", "account", "绑定"):
            return Reply().say(self.accounts_text(ctx.uid))
        if sub in ("别名库", "外号库", "aliases", "别名导出"):
            counts = await asyncio.to_thread(self.alias_library)
            names = {"mai": "舞萌", "chu": "中二", "geki": "音击", "sdvx": "SDVX", "pjsk": "PJSK"}
            body = "　".join(f"{names[g]} {n}" for g, n in counts.items()) or "导出失败，看日志"
            lines = [f"本 bot 收录的外号（指令加的 + 猜歌投票通过的）：{body}"]
            if self._is_owner(event):
                lines.append(f"已按游戏导出到：{os.path.join(self.root, 'alias_library')}（每个游戏一个 JSON + README，CC0，不含 QQ 号 / 群号）")
            return Reply().say("\n".join(lines))
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
        # 音击：私服 AquaDX（和舞萌中二共用的那个绑定）+ 官服手动传的；SDVX：只有手动传的
        aqua = self.priv.bindings.get(uid, "aqua") if getattr(self, "priv", None) is not None else ""
        try:
            gn = len(self.scorebook.store.scores(uid, "geki"))
            sn = len(self.scorebook.store.scores(uid, "sdvx"))
        except Exception:  # noqa: BLE001
            gn = sn = 0
        geki = [f"私服 AquaDX（{aqua}）"] if aqua else []
        off = getattr(self, "geki_official", None)
        if off is not None and off.bound(uid):
            geki.append("官服 SEGA ID（自动查" + ("，没开 Standard" if off.last(uid).get("std") is False else "") + "）")
        if gn:
            geki.append(f"官服成绩 {gn} 张")
        lines.append("· 音击：" + ("、".join(geki) if geki else "没绑定私服，官服也还没传分"))
        lines.append("· SDVX：" + (f"手动传分 {sn} 张" if sn else "还没传分（官服不用绑定，发 /sdvx 传分）"))
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
        if r is None and not ctx.private:
            r = self._alias_vote(event.unified_msg_origin, ctx, text)          # 别名投票的 y / n
        if r is None and self._games_on():
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
        if not ctx.private:
            self._invite_watch(event, ctx, text)
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
