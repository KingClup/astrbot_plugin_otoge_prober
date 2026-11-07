"""O.N.G.E.K.I. rating math.

All values are integers in thousandths (1 rating point = 1000) so the
in-game truncation can be reproduced exactly:
  * each chart's rate is truncated to 0.001,
  * the profile rating is (sum of New10 + Best50 + Platinum50) / 50, truncated to 0.001.

Re:Fresh (client 1.50+) per-chart TS rate =
    score part (constant + piecewise linear offset)
  + score mark   SS +0.100 / SSS +0.200 / SSS+ +0.300
  + FULL BELL    +0.050
  + clear mark   FC +0.100 / AB +0.300 / AB+ (1,010,000 with AB) +0.350
Per-chart PS rate = stars(0..5) * constant^2 / 1000.

bright MEMORY and earlier (client <= 1.45) use the score part only, capped at
constant +2.000 at 1,007,500, with no bonuses.
"""
from __future__ import annotations

MAX_SCORE = 1_010_000

# (technical score, offset from the constant in thousandths); linear between points
_REFRESH_POINTS = [
    (1_010_000, 2000),
    (1_007_500, 1750),
    (1_000_000, 1250),
    (990_000, 750),
    (970_000, 0),
    (900_000, -4000),
    (800_000, -6000),
]
_OLD_POINTS = [
    (1_007_500, 2000),
    (1_000_000, 1500),
    (970_000, 0),
    (900_000, -4000),
]

RANKS = [
    (1_007_500, "SSS+"), (1_000_000, "SSS"), (990_000, "SS"), (970_000, "S"),
    (940_000, "AAA"), (900_000, "AA"), (850_000, "A"), (800_000, "BBB"),
    (750_000, "BB"), (700_000, "B"), (500_000, "C"), (0, "D"),
]


def rank_of(score: int) -> str:
    for border, name in RANKS:
        if score >= border:
            return name
    return "D"


def const_k(const: float) -> int:
    """Chart constant (e.g. 14.7) -> thousandths (14700)."""
    return int(round(const * 1000))


def _interp(points, c: int, score: int) -> int | None:
    if score >= points[0][0]:
        return c + points[0][1]
    for (hi, hv), (lo, lv) in zip(points, points[1:]):
        if lo <= score < hi:
            # floor((hv-lv)*(score-lo)/(hi-lo)) without float error
            return c + lv + ((hv - lv) * (score - lo)) // (hi - lo)
    return None


def score_part(const: float, score: int) -> int:
    """Re:Fresh score part, thousandths, truncated."""
    c = const_k(const)
    v = _interp(_REFRESH_POINTS, c, score)
    if v is None:
        if score < 500_000:
            return 0
        # 800,000 -> constant-6.000, 500,000 -> 0 (independent of the constant)
        v = ((c - 6000) * (score - 500_000)) // 300_000
    return max(v, 0)


# techScoreRank as stored by the game (AquaDX data: 1,008,710 -> 12, 1,006,953 -> 11, 997,286 -> 10)
_RANK_FLOOR = {12: 1_007_500, 11: 1_000_000, 10: 990_000, 9: 970_000}


def score_from_rank(tech_rank: int | None) -> int:
    """Lowest technical score that owns a given techScoreRank (for the score mark)."""
    return _RANK_FLOOR.get(int(tech_rank or 0), 0)


def score_bonus(best_score: int) -> int:
    if best_score >= 1_007_500:
        return 300
    if best_score >= 1_000_000:
        return 200
    if best_score >= 990_000:
        return 100
    return 0


def lamp_bonus(fc: bool, ab: bool, best_score: int) -> int:
    if ab and best_score >= MAX_SCORE:
        return 350
    if ab:
        return 300
    if fc:
        return 100
    return 0


def ts_rate(const: float, score: int, *, best_score: int | None = None,
            fc: bool = False, ab: bool = False, fb: bool = False) -> int:
    """Re:Fresh per-chart rate (New / Best frames), thousandths.

    best_score is the best technical score ever recorded on the chart (the score
    mark is "owned" independently of the score used here); defaults to score.
    """
    best = max(score, best_score or 0)
    return (score_part(const, score) + score_bonus(best) + (50 if fb else 0)
            + lamp_bonus(fc, ab, best))


def ps_rate(const: float, stars: int) -> int:
    """Re:Fresh Platinum Score rate, thousandths, truncated. Rainbow star (6) counts as 5."""
    s = max(0, min(int(stars), 5))
    c10 = int(round(const * 10))
    return (s * c10 * c10) // 100


def stars_of(platinum: int, platinum_max: int) -> int:
    """Stars from a platinum score ratio: 94/95/96/97/98% -> 1..5 (0 below 94%)."""
    if platinum_max <= 0:
        return 0
    pct = platinum * 100 / platinum_max
    for border, star in ((98, 5), (97, 4), (96, 3), (95, 2), (94, 1)):
        if pct >= border:
            return star
    return 0


def old_rate(const: float, score: int) -> int:
    """bright MEMORY (<= 1.45) per-chart rate, thousandths (game shows 0.01)."""
    c = const_k(const)
    v = _interp(_OLD_POINTS, c, score)
    if v is None:  # below 900,000: keep the AA slope (-0.01 per 175), not below 0
        v = c - 4000 - ((900_000 - score) * 10 + 174) // 175
    return max(v, 0)


def refresh_total(new10: list[int], best50: list[int], plat50: list[int]) -> int:
    """Profile rating in thousandths from per-chart rates (already truncated)."""
    return (sum(new10) + sum(best50) + sum(plat50)) // 50


def fmt(k: int) -> str:
    """Thousandths -> '21.202'."""
    sign = "-" if k < 0 else ""
    k = abs(k)
    return f"{sign}{k // 1000}.{k % 1000:03d}"
