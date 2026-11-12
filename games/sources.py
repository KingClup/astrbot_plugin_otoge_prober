"""Where the games get their songs, jackets and chart pictures from (the plugin's existing data stores).

Every source turns its own song database into games.core.Song objects. Song lists are cached for a few minutes
(building them walks a couple of thousand songs; a game start should be instant).
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

from PIL import Image

from .core import Chart, Song, norm


def _tkey(title: str) -> str:
    return norm(title)

MAI_DIFF = {"basic": "BASIC", "advanced": "ADVANCED", "expert": "EXPERT", "master": "MASTER", "remaster": "Re:MASTER"}
CHU_KEY = {0: "bsc", 1: "adv", 2: "exp", 3: "mst", 4: "ult"}
CHU_LABEL = {"bsc": "BASIC", "adv": "ADVANCED", "exp": "EXPERT", "mst": "MASTER", "ult": "ULTIMA"}
GEKI_LABEL = {"bsc": "BASIC", "adv": "ADVANCED", "exp": "EXPERT", "mst": "MASTER", "lun": "LUNATIC"}
GEKI_GAME_DIFF = {"bsc": 0, "adv": 1, "exp": 2, "mst": 3, "lun": 10}
CHART_KEYS = {"chu": ("bsc", "adv", "exp", "mst", "ult"), "geki": ("bsc", "adv", "exp", "mst", "lun"),
              "sdvx": ("nov", "adv", "exh", "mxm"), "pjsk": ("esy", "nml", "hrd", "exp", "mst", "apd")}
SONG_TTL = 600


def _open(path) -> Image.Image | None:
    try:
        if path and os.path.exists(path) and os.path.getsize(path) > 0:
            with Image.open(path) as im:
                return im.convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    return None


def _level_num(game: str, raw: str) -> float | None:
    """sdvx.in level text → number used for ranges (sdvx 4th "h184" → 18.4; "14+" → 14)."""
    lv = (raw or "").lstrip("_")
    m = re.search(r"(\d+)(\.\d+)?", lv)
    if not m:
        return None
    digits = m.group(1)
    if game == "sdvx" and len(digits) == 3 and not m.group(2):
        return int(digits) / 10
    return float(digits + (m.group(2) or ""))


class GameData:
    """Adapter over the plugin (`p` = the Star instance). Everything is looked up lazily, so tests can pass a
    stub with only the attributes a test needs."""

    def __init__(self, p):
        self.p = p
        self._cache: dict[tuple, tuple[float, list[Song]]] = {}

    def _cached(self, key, build) -> list[Song]:
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < SONG_TTL:
            return hit[1]
        songs = build()
        self._cache[key] = (time.time(), songs)
        return songs

    # ------------------------------------------------------------ song lists (开字母 / 猜曲绘)
    def songs(self, game: str, region: str = "jp") -> list[Song]:
        if game == "mai":
            return self._cached(("mai", region), lambda: self._mai(region))
        if game == "chu":
            return self._cached(("chu", region), lambda: self._chu(region))
        if game == "geki":
            return self._cached(("geki",), self._geki)
        if game in ("sdvx", "pjsk"):                # 只有 sdvx.in 的曲目表；定数 = 等级
            return self.chart_songs(game)
        return []

    def borrowed_aliases(self) -> dict[str, list[str]]:
        """规范化歌名 → 舞萌 / 中二同名歌的外号。音击 / sdvx.in 自己几乎没有外号，
        同名歌（很多音击曲和中二、舞萌是同一首）就借过来。取不到的游戏跳过。"""
        hit = self._cache.get(("borrow",))
        if hit and time.time() - hit[0] < SONG_TTL:
            return hit[1]
        out: dict[str, list[str]] = {}
        for g in ("chu", "mai"):
            try:
                lst = self.songs(g)
            except Exception:  # noqa: BLE001  某个游戏数据没加载好就不借它的
                continue
            for song in lst:
                k = _tkey(song.title)
                if not k:
                    continue
                cur = out.setdefault(k, [])
                for a in song.aliases:
                    if a not in cur:
                        cur.append(a)
        self._cache[("borrow",)] = (time.time(), out)
        return out

    def _with_borrowed(self, title: str, own: list[str]) -> list[str]:
        out = list(own)
        for a in self.borrowed_aliases().get(_tkey(title), []):
            if a not in out:
                out.append(a)
        return out

    def versions(self, game: str) -> list[tuple[str, list[str]]]:
        """这个游戏的版本（按时间先后）和额外叫法；没有版本信息的游戏返回空列表。"""
        if game == "mai":
            db = self.p.catalog.db
            if db is None:
                return []
            return [(v, [db.version_abbr.get(v, "")]) for v in db.versions]
        if game == "chu":
            first: dict[str, int] = {}
            for s in self.songs("chu"):
                if s.version:
                    try:
                        first[s.version] = min(first.get(s.version, 10 ** 9), int(s.sid))
                    except ValueError:
                        first.setdefault(s.version, 10 ** 9)
            return [(v, []) for v in sorted(first, key=first.get)]
        return []

    @property
    def _sx(self):
        """sdvx.in client: ChartCommands keeps it as .src (main.py)."""
        c = self.p.charts
        return getattr(c, "src", None) or getattr(c, "sdvx")

    def _mai(self, region: str) -> list[Song]:
        db = self.p.catalog.db
        if db is None:
            return []
        rv = db.current_version.get(region)
        out = []
        for s in db.songs:
            charts = []
            for c in s.charts:
                if c.type == "utage" or not c.available(region):
                    continue
                kind = "DX" if c.type == "dx" else "标准"
                charts.append(Chart(f"{kind} {MAI_DIFF.get(c.diff, c.diff.upper())}", c.level_in(region),
                                    c.ds_in(region, rv), c))
            if charts:
                out.append(Song("mai", str(s.id), s.title, list(s.aliases), charts, s, version=s.version or ""))
        return out

    def _chu(self, region: str) -> list[Song]:
        """只出这个服现在还能玩的谱面。
        以前查不到这个服的定数时会退回曲库里的旧定数，结果已经删掉的曲（比如 SUN 删的 ]-[|/34<#!）
        也会被抽到（2026-11-07 群里实测踩坑）。现在：
          日服 / 国服：只认那个服的定数表（表里没有 = 这个服没有这张谱）；
          国际服、或者那个服的定数表还没加载：只认国际服还在的曲（song.intl）。"""
        svc = self.p.chu_svc
        db = svc.songdb
        table = {"jp": getattr(svc.consts, "jp", None), "cn": getattr(svc.consts, "cn", None)}.get(region)
        use_table = region in ("jp", "cn") and bool(table)
        out = []
        for s in db.songs.values():
            charts = []
            for d, ch in s.charts.items():
                if int(d) >= 5:                     # WORLD'S END has no constant
                    continue
                if use_table:
                    const = table.get((s.id, d))
                else:
                    const = ch.const if s.intl else None
                if const is None:                   # 这个服没有（删曲 / 还没上）→ 不抽
                    continue
                charts.append(Chart(CHU_LABEL[CHU_KEY[int(d)]], ch.level, const, (s, int(d))))
            if charts:
                out.append(Song("chu", str(s.id), s.title, db.aliases_of(s), charts, s, version=s.version or ""))
        return out

    def _geki(self) -> list[Song]:
        sx = self._sx
        entries = sx.entries.get("geki") or {}
        local = (sx.aliases.get("geki") or {}) if hasattr(sx, "aliases") else {}
        mdb = getattr(self.p.geki, "db", None)
        out = []
        for sid, e in entries.items():
            if e.removed:                                   # 音击只有日服（不分区服）
                continue
            charts = []
            for k in CHART_KEYS["geki"]:
                if not e.exists(k):
                    continue
                const = None
                if mdb is not None:
                    try:
                        song = mdb.match(e.title, e.artist, lunatic=(k == "lun"))
                        const = song.const(GEKI_GAME_DIFF[k], None) if song is not None else None
                    except Exception:  # noqa: BLE001
                        const = None
                charts.append(Chart(GEKI_LABEL[k], e.level_text(k), const, (e, k)))
            if charts:
                out.append(Song("geki", sid, e.title, self._with_borrowed(e.title, list(local.get(sid, []))), charts, e))
        return out

    # ------------------------------------------------------------ sdvx.in charts (猜谱面)
    def chart_songs(self, game: str, region: str = "jp") -> list[Song]:
        """region 只对中二有用：国服 / 国际服只出那个服有的歌，定数用那个服的。"""
        region = region if game == "chu" else "jp"
        key = ("chart", game) if region == "jp" else ("chart", game, region)
        return self._cached(key, lambda: self._chart_songs(game, region))

    def _chart_songs(self, game: str, region: str = "jp") -> list[Song]:
        sx = self._sx
        entries = sx.entries.get(game) or {}
        local = (sx.aliases.get(game) or {}) if hasattr(sx, "aliases") else {}
        consts = {}
        if game in ("chu", "geki"):
            for s in (self.songs(game, region) if game == "chu" else self.songs(game)):
                consts[s.title] = {c.diff: c.const for c in s.charts}
        aliases_from, versions_from = {}, {}
        if game == "chu":
            for s in self.songs("chu"):
                aliases_from[s.title] = s.aliases
                versions_from[s.title] = s.version
        out = []
        for sid, e in entries.items():
            if e.removed:
                continue
            charts = []
            for k in CHART_KEYS.get(game, ()):
                if not e.has_view(k):
                    continue
                label = e.diff_label(k)
                const = None
                if game == "chu":
                    const = (consts.get(e.title) or {}).get(CHU_LABEL[k])
                elif game == "geki":
                    const = (consts.get(e.title) or {}).get(GEKI_LABEL[k])
                if const is None and game == "chu" and region != "jp":
                    continue                                   # 这个服没有这张谱
                if const is None and game in ("sdvx", "pjsk"):
                    const = _level_num(game, e.level(k))
                charts.append(Chart(label, e.level_text(k), const, (e, k)))
            if charts:
                al = list(local.get(sid, [])) + list(aliases_from.get(e.title, []))
                if game in ("chu", "geki"):
                    al = self._with_borrowed(e.title, al)
                out.append(Song(game, sid, e.title, al, charts, e, version=versions_from.get(e.title, "")))
        return out

    async def ensure_charts(self, game: str) -> int:
        try:
            return await self._sx.ensure(game)
        except Exception:  # noqa: BLE001
            return len(self._sx.entries.get(game) or {})

    async def chart_picture(self, chart: Chart):
        """(full chart picture, measure rectangles in reading order) or None."""
        e, key = chart.ref
        return await self._sx.chart_measures(e, key)

    # ------------------------------------------------------------ jackets (猜曲绘)
    async def jacket(self, song: Song) -> Image.Image | None:
        if song.game == "mai":
            s = song.ref
            assets = self.p.cmd.renderer.assets if getattr(self.p.cmd, "renderer", None) else None
            if assets is None:
                return None
            for c in s.charts:
                if c.music_id:
                    p = os.path.join(assets.hdd_jackets, f"{int(c.music_id) % 10000:06d}.png")
                    if os.path.exists(p):
                        return _open(p)
            if not s.image:
                return None
            await asyncio.to_thread(assets.prefetch, [s.image])
            return _open(assets._cover_path(s.image))
        if song.game == "chu":
            s = song.ref
            got = await self.p.chu_svc.jackets.get_many([s.id], {s.id: s.jacket_url} if s.jacket_url else {})
            return _open(got.get(s.id))
        if song.game == "geki":
            got = await self._sx.geki_jackets([song.title], budget=20)
            return _open(got.get(song.title))
        if song.game in ("sdvx", "pjsk"):
            return _open(await self._sx.song_jacket(song.ref, budget=20))
        return None


def jacket_ok(path: Path | str | None) -> bool:
    return bool(path) and os.path.exists(path)
