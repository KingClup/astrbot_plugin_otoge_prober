"""数据结构（改写自 beer-psi/chuni-penguin，0BSD 许可）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum


class Difficulty(IntEnum):
    BASIC = 0
    ADVANCED = 1
    EXPERT = 2
    MASTER = 3
    ULTIMA = 4
    WORLDS_END = 5

    @property
    def short(self) -> str:
        return ["BAS", "ADV", "EXP", "MAS", "ULT", "WE"][self.value]

    @property
    def page_name(self) -> str:
        """CHUNITHM-NET musicGenre/sendXxx 的后缀。"""
        return ["Basic", "Advanced", "Expert", "Master", "Ultima", ""][self.value]


class Rank(IntEnum):
    D = 0
    C = 1
    B = 2
    BB = 3
    BBB = 4
    A = 5
    AA = 6
    AAA = 7
    S = 8
    S_PLUS = 9
    SS = 10
    SS_PLUS = 11
    SSS = 12
    SSS_PLUS = 13

    def __str__(self) -> str:
        return self.name.replace("_PLUS", "+")

    @classmethod
    def from_score(cls, score: int) -> "Rank":
        for th, r in ((1_009_000, cls.SSS_PLUS), (1_007_500, cls.SSS), (1_005_000, cls.SS_PLUS),
                      (1_000_000, cls.SS), (990_000, cls.S_PLUS), (975_000, cls.S), (950_000, cls.AAA),
                      (925_000, cls.AA), (900_000, cls.A), (800_000, cls.BBB), (700_000, cls.BB),
                      (600_000, cls.B), (500_000, cls.C)):
            if score >= th:
                return r
        return cls.D


class ClearLamp(Enum):
    FAILED = ""
    CLEAR = "CLEAR"
    HARD = "HARD"
    BRAVE = "BRAVE"
    ABSOLUTE = "ABSOLUTE"
    CATASTROPHY = "CATASTROPHY"


class ComboLamp(Enum):
    NONE = ""
    FULL_COMBO = "FC"
    ALL_JUSTICE = "AJ"
    ALL_JUSTICE_CRITICAL = "AJC"


@dataclass(slots=True)
class Score:
    song_id: int | None
    title: str
    difficulty: Difficulty
    score: int
    rank: Rank = Rank.D
    clear_lamp: ClearLamp = ClearLamp.FAILED
    combo_lamp: ComboLamp = ComboLamp.NONE
    jacket_url: str | None = None
    play_count: int | None = None
    # 由曲库补全
    const: float | None = None
    level: str | None = None

    @property
    def lamp_text(self) -> str:
        parts = [p for p in (self.combo_lamp.value, self.clear_lamp.value) if p]
        return "/".join(parts)


@dataclass(slots=True)
class RecentScore(Score):
    played_at: datetime | None = None
    track_no: int | None = None
    is_new_record: bool = False


@dataclass(slots=True)
class Profile:
    name: str
    level: int
    rating: float
    over_power: float | None = None
    over_power_pct: float | None = None
    last_played: datetime | None = None
    titles: list[str] = field(default_factory=list)
    team: str | None = None
    reborn: int = 0
    play_count: int | None = None
    friend_code: str | None = None
    uploaded_at: str = ""        # 国服（落雪）：成绩上传到查分器的时间（ISO，UTC）
