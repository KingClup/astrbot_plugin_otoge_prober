"""理论最高 B50（b50 sample）：当前版本每张谱面都按 1,010,000 算，取旧曲 B30 + 新曲 N20。"""
from __future__ import annotations

try:
    from ..core.progress import chu_key
except ImportError:  # tests
    from core.progress import chu_key
from .models import ClearLamp, ComboLamp, Difficulty, Rank, Score
from .rating import B50

MAX_SCORE = 1_010_000


def _max_score(song, d, const, title=None, level=None) -> Score:
    return Score(song_id=song.id if song else None, title=title or (song.title if song else "?"), difficulty=d,
                 score=MAX_SCORE, rank=Rank.SSS_PLUS, clear_lamp=ClearLamp.CLEAR,
                 combo_lamp=ComboLamp.ALL_JUSTICE_CRITICAL, jacket_url=song.jacket_url if song else None,
                 const=const, level=level)


def _finish(old, new, name="理论 Rating") -> tuple[str, B50]:
    b = B50(best=old, new=new)
    b.best, b.new = b.best[:30], b.new[:20]
    b.displayed_rating = float(b.total)
    return name, b


def sample_cn(svc) -> tuple[str, B50, str]:
    """国服：落雪国服曲库（谱面定数 + 收录版本，版本 ≥ 国服当前版本算新曲）；落雪没下载到时用水鱼国服定数 +
    曲库版本名。"""
    db, lx = svc.songdb, getattr(svc, "lx_songs", None)
    old, new = [], []
    if lx is not None and lx.charts:
        for (sid, _t, li), (lv, ver) in lx.charts.items():
            if li > 4 or sid >= 8000:          # 5 = WORLD'S END（8000 号以后也是 WE）
                continue
            d = Difficulty(li)
            const = lv if lv else svc.consts.cn.get((sid, d))
            if not const:
                continue
            song = db.songs.get(sid)
            if song is not None and "WORLD" in (song.genre or "").upper():
                continue
            ch = song.charts.get(d) if song is not None else None
            sc = _max_score(song, d, float(const), title=None if song else lx.titles.get(sid),
                            level=ch.level if ch else None)
            (new if ver >= lx.current else old).append(sc)
        cur = svc.cn_version or lx.version_title()
        return (*_finish(old, new), cur)
    cur = svc.cn_version or ""
    for (sid, d), const in svc.consts.cn.items():
        if d == Difficulty.WORLDS_END:
            continue
        song = db.songs.get(sid)
        if song is None or "WORLD" in (song.genre or "").upper():
            continue
        ch = song.charts.get(d)
        is_new = bool(cur) and chu_key(song.version) == chu_key(cur)
        (new if is_new else old).append(_max_score(song, d, const, level=ch.level if ch else None))
    return (*_finish(old, new), cur)


def sample_b50(svc, server: str = "intl") -> tuple[str, B50, str]:
    """→ (显示名, B50, 当前版本名)。国际服用曲库定数，日服用日服定数表，国服见 sample_cn。"""
    if server == "cn":
        return sample_cn(svc)
    db = svc.songdb
    cur = (svc.current_version if server == "intl" else svc.jp_version) or ""
    old, new = [], []
    for song in db.songs.values():
        if "WORLD" in (song.genre or "").upper() or (server == "intl" and not song.intl):
            continue
        is_new = bool(cur) and chu_key(song.version) == chu_key(cur)
        for d, ch in song.charts.items():
            if d == Difficulty.WORLDS_END:
                continue
            const = ch.const if server == "intl" else svc.consts.jp.get((song.id, d))
            if const is None:
                continue
            s = Score(song_id=song.id, title=song.title, difficulty=d, score=MAX_SCORE, rank=Rank.SSS_PLUS,
                      clear_lamp=ClearLamp.CLEAR, combo_lamp=ComboLamp.ALL_JUSTICE_CRITICAL,
                      jacket_url=song.jacket_url, const=const, level=ch.level)
            (new if is_new else old).append(s)
    b = B50(best=old, new=new)
    b.best, b.new = b.best[:30], b.new[:20]
    b.displayed_rating = float(b.total)
    return "理论 Rating", b, cur
