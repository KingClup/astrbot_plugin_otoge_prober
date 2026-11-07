"""Score list pages: /record/musicGenre/search/?genre=99&diff=N and /home/ratingTargetMusic/."""
from __future__ import annotations

import re

from ..consts import (diff_from_icon, flag_from_icon, parse_achievement, parse_pair, rank_from_icon,
                      type_from_icon)
from ..data.songdb import norm_genre, norm_title
from ..models import Score
from .html import attr, check_page, parse, text

_BACK_RE = re.compile(r"music_(basic|advanced|expert|master|remaster|utage)_score_back")
ROW_SEL = "div.screw_block, div.w_450.m_15.p_r.f_0"


def _row_type(row) -> str | None:
    rid = attr(row, "id")
    if rid:
        if "sta_" in rid:
            return "std"
        if "dx_" in rid:
            return "dx"
    for sel in ("img.music_kind_icon", "img.playlog_music_kind_icon"):
        node = row.css_first(sel)
        if node is not None:
            t = type_from_icon(attr(node, "src"))
            if t:
                return t
    # songs with both charts: the "on" tab says which one this block is
    for node in row.css("[class*='music_kind_icon_']"):
        cls = attr(node, "class")
        if "_btn_on" in cls:
            return "std" if "standard" in cls else "dx"
    return None


def _row_diff(row) -> str | None:
    for node in row.css("[class*='_score_back']"):
        m = _BACK_RE.search(attr(node, "class"))
        if m:
            return m.group(1)
    return diff_from_icon(attr(row.css_first("img.h_20.f_l"), "src"))


def parse_score_row(row, genre: str = "") -> Score | None:
    blocks = row.css(".music_score_block")
    if not blocks:
        return None  # not played
    ach = parse_achievement(text(blocks[0]))
    if ach is None:
        return None
    diff = _row_diff(row) or ""
    type_ = "utage" if diff == "utage" else (_row_type(row) or "dx")
    dx, dx_max = parse_pair(text(blocks[1])) if len(blocks) > 1 and parse_pair(text(blocks[1])) else (0, 0)
    fc = fs = rank = None
    for img in row.css("img"):
        src = attr(img, "src")
        kind, flag = flag_from_icon(src)
        if kind == "fc":
            fc = flag
        elif kind == "fs":
            fs = flag
        elif "music_icon_" in src:
            rank = rank_from_icon(src) or rank
    idx_node = row.css_first("input[name=idx]")
    return Score(
        title=norm_title(text(row.css_first(".music_name_block"))),
        type=type_, diff=diff,
        level=text(row.css_first(".music_lv_block")),
        ach=ach, dx=dx, dx_max=dx_max, fc=fc, fs=fs, rank=rank,
        idx=attr(idx_node, "value"), genre=norm_genre(genre),
    )


def parse_score_list(html: str) -> list[Score]:
    check_page(html)
    tree = parse(html)
    genre = ""
    out: list[Score] = []
    for node in tree.css(ROW_SEL):
        if "screw_block" in attr(node, "class"):
            genre = text(node)
            continue
        s = parse_score_row(node, genre)
        if s is not None and s.title:
            out.append(s)
    return out


def parse_rating_target(html: str) -> dict[str, list[Score]]:
    """Rating target page → {'new': [...], 'old': [...], 'candidates_new': [...], ...}.

    Section headings differ between JP and International, so they are classified by keywords;
    unknown headings are kept under their own text."""
    check_page(html)
    tree = parse(html)
    sections: dict[str, list[Score]] = {}
    key = "unknown"
    for node in tree.css(ROW_SEL):
        if "screw_block" in attr(node, "class"):
            key = _section_key(text(node))
            sections.setdefault(key, [])
            continue
        s = parse_score_row(node)
        if s is not None and s.title:
            sections.setdefault(key, []).append(s)
    return sections


def _section_key(heading: str) -> str:
    h = heading.lower()
    candidate = any(k in h for k in ("selection", "候補", "候补", "target"))
    if any(k in h for k in ("new", "新曲", "新")):
        return "candidates_new" if candidate else "new"
    if any(k in h for k in ("other", "old", "旧曲", "それ以外", "以外")):
        return "candidates_old" if candidate else "old"
    return heading.strip() or "unknown"
