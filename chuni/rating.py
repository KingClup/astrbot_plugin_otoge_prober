"""单曲 rating 与 B50 计算（公式改写自 beer-psi/chuni-penguin，0BSD 许可）。

VERSE 起的规则：玩家 rating = (旧曲 Best30 + 新曲 Best20) / 50，单曲上限为定数 + 2.15（1,009,000 分）。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from .models import Score


def whole_rating(score: int, const: float | None) -> int:
    """返回 rating × 10000 的整数值。"""
    il = int(round((const or 0) * 10000))
    if score >= 1_009_000:
        return il + 21_500
    if score >= 1_007_500:
        return il + 20_000 + (score - 1_007_500)
    if score >= 1_005_000:
        return il + 15_000 + (score - 1_005_000) * 2
    if score >= 1_000_000:
        return il + 10_000 + (score - 1_000_000)
    if score >= 975_000:
        return int(il + (score - 975_000) * 2 / 5)
    # S 以下分段线性：AAA(950,000) = 定数 −1.5、AA(925,000) = −3.0、A(900,000) = −5.0
    # （v1.10.0 以前是 A→S 一条直线，S 以下会偏低一点；RinNET 实测 965,161 / 15.1 → 14.50）
    if score >= 950_000:
        return max(il - 15_000 + (score - 950_000) * 3 // 5, 0)
    if score >= 925_000:
        return max(il - 30_000 + (score - 925_000) * 3 // 5, 0)
    eff = max(il - 50_000, 0)
    if score >= 900_000:
        return max(il - 50_000 + (score - 900_000) * 4 // 5, 0)
    if score >= 800_000:
        return int(eff / 2 + (score - 800_000) / 100_000 * (eff / 2))
    if score >= 500_000:
        return int((score - 500_000) / 300_000 * (eff / 2))
    return 0


def song_rating(score: int, const: float | None) -> Decimal:
    """单曲 rating，截断到两位小数（和游戏内显示一致）。"""
    return Decimal(whole_rating(score, const) // 100) / 100


@dataclass(slots=True)
class B50:
    best: list[Score]
    new: list[Score]
    displayed_rating: float | None = None
    version: str | None = None        # 私服：玩家客户端对应的版本名（出图用）
    rom: str = ""                     # 私服：玩家客户端版本号（"2.50.00"），页头标出来

    def __post_init__(self) -> None:
        # 排名按单曲 rating（同分时定数高、分数高的在前），不是按定数
        def key(s: Score):
            r = song_rating(s.score, s.const) if s.const is not None else -1
            return (-r, -(s.const or 0), -s.score)

        self.best = sorted(self.best, key=key)
        self.new = sorted(self.new, key=key)

    @staticmethod
    def _sum(scores: list[Score]) -> int:
        # 每首先截断到两位小数再求和（阶段 3 用真实数据核对这一点）
        return sum(
            whole_rating(s.score, s.const) // 100 * 100 for s in scores if s.const is not None
        )

    @property
    def missing_const(self) -> list[Score]:
        return [s for s in self.best + self.new if s.const is None]

    @property
    def best_avg(self) -> Decimal:
        return self._avg(self._sum(self.best), 30)

    @property
    def new_avg(self) -> Decimal:
        return self._avg(self._sum(self.new), 20)

    @property
    def total(self) -> Decimal:
        return self._avg(self._sum(self.best) + self._sum(self.new), 50)

    @staticmethod
    def _avg(total10000: int, n: int) -> Decimal:
        # 游戏内按截断显示到两位小数
        return (Decimal(total10000) / 10000 / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
