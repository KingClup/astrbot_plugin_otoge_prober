"""曲目 / 定数库。

主数据源：chunithm.beerpsi.cc/songs（chuni-penguin 公开接口；带国际服可用性、来源版本、发布日期，跟版本最快）。
备用数据源：Tachi 的 CHUNITHM 种子数据（GitHub raw，带国际服版本标签 *-intl）。
当前国际服版本 = 国际服可玩曲目里发布日期最新那首的来源版本（Tachi 时用最新的 *-intl 标签）。
下载后缓存到插件数据目录，默认 24 小时刷新一次；下载失败时继续用旧缓存。
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import httpx

try:
    from ..mai.data.fuzzy import FuzzyIndex, Match
except ImportError:  # tests import the subpackages top-level
    from mai.data.fuzzy import FuzzyIndex, Match
from .models import Difficulty

log = logging.getLogger("chuni_intl.songdb")

TACHI_CHARTS = "https://raw.githubusercontent.com/zkldi/Tachi/refs/heads/main/db/seeds/charts-chunithm.json"
TACHI_SONGS = "https://raw.githubusercontent.com/zkldi/Tachi/refs/heads/main/db/seeds/songs-chunithm.json"
BEERPSI_SONGS = "https://chunithm.beerpsi.cc/songs"

TACHI_VERSION_NAMES = {
    "sun": "SUN", "sunplus": "SUN PLUS", "luminous": "LUMINOUS", "luminousplus": "LUMINOUS PLUS",
    "verse": "VERSE", "xverse": "X-VERSE", "xversex": "X-VERSE-X", "mate": "Mate",
}

_TACHI_DIFF = {
    "BASIC": Difficulty.BASIC,
    "ADVANCED": Difficulty.ADVANCED,
    "EXPERT": Difficulty.EXPERT,
    "MASTER": Difficulty.MASTER,
    "ULTIMA": Difficulty.ULTIMA,
}
_BEERPSI_DIFF = {
    "BAS": Difficulty.BASIC,
    "ADV": Difficulty.ADVANCED,
    "EXP": Difficulty.EXPERT,
    "MAS": Difficulty.MASTER,
    "ULT": Difficulty.ULTIMA,
}


def _tachi_rank(name: str, order: list[str]) -> int:
    inv = {v: k for k, v in TACHI_VERSION_NAMES.items()}
    tag = inv.get(name, name)
    return order.index(tag) if tag in order else len(order)


@dataclass(slots=True)
class ChartInfo:
    difficulty: Difficulty
    level: str
    const: float | None
    charter: str = ""
    notes: dict = field(default_factory=dict)


@dataclass(slots=True)
class SongInfo:
    id: int
    title: str
    artist: str = ""
    aliases: list[str] = field(default_factory=list)
    intl: bool = True
    version: str | None = None
    release_date: str | None = None
    jacket_url: str | None = None  # beerpsi 给的曲绘地址（国际服独占 / 已删除曲也有）
    charts: dict[Difficulty, ChartInfo] = field(default_factory=dict)
    genre: str = ""
    bpm: float | None = None
    from_otoge: bool = False          # 曲库里原本没有、由 otoge-db 补进来的（core/progress + chuni/augment）


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s\-_~〜・'\"!?！？.,:;()\[\]（）「」『』]", "", s)


class SongDB:
    def __init__(self, cache_dir: Path, refresh_hours: float = 24, alias_file: Path | None = None,
                 primary: str = "beerpsi"):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_seconds = refresh_hours * 3600
        self.alias_file = alias_file
        self.songs: dict[int, SongInfo] = {}
        self.source = "未加载"
        self.intl_version: str | None = None
        self.current_version: str | None = None
        self.primary = primary
        self._title_index: dict[str, int] = {}
        self._fuzzy = None
        self.extra_aliases: dict[int, list[str]] = {}
        self._loaded_at = 0.0
        self.post_load: list = []          # 每次（重新）加载完调用：用 otoge-db / 官方曲目表补新歌（core/progress）

    # ---------- 加载 ----------

    def _cache(self, name: str) -> Path:
        return self.cache_dir / name

    async def _download(self, client: httpx.AsyncClient, url: str, dest: Path) -> None:
        r = await client.get(url, timeout=60, follow_redirects=True)
        r.raise_for_status()
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(r.content)
        tmp.replace(dest)

    def _is_fresh(self, p: Path) -> bool:
        return p.exists() and time.time() - p.stat().st_mtime < self.refresh_seconds

    async def ensure_loaded(self, force: bool = False) -> None:
        if self.songs and not force and time.time() - self._loaded_at < self.refresh_seconds:
            return
        order = ["beerpsi", "tachi"] if self.primary != "tachi" else ["tachi", "beerpsi"]
        async with httpx.AsyncClient(headers={"user-agent": "astrbot-plugin-chuni-intl"}) as client:
            for src in order:
                try:
                    if src == "beerpsi":
                        p = self._cache("beerpsi-songs.json")
                        if force or not self._is_fresh(p):
                            try:
                                await self._download(client, BEERPSI_SONGS, p)
                            except Exception as e:  # noqa: BLE001
                                log.warning("beerpsi 曲库下载失败，尝试缓存: %s", e)
                        if p.exists():
                            self.load_beerpsi(json.loads(p.read_text("utf-8")))
                            self._after_load()
                            return
                    else:
                        cp, sp = self._cache("tachi-charts.json"), self._cache("tachi-songs.json")
                        if force or not (self._is_fresh(cp) and self._is_fresh(sp)):
                            try:
                                await self._download(client, TACHI_CHARTS, cp)
                                await self._download(client, TACHI_SONGS, sp)
                            except Exception as e:  # noqa: BLE001
                                log.warning("Tachi 曲库下载失败，尝试缓存: %s", e)
                        if cp.exists() and sp.exists():
                            self.load_tachi(json.loads(sp.read_text("utf-8")), json.loads(cp.read_text("utf-8")))
                            self._after_load()
                            return
                except Exception as e:  # noqa: BLE001
                    log.warning("%s 曲库解析失败: %s", src, e)
        raise RuntimeError("曲库不可用：两个数据源都下载失败，且没有本地缓存")

    def _after_load(self) -> None:
        for fn in self.post_load:
            try:
                fn(self)
            except Exception as e:  # noqa: BLE001
                log.warning("曲库补充失败: %s", e)
        self._load_user_aliases()
        self._build_index()
        self._loaded_at = time.time()
        log.info("曲库已加载: %s, %d 首", self.source, len(self.songs))

    def load_tachi(self, songs: list[dict], charts: list[dict]) -> None:
        legacy = {s["id"]: s for s in songs}
        # 找出最新的国际服版本标签，例如 xversex-intl
        intl_tags = {v for c in charts for v in c.get("versions", []) if v.endswith("-intl")}
        order = ["sun", "sunplus", "luminous", "luminousplus", "verse", "xverse", "xversex", "mate"]

        def rank(tag: str) -> int:
            base = tag[: -len("-intl")]
            return order.index(base) if base in order else len(order) + len(base)

        latest = max(intl_tags, key=rank) if intl_tags else None
        self.intl_version = latest

        out: dict[int, SongInfo] = {}
        for c in charts:
            diff = _TACHI_DIFF.get(c.get("difficulty", ""))
            if diff is None or not c.get("isPrimary", True):
                continue  # 跳过 WORLD'S END 和非主谱面
            data = c.get("data") or {}
            sid = data.get("inGameID")
            song = legacy.get(c.get("songID"))
            if sid is None or song is None:
                continue
            info = out.get(sid)
            if info is None:
                info = out[sid] = SongInfo(
                    id=int(sid),
                    title=song["title"],
                    artist=song.get("artist", ""),
                    aliases=list(song.get("altTitles", [])) + list(song.get("searchTerms", [])),
                    intl=False,
                    genre=str((song.get("data") or {}).get("genre") or ""),
                )
            if latest and latest in c.get("versions", []):
                info.intl = True
            # 歌曲出现的版本 = 谱面版本标签里最早的那个（新曲 N20 / b50 sample 要用）
            jp_tags = [v for v in c.get("versions", []) if "-" not in v and v in order]
            if jp_tags:
                first = min(jp_tags, key=order.index)
                name = TACHI_VERSION_NAMES.get(first, first)
                if info.version is None or order.index(first) < _tachi_rank(info.version, order):
                    info.version = name
            # 优先使用国际服版本记录的定数
            hist = (data.get("levelHistory") or {}).get(latest or "") or {}
            const = hist.get("levelNum", c.get("levelNum"))
            level = hist.get("level", c.get("level", "?"))
            info.charts[diff] = ChartInfo(diff, str(level), float(const) if const is not None else None)
        self.songs = out
        self.source = f"Tachi ({latest or '无国际服标签'})"
        if latest:
            base = latest[: -len("-intl")]
            self.current_version = TACHI_VERSION_NAMES.get(base, base)

    def load_beerpsi(self, songs: list[dict]) -> None:
        out: dict[int, SongInfo] = {}
        for s in songs:
            info = SongInfo(
                id=int(s["id"]),
                title=s["title"],
                artist=s.get("artist", ""),
                aliases=list(s.get("aliases", [])),
                intl=bool((s.get("availablility") or s.get("availability") or {}).get("intl", True)),
                version=s.get("version"),
                release_date=s.get("release_date"),
                jacket_url=s.get("jacket_url") if str(s.get("jacket_url") or "").startswith("http") else None,
                genre=str(s.get("genre") or s.get("category") or ""),
                bpm=_num(s.get("bpm")),
            )
            for c in s.get("charts", []):
                diff = _BEERPSI_DIFF.get(c.get("difficulty", ""))
                if diff is None:
                    continue
                const = c.get("const")
                notes = c.get("notecounts") or c.get("note_counts") or c.get("notes") or {}
                info.charts[diff] = ChartInfo(diff, str(c.get("level", "?")), float(const) if const else None,
                                              charter=str(c.get("charter") or c.get("designer") or ""),
                                              notes=notes if isinstance(notes, dict) else {})
            out[info.id] = info
        self.songs = out
        intl_songs = [x for x in out.values() if x.intl and x.release_date and x.version]
        self.current_version = max(intl_songs, key=lambda x: x.release_date).version if intl_songs else None
        self.source = f"chunithm.beerpsi.cc ({self.current_version or '?'})"

    def _load_user_aliases(self) -> None:
        """aliases.json: {"别名": 曲目ID, ...}"""
        if not self.alias_file or not self.alias_file.exists():
            return
        try:
            data = json.loads(self.alias_file.read_text("utf-8"))
        except Exception as e:  # noqa: BLE001
            log.warning("别名文件读取失败: %s", e)
            return
        for alias, sid in data.items():
            if (song := self.songs.get(int(sid))) is not None:
                song.aliases.append(alias)

    def _build_index(self) -> None:
        idx: dict[str, int] = {}
        for s in self.songs.values():          # titles first so an alias never hides a real title
            if key := normalize(s.title):
                idx.setdefault(key, s.id)
        fz = FuzzyIndex()
        for s in self.songs.values():
            extra = [a for a in self.extra_aliases.get(s.id, []) if a.lower() not in {x.lower() for x in s.aliases}]
            names = [*s.aliases, *extra]
            for name in names:
                if key := normalize(name):
                    idx.setdefault(key, s.id)
            fz.add(s.id, s, s.title, names)
        self._title_index = idx
        self._fuzzy = fz

    def reindex(self) -> None:
        """补完新歌后重建标题 / 模糊索引。"""
        self._build_index()

    def apply_aliases(self, extra: dict[int, list[str]]) -> None:
        """Community nicknames keyed by official song id (落雪 / Yuzuchan / local)."""
        self.extra_aliases = extra or {}
        if self.songs:
            self._build_index()

    def aliases_of(self, song: SongInfo) -> list[str]:
        out, low = [], {song.title.lower()}
        for a in [*song.aliases, *self.extra_aliases.get(song.id, [])]:
            if a.lower() not in low:
                low.add(a.lower())
                out.append(a)
        return out

    def search_ranked(self, query: str, limit: int = 8) -> list[Match]:
        q = query.strip()
        if q.isdigit() and int(q) in self.songs:
            s = self.songs[int(q)]
            return [Match(100, s, s.title, False)]
        return self._fuzzy.search(q, limit) if self._fuzzy is not None else []

    # ---------- 查询 ----------

    def get(self, song_id: int | None) -> SongInfo | None:
        return self.songs.get(song_id) if song_id is not None else None

    def by_title(self, title: str) -> SongInfo | None:
        sid = self._title_index.get(normalize(title))
        return self.songs.get(sid) if sid is not None else None

    def search(self, query: str, limit: int = 5) -> list[SongInfo]:
        return [m.item for m in self.search_ranked(query, limit)]

    def charts_by_const(self, lo: float, hi: float, const_of=None) -> list[tuple[SongInfo, ChartInfo, float]]:
        """All charts whose constant (for the chosen server, via const_of(song, chart)) is in [lo, hi]."""
        out = []
        for s in self.songs.values():
            for ch in s.charts.values():
                v = const_of(s, ch) if const_of else (ch.const if s.intl else None)
                if v is not None and lo - 1e-9 <= v <= hi + 1e-9:
                    out.append((s, ch, v))
        out.sort(key=lambda x: (x[2], x[0].title))
        return out

    def fill(self, score) -> None:
        """给 Score 补上定数和等级；列表页没有曲目 ID 时按标题匹配。"""
        song = self.get(score.song_id) or self.by_title(score.title)
        if song is None:
            return
        if score.song_id is None:
            score.song_id = song.id
        chart = song.charts.get(score.difficulty)
        if chart is not None:
            score.const = chart.const
            score.level = chart.level
