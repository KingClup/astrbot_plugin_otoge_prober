"""Arcaea 潜力值计算（v7.0 起的新规则，2026-08-27 移动版更新）。

v7.0 改动（官方公告 + Arcaea 中文维基「潜力值」）：
  · 不再有 Recent 10，玩歌不会掉 PTT
  · 总 PTT = (Best 50 总和 + Best 10 总和) / 60   —— 前 10 名权重翻倍
  · 通关（TC 及以上，含 HC/EC/FR/PM）的成绩单曲潜力值 +0.2；Track Lost 没有这 0.2

单曲潜力值 = 定数 + 分数修正 (+0.2 若通关)：
  ≥ 10,000,000            +2.0
  9,800,000 ~ 9,999,999   +1.0 + (分数 − 9,800,000) / 200,000
  其余                     (分数 − 9,500,000) / 300,000
  最终不低于 0
旧规则（v7.0 前）= 没有 +0.2、总 PTT = (B30 + R10) / 40，留着 legacy=True 算老截图用。
"""
from __future__ import annotations

from dataclasses import dataclass, field

DIFFS = ("PST", "PRS", "FTR", "BYD", "ETR")          # ratingClass 0..4
DIFF_ALIASES = {
    "pst": 0, "past": 0,
    "prs": 1, "present": 1,
    "ftr": 2, "future": 2,
    "byd": 3, "beyond": 3, "byn": 3,
    "etr": 4, "eternal": 4,
}
CLEAR_BONUS = 0.2


def score_modifier(score: int) -> float:
    if score >= 10_000_000:
        return 2.0
    if score >= 9_800_000:
        return 1.0 + (score - 9_800_000) / 200_000
    return (score - 9_500_000) / 300_000


def play_rating(const: float, score: int, *, cleared: bool = True, legacy: bool = False) -> float:
    """单曲潜力值。cleared=False 表示 Track Lost。"""
    r = const + score_modifier(score)
    if cleared and not legacy:
        r += CLEAR_BONUS
    return max(0.0, r)


@dataclass
class Play:
    song_id: str
    diff: int                 # ratingClass
    score: int
    const: float
    cleared: bool = True
    title: str = ""
    rating: float = field(init=False)

    def __post_init__(self):
        self.rating = play_rating(self.const, self.score, cleared=self.cleared)


def best_per_chart(plays: list[Play]) -> list[Play]:
    """同一谱面只留潜力值最高的那次，按潜力值从高到低排。"""
    best: dict[tuple[str, int], Play] = {}
    for p in plays:
        k = (p.song_id, p.diff)
        if k not in best or p.rating > best[k].rating:
            best[k] = p
    return sorted(best.values(), key=lambda p: p.rating, reverse=True)


@dataclass
class B50:
    plays: list[Play]          # 最多 50 个，已排序

    @property
    def top10(self) -> list[Play]:
        return self.plays[:10]

    @property
    def total(self) -> float:
        """(B50 总和 + B10 总和) / 60；不足 50 首时空位按 0 算（和游戏里一样）。"""
        return (sum(p.rating for p in self.plays) + sum(p.rating for p in self.top10)) / 60

    @property
    def floor(self) -> float:
        """进 B50 的门槛：第 50 名的潜力值（不满 50 首时是 0）。"""
        return self.plays[49].rating if len(self.plays) >= 50 else 0.0

    def gain_if(self, p: Play) -> float:
        """如果打出这个成绩，总 PTT 会涨多少（用来做推分建议）。"""
        others = [q for q in self.plays if (q.song_id, q.diff) != (p.song_id, p.diff)]
        old_same = next((q for q in self.plays if (q.song_id, q.diff) == (p.song_id, p.diff)), None)
        if old_same and old_same.rating >= p.rating:
            return 0.0
        return B50(sorted(others + [p], key=lambda q: q.rating, reverse=True)[:50]).total - self.total


def build_b50(plays: list[Play]) -> B50:
    return B50(best_per_chart(plays)[:50])


def score_for(const: float, target: float, *, cleared: bool = True) -> int | None:
    """要拿到单曲潜力值 target 至少要多少分；够不到返回 None。"""
    need = target - const - (CLEAR_BONUS if cleared else 0.0)
    if need > 2.0:
        return None
    if need >= 1.0:
        s = 9_800_000 + (need - 1.0) * 200_000
    else:
        s = 9_500_000 + need * 300_000
    s = max(0, int(-(-s // 1)))     # 向上取整
    return min(s, 10_000_000)


def parse_diff(text: str) -> int | None:
    return DIFF_ALIASES.get(str(text or "").strip().lower())


def fmt_ptt(v: float) -> str:
    # 游戏内 PTT 显示两位小数且是截断不是四舍五入
    return f"{int(v * 100) / 100:.2f}"
