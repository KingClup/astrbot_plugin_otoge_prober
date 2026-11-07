"""Arcaea 曲库 + 定数表 + 别名。

数据来源：DarrenDanielDay/arcaea-toolbelt-data（MIT），走 jsDelivr 镜像，不碰 lowiro 自己的服务器。
  songlist.json      曲目（id / 标题 / 曲师 / 各难度等级）
  ChartConstant.json {song_id: [PST, PRS, FTR, BYD, ETR]}，每项 {constant, old} 或 null
  alias.json         [{id, alias: [...]}]  中文社区别名
2026-11 时点这份数据停在 6.16.1c（7.0 前）；7.0 新曲的定数先放在 data/arcaea_const_patch.json
手动补（格式和 ChartConstant 一样），补丁优先。没有曲绘：lowiro 不允许第三方用游戏素材，
图里只放文字。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field

import httpx

from .calc import DIFFS

log = logging.getLogger("astrbot")

CDN = "https://cdn.jsdelivr.net/gh/DarrenDanielDay/arcaea-toolbelt-data@main/src/data/"
FILES = ("songlist.json", "ChartConstant.json", "alias.json")
TTL = 7 * 86400


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKC", str(t or "")).casefold()
    return re.sub(r"[\s\W_]+", "", t)


@dataclass
class Chart:
    diff: int
    level: str          # 显示用，如 "10+"
    const: float | None


@dataclass
class Song:
    sid: str
    title: str
    artist: str
    pack: str
    charts: dict[int, Chart] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)

    def label(self, diff: int) -> str:
        c = self.charts.get(diff)
        if not c:
            return f"{self.title} [{DIFFS[diff]}]"
        k = f"{c.const:.1f}" if c.const is not None else "?"
        return f"{self.title} [{DIFFS[diff]} {c.level} · {k}]"


def _level(rating: int, plus: bool) -> str:
    return f"{rating}+" if plus else str(rating)


def build(songlist: dict, consts: dict, alias: list, patch: dict | None = None) -> dict[str, Song]:
    consts = dict(consts or {})
    consts.update(patch or {})
    al = {a.get("id"): list(a.get("alias") or []) for a in alias or [] if isinstance(a, dict)}
    out: dict[str, Song] = {}
    for s in (songlist or {}).get("songs", []):
        sid = s.get("id")
        if not sid or s.get("deleted"):
            continue
        title = (s.get("title_localized") or {}).get("en") or sid
        song = Song(sid, title, s.get("artist", ""), s.get("set", ""), aliases=al.get(sid, []))
        cs = consts.get(sid) or []
        for d in s.get("difficulties") or []:
            i = d.get("ratingClass")
            if not isinstance(i, int) or not 0 <= i < len(DIFFS) or d.get("rating", 0) <= 0:
                continue
            c = cs[i] if i < len(cs) and isinstance(cs[i], dict) else None
            const = float(c["constant"]) if c and c.get("constant") is not None else None
            song.charts[i] = Chart(i, _level(int(d["rating"]), bool(d.get("ratingPlus"))), const)
        if song.charts:
            out[sid] = song
    return out


class SongDB:
    def __init__(self, data_dir: str):
        self.dir = os.path.join(data_dir, "arcaea")
        os.makedirs(self.dir, exist_ok=True)
        self.songs: dict[str, Song] = {}
        self._index: dict[str, set[str]] = {}

    # ---------- 加载 ----------
    def _path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def _load_local(self) -> dict | None:
        try:
            raw = {n: json.load(open(self._path(n), encoding="utf-8")) for n in FILES}
        except (OSError, ValueError):
            return None
        return raw

    async def refresh(self, force: bool = False) -> bool:
        fresh = all(os.path.exists(self._path(n)) and time.time() - os.path.getmtime(self._path(n)) < TTL
                    for n in FILES)
        if force or not fresh:
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                    for n in FILES:
                        r = await c.get(CDN + n)
                        r.raise_for_status()
                        json.loads(r.text)                     # 坏数据不落盘
                        tmp = self._path(n) + ".tmp"
                        open(tmp, "w", encoding="utf-8").write(r.text)
                        os.replace(tmp, self._path(n))
            except Exception as e:                              # 拉不到就用旧的
                log.warning("[otoge] arcaea 曲库更新失败：%s", e)
        raw = self._load_local()
        if not raw:
            return False
        patch = None
        try:
            patch = json.load(open(self._path("const_patch.json"), encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.load(raw["songlist.json"], raw["ChartConstant.json"], raw["alias.json"], patch)
        return True

    def load(self, songlist, consts, alias, patch=None):
        self.songs = build(songlist, consts, alias, patch)
        idx: dict[str, set[str]] = {}
        for s in self.songs.values():
            for k in [s.sid, s.title, *s.aliases]:
                n = _norm(k)
                if n:
                    idx.setdefault(n, set()).add(s.sid)
        self._index = idx

    # ---------- 查询 ----------
    def find(self, q: str) -> list[Song]:
        """精确（标题 / id / 别名）优先，其次包含匹配。"""
        n = _norm(q)
        if not n:
            return []
        hit = self._index.get(n)
        if hit:
            return [self.songs[i] for i in sorted(hit)]
        part = {i for k, ids in self._index.items() if n in k for i in ids}
        return sorted((self.songs[i] for i in part), key=lambda s: len(s.title))[:10]

    def const(self, sid: str, diff: int) -> float | None:
        s = self.songs.get(sid)
        c = s.charts.get(diff) if s else None
        return c.const if c else None

    def charts_in(self, lo: float, hi: float):
        for s in self.songs.values():
            for c in s.charts.values():
                if c.const is not None and lo <= c.const <= hi:
                    yield s, c
