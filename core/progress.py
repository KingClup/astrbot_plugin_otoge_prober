"""版本进度核实：每个游戏、每个服现在是哪个版本，曲库 / 定数跟上了没有。

社区曲库（DXRating、Tachi、beerpsi）经常比游戏晚几天到几周，所以这里另外拿几份"更快"的资料互相印证：

  官方曲目表   maimai.sega.jp / maimai.sega.com / chunithm.sega.jp / chunithm.sega.com 的 music json
               → 这个服现在能玩哪些歌（舞萌还带版本号 270xx = MAGiCAL）
  otoge-db     zvuc/otoge-db 的 music-ex.json（每天更新）→ 每首歌属于哪个版本 + 日服定数（中二新歌主要靠它）
  公告日期     下面 TIMELINE 里写死的已确认上线日期（只写查证过的）

当前版本 = 这几份证据里最新的那个（官方曲目表里这个版本的歌至少 MIN_SONGS 首才算）。
结果存 progress.json；版本一变，插件私聊通知机器人主人。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field

import httpx

log = logging.getLogger("astrbot")

OFFICIAL = {
    ("mai", "jp"): "https://maimai.sega.jp/data/maimai_songs.json",
    ("mai", "intl"): "https://maimai.sega.com/assets/data/maimai_songs.json",
    ("chu", "jp"): "https://chunithm.sega.jp/storage/json/music.json",
    ("chu", "intl"): "https://chunithm.sega.com/assets/data/music.json",
}
OTOGE_DB = {
    "chu": "https://raw.githubusercontent.com/zvuc/otoge-db/master/chunithm/data/music-ex.json",
    "mai": "https://raw.githubusercontent.com/zvuc/otoge-db/master/maimai/data/music-ex.json",
}
MIN_SONGS = 5          # 官方曲目表里某版本至少这么多首（不算宴），才认为这个服到了这个版本

# 已确认的上线日期（查证过的才写；没写的就靠官方曲目表 / 曲库判断）
TIMELINE = {
    ("mai", "jp"): [("CiRCLE", "2025-09-18"), ("CiRCLE PLUS", "2026-03-19"), ("MAGiCAL", "2026-09-17")],
    ("mai", "intl"): [("CiRCLE", "2026-01-22"), ("CiRCLE PLUS", "2026-07-23")],
    ("chu", "jp"): [("X-VERSE-X", "2025-12-11"), ("Mate", "2026-07-02")],
    ("chu", "intl"): [("X-VERSE-X", "2026-04-09"), ("Mate", "2026-10-22")],
}

# 舞萌官方曲目表的 version 是 5 位数：200xx = でらっくす，之后每个版本 +500
MAI_DX_NAMES = ["maimaiでらっくす", "maimaiでらっくす PLUS", "Splash", "Splash PLUS", "UNiVERSE", "UNiVERSE PLUS",
                "FESTiVAL", "FESTiVAL PLUS", "BUDDiES", "BUDDiES PLUS", "PRiSM", "PRiSM PLUS", "CiRCLE",
                "CiRCLE PLUS", "MAGiCAL"]

# 中二版本名统一成插件里用的写法（otoge-db 写 LUMINOUS+，Tachi 写 luminousplus，beerpsi 可能带 CHUNITHM 前缀）
CHU_ORDER = ["無印", "PLUS", "AIR", "AIR PLUS", "STAR", "STAR PLUS", "AMAZON", "AMAZON PLUS", "CRYSTAL", "CRYSTAL PLUS",
             "PARADISE", "PARADISE LOST", "NEW", "NEW PLUS", "SUN", "SUN PLUS", "LUMINOUS", "LUMINOUS PLUS", "VERSE",
             "X-VERSE", "X-VERSE-X", "Mate"]


def chu_key(v: str | None) -> str:
    """版本名 → 比较用的键：「CHUNITHM LUMINOUS+」「luminousplus」「LUMINOUS PLUS」都是 luminousplus。"""
    s = unicodedata.normalize("NFKC", str(v or "")).lower()
    s = s.replace("chunithm", "").replace("+", "plus").replace("×", "lost")
    return re.sub(r"[\s\-_]", "", s)


_CHU_CANON = {chu_key(n): n for n in CHU_ORDER}
_CHU_CANON.update({"paradise×": "PARADISE LOST", "paradiselost": "PARADISE LOST"})


def chu_name(v: str | None) -> str:
    return _CHU_CANON.get(chu_key(v), str(v or ""))


def chu_rank(v: str | None) -> int:
    k = chu_key(v)
    keys = [chu_key(n) for n in CHU_ORDER]
    return keys.index(k) if k in keys else -1


def mai_code_name(code: str) -> str:
    try:
        n = int(str(code)[:3])
    except ValueError:
        return ""
    if n < 200:
        return ""
    i = (n - 200) // 5
    return MAI_DX_NAMES[i] if i < len(MAI_DX_NAMES) else f"v{n}"


def mai_code_ver(code: str | int | None) -> str:
    """舞萌 5 位版本码 → 游戏版本号：27004 → '1.70'，25506 → '1.55'。"""
    try:
        n = int(str(code)[:3])
    except ValueError:
        return ""
    return f"1.{n - 200:02d}" if 200 <= n < 300 else ""


# 中二：客户端版本号（私服玩家实测 / 公开资料确认过的才写；X-VERSE、X-VERSE-X 还没查到可靠的对应）
CHU_VERSION_NUMBERS = {"LUMINOUS": "2.20", "LUMINOUS PLUS": "2.25", "VERSE": "2.30", "Mate": "2.50"}


def mai_rank(v: str | None, versions: list[str] | None = None) -> int:
    order = versions or MAI_DX_NAMES
    return order.index(v) if v in order else -1


@dataclass
class RegionProgress:
    game: str
    region: str
    current: str = ""
    official: str = ""            # 官方曲目表推断的版本
    official_new: int = 0         # 官方曲目表里当前版本的歌数
    official_total: int = 0
    timeline: str = ""            # 公告日期推断的版本
    catalog: str = ""             # 插件曲库（DXRating / Tachi / beerpsi）自己认为的版本
    code: str = ""                # 小版本号证据：舞萌官方曲目表里当前版本最新的 5 位码（27004 = Ver.1.70 第 04 批）
    notes: list[str] = field(default_factory=list)


@dataclass
class Progress:
    at: float = 0.0
    regions: dict[str, RegionProgress] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)       # 来源 → 「ok 1652 首 / 失败原因」+ 更新时间
    changes: list[str] = field(default_factory=list)

    def get(self, game: str, region: str) -> RegionProgress | None:
        return self.regions.get(f"{game}/{region}")


class ProgressTracker:
    def __init__(self, root: str, proxy: str | None = None, transport=None):
        self.dir = os.path.join(root, "progress")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "progress.json")
        self.proxy = proxy
        self.transport = transport
        self.official: dict[tuple[str, str], list[dict]] = {}
        self.otoge: dict[str, list[dict]] = {}
        self.state = self._load()
        self._lock = asyncio.Lock()

    # ---------- persistence ----------
    def _load(self) -> Progress:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            p = Progress(at=d.get("at", 0), sources=d.get("sources", {}), changes=d.get("changes", []))
            for k, v in (d.get("regions") or {}).items():
                p.regions[k] = RegionProgress(**v)
            return p
        except Exception:  # noqa: BLE001
            return Progress()

    def _save(self) -> None:
        d = {"at": self.state.at, "sources": self.state.sources, "changes": self.state.changes,
             "regions": {k: asdict(v) for k, v in self.state.regions.items()}}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def _cache_file(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def load_cached(self) -> None:
        """启动时先用上次下载的文件（不联网），让补曲库马上能用。"""
        for (g, r) in OFFICIAL:
            self.official[(g, r)] = self._read(f"official_{g}_{r}.json") or []
        for g in OTOGE_DB:
            self.otoge[g] = self._read(f"otogedb_{g}.json") or []

    def _read(self, name: str):
        try:
            with open(self._cache_file(name), encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return None

    # ---------- download ----------
    async def _fetch(self, c: httpx.AsyncClient, url: str, name: str, label: str,
                     max_age_hours: float | None = None) -> list[dict]:
        if max_age_hours is not None:
            try:
                if time.time() - os.path.getmtime(self._cache_file(name)) < max_age_hours * 3600:
                    old = self._read(name) or []
                    if old:
                        self.state.sources.setdefault(label, f"缓存 {len(old)} 首")
                        return old
            except OSError:
                pass
        try:
            r = await c.get(url, headers={"Referer": url.rsplit("/", 2)[0] + "/"})
            r.raise_for_status()
            data = json.loads(r.content.decode("utf-8-sig"))
            if not isinstance(data, list) or len(data) < 100:
                raise ValueError("内容不像曲目表")
            tmp = self._cache_file(name) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self._cache_file(name))
            self.state.sources[label] = f"ok {len(data)} 首 · {time.strftime('%m-%d %H:%M')}"
            return data
        except Exception as e:  # noqa: BLE001
            old = self._read(name) or []
            self.state.sources[label] = f"下载失败（{type(e).__name__}）" + (f"，用上次的 {len(old)} 首" if old else "")
            log.warning(f"[otoge] progress {label} 下载失败: {e}")
            return old

    async def download(self, max_age_hours: float | None = None) -> None:
        kw = {"proxy": self.proxy} if self.proxy else {}
        if self.transport is not None:
            kw = {"transport": self.transport}
        async with httpx.AsyncClient(timeout=40, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 (astrbot_plugin_otoge_prober)"}, **kw) as c:
            for (g, r), url in OFFICIAL.items():
                self.official[(g, r)] = await self._fetch(c, url, f"official_{g}_{r}.json", f"官方曲目表 {g}/{r}",
                                                          max_age_hours)
            for g, url in OTOGE_DB.items():
                self.otoge[g] = await self._fetch(c, url, f"otogedb_{g}.json", f"otoge-db {g}", max_age_hours)

    # ---------- evidence ----------
    @staticmethod
    def timeline_version(game: str, region: str, today: str | None = None) -> str:
        today = today or dt.date.today().isoformat()
        cur = ""
        for name, date in TIMELINE.get((game, region), []):
            if date <= today:
                cur = name
        return cur

    def mai_code(self, region: str, version: str) -> str:
        """官方曲目表里 version 这一版最新的 5 位码（宴不算）：27004 → 1.70 的第 04 批新歌。"""
        codes = [str(x.get("version", "")) for x in self.official.get(("mai", region), [])
                 if x.get("catcode") != "宴会場" and str(x.get("version", "")).isdigit()]
        codes = [c for c in codes if mai_code_name(c) == version]
        return max(codes, key=int) if codes else ""

    def mai_official(self, region: str) -> tuple[str, int, int]:
        songs = [x for x in self.official.get(("mai", region), []) if x.get("catcode") != "宴会場"]
        counts: dict[str, int] = {}
        for x in songs:
            name = mai_code_name(x.get("version", ""))
            if name:
                counts[name] = counts.get(name, 0) + 1
        ok = [v for v, n in counts.items() if n >= MIN_SONGS]
        if not ok:
            return "", 0, len(songs)
        best = max(ok, key=mai_rank)
        return best, counts[best], len(songs)

    def chu_versions(self) -> dict[str, str]:
        """曲目 ID → 版本（otoge-db）。"""
        return {str(x.get("id")): chu_name(x.get("version")) for x in self.otoge.get("chu", [])}

    def chu_official(self, region: str) -> tuple[str, int, int]:
        ids = {str(x.get("id")) for x in self.official.get(("chu", region), []) if str(x.get("id", "")).isdigit()
               and int(x["id"]) < 8000}                                  # 8000 号以后是 WORLD'S END
        vmap = self.chu_versions()
        counts: dict[str, int] = {}
        for i in ids:
            if (v := vmap.get(i)):
                counts[v] = counts.get(v, 0) + 1
        ok = [v for v, n in counts.items() if n >= MIN_SONGS]
        if not ok:
            return "", 0, len(ids)
        best = max(ok, key=chu_rank)
        return best, counts[best], len(ids)

    def official_ids(self, region: str) -> set[int]:
        return {int(x["id"]) for x in self.official.get(("chu", region), []) if str(x.get("id", "")).isdigit()}

    # ---------- main ----------
    async def refresh(self, catalog_versions: dict[tuple[str, str], str] | None = None,
                      mai_versions: list[str] | None = None, download: bool = True,
                      max_age_hours: float | None = None) -> Progress:
        """下载（可选）→ 每个服给出当前版本 → 跟上次比，变了的写进 changes。"""
        async with self._lock:
            if download:
                await self.download(max_age_hours)
            elif not self.official:
                self.load_cached()
            before = {k: v.current for k, v in self.state.regions.items()}
            cat = catalog_versions or {}
            regions: dict[str, RegionProgress] = {}
            for game in ("mai", "chu"):
                for region in ("jp", "intl"):
                    rp = RegionProgress(game, region)
                    if game == "mai":
                        rp.official, rp.official_new, rp.official_total = self.mai_official(region)
                        rank = lambda v: mai_rank(v, mai_versions)     # noqa: E731
                    else:
                        rp.official, rp.official_new, rp.official_total = self.chu_official(region)
                        rank = chu_rank
                    rp.timeline = self.timeline_version(game, region)
                    rp.catalog = (chu_name(cat.get((game, region))) if game == "chu" else cat.get((game, region))) or ""
                    cands = [v for v in (rp.official, rp.timeline, rp.catalog) if v]
                    rp.current = max(cands, key=rank) if cands else ""
                    if game == "mai" and rp.current:
                        rp.code = self.mai_code(region, rp.current)
                    if rp.catalog and rp.current and rank(rp.catalog) < rank(rp.current):
                        rp.notes.append(f"曲库还停在 {rp.catalog}")
                    regions[f"{game}/{region}"] = rp
            self.state.regions = regions
            self.state.at = time.time()
            names = {"mai": "舞萌", "chu": "中二", "jp": "日服", "intl": "国际服"}
            changes = []
            for k, rp in regions.items():
                old = before.get(k)
                if old and rp.current and old != rp.current:
                    changes.append(f"{names[rp.game]}{names[rp.region]}：{old} → {rp.current}")
            self.state.changes = changes
            self._save()
            return self.state


# ---------- 用 otoge-db + 官方曲目表补中二曲库 ----------
_CHU_DIFFS = (("bas", 0), ("adv", 1), ("exp", 2), ("mas", 3), ("ult", 4))


def otoge_charts(x: dict) -> list[tuple[int, str, float | None]]:
    """otoge-db 一首中二歌 → [(难度序号, 等级, 定数或 None)]。"""
    out = []
    for k, i in _CHU_DIFFS:
        lv = str(x.get(f"lev_{k}") or "").strip()
        if not lv:
            continue
        try:
            c = float(x.get(f"lev_{k}_i") or "") or None
        except ValueError:
            c = None
        out.append((i, lv, c))
    return out
