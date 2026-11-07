"""私服（core/privsrv）的中二数据 → 插件已有的 Score / RecentScore / Profile。

只做类型转换；拉数据在 core/privsrv，算 B50、出图沿用插件原来的代码。
"""
from __future__ import annotations

from datetime import datetime

from .models import ComboLamp, Difficulty, Profile, Rank, RecentScore, Score

try:
    from ..core.privsrv import servers as PS
    from ..core.privsrv.models import ChuPlay, ChuScore, PrivProfile
except ImportError:  # tests
    from core.privsrv import servers as PS
    from core.privsrv.models import ChuPlay, ChuScore, PrivProfile


def _lamp(full_combo: bool, all_justice: bool) -> ComboLamp:
    return ComboLamp.ALL_JUSTICE if all_justice else ComboLamp.FULL_COMBO if full_combo else ComboLamp.NONE


def _song_bits(songdb, music_id: int, diff: Difficulty, fallback_title: str) -> tuple[str, str | None]:
    """歌名优先用插件曲库的写法（好和曲绘、查歌对上），再带上显示等级。"""
    song = songdb.songs.get(music_id) if songdb is not None else None
    chart = song.charts.get(diff) if song is not None else None
    return (song.title if song is not None else "") or fallback_title or f"#{music_id}", \
        (chart.level if chart is not None else None)


def to_scores(rows: list[ChuScore], songdb, const_of=None) -> list[Score]:
    """定数用私服给的（和私服网站显示的 rating 一致）；私服没给时用 const_of(music_id, Difficulty)（日服定数表）。"""
    out = []
    for r in rows:
        if not 0 <= r.level_index <= 4:          # WORLD'S END 不计 rating
            continue
        diff = Difficulty(r.level_index)
        title, level = _song_bits(songdb, r.music_id, diff, r.title)
        out.append(Score(song_id=r.music_id, title=title, difficulty=diff, score=r.score,
                         rank=Rank.from_score(r.score), combo_lamp=_lamp(r.full_combo, r.all_justice),
                         play_count=r.play_count,
                         const=r.const if r.const is not None else (const_of(r.music_id, diff) if const_of else None),
                         level=level))
    return out


def to_profile(p: PrivProfile) -> Profile:
    return Profile(name=p.name, level=0, rating=p.rating / 100, play_count=p.plays)


def version_of(p: PrivProfile) -> str:
    """'2.50.00' → 'Mate'；表里没有的版本写成 'Ver.2.45'（出图标签用，曲绘主题会退回默认）。"""
    return PS.chu_version_name(p.rom_version) or PS.rom_label(p.rom_version)


def _when(iso: str, naive_tz=None) -> datetime | None:
    """带时区的照常换算；不带时区的（RinNET）就是游戏记下的时间，挂上显示用的时区，原样显示。"""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=naive_tz) if dt.tzinfo is None and naive_tz is not None else dt


def to_recent(plays: list[ChuPlay], songdb, const_of, naive_tz=None) -> list[RecentScore]:
    """const_of(music_id, Difficulty) → 定数或 None（日服定数表，私服跟日服数据走）。"""
    out = []
    for i, p in enumerate(plays, 1):
        if not 0 <= p.level_index <= 5:
            continue
        diff = Difficulty(p.level_index)
        title, level = _song_bits(songdb, p.music_id, diff, p.title)
        out.append(RecentScore(song_id=p.music_id, title=title, difficulty=diff, score=p.score,
                               rank=Rank.from_score(p.score), combo_lamp=_lamp(p.full_combo, p.all_justice),
                               const=const_of(p.music_id, diff), level=level, played_at=_when(p.played_at, naive_tz),
                               track_no=p.track or i, is_new_record=p.new_record))
    return out
