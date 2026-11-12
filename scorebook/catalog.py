"""录分网站的曲库：SDVX（Tachi seeds）和音击（otoge-db + 插件自己的定数表）。

两份都整理成同一种精简格式（网页直接用，也存到磁盘当缓存）：

  {"game": "sdvx", "built": "2026-11-11", "source": "...",
   "versions": [["booth", "BOOTH"], ...], "genres": [...], "diffs": ["NOV", ...],
   "songs": [{"k": "2269", "t": 标题, "a": 艺术家, "v": 版本代码, "g": 分类, "s": [搜索词…], "b": 1(BONUS),
              "c": [{"d": "MXM", "l": "18.5", "n": 18.5, "x": 1(现行机台有), "p": 白金分满分(音击)}, ...]}]}

谱面键 = "<歌曲键>:<难度>"，例如 SDVX "2269:MXM"（歌曲键是游戏内曲目 ID）、音击 "600106:MAS"（otoge-db 的 id）。
SDVX 的等级就是 ∇ 的等级（17、17.5、18.0～20.9）；音击的 n 是定数（Re:Fresh 当前版本），l 是等级（14+）。
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field

try:
    from ..mai.data.fuzzy import FuzzyIndex
    from ..ongeki import versions as GV
except ImportError:  # tests import packages top-level
    from mai.data.fuzzy import FuzzyIndex
    from ongeki import versions as GV

GAMES = ("sdvx", "geki")
GAME_NAME = {"sdvx": "SOUND VOLTEX", "geki": "オンゲキ"}

# ---------- SDVX ----------
SDVX_VERSIONS = [("booth", "BOOTH"), ("inf", "II -infinite infection-"), ("gw", "III GRAVITY WARS"),
                 ("heaven", "IV HEAVENLY HAVEN"), ("vivid", "VIVID WAVE"), ("exceed", "EXCEED GEAR"),
                 ("nabla", "∇")]
SDVX_DIFFS = ["NOV", "ADV", "EXH", "MXM", "INF", "GRV", "HVN", "VVD", "XCD", "NBL", "ULT"]
SDVX_DIFF_NAME = {"NOV": "NOVICE", "ADV": "ADVANCED", "EXH": "EXHAUST", "MXM": "MAXIMUM", "INF": "INFINITE",
                  "GRV": "GRAVITY", "HVN": "HEAVENLY", "VVD": "VIVID", "XCD": "EXCEED", "NBL": "NABLA",
                  "ULT": "ULTIMATE"}
SDVX_CURRENT = "nabla"          # Tachi 的版本名：现行机台
SDVX_KONASTE = "konaste"
TACHI_BASE = "https://raw.githubusercontent.com/zkldi/Tachi/main/db/seeds/"
SDVX_URLS = (TACHI_BASE + "songs-sdvx.json", TACHI_BASE + "charts-sdvx.json")

# ---------- 音击 ----------
GEKI_DIFFS = ["BAS", "ADV", "EXP", "MAS", "LUN"]
GEKI_DIFF_NAME = {"BAS": "BASIC", "ADV": "ADVANCED", "EXP": "EXPERT", "MAS": "MASTER", "LUN": "LUNATIC"}
GEKI_OTOGE_KEYS = {"BAS": "bas", "ADV": "adv", "EXP": "exc", "MAS": "mas", "LUN": "lnt"}
GEKI_GENRES = ["オンゲキ", "POPS＆ANIME", "niconico", "東方Project", "VARIETY", "チュウマイ", "LUNATIC", "ボーナストラック"]
GEKI_URL = "https://raw.githubusercontent.com/zvuc/otoge-db/master/ongeki/data/music-ex.json"


def _today() -> str:
    return dt.date.today().isoformat()


def _num(s) -> float | None:
    try:
        v = float(str(s).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def build_sdvx(songs: list[dict], charts: list[dict]) -> dict:
    """Tachi seeds → 精简曲库。只用主谱面（isPrimary）；按游戏内曲目 ID 当歌曲键。"""
    by_song: dict[str, list[dict]] = {}
    for c in charts:
        if c.get("isPrimary", True):
            by_song.setdefault(c["songID"], []).append(c)
    order = {d: i for i, d in enumerate(SDVX_DIFFS)}
    out = []
    for s in songs:
        cs = by_song.get(s["id"]) or []
        if not cs:
            continue
        gid = cs[0].get("data", {}).get("inGameID")
        if gid is None:
            continue
        rows = []
        for c in sorted(cs, key=lambda c: order.get(c["difficulty"], 99)):
            vers = c.get("versions") or []
            row = {"d": c["difficulty"], "l": str(c.get("level") or "?"), "n": float(c.get("levelNum") or 0)}
            if SDVX_CURRENT in vers:
                row["x"] = 1
            elif SDVX_KONASTE in vers:
                row["x"] = 2                    # 只有コナステ
            rows.append(row)
        terms = [t for t in [*(s.get("altTitles") or []), *(s.get("searchTerms") or [])] if t]
        song = {"k": str(gid), "t": s["title"], "a": s.get("artist") or "",
                "v": (s.get("data") or {}).get("displayVersion") or "", "c": rows}
        if terms:
            song["s"] = terms
        out.append(song)
    out.sort(key=lambda x: int(x["k"]))
    return {"game": "sdvx", "built": _today(), "source": "Tachi seeds (unlicense)",
            "versions": [list(v) for v in SDVX_VERSIONS], "genres": [], "diffs": SDVX_DIFFS, "songs": out}


def build_geki(music_ex: list[dict], db=None) -> dict:
    """otoge-db 的 music-ex.json → 精简曲库。定数优先用插件自己的定数表（和 /geki b50 一致）。"""
    out = []
    for m in music_ex:
        lunatic = bool(m.get("lunatic"))
        bonus = bool(m.get("bonus"))
        song_db = db.match(m.get("title") or "", m.get("artist"), lunatic=lunatic) if db is not None else None
        ver = GV.song_version(otoge_name=m.get("version"))
        rows = []
        for d in GEKI_DIFFS:
            k = GEKI_OTOGE_KEYS[d]
            lv = str(m.get(f"lev_{k}") or "").strip()
            if not lv:
                continue
            const = None
            if song_db is not None and not song_db.bonus:
                const = song_db.const(10 if d == "LUN" else GEKI_DIFFS.index(d), None)
            if const is None:
                const = _num(m.get(f"lev_{k}_i"))
            row = {"d": d, "l": lv, "n": const if const is not None else _level_guess(lv), "x": 1}
            if const is None:
                row["q"] = 1                     # 没有定数（按等级估的，不算 rating）
            notes = str(m.get(f"lev_{k}_notes") or "").strip()
            if notes.isdigit():
                row["p"] = int(notes) * 2         # 白金分满分 = 物量 × 2
            rows.append(row)
        if not rows:
            continue
        song = {"k": str(m.get("id") or ""), "t": m.get("title") or "", "a": m.get("artist") or "",
                "v": ver or 0, "g": m.get("category") or "", "c": rows}
        if lunatic:                               # 游戏里 LUNATIC / Re:MASTER 单独一个分类
            song["lun"] = 1
            song["g"] = "LUNATIC"
        if bonus:
            song["b"] = 1
            song["g"] = "ボーナストラック"
        terms = [t for t in (m.get("title_sort"), m.get("character")) if t]
        if terms:
            song["s"] = terms
        if song["k"]:
            out.append(song)
    vers = [[str(code), name] for code, name, _ in GV.VERSIONS]
    genres = [g for g in GEKI_GENRES if any(s.get("g") == g for s in out)]
    genres += sorted({s["g"] for s in out if s.get("g") and s["g"] not in genres})
    return {"game": "geki", "built": _today(), "source": "otoge-db (zvuc/otoge-db)",
            "versions": vers, "genres": genres, "diffs": GEKI_DIFFS, "songs": out}


def _level_guess(lv: str) -> float:
    try:
        return float(lv.rstrip("+")) + (0.5 if lv.endswith("+") else 0)
    except ValueError:
        return 0.0


# ---------- 运行时 ----------
@dataclass
class Chart:
    key: str
    song: "Song"
    diff: str
    level: str
    num: float
    current: int = 1               # 1 现行机台 / 2 只有コナステ / 0 已删除
    plat_max: int = 0
    no_const: bool = False


@dataclass
class Song:
    key: str
    title: str
    artist: str
    version: str
    genre: str = ""
    terms: list[str] = field(default_factory=list)
    bonus: bool = False
    lunatic: bool = False
    charts: dict[str, Chart] = field(default_factory=dict)

    @property
    def version_code(self) -> int:
        try:
            return int(self.version)
        except (TypeError, ValueError):
            return 0


class Catalog:
    """一个游戏的曲库 + 搜索。aliases：歌曲键 → 外号列表（插件里各处的外号合在一起）。"""

    def __init__(self, data: dict):
        self.data = data
        self.game = data.get("game", "sdvx")
        self.songs: dict[str, Song] = {}
        self.charts: dict[str, Chart] = {}
        for s in data.get("songs") or []:
            song = Song(s["k"], s["t"], s.get("a", ""), str(s.get("v", "")), s.get("g", ""), list(s.get("s") or []),
                        bool(s.get("b")), bool(s.get("lun")))
            for c in s.get("c") or []:
                key = f"{song.key}:{c['d']}"
                ch = Chart(key, song, c["d"], str(c.get("l", "?")), float(c.get("n") or 0), int(c.get("x", 0)),
                           int(c.get("p") or 0), bool(c.get("q")))
                song.charts[c["d"]] = ch
                self.charts[key] = ch
            self.songs[song.key] = song
        self.aliases: dict[str, list[str]] = {}
        self._index = None

    @property
    def built(self) -> str:
        return str(self.data.get("built") or "")

    def __len__(self) -> int:
        return len(self.songs)

    def set_aliases(self, aliases: dict[str, list[str]]) -> None:
        self.aliases = {k: list(v) for k, v in aliases.items() if k in self.songs and v}
        self._index = None

    def index(self) -> FuzzyIndex:
        if self._index is None:
            idx = FuzzyIndex()
            for k, s in self.songs.items():
                idx.add(k, s, s.title, [*self.aliases.get(k, []), *s.terms, s.artist])
            self._index = idx
        return self._index

    def search(self, q: str, limit: int = 30):
        return self.index().search(q, limit)

    def client_payload(self) -> dict:
        """给网页的曲库（带外号）。"""
        d = dict(self.data)
        if self.aliases:
            songs = []
            for s in self.data.get("songs") or []:
                al = self.aliases.get(s["k"])
                songs.append({**s, "al": al} if al else s)
            d["songs"] = songs
        return d


def load(path: str) -> Catalog | None:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return Catalog(d) if d.get("songs") else None
    except (OSError, ValueError):
        return None


def save(data: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
