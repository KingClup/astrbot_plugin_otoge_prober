"""Plain data classes passed between parse → calc → render. All JSON-serialisable."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Score:
    """One best score from the NET score list (or a play-log entry)."""
    title: str
    type: str            # dx / std / utage
    diff: str            # basic … remaster / utage
    level: str           # NET display level, e.g. "14+"
    ach: int             # achievement ×10000
    dx: int = 0          # DX score
    dx_max: int = 0
    fc: str | None = None
    fs: str | None = None
    rank: str | None = None
    idx: str = ""        # NET detail idx (opaque)
    genre: str = ""
    # filled in by matching against the song DB
    music_id: int | None = None
    song_id: str | None = None
    ds: float | None = None
    ds_exact: bool = False
    version: str | None = None
    rating: int = 0

    def key(self) -> tuple[str, str, str]:
        return (self.title, self.type, self.diff)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Score":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Profile:
    name: str = ""
    rating: int = 0
    rating_max: int | None = None
    title: str = ""
    title_kind: str = "normal"   # normal / bronze / silver / gold / rainbow
    icon_url: str = ""
    course_rank: str = ""        # icon url / code
    class_rank: str = ""
    stars: int | None = None
    play_count_version: int | None = None
    play_count_total: int | None = None
    friend_code: str = ""
    comment: str = ""
    region: str = ""
    uploaded_at: str = ""        # 国服（落雪）：成绩上传到查分器的时间（ISO，UTC）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class RecentPlay:
    track: int
    played_at: str        # 'YYYY-MM-DD HH:MM' JST as shown on NET
    title: str
    type: str
    diff: str
    level: str
    ach: int
    dx: int = 0
    dx_max: int = 0
    fc: str | None = None
    fs: str | None = None
    rank: str | None = None
    new_record: bool = False
    idx: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlaylogDetail:
    notes: dict[str, dict[str, int | None]] = field(default_factory=dict)  # tap/hold/slide/touch/break → cp/p/gr/gd/miss
    fast: int = 0
    late: int = 0
    combo: int = 0
    combo_max: int = 0
    sync: int | None = None
    sync_max: int | None = None
    rating: int | None = None
    rating_delta: int | None = None
    place: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
