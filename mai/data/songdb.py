"""Song / chart database built from the DXRating catalog (Data from DXRating, dxrating.net).

Accepts both catalog shapes:
  * API document (schemaVersion 1, ``/api/v1/dxdata`` and ``packages/dxdata/snapshot.json``):
    sheets carry ``serverIds`` / ``serverOverrides`` / ``internalId``; aliases are a top-level list.
  * legacy ``dxdata.json``: sheets carry ``regions`` / ``regionOverrides``; aliases in ``searchAcronyms``.
"""
from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from .fuzzy import FuzzyIndex, Match
from ..consts import DIFFS, REGIONS

COVER_URL = "https://shama.dxrating.net/images/cover/v2/{image}.jpg"
MIN_SONGS_FOR_CURRENT_VERSION = 10


def norm_title(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("　", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def search_key(s: str) -> str:
    """Looser key for user search: case/space/punctuation-insensitive."""
    s = norm_title(s).lower()
    return re.sub(r"[\s\-_~〜・･.,'\"!！?？:：/／()（）\[\]【】]+", "", s)


_GENRE_RULES = (
    ("pops", "POPS＆アニメ"), ("アニメ", "POPS＆アニメ"),
    ("niconico", "niconico＆ボーカロイド"), ("ボーカロイド", "niconico＆ボーカロイド"),
    ("東方", "東方Project"), ("touhou", "東方Project"),
    ("game", "ゲーム＆バラエティ"), ("ゲーム", "ゲーム＆バラエティ"),
    ("ongeki", "オンゲキ＆CHUNITHM"), ("オンゲキ", "オンゲキ＆CHUNITHM"), ("chunithm", "オンゲキ＆CHUNITHM"),
    ("宴", "宴会場"), ("utage", "宴会場"),
    ("maimai", "maimai"),
)


def norm_genre(s: str) -> str:
    low = unicodedata.normalize("NFKC", s or "").lower()
    for needle, canon in _GENRE_RULES:
        if needle in low:
            return canon
    return s.strip()


@dataclass
class Chart:
    song: "Song"
    type: str
    diff: str
    level: str
    ds: float | None
    music_id: int | None
    servers: frozenset[str]
    version: str
    overrides: dict[str, dict] = field(default_factory=dict)
    multiver: dict[str, float] = field(default_factory=dict)
    notes: dict[str, int | None] = field(default_factory=dict)
    designer: str = ""
    release: str = ""
    sheet_id: str = ""

    def available(self, region: str) -> bool:
        return region in self.servers

    def version_in(self, region: str) -> str:
        return (self.overrides.get(region) or {}).get("version") or self.version

    def level_in(self, region: str) -> str:
        return (self.overrides.get(region) or {}).get("level") or self.level

    def ds_in(self, region: str, region_version: str | None = None) -> float | None:
        ov = self.overrides.get(region) or {}
        if ov.get("levelValue") is not None:
            return float(ov["levelValue"])
        if region_version and region_version in self.multiver:
            return float(self.multiver[region_version])
        return self.ds


@dataclass
class Song:
    id: str
    title: str
    artist: str
    category: str
    image: str
    bpm: float | None
    version: str
    aliases: list[str] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)

    @property
    def cover_url(self) -> str:
        return COVER_URL.format(image=self.image) if self.image else ""

    def chart(self, type_: str, diff: str) -> Chart | None:
        for c in self.charts:
            if c.type == type_ and c.diff == diff:
                return c
        return None

    def music_ids(self) -> set[int]:
        return {c.music_id for c in self.charts if c.music_id}


class SongDB:
    def __init__(self, doc: dict, version_override: dict[str, str] | None = None):
        self.updated_at: str = doc.get("updatedAt") or doc.get("updateTime") or ""
        self.versions: list[str] = [v["version"] for v in doc.get("versions", [])]
        self.version_abbr: dict[str, str] = {v["version"]: v.get("abbr", v["version"]) for v in doc.get("versions", [])}
        self.songs: list[Song] = []
        self._by_key: dict[tuple[str, str, str], list[Chart]] = {}
        self._by_music_id: dict[int, Song] = {}
        aliases: dict[str, list[str]] = {}
        for a in doc.get("aliases", []) or []:
            aliases.setdefault(a.get("song_id", ""), []).append(a.get("name", ""))
        for raw in doc.get("songs", []):
            self._add_song(raw, aliases)
        self._rebuild_fuzzy()
        self.current_version: dict[str, str] = {}
        self.set_version_override(version_override)

    # ---------- build ----------
    def _add_song(self, raw: dict, aliases: dict[str, list[str]]) -> None:
        sid = raw.get("id") or raw.get("songId") or raw.get("title", "")
        song = Song(
            id=sid,
            title=raw.get("title", ""),
            artist=raw.get("artist", "") or "",
            category=raw.get("category", "") or "",
            image=raw.get("imageName", "") or "",
            bpm=raw.get("bpm"),
            version=raw.get("version", "") or "",
            aliases=list(dict.fromkeys((raw.get("searchAcronyms") or []) + aliases.get(sid, []))),
        )
        for sh in raw.get("sheets", []):
            stype = sh.get("type")
            if stype not in ("dx", "std", "utage", "utage2p"):
                continue
            stype = "utage" if stype.startswith("utage") else stype
            diff = sh.get("difficulty", "")
            if stype != "utage" and diff not in DIFFS:
                continue
            if "serverIds" in sh:
                servers = frozenset(sh.get("serverIds") or [])
                overrides = sh.get("serverOverrides") or {}
            else:
                servers = frozenset(k for k, v in (sh.get("regions") or {}).items() if v)
                overrides = {}
                for k, v in (sh.get("regionOverrides") or {}).items():
                    if v:
                        overrides[k] = dict(v)
            if not song.version:
                song.version = sh.get("version", "")
            chart = Chart(
                song=song, type=stype, diff=diff if stype != "utage" else "utage",
                level=str(sh.get("level", "")),
                ds=sh.get("internalLevelValue"),
                music_id=sh.get("internalId"),
                servers=servers,
                version=sh.get("version") or song.version,
                overrides=overrides,
                multiver=dict(sh.get("multiverInternalLevelValue") or {}),
                notes=dict(sh.get("noteCounts") or {}),
                designer=sh.get("noteDesigner") or "",
                release=sh.get("releaseDate") or "",
                sheet_id=sh.get("id", ""),
            )
            song.charts.append(chart)
            self._by_key.setdefault((norm_title(song.title), chart.type, chart.diff), []).append(chart)
            if chart.music_id:
                self._by_music_id.setdefault(chart.music_id, song)
        self.songs.append(song)

    def set_version_override(self, override: dict[str, str] | None) -> None:
        for r in REGIONS:
            v = (override or {}).get(r)
            self.current_version[r] = v if v and v != "auto" and v in self.versions else self._detect_current(r)

    def detected_version(self, region: str) -> str:
        return self._detect_current(region)

    def _detect_current(self, region: str) -> str:
        counts: dict[str, int] = {}
        for song in self.songs:
            vs = {c.version_in(region) for c in song.charts if c.available(region) and c.type in ("dx", "std")}
            for v in vs:
                counts[v] = counts.get(v, 0) + 1
        for v in reversed(self.versions):
            if counts.get(v, 0) >= MIN_SONGS_FOR_CURRENT_VERSION:
                return v
        return self.versions[-1] if self.versions else ""

    # ---------- versions ----------
    def version_index(self, v: str | None) -> int:
        try:
            return self.versions.index(v or "")
        except ValueError:
            return -1

    def new_versions(self, region: str) -> set[str]:
        """Versions that count as B15 ("new") on this region.

        Since CiRCLE the new frame is the current version *and* the one before it."""
        cur = self.current_version.get(region, "")
        ci = self.version_index(cur)
        if ci < 0:
            return {cur}
        circle = self.version_index("CiRCLE")
        if circle >= 0 and ci >= circle and ci >= 1:
            return {cur, self.versions[ci - 1]}
        return {cur}

    def is_new(self, chart: Chart, region: str) -> bool:
        return chart.version_in(region) in self.new_versions(region)

    # ---------- lookup ----------
    def by_music_id(self, music_id: int) -> Song | None:
        return self._by_music_id.get(music_id)

    def find_chart(self, title: str, type_: str, diff: str, *, genre: str = "",
                   level: str = "", region: str | None = None) -> Chart | None:
        cands = self._by_key.get((norm_title(title), type_, diff), [])
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        if genre:
            g = norm_genre(genre)
            by_genre = [c for c in cands if norm_genre(c.song.category) == g]
            if len(by_genre) == 1:
                return by_genre[0]
            if by_genre:
                cands = by_genre
        if level:
            by_level = [c for c in cands if (c.level_in(region) if region else c.level) == level]
            if len(by_level) == 1:
                return by_level[0]
            if by_level:
                cands = by_level
        if region:
            avail = [c for c in cands if c.available(region)]
            if avail:
                cands = avail
        return cands[0]

    # ---------- nicknames + fuzzy search ----------
    def _rebuild_fuzzy(self) -> None:
        self._fuzzy = FuzzyIndex()
        for s in self.songs:
            self._fuzzy.add(s.id, s, s.title, s.aliases)

    def apply_aliases(self, extra: dict[int, list[str]]) -> int:
        """Community nicknames keyed by base music id (1475 = SUPER AMBULANCE, both STD and DX)."""
        n = 0
        for s in self.songs:
            bases = {m % 10000 for m in s.music_ids() if m < 100000}
            add = [a for b in sorted(bases) for a in extra.get(b, [])]
            if add:
                low = {a.lower() for a in s.aliases}
                for a in add:
                    if a.lower() not in low and a.lower() != s.title.lower():
                        s.aliases.append(a)
                        low.add(a.lower())
                        n += 1
        self._rebuild_fuzzy()
        return n

    def song_by_any_id(self, n: int) -> Song | None:
        """11475, 1475 or 水鱼 / 落雪 style ids all find SUPER AMBULANCE."""
        s = self.by_music_id(n)
        if s is None and n < 100000:
            s = self.by_music_id(n % 10000) or self.by_music_id(n % 10000 + 10000)
        return s

    def search_ranked(self, query: str, limit: int = 10) -> list[Match]:
        q = query.strip()
        if q.isdigit() and (s := self.song_by_any_id(int(q))) is not None:
            return [Match(100, s, s.title, False)]
        return self._fuzzy.search(q, limit)

    def search(self, query: str, limit: int = 10) -> list[Song]:
        return [m.item for m in self.search_ranked(query, limit)]

    def charts_by_ds(self, lo: float, hi: float, region: str) -> list[Chart]:
        rv = self.current_version.get(region)
        out = []
        for song in self.songs:
            for c in song.charts:
                if c.type == "utage" or not c.available(region):
                    continue
                ds = c.ds_in(region, rv)
                if ds is not None and lo - 1e-9 <= ds <= hi + 1e-9:
                    out.append(c)
        out.sort(key=lambda c: (c.ds_in(region, rv) or 0, c.song.title))
        return out

    def random_chart(self, region: str, *, type_: str | None = None, diff: str | None = None,
                     level: str | None = None, rng: random.Random | None = None) -> Chart | None:
        pool = [c for s in self.songs for c in s.charts
                if c.type != "utage" and c.available(region)
                and (type_ is None or c.type == type_)
                and (diff is None or c.diff == diff)
                and (level is None or c.level_in(region) == level)]
        return (rng or random).choice(pool) if pool else None

    def stats(self) -> dict:
        return {
            "updated_at": self.updated_at,
            "songs": len(self.songs),
            "charts": sum(len(s.charts) for s in self.songs),
            "current_version": dict(self.current_version),
            "new_versions": {r: sorted(self.new_versions(r), key=self.version_index) for r in REGIONS},
        }


def iter_charts(db: SongDB) -> Iterable[Chart]:
    for s in db.songs:
        yield from s.charts
