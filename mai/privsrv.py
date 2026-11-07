"""私服（core/privsrv）的舞萌数据 → 插件已有的 Score / Profile / RecentPlay。

只做类型转换；拉数据在 core/privsrv，算 B50、出图沿用插件原来的代码。
"""
from __future__ import annotations

from datetime import datetime

from .calc.rating import chart_rating, rank_of
from .consts import DIFFS
from .models import Profile, RecentPlay, Score

try:
    from ..core.privsrv import servers as PS
    from ..core.privsrv.models import MaiBest, MaiPlay, PrivProfile
except ImportError:  # tests import mai as a top-level package
    from core.privsrv import servers as PS
    from core.privsrv.models import MaiBest, MaiPlay, PrivProfile


def level_of(const: float | None) -> str:
    """没在曲库里找到谱面时，用定数推显示等级：14.6 → 14+。"""
    if const is None:
        return ""
    whole = int(const)
    return f"{whole}+" if round(const - whole, 1) >= 0.6 else str(whole)


def _chart(db, music_id: int, diff: str):
    song = db.by_music_id(music_id) if db is not None else None
    return song.chart("dx" if music_id >= 10000 else "std", diff) if song else None


AP_BONUS_FROM = "CiRCLE"      # AP / AP+ 加 1 分是 CiRCLE（1.60）起才有的


def ap_bonus_on(db, version: str) -> bool:
    if db is None or not version:
        return True
    try:
        return db.version_index(version) >= db.version_index(AP_BONUS_FROM)
    except Exception:  # noqa: BLE001  认不出版本就按现在的规则
        return True


def to_scores(best: MaiBest, db, version: str = "") -> tuple[list[Score], dict[str, list]]:
    """→ (成绩, {"old": [key…], "new": [key…]})，和国服 _cn_fetch 的返回一样。
    定数优先级：私服按版本给的（MuNET）→ 插件曲库里玩家客户端版本的日服定数（RinNET / AquaDX）→ 私服自己曲目表的
    （AquaDX，只有一个版本）。都没有的谱（自制谱？）定数空着、rating 记 0。
    AP+1 按玩家客户端版本：CiRCLE 以前没有。歌名优先用插件曲库的写法，好和曲绘、查歌对上。"""
    bonus = ap_bonus_on(db, version)
    scores: list[Score] = []
    split: dict[str, list] = {"old": [], "new": []}
    for sec, rows in (("old", best.old), ("new", best.new)):
        for r in rows:
            if not 0 <= r.level_index < len(DIFFS):
                continue
            diff = DIFFS[r.level_index]
            chart = _chart(db, r.music_id, diff)
            title = (chart.song.title if chart is not None else "") or r.title or f"未知谱面 {r.music_id}"
            const = r.const if r.const is not None else (chart.ds_in("jp", version or None) if chart is not None else None)
            if const is None:
                const = r.const_hint
            s = Score(title=title, type=r.kind, diff=diff, level=chart.level if chart is not None else level_of(const),
                      ach=r.achievement, dx=r.dx_score or 0, fc=r.fc or None, fs=r.fs or None,
                      rank=rank_of(r.achievement), music_id=r.music_id)
            s.ds, s.ds_exact = const, const is not None
            s.rating = chart_rating(const, r.achievement, s.fc, ap_bonus=bonus) if const is not None else 0
            scores.append(s)
            split[sec].append(list(s.key()))
    return scores, split


def to_profile(p: PrivProfile, region: str) -> Profile:
    return Profile(name=p.name, rating=p.rating, rating_max=p.rating_highest, region=region,
                   play_count_total=p.plays)


def version_of(p: PrivProfile) -> str:
    """玩家客户端版本对应的版本名（出图 logo / 标签用），如 1.66 → CiRCLE PLUS。"""
    return PS.mai_version_name(p.rom_version)


def _local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16].replace("T", " ")


def to_recent(plays: list[MaiPlay], db) -> list[RecentPlay]:
    out = []
    for i, p in enumerate(plays, 1):
        diff = DIFFS[p.level_index] if 0 <= p.level_index < len(DIFFS) else "master"
        chart = _chart(db, p.music_id, diff)
        out.append(RecentPlay(
            track=p.track or i, played_at=_local_time(p.played_at),
            title=(chart.song.title if chart is not None else "") or p.title or f"#{p.music_id}",
            type="dx" if p.music_id >= 10000 else "std", diff=diff, level=chart.level if chart is not None else "",
            ach=p.achievement, dx=p.dx_score, fc=p.fc or None, fs=p.fs or None,
            rank=rank_of(p.achievement), new_record=p.new_record))
    return out
