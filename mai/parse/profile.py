"""Player profile (/home/, /playerData/) and friend-code search result."""
from __future__ import annotations

import re

from ..models import Profile
from .html import attr, check_page, parse, text

_PLAY_RE = {
    "version": (r"play count of current version\s*[：:]\s*([\d,]+)", r"現バージョンプレイ回数\s*[：:]\s*([\d,]+)"),
    "total": (r"maimai\s*DX total play count\s*[：:]\s*([\d,]+)", r"累計プレイ回数\s*[：:]\s*([\d,]+)"),
}


def _num(s: str) -> int | None:
    m = re.search(r"([\d,]+)", s or "")
    return int(m.group(1).replace(",", "")) if m else None


def _title_kind(cls: str) -> str:
    for k in ("Rainbow", "Gold", "Silver", "Bronze", "Normal"):
        if f"trophy_{k}" in cls:
            return k.lower()
    return "normal"


def _fill_common(p: Profile, root) -> None:
    p.name = text(root.css_first(".name_block"))
    p.rating = _num(text(root.css_first(".rating_block"))) or 0
    trophy = root.css_first(".trophy_block")
    if trophy is not None:
        p.title = text(trophy.css_first(".trophy_inner_block span")) or text(trophy)
        p.title_kind = _title_kind(attr(trophy, "class"))
    icon = root.css_first("img.w_112")
    p.icon_url = attr(icon, "src")
    for img in root.css("img"):
        src = attr(img, "src")
        if "course_rank_" in src and not p.course_rank:
            p.course_rank = src
        elif "class_rank_" in src and not p.class_rank:
            p.class_rank = src
        elif "grade_" in src and not p.class_rank:
            p.class_rank = src


def parse_profile(html: str, region: str = "") -> Profile:
    check_page(html)
    tree = parse(html)
    root = tree.css_first(".see_through_block") or tree.body
    if root is None or root.css_first(".name_block") is None:
        raise ValueError("profile page has no player block (rate-limited or layout changed)")
    p = Profile(region=region)
    _fill_common(p, root)
    stars = root.css_first(".p_l_10.f_l.f_14")
    p.stars = _num(text(stars)) if stars is not None else None
    whole = text(tree.body) if tree.body is not None else ""
    for key, pats in _PLAY_RE.items():
        for pat in pats:
            m = re.search(pat, whole, re.I)
            if m:
                val = int(m.group(1).replace(",", ""))
                if key == "version":
                    p.play_count_version = val
                else:
                    p.play_count_total = val
                break
    m = re.search(r"(?:Friend Code|フレンドコード|好友代码)\s*[：:]\s*(\d{10,})", whole, re.I)
    if m:
        p.friend_code = m.group(1)
    return p


def parse_friend_search(html: str, region: str = "") -> Profile | None:
    """/friend/search/searchUser/?friendCode=… → public profile card, None if not found."""
    check_page(html)
    tree = parse(html)
    block = tree.css_first(".basic_block")
    if block is None or tree.css_first(".name_block") is None:
        return None
    root = block.parent or block
    p = Profile(region=region)
    _fill_common(p, root)
    star_img = root.css_first("img.h_20")
    if star_img is not None:
        tail = star_img.next
        tail_txt = ""
        while tail is not None and not tail_txt.strip():
            tail_txt = tail.text_content if tail.tag == "-text" else tail.text()
            tail = tail.next
        p.stars = _num(tail_txt)
    p.comment = text(tree.css_first(".friend_comment_block"))
    return p
