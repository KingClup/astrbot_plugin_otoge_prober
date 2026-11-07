"""用 otoge-db（版本 + 日服定数）和官方曲目表（哪个服有哪首歌）给中二曲库补新歌。

Tachi / beerpsi 常常比游戏晚：Tachi 到现在都没有 Mate。这里在每次曲库加载完以后：
  * 曲库里没有的歌（otoge-db 有、官方曲目表里也有）→ 加进去，等级 / 定数用 otoge-db 的（日服定数）；
  * 官方国际服曲目表里有的歌 → 标成国际服可玩（新版本上线后曲库的国际服标记往往还没更新）；
  * 缺版本名 / 缺定数的谱面 → 用 otoge-db 补上。
日服定数表（Tachi 只到旧版本）也用 otoge-db 覆盖成最新的日服定数。
"""
from __future__ import annotations

try:
    from ..core.progress import chu_name, otoge_charts
except ImportError:  # tests import packages top-level
    from core.progress import chu_name, otoge_charts
from .models import Difficulty
from .songdb import ChartInfo, SongInfo


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def augment_songdb(db, tracker) -> dict:
    oge = tracker.otoge.get("chu") or []
    if not oge:
        return {"added": 0, "intl": 0, "const": 0}
    intl_ids, jp_ids = tracker.official_ids("intl"), tracker.official_ids("jp")
    added = flagged = consts = 0
    for x in oge:
        sid = int(x["id"]) if str(x.get("id", "")).isdigit() else None
        if sid is None or sid >= 8000:
            continue
        ver = chu_name(x.get("version"))
        info = db.songs.get(sid)
        if info is None:
            if (jp_ids or intl_ids) and sid not in jp_ids and sid not in intl_ids:
                continue                       # 两个服都没有了 = 已删除，不加
            info = SongInfo(id=sid, title=str(x.get("title") or ""), artist=str(x.get("artist") or ""),
                            intl=sid in intl_ids, version=ver, genre=str(x.get("catname") or ""),
                            bpm=_num(x.get("bpm")))
            for i, lv, c in otoge_charts(x):
                d = Difficulty(i)
                info.charts[d] = ChartInfo(d, lv, c)
            info.from_otoge = True             # 标记：这首是补进来的（统计用）
            db.songs[sid] = info
            added += 1
            continue
        if intl_ids and sid in intl_ids and not info.intl:
            info.intl = True
            flagged += 1
        if not info.version and ver:
            info.version = ver
        for i, lv, c in otoge_charts(x):
            d = Difficulty(i)
            ch = info.charts.get(d)
            if ch is None:
                info.charts[d] = ChartInfo(d, lv, c)
                consts += 1
            elif ch.const is None and c is not None:
                ch.const = c
                consts += 1
    total = sum(1 for x in db.songs.values() if getattr(x, "from_otoge", False))
    return {"added": added, "total": total, "intl": flagged, "const": consts}


def augment_jp_consts(consts, tracker) -> int:
    """日服定数：otoge-db 的是最新的（跟着日服版本更新），有就用它。"""
    oge = tracker.otoge.get("chu") or []
    jp_ids = tracker.official_ids("jp")
    n = 0
    for x in oge:
        sid = int(x["id"]) if str(x.get("id", "")).isdigit() else None
        if sid is None or sid >= 8000 or (jp_ids and sid not in jp_ids):
            continue
        for i, _lv, c in otoge_charts(x):
            if c is not None:
                key = (sid, Difficulty(i))
                if consts.jp.get(key) != c:
                    consts.jp[key] = c
                    n += 1
    return n


def apply_chu_consts(svc, merged: dict) -> dict:
    """定数中心的合并结果写回：日服 / 国服定数表，国际服写到曲库谱面上（国际服 b50 用的就是它）。"""
    n = {"jp": 0, "intl": 0, "cn": 0}
    for region, table in (("jp", svc.consts.jp), ("cn", svc.consts.cn)):
        m = merged.get(("chu", region))
        for (sid, i), v in (m.values.items() if m else ()):
            k = (sid, Difficulty(i))
            if table.get(k) != v:
                table[k] = v
                n[region] += 1
    m = merged.get(("chu", "intl"))
    for (sid, i), v in (m.values.items() if m else ()):
        song = svc.songdb.songs.get(sid)
        ch = song.charts.get(Difficulty(i)) if song is not None else None
        if ch is not None and ch.const != v:
            ch.const = v
            n["intl"] += 1
    return n
