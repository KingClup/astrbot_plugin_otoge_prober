"""理论最高 B50（b50 sample）：当前版本每张谱面都按满分算，取 rating 最高的 B35 + B15。"""
from __future__ import annotations

from ..data.songdb import SongDB
from ..models import Profile, Score
from .rating import Best50, build_best50, chart_rating

MAX_ACH = 1010000          # 101.0000%
# 「/mai 理论 日服」「/chu 理论ra 国服」「/查分 理论」
THEORY_WORDS = ("理论", "理论ra", "理论rating", "理论值", "理论最高", "查理论", "查理论ra", "理论分", "theory", "max")
SAMPLE_WORDS = ("sample", "样例", "示例", "理论", "理论值", "满分", "max", "最高")


def is_sample(args: list[str]) -> bool:
    return any(a.lower() in SAMPLE_WORDS for a in args)


def sample_best50(db: SongDB, region: str) -> tuple[Best50, Profile]:
    rv = db.current_version.get(region)
    scores: list[Score] = []
    for song in db.songs:
        for ch in song.charts:
            if ch.type == "utage" or not ch.available(region):
                continue
            ds = ch.ds_in(region, rv)
            if ds is None:
                continue
            total = int((ch.notes or {}).get("total") or 0)
            s = Score(title=song.title, type=ch.type, diff=ch.diff, level=ch.level_in(region), ach=MAX_ACH,
                      dx=total * 3, dx_max=total * 3, fc="app", fs="fsdp", rank="sssp", genre=song.category,
                      music_id=ch.music_id, song_id=song.id, ds=ds, ds_exact=True, version=ch.version_in(region))
            s.rating = chart_rating(ds, MAX_ACH, "app")
            scores.append(s)
    b = build_best50(scores, db, region)
    b.source = "理论值"
    prof = Profile(name="理论 Rating", rating=b.total, title="全部 SSS+ · AP+", region=region)
    return b, prof
