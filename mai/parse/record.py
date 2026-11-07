"""Play log: /record/ (recent 50) and /record/playlogDetail/?idx=…"""
from __future__ import annotations

import re

from ..consts import (diff_from_icon, flag_from_icon, parse_achievement, parse_pair, rank_from_icon,
                      type_from_icon)
from ..data.songdb import norm_title
from ..models import PlaylogDetail, RecentPlay
from .html import attr, check_page, direct_text, parse, text

NOTE_ROWS = ("tap", "hold", "slide", "touch", "break")
JUDGES = ("cp", "p", "gr", "gd", "miss")


def parse_recent(html: str) -> list[RecentPlay]:
    check_page(html)
    tree = parse(html)
    out: list[RecentPlay] = []
    for rec in tree.css("div.p_10.t_l.f_0.v_b"):
        diff = diff_from_icon(attr(rec.css_first("img.playlog_diff"), "src")) or ""
        sub = rec.css(".sub_title .v_b")
        track_txt = text(sub[0]) if sub else ""
        m = re.search(r"(\d+)", track_txt)
        track = int(m.group(1)) if m else 0
        played = ""
        for node in sub[1:]:
            mm = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", text(node))
            if mm:
                y, mo, d, h, mi = mm.groups()
                played = f"{y}-{int(mo):02d}-{int(d):02d} {int(h):02d}:{mi}"
        name_node = rec.css_first(".basic_block.break") or rec.css_first(".basic_block")
        title = norm_title(direct_text(name_node))
        level = text(rec.css_first(".music_lv_back"))
        ach = parse_achievement(text(rec.css_first(".playlog_achievement_txt")))
        if not title or ach is None:
            continue
        if diff == "utage":
            type_ = "utage"
        else:
            type_ = type_from_icon(attr(rec.css_first("img.playlog_music_kind_icon"), "src")) or "dx"
        pair = parse_pair(text(rec.css_first(".playlog_score_block")))
        fc = fs = None
        for img in rec.css(".playlog_result_innerblock img"):
            kind, flag = flag_from_icon(attr(img, "src"))
            if kind == "fc":
                fc = flag
            elif kind == "fs":
                fs = flag
        rank = rank_from_icon(attr(rec.css_first("img.playlog_scorerank"), "src"))
        out.append(RecentPlay(
            track=track, played_at=played, title=title, type=type_, diff=diff, level=level,
            ach=ach, dx=pair[0] if pair else 0, dx_max=pair[1] if pair else 0, fc=fc, fs=fs, rank=rank,
            new_record=rec.css_first(".playlog_achievement_newrecord") is not None,
            idx=attr(rec.css_first("input[name=idx]"), "value"),
        ))
    return out


def _int(s: str) -> int | None:
    s = (s or "").replace(",", "").strip()
    return int(s) if s.isdigit() else None


def parse_playlog_detail(html: str) -> PlaylogDetail:
    check_page(html)
    tree = parse(html)
    d = PlaylogDetail()
    table = tree.css_first(".playlog_notes_detail")
    if table is not None:
        rows = [r for r in table.css("tr") if r.css("td")]
        for name, row in zip(NOTE_ROWS, rows):
            cells = row.css("td")
            d.notes[name] = {j: _int(text(c)) for j, c in zip(JUDGES, cells)}
    fl = tree.css(".playlog_fl_block .w_96")
    if len(fl) >= 2:
        d.fast = _int(text(fl[0])) or 0
        d.late = _int(text(fl[1])) or 0
    whites = tree.css(".playlog_score_block div.white")
    if len(whites) > 1:
        p = parse_pair(text(whites[1]))
        if p:
            d.combo, d.combo_max = p
    if len(whites) > 2:
        p = parse_pair(text(whites[2]))
        if p:
            d.sync, d.sync_max = p
    rb = tree.css_first(".playlog_rating_detail_block .rating_block")
    d.rating = _int(text(rb))
    for span in tree.css(".playlog_rating_detail_block span"):
        m = re.search(r"([+-])\s*(\d+)", text(span))
        if m:
            d.rating_delta = int(m.group(1) + m.group(2))
            break
    place = tree.css_first("#placeName")
    d.place = text(place) or None
    return d


def break_loss(detail: PlaylogDetail) -> dict[str, int]:
    """BREAK judgement summary for the result card (exact 50/100 split needs the score; see notes)."""
    b = detail.notes.get("break") or {}
    return {k: (b.get(k) or 0) for k in JUDGES}
