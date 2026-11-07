"""Plain-text replies (used when images are off or fail)."""
from __future__ import annotations

import time

from ..calc.rating import Best50, rating_table
from ..consts import DIFF_LABEL, FLAG_LABEL, PRIV_REGIONS, REGION_NAMES, RANK_LABEL, catalog_region, fmt_ach
from ..data.songdb import Song, SongDB
from ..models import PlaylogDetail, Profile, RecentPlay, Score


def _flags(fc, fs) -> str:
    out = " ".join(FLAG_LABEL[f] for f in (fc, fs) if f)
    return f" [{out}]" if out else ""


def score_line(i: int, s: Score) -> str:
    ds = f"{s.ds:.1f}" if s.ds is not None else "?"
    est = "" if s.ds_exact else "≈"
    t = "DX" if s.type == "dx" else "SD"
    return (f"#{i:<2} {s.title} [{t} {DIFF_LABEL.get(s.diff, s.diff)}] {est}{ds} "
            f"{fmt_ach(s.ach)} {RANK_LABEL.get(s.rank or '', '')}{_flags(s.fc, s.fs)} → {s.rating}")


def best50_text(b: Best50, profile: Profile | None, db: SongDB, at: int | None = None) -> str:
    region = REGION_NAMES.get(b.region, b.region)
    head = [f"舞萌 {region} B50 · {b.version or db.current_version.get(catalog_region(b.region), '')}"
            + (f"（客户端 Ver.{b.rom[:4]}）" if getattr(b, "rom", "") else "")]
    shown = "Rating" if b.region in PRIV_REGIONS else "NET Rating"
    if profile:
        head.append(f"{profile.name}  {shown} {profile.rating}")
    calc = b.total
    head.append(f"计算值 {calc} = 旧曲 {b.old_total} + 新曲 {b.new_total}")
    if profile and profile.rating and calc != profile.rating:
        head.append(f"⚠ 与{'服务器' if b.region in PRIV_REGIONS else ' NET '}显示值相差 {calc - profile.rating:+d}"
                    "（定数或版本归属可能有误）")
    lines = head + ["", f"— 旧曲 B35（底分 {b.old_floor}）—"]
    lines += [score_line(i + 1, s) for i, s in enumerate(b.old)]
    news = "" if b.region in PRIV_REGIONS else "/".join(sorted(db.new_versions(b.region), key=db.version_index)) + "，"
    lines += ["", f"— 新曲 B15（{news}底分 {b.new_floor}）—"]
    lines += [score_line(i + 1, s) for i, s in enumerate(b.new)]
    if at:
        lines += ["", f"数据时间 {time.strftime('%Y-%m-%d %H:%M', time.localtime(at))}"]
    return "\n".join(lines)


def profile_text(p: Profile) -> str:
    out = [f"{p.name}（{REGION_NAMES.get(p.region, p.region)}）", f"DX Rating {p.rating}"]
    if p.title:
        out.append(f"称号：{p.title}")
    if p.stars is not None:
        out.append(f"★ ×{p.stars}")
    if p.play_count_version is not None:
        out.append(f"本版本游玩 {p.play_count_version} 次 / 累计 {p.play_count_total}")
    if p.comment:
        out.append(f"留言：{p.comment}")
    return "\n".join(out)


def recent_text(plays: list[RecentPlay], n: int = 10) -> str:
    out = []
    for p in plays[:n]:
        t = "DX" if p.type == "dx" else ("宴" if p.type == "utage" else "SD")
        nr = " NEW" if p.new_record else ""
        out.append(f"{p.played_at[5:]} T{p.track} {p.title} [{t} {DIFF_LABEL.get(p.diff, p.diff)} {p.level}] "
                   f"{fmt_ach(p.ach)} {RANK_LABEL.get(p.rank or '', '')}{_flags(p.fc, p.fs)}{nr}")
    return "\n".join(out) or "没有最近游玩记录"


def playlog_text(p: RecentPlay, d: PlaylogDetail) -> str:
    out = [f"{p.title} [{DIFF_LABEL.get(p.diff, p.diff)} {p.level}] {fmt_ach(p.ach)}{_flags(p.fc, p.fs)}",
           f"DX {p.dx}/{p.dx_max}  COMBO {d.combo}/{d.combo_max}  FAST {d.fast} / LATE {d.late}"]
    out.append("         CP     P    GR    GD  MISS")
    for k in ("tap", "hold", "slide", "touch", "break"):
        row = d.notes.get(k) or {}
        cells = " ".join(f"{('-' if row.get(j) is None else row.get(j)):>5}" for j in ("cp", "p", "gr", "gd", "miss"))
        out.append(f"{k.upper():<6}{cells}")
    if d.rating is not None:
        delta = f"（{d.rating_delta:+d}）" if d.rating_delta else ""
        out.append(f"Rating {d.rating}{delta}")
    if d.place:
        out.append(f"店铺：{d.place}")
    return "\n".join(out)


def song_text(song: Song, db: SongDB, region: str) -> str:
    rv = db.current_version.get(region)
    out = [f"{song.title} — {song.artist}", f"分类 {song.category} · 初出 {song.version}"
           + (f" · BPM {song.bpm:g}" if song.bpm else "")]
    if song.aliases:
        out.append("别名：" + "、".join(song.aliases[:8]))
    for c in song.charts:
        if c.type == "utage":
            continue
        ds = c.ds_in(region, rv)
        avail = "" if c.available(region) else f"（{REGION_NAMES.get(region, region)}无）"
        n = c.notes.get("total")
        out.append(f"{'DX' if c.type == 'dx' else 'SD'} {DIFF_LABEL[c.diff]:<9} {c.level_in(region):>3} "
                   f"定数 {ds if ds is not None else '?'}" + (f" 物量 {n}" if n else "")
                   + (f" 谱师 {c.designer}" if c.designer and c.designer != '-' else "") + avail)
    ids = sorted(song.music_ids())
    if ids:
        out.append("ID " + "/".join(map(str, ids)))
    return "\n".join(out)


def line_text(ds: float) -> str:
    return "\n".join(f"{label:<4} {a / 10000:.4f}% → {r}" for label, a, r in rating_table(ds))
