"""Glue between storage, NET sessions, parsers and rating. No AstrBot imports here."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .calc.rating import Best50, attach_charts, build_best50
from .consts import API_REGIONS, DIFFS, DIFF_INDEX, PRIV_REGIONS, REGION_NAMES, catalog_region
from .data.loader import CatalogStore
from .models import PlaylogDetail, Profile, RecentPlay, Score
from .net.client import (P_HOME, P_PLAYER, P_RECORD, P_TARGET, Credentials, HostThrottle, NetSession,
                         THROTTLE, p_friend_search, p_playlog, p_scores)
from .parse.profile import parse_friend_search, parse_profile
from .parse.record import parse_playlog_detail, parse_recent
from .parse.scores import parse_rating_target, parse_score_list
from .bot.storage import UserStore

SESSION_IDLE = 15 * 60


QQ_MISS_TTL = 600     # 按 QQ 自动找落雪没找到的，10 分钟内不再问


class NotBound(Exception):
    pass


class NotSupported(Exception):
    """Feature not available on this server (e.g. 国服 recent plays through 水鱼)."""


_DF_FC = {"fc": "fc", "fcp": "fcp", "ap": "ap", "app": "app"}
_DF_FS = {"sync": "sync", "fs": "fs", "fsp": "fsp", "fsd": "fsd", "fsdp": "fsdp", "fdx": "fsd", "fdxp": "fsdp"}
_DF_DIFF = ("basic", "advanced", "expert", "master", "remaster")


_LX_DIFF = _DF_DIFF
_LX_TITLE_KIND = {"normal": "normal", "bronze": "bronze", "silver": "silver", "gold": "gold", "rainbow": "rainbow"}
LX_ICON = "https://assets2.lxns.net/maimai/icon/{id}.png"
LX_PLATE = "https://assets2.lxns.net/maimai/plate/{id}.png"
LX_FRAME = "https://assets2.lxns.net/maimai/frame/{id}.png"


def lx_score(r: dict) -> Score | None:
    """One 落雪 maimai score → Score (国服 rating kept; constant filled from the 落雪 song list later)."""
    typ = str(r.get("type") or "").lower()
    if typ not in ("dx", "standard"):
        return None                       # 宴 charts are not rated
    try:
        sid = int(r.get("id"))
        li = int(r.get("level_index") or 0)
    except (TypeError, ValueError):
        return None
    if sid >= 100000 or not 0 <= li < len(_LX_DIFF):
        return None
    ach = int(round(float(r.get("achievements") or 0) * 10000))
    s = Score(title=r.get("song_name") or "", type="dx" if typ == "dx" else "std", diff=_LX_DIFF[li],
              level=str(r.get("level") or ""), ach=ach, dx=int(r.get("dx_score") or 0),
              fc=_DF_FC.get(str(r.get("fc") or "").lower()), fs=_DF_FS.get(str(r.get("fs") or "").lower()),
              rank=str(r.get("rate") or "").lower() or None)
    base = sid % 10000
    s.music_id = base + 10000 if s.type == "dx" else base
    s.rating = int(float(r.get("dx_rating") or 0))
    return s


def lx_profile(d: dict) -> Profile:
    trophy = d.get("trophy") or {}
    icon = d.get("icon") or {}
    plate = d.get("name_plate") or {}
    frame = d.get("frame") or {}
    color = str(trophy.get("color") or "normal").lower()
    cls = d.get("class_rank")
    return Profile(name=d.get("name") or "", rating=int(d.get("rating") or 0), title=trophy.get("name") or "",
                   title_kind=_LX_TITLE_KIND.get(color, "normal"),
                   icon_url=LX_ICON.format(id=icon["id"]) if icon.get("id") is not None else "",
                   plate_url=LX_PLATE.format(id=plate["id"]) if plate.get("id") is not None else "",
                   frame_url=LX_FRAME.format(id=frame["id"]) if frame.get("id") is not None else "",
                   # 阶级（B5 … LEGEND）：落雪给的是游戏里的编号，图用本地 themes/icons/class_NN.png
                   class_rank=f"icon:class_{int(cls):02d}" if isinstance(cls, int) and 0 <= cls <= 25 else "",
                   stars=d.get("star"), friend_code=str(d.get("friend_code") or ""), region="cn",
                   uploaded_at=str(d.get("upload_time") or ""))


def df_score(r: dict) -> Score:
    """One 水鱼 maimai record → Score (国服 constant / rating kept)."""
    ach = int(round(float(r.get("achievements") or 0) * 10000))
    li = int(r.get("level_index") or 0)
    s = Score(title=r.get("title") or "", type="dx" if str(r.get("type", "")).upper() == "DX" else "std",
              diff=_DF_DIFF[li] if 0 <= li < len(_DF_DIFF) else "master", level=str(r.get("level") or ""),
              ach=ach, dx=int(r.get("dxScore") or 0), fc=_DF_FC.get(str(r.get("fc") or "").lower()),
              fs=_DF_FS.get(str(r.get("fs") or "").lower()), rank=str(r.get("rate") or "").lower() or None)
    sid = r.get("song_id")
    s.music_id = int(sid) if str(sid or "").isdigit() else None
    s.ds = float(r["ds"]) if r.get("ds") is not None else None
    s.ds_exact = s.ds is not None
    s.rating = int(r.get("ra") or 0)
    return s


@dataclass
class Snapshot:
    region: str
    at: int
    profile: Profile | None
    scores: list[Score]
    target: dict | None = None
    version: str = ""        # 私服：玩家客户端对应的版本名（出图用）；其余服看曲库的当前版本
    rom: str = ""            # 私服：玩家客户端版本号

    def best50(self, catalog: CatalogStore) -> Best50:
        if self.region in API_REGIONS and self.target:
            # 查分器 / 私服 already split B35 / B15 with their own constants and ratings → keep their answer
            keys = {k: {tuple(x) for x in v} for k, v in self.target.items()}
            attach_charts(self.scores, catalog.db, catalog_region(self.region), keep_ds=True)
            old = [s for s in self.scores if s.key() in keys.get("old", set())]
            new = [s for s in self.scores if s.key() in keys.get("new", set())]
            from .calc.rating import _sort_key
            return Best50(region=self.region, old=sorted(old, key=_sort_key)[:35],
                          new=sorted(new, key=_sort_key)[:15], version=self.version, rom=self.rom)
        attach_charts(self.scores, catalog.db, self.region)
        return build_best50(self.scores, catalog.db, self.region)


class MaiService:
    def __init__(self, store: UserStore, catalog: CatalogStore, throttle: HostThrottle = THROTTLE,
                 transport=None):
        self.store = store
        self.catalog = catalog
        self.throttle = throttle
        self.transport = transport
        self.df_transport = None   # tests inject a mock transport for 水鱼
        self.lx_transport = None   # … and for 落雪
        self.lx_dev = ""           # 落雪开发者令牌：有它就能按 QQ 查国服，不用每个人去申请个人密钥
        self.lx_oauth = None       # core.lxoauth.LxOAuth：网页上点授权（main 里设置）
        try:
            from ..core.lxns import SongIndex
        except ImportError:  # tests import mai as a top-level package
            from core.lxns import SongIndex
        self.lx_songs = SongIndex("maimai", store.root)
        self.priv = None           # core.privsrv.Hub（main 里设置）；私服绑定舞萌中二共用
        self._sessions: dict[tuple[str, str], tuple[NetSession, float]] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    # ---------- sessions ----------
    def _lock(self, key) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _creds(self, uid: str, region: str) -> Credentials:
        c = self.store.get_creds(uid, region)
        if not c:
            raise NotBound(region)
        return Credentials(region=region, clal=c.get("clal", ""), sega_id=c.get("sega_id", ""),
                           password=c.get("password", ""), aime_idx=int(c.get("aime_idx", 0)))

    def _session(self, uid: str, region: str) -> NetSession:
        key = (uid, region)
        now = time.time()
        hit = self._sessions.get(key)
        if hit and now - hit[1] < SESSION_IDLE:
            self._sessions[key] = (hit[0], now)
            return hit[0]
        s = NetSession(self._creds(uid, region), throttle=self.throttle, transport=self.transport)
        self._sessions[key] = (s, now)
        return s

    async def drop_session(self, uid: str, region: str) -> None:
        hit = self._sessions.pop((uid, region), None)
        if hit:
            await hit[0].close()

    # ---------- which servers this user can query ----------
    def bound_regions(self, uid: str) -> list[str]:
        """NET / 国服绑定（UserStore）+ 私服绑定（舞萌中二共用）。"""
        out = self.store.bound_regions(uid)
        if self.priv is not None:
            out += [r for r in self.priv.bindings.bound(uid) if r in PRIV_REGIONS and r not in out]
        return out

    def default_region(self, uid: str) -> str:
        bound = self.bound_regions(uid)
        r = self.store.load(uid).get("default_region") or ""     # /mai 切换 也可能存的是私服
        return r if r in bound else (bound[0] if bound else "")

    async def _get(self, uid: str, region: str, path: str) -> str:
        if region == "cn":
            raise NotSupported("国服数据来自水鱼 / 落雪查分器，这个功能要用国际服或日服（最近游玩详情 / 好友码要查 NET）")
        if region in PRIV_REGIONS:
            raise NotSupported(f"{REGION_NAMES[region]} 只提供 B50 和最近 50 条记录，这个功能要用国际服或日服")
        s = self._session(uid, region)
        html = await s.get(path)
        if s.clal_changed:  # password login produced a fresh clal → keep it for next time
            c = self.store.get_creds(uid, region) or {}
            c["clal"] = s.creds.clal
            self.store.set_creds(uid, region, c)
            s.clal_changed = False
        return html

    # ---------- binding test ----------
    # ---------- 国服 via 水鱼 / 落雪 ----------
    @staticmethod
    def cn_source(binding: dict | None) -> str:
        src = (binding or {}).get("source")
        if src == "lxoauth":       # OAuth 授权和个人密钥用的是同一套个人 API
            return "lx"
        return src if src in ("lx", "lxqq") else "df"

    async def lx_bearer(self, binding: dict) -> str:
        """个人 API 用的令牌：个人密钥，或 OAuth 的 access_token（自动续期）。"""
        if (binding or {}).get("source") == "lxoauth":
            try:
                from ..core.lxoauth import OAuthExpired
            except ImportError:
                from core.lxoauth import OAuthExpired
            if self.lx_oauth is None:
                raise NotSupported("落雪授权没有启用（bot 主人没配置 OAuth 应用）")
            try:
                return await self.lx_oauth.access(binding.get("qq") or "")
            except OAuthExpired as e:
                raise NotSupported(f"{e}。发「/网页绑定」→ 国服 → 落雪授权，重新点一下授权") from e
        return (binding or {}).get("token") or ""

    async def bind_cn_qq(self, uid: str) -> Profile:
        """开发者令牌按 QQ 找落雪账号，找到就记下（不存任何密钥）。"""
        try:
            from ..core import lxns as LX
        except ImportError:
            from core import lxns as LX
        pdata = await LX.player_by_qq("maimai", uid, self.lx_dev, transport=self.lx_transport)
        prof = lx_profile(pdata)
        self.store.set_creds(uid, "cn", {"source": "lxqq", "qq": str(uid), "friend_code": prof.friend_code,
                                         "username": prof.name})
        return prof

    async def _cn_fetch(self, binding: dict) -> tuple[Profile, list[Score], dict]:
        if self.cn_source(binding) == "lx":
            return await self._lx_fetch(binding)
        if self.cn_source(binding) == "lxqq":
            return await self._lxqq_fetch(binding)
        try:
            from ..core import divingfish as DF
        except ImportError:  # tests import mai as a top-level package
            from core import divingfish as DF
        data = await DF.mai_player(binding, transport=self.df_transport)
        prof = Profile(name=data.get("nickname") or binding.get("username") or "", rating=int(data.get("rating") or 0),
                       title=data.get("plate") or "", region="cn")
        charts = data.get("charts") or {}
        scores: list[Score] = []
        split: dict[str, list] = {"old": [], "new": []}
        for sec, key in (("sd", "old"), ("dx", "new")):
            for r in charts.get(sec) or []:
                s = df_score(r)
                scores.append(s)
                split[key].append(list(s.key()))
        return prof, scores, split

    async def _lx_fetch(self, binding: dict) -> tuple[Profile, list[Score], dict]:
        """落雪 personal API: profile + every score; old / new split by chart version on the 国服 song list."""
        try:
            from ..core import lxns as LX
        except ImportError:
            from core import lxns as LX
        token = await self.lx_bearer(binding)
        pdata, raw, _ok = await asyncio.gather(
            LX.player("maimai", token, transport=self.lx_transport),
            LX.scores("maimai", token, transport=self.lx_transport),
            self.lx_songs.ensure())
        prof = lx_profile(pdata)
        scores: list[Score] = []
        split: dict[str, list] = {"old": [], "new": []}
        db = self.catalog.db
        for r in raw:
            s = lx_score(r)
            if s is None:
                continue
            li = _LX_DIFF.index(s.diff)
            hit = self.lx_songs.get(s.music_id or 0, "dx" if s.type == "dx" else "standard", li)
            if hit and hit[0] is not None:
                s.ds, s.ds_exact = hit[0], True
            new = self.lx_songs.is_new(s.music_id or 0, "dx" if s.type == "dx" else "standard", li)
            if new is None and db is not None:      # song list unavailable → fall back to DXRating's 国服 version
                song = db.by_music_id(s.music_id) if s.music_id else None
                chart = song.chart(s.type, s.diff) if song else None
                new = bool(chart is not None and db.is_new(chart, "cn"))
                if s.ds is None and chart is not None and chart.ds is not None:
                    s.ds, s.ds_exact = chart.ds_in("cn", db.current_version.get("cn")), True
            if s.ds is None:               # keep 落雪's rating; only the shown constant is an estimate
                from .calc.rating import estimate_ds
                s.ds, s.ds_exact = estimate_ds(s.level), False
            scores.append(s)
            split["new" if new else "old"].append(list(s.key()))
        return prof, scores, split

    async def _lxqq_fetch(self, binding: dict) -> tuple[Profile, list[Score], dict]:
        """落雪开发者 API：资料 + 落雪算好的 B35 / B15（再带上候补 selections）。只有这 60 来首，没有全部成绩。"""
        try:
            from ..core import lxns as LX
        except ImportError:
            from core import lxns as LX
        if not self.lx_dev:
            raise NotSupported("bot 主人还没配置落雪开发者令牌；可以私聊「/mai 绑定 落雪 <个人API密钥>」")
        fc = binding.get("friend_code")
        if not fc:
            pdata = await LX.player_by_qq("maimai", binding.get("qq") or "", self.lx_dev, transport=self.lx_transport)
            fc = pdata.get("friend_code")
        pdata, best, _ok = await asyncio.gather(
            LX.dev_player("maimai", fc, self.lx_dev, transport=self.lx_transport),
            LX.dev_bests("maimai", fc, self.lx_dev, transport=self.lx_transport),
            self.lx_songs.ensure())
        prof = lx_profile(pdata)
        scores: list[Score] = []
        split: dict[str, list] = {"old": [], "new": []}
        seen = set()
        for sec, key, in_b50 in (("standard", "old", True), ("dx", "new", True),
                                 ("standard_selections", "old", False), ("dx_selections", "new", False)):
            for r in best.get(sec) or []:
                s = lx_score(r)
                if s is None or s.key() in seen:
                    continue
                seen.add(s.key())
                li = _LX_DIFF.index(s.diff)
                hit = self.lx_songs.get(s.music_id or 0, "dx" if s.type == "dx" else "standard", li)
                if hit and hit[0] is not None:
                    s.ds, s.ds_exact = hit[0], True
                if s.ds is None:
                    from .calc.rating import estimate_ds
                    s.ds, s.ds_exact = estimate_ds(s.level), False
                scores.append(s)
                if in_b50:
                    split[key].append(list(s.key()))
        return prof, scores, split

    def cn_uploaded_at(self, uid: str) -> str:
        """国服（落雪）上次上传时间（ISO）：看已经拉到的快照，或 /mai 更新 单独拉资料时记下的；水鱼 / 没查过 → ''。"""
        snap = self.cached(uid, "cn")
        seen = self.__dict__.setdefault("_cn_upload_seen", {})
        return (getattr(snap.profile, "uploaded_at", "") if snap and snap.profile else "") or seen.get(uid, "")

    def remember_cn_uploaded(self, uid: str, iso: str) -> None:
        self.__dict__.setdefault("_cn_upload_seen", {})[uid] = iso

    async def cn_recent(self, uid: str) -> list[dict]:
        """落雪 recent plays (raw dicts) if 落雪 offers them for this key; NotSupported otherwise."""
        binding = self.store.get_creds(uid, "cn")
        if not binding:
            raise NotBound("cn")
        if self.cn_source(binding) == "lxqq":
            raise NotSupported("按 QQ 查落雪拿不到最近游玩；发「/网页绑定」选「落雪授权」（或私聊绑个人密钥）就能看")
        if self.cn_source(binding) != "lx":
            raise NotSupported("水鱼查分器没有最近游玩记录；绑定落雪（/mai 绑定 落雪 <个人API密钥>）可以试试")
        try:
            from ..core import lxns as LX
        except ImportError:
            from core import lxns as LX
        try:
            return await LX.recents("maimai", await self.lx_bearer(binding), transport=self.lx_transport)
        except LX.LxnsError as e:
            raise NotSupported(f"落雪没有给出最近游玩（{e}）") from e

    # ---------- 私服 ----------
    def _priv_client(self, region: str):
        if self.priv is None:
            raise NotSupported("私服查分没有启用")
        return self.priv.client(region)

    async def priv_profile(self, region: str, username: str):
        """绑定前验证用户名：→ core.privsrv 的 PrivProfile。"""
        prof, _privacy = await self._priv_client(region).profile(username, "mai2")
        return prof

    async def _priv_sync(self, uid: str, region: str) -> Snapshot:
        from . import privsrv as PV
        client = self._priv_client(region)
        pprof, best = await client.mai_best(self.priv.cred(uid, region, "mai"))
        prof = PV.to_profile(pprof, region)
        version = PV.version_of(pprof)
        scores, split = PV.to_scores(best, self.catalog.db, version)
        self.store.save_snapshot(uid, region, prof, scores,
                                 {"target": split, "version": version, "rom": pprof.rom_version or ""})
        return Snapshot(region, int(time.time()), prof, scores, split, version, pprof.rom_version or "")

    async def priv_recent(self, uid: str, region: str) -> list[RecentPlay]:
        from . import privsrv as PV
        client = self._priv_client(region)
        _prof, plays = await client.mai_recent(self.priv.cred(uid, region, "mai"))
        return PV.to_recent(plays, self.catalog.db)

    async def verify(self, region: str, creds: dict) -> Profile:
        """Log in with fresh credentials (not yet stored) and return the profile."""
        if region == "cn":
            return (await self._cn_fetch(creds))[0]
        c = Credentials(region=region, clal=creds.get("clal", ""), sega_id=creds.get("sega_id", ""),
                        password=creds.get("password", ""), aime_idx=int(creds.get("aime_idx", 0)))
        s = NetSession(c, throttle=self.throttle, transport=self.transport)
        try:
            html = await s.get(P_PLAYER)
            prof = parse_profile(html, region)
            if s.clal_changed:
                creds["clal"] = s.creds.clal
            return prof
        finally:
            await s.close()

    # ---------- data ----------
    async def sync(self, uid: str, region: str, *, with_target: bool = True) -> Snapshot:
        if region in PRIV_REGIONS:
            return await self._priv_sync(uid, region)
        if region == "cn":
            binding = self.store.get_creds(uid, "cn")
            if not binding and self.lx_dev and str(uid).isdigit():
                miss = self.__dict__.setdefault("_qq_miss", {})
                hit = miss.get(uid)
                if hit and time.time() - hit[0] < QQ_MISS_TTL:   # 10 分钟内找过没找到：别每次都去问落雪
                    raise NotBound("cn", hit[1])
                try:            # 没绑过国服：先用开发者令牌按 QQ 找落雪账号
                    await self.bind_cn_qq(uid)
                    binding = self.store.get_creds(uid, "cn")
                    miss.pop(uid, None)
                except Exception as e:  # noqa: BLE001
                    why = f"按 QQ 在落雪没找到你（{e}）"
                    miss[uid] = (time.time(), why)
                    raise NotBound("cn", why) from e
            if not binding:
                raise NotBound("cn")
            prof, scores, split = await self._cn_fetch(binding)
            self.store.save_snapshot(uid, "cn", prof, scores, {"target": split})
            return Snapshot("cn", int(time.time()), prof, scores, split)
        async with self._lock((uid, region)):
            prof = parse_profile(await self._get(uid, region, P_PLAYER), region)
            await self._cache_images(uid, region, prof)
            scores: list[Score] = []
            for d in DIFFS:
                scores += parse_score_list(await self._get(uid, region, p_scores(DIFF_INDEX[d])))
            target = None
            if with_target:
                try:
                    target = parse_rating_target(await self._get(uid, region, P_TARGET))
                    have = {s.key() for s in scores}
                    for sec in ("new", "old"):
                        for s in target.get(sec, []):
                            if s.key() not in have:  # hidden / deleted songs still count on NET
                                s.genre = s.genre or ""
                                scores.append(s)
                                have.add(s.key())
                except Exception:
                    target = None
            attach_charts(scores, self.catalog.db, region)
            extra = {"target": {k: [x.key() for x in v] for k, v in (target or {}).items()}} if target else {}
            self.store.save_snapshot(uid, region, prof, scores, extra)
            return Snapshot(region, int(time.time()), prof, scores, extra.get("target"))

    async def _cache_images(self, uid: str, region: str, prof: Profile) -> None:
        """NET avatar / 段位 / class images need the NET TLS fix (and sometimes the session), so fetch them
        here once and let the renderer read the local copies (avatars/<sha1(url)>.png)."""
        import hashlib
        import os
        folder = os.path.join(self.store.root, "avatars")
        os.makedirs(folder, exist_ok=True)
        for url in (prof.icon_url, prof.course_rank, prof.class_rank):
            if not url or not url.startswith("http"):
                continue
            path = os.path.join(folder, hashlib.sha1(url.encode()).hexdigest() + ".png")
            if os.path.exists(path):
                continue
            try:
                data = await self._session(uid, region).get_bytes(url)
                if data[:4] == b"\x89PNG" or data[:3] == b"\xff\xd8\xff":
                    with open(path, "wb") as f:
                        f.write(data)
            except Exception:
                pass

    def cached(self, uid: str, region: str) -> Snapshot | None:
        hit = self.store.load_snapshot(uid, region)
        if not hit:
            return None
        at, prof, scores, raw = hit
        return Snapshot(region, at, prof, scores, raw.get("target"), raw.get("version") or "", raw.get("rom") or "")

    async def profile(self, uid: str, region: str) -> Profile:
        return parse_profile(await self._get(uid, region, P_PLAYER), region)

    async def recent(self, uid: str, region: str) -> list[RecentPlay]:
        return parse_recent(await self._get(uid, region, P_RECORD))

    async def playlog(self, uid: str, region: str, idx: str) -> PlaylogDetail:
        return parse_playlog_detail(await self._get(uid, region, p_playlog(idx)))

    async def friend_card(self, uid: str, region: str, code: str) -> Profile | None:
        return parse_friend_search(await self._get(uid, region, p_friend_search(code)), region)

    async def home_ok(self, uid: str, region: str) -> bool:
        return "name_block" in await self._get(uid, region, P_HOME)
