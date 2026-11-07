"""Server-neutral O.N.G.E.K.I. result types (what the B50 text / image consume)."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import rating, versions
from .music import DIFF_SHORT, diff_index


@dataclass
class GekiChart:
    music_id: int
    diff: int                      # game id: 0-3, 10 = LUNATIC
    title: str
    score: int
    const: float | None = None     # None = unknown chart (not counted)
    best_score: int = 0            # best technical score ever (for the score mark)
    fc: bool = False
    ab: bool = False
    fb: bool = False
    stars: int = 0                 # platinum score stars (6 = rainbow, counts as 5)
    platinum: int = 0
    bonus: bool = False            # BONUS TRACK (never counts)
    rate: int | None = None        # thousandths; TS rate (Re:Fresh) or old rate
    ps: int | None = None          # thousandths; platinum frame only

    @property
    def diff_name(self) -> str:
        return DIFF_SHORT[diff_index(self.diff)]

    @property
    def rank(self) -> str:
        return rating.rank_of(self.score)

    @property
    def lamp(self) -> str:
        best = max(self.score, self.best_score)
        if self.ab and best >= rating.MAX_SCORE:
            return "AB+"
        return "AB" if self.ab else "FC" if self.fc else ""

    @property
    def known(self) -> bool:
        return self.const is not None and not self.bonus


@dataclass
class GekiBest:
    server: str
    player: str
    client: int | None                         # 151 = 1.51
    shown: int | None = None                   # rating the server shows, thousandths
    new: list[GekiChart] = field(default_factory=list)
    best: list[GekiChart] = field(default_factory=list)
    plat: list[GekiChart] = field(default_factory=list)      # Re:Fresh only
    recent: list[GekiChart] = field(default_factory=list)    # bright MEMORY and earlier only
    refresh: bool = True                       # Re:Fresh rating system (New10 + Best50 + P50)

    @property
    def version_name(self) -> str:
        return versions.name(self.client)

    @property
    def unknown(self) -> list[GekiChart]:
        return [c for c in (*self.new, *self.best, *self.plat, *self.recent) if not c.known]

    @property
    def calc(self) -> int | None:
        """Rating recomputed from the charts (thousandths); None for the old system,
        whose total formula is not pinned down yet."""
        if not self.refresh:
            return None
        return rating.refresh_total(
            [c.rate or 0 for c in self.new if c.known],
            [c.rate or 0 for c in self.best if c.known],
            [c.ps or 0 for c in self.plat if c.known])

    def frame_sums(self) -> dict[str, int]:
        return {
            "new": sum(c.rate or 0 for c in self.new if c.known),
            "best": sum(c.rate or 0 for c in self.best if c.known),
            "plat": sum(c.ps or 0 for c in self.plat if c.known),
        }

    def frame_stats(self) -> dict[str, dict[str, int]]:
        """Per section: n (charts counted), sum, avg (sum / n) and contrib (sum / 50, i.e. how much
        this section adds to the profile rating). All values in thousandths, truncated."""
        out = {}
        for key, charts, plat in (("new", self.new, False), ("best", self.best, False), ("plat", self.plat, True)):
            vals = [(c.ps if plat else c.rate) or 0 for c in charts if c.known]
            total = sum(vals)
            out[key] = {"n": len(vals), "sum": total,
                        "avg": total // len(vals) if vals else 0, "contrib": total // 50}
        return out

