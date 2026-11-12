"""DX Rating: single-chart rating, best-50 assembly and target helpers.

Rules (same on JP and International):
  * chart rating = floor(ds×10 · min(ach,100.5%)×10000 · coef×10 / 1e8), coefficient by rank band;
  * since CiRCLE an AP / AP+ adds 1;
  * total = best 35 "old" charts + best 15 "new" charts; since CiRCLE the new frame is
    the current version plus the one before it (see SongDB.new_versions).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..consts import ACH_CAP, RANK_LABEL, SCORE_COEFFICIENTS
from ..data.songdb import SongDB
from ..models import Score

AP_FLAGS = ("ap", "app")


def coefficient(ach: int) -> tuple[int, str]:
    """Return (coefficient ×10, rank key) for an achievement in units."""
    coef, rank = 0, "d"
    for lo, c, r in SCORE_COEFFICIENTS:
        if ach >= lo:
            coef, rank = c, r
        else:
            break
    return coef, rank


def rank_of(ach: int) -> str:
    return coefficient(ach)[1]


def chart_rating(ds: float, ach: int, fc: str | None = None, *, ap_bonus: bool = True) -> int:
    ds10 = int(round(ds * 10))
    a = min(ach, ACH_CAP)
    coef, _ = coefficient(a)
    value = ds10 * a * coef // 100_000_000
    if ap_bonus and fc in AP_FLAGS:
        value += 1
    return value


def estimate_ds(level: str) -> float | None:
    """Lowest constant a displayed level can have: '14' → 14.0, '14+' → 14.6."""
    m = re.match(r"^\s*(\d+)(\+?)", level or "")
    if not m:
        return None
    return int(m.group(1)) + (0.6 if m.group(2) else 0.0)


def attach_charts(scores: list[Score], db: SongDB, region: str, keep_ds: bool = False) -> list[Score]:
    """Fill music_id / ds / version / rating on each score from the song DB.
    keep_ds: the source already gave constant + rating (国服 / 水鱼) → only fill ids and version."""
    rv = db.current_version.get(region)
    for s in scores:
        chart = db.find_chart(s.title, s.type, s.diff, genre=s.genre, level=s.level, region=region)
        if chart is None and s.music_id:
            song = db.by_music_id(s.music_id)
            chart = song.chart(s.type, s.diff) if song else None
        if chart is not None:
            s.music_id = chart.music_id
            s.song_id = chart.song.id
            s.version = chart.version_in(region)
            if keep_ds and s.ds is not None:
                s.rank = s.rank or rank_of(s.ach)
                continue
            ds = chart.ds_in(region, rv)
            s.ds = ds
            s.ds_exact = ds is not None
        elif keep_ds and s.ds is not None:
            s.rank = s.rank or rank_of(s.ach)
            continue
        if s.ds is None:
            s.ds = estimate_ds(s.level)
            s.ds_exact = False
        s.rank = s.rank or rank_of(s.ach)
        s.rating = chart_rating(s.ds, s.ach, s.fc) if s.ds is not None and s.type != "utage" else 0
    return scores


def _sort_key(s: Score):
    return (-s.rating, -(s.ds or 0), -s.ach, s.title)


@dataclass
class Best50:
    region: str
    old: list[Score] = field(default_factory=list)
    new: list[Score] = field(default_factory=list)
    unmatched: list[Score] = field(default_factory=list)
    source: str = ""          # 国服 data source shown on the image (水鱼查分器 / 落雪查分器)
    version: str = ""         # 私服：玩家客户端对应的版本名；空 = 这个服曲库的当前版本
    rom: str = ""             # 私服：玩家客户端版本号（"1.55.00"），页头标出来
    show_dx: bool = True      # 卡片上显示 DX 分 + DX 星（/mai dx分 关 可以关）

    @property
    def old_total(self) -> int:
        return sum(s.rating for s in self.old)

    @property
    def new_total(self) -> int:
        return sum(s.rating for s in self.new)

    @property
    def total(self) -> int:
        return self.old_total + self.new_total

    @property
    def old_floor(self) -> int:
        return self.old[-1].rating if len(self.old) >= 35 else 0

    @property
    def new_floor(self) -> int:
        return self.new[-1].rating if len(self.new) >= 15 else 0


def build_best50(scores: list[Score], db: SongDB, region: str) -> Best50:
    """scores must already have attach_charts() applied."""
    new_versions = db.new_versions(region)
    old, new, unmatched = [], [], []
    for s in scores:
        if s.type == "utage" or s.ds is None:
            continue
        if s.music_id is None and s.song_id is None:
            unmatched.append(s)
        (new if s.version in new_versions else old).append(s)
    old.sort(key=_sort_key)
    new.sort(key=_sort_key)
    return Best50(region=region, old=old[:35], new=new[:15], unmatched=unmatched)


def min_ach_for_rating(ds: float, target: int, fc: str | None = None) -> int | None:
    """Smallest achievement (units) whose rating ≥ target, or None if impossible."""
    lo, hi = 0, ACH_CAP
    if chart_rating(ds, hi, fc) < target:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if chart_rating(ds, mid, fc) >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def rating_table(ds: float) -> list[tuple[str, int, int]]:
    """[(rank label, min achievement units, rating)] for the usual rank lines."""
    lines = [(1005000, "sssp"), (1000000, "sss"), (995000, "ssp"), (990000, "ss"),
             (980000, "sp"), (970000, "s")]
    return [(RANK_LABEL[r], a, chart_rating(ds, a)) for a, r in lines]
