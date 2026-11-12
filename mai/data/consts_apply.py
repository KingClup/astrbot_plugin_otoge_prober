"""定数中心（core/consts_hub）的合并结果写回舞萌曲库。

国服：落雪 / 水鱼的定数优先（DXRating 的国服定数有几十张跟它们对不上）→ 写成 regionOverrides["cn"]。
      落雪 / 水鱼的曲目表本身就是国服现在能玩的歌：DXRating 还没标国服的（国服新一批更新常见），顺便标上。
日服：DXRating 本身就最新，只给它缺定数的谱面补上（otoge-db / zetaraku）。
国际服：不动（DXRating 按版本记了定数，国际服落后日服时只有它对）。
"""
from __future__ import annotations

try:
    from ...core.consts_hub import norm_title
except ImportError:  # tests
    from core.consts_hub import norm_title
from ..consts import DIFFS


def _index(db) -> dict:
    idx: dict = {}
    for song in db.songs:
        for ch in song.charts:
            if ch.type in ("dx", "std") and ch.diff in DIFFS:
                idx.setdefault((norm_title(song.title), ch.type, list(DIFFS).index(ch.diff)), []).append(ch)
    return idx


def apply_mai_consts(db, merged: dict) -> dict:
    n = {"jp": 0, "cn": 0, "cn_new": 0, "ambiguous": 0}
    if db is None:
        return n
    idx = _index(db)
    m = merged.get(("mai", "cn"))
    rv = db.current_version.get("cn")
    for key, v in (m.values.items() if m else ()):
        charts = idx.get(key) or []
        if len(charts) != 1:
            n["ambiguous"] += bool(charts)
            continue
        ch = charts[0]
        if not ch.available("cn"):
            ch.servers = frozenset(ch.servers | {"cn"})       # 落雪 / 水鱼里有 = 国服已经上了
            n["cn_new"] += 1
        cur = ch.ds_in("cn", rv)
        if cur is None or abs(cur - v) > 0.001:
            ch.overrides.setdefault("cn", {})["levelValue"] = v
            n["cn"] += 1
    m = merged.get(("mai", "jp"))
    rv = db.current_version.get("jp")
    for key, v in (m.values.items() if m else ()):
        charts = idx.get(key) or []
        if len(charts) == 1 and charts[0].available("jp") and charts[0].ds_in("jp", rv) is None:
            charts[0].overrides.setdefault("jp", {})["levelValue"] = v
            n["jp"] += 1
    return n
