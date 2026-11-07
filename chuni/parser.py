"""CHUNITHM-NET 国际服 HTML 解析（选择器改写自 beer-psi/chuni-penguin，0BSD 许可）。

解析都集中在这里：CHUNITHM-NET 改版时只需要改这个文件。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .models import ClearLamp, ComboLamp, Difficulty, Profile, Rank, RecentScore, Score

JST = ZoneInfo("Asia/Tokyo")
_RE_BG_URL = re.compile(r"background-image\s*:\s*url\(['\"]?(?P<url>.+?)['\"]?\)")


class ParseError(Exception):
    pass


def soup_of(content: bytes | str) -> LexborHTMLParser:
    return LexborHTMLParser(content, is_fragment=False)


# ---------- 小工具 ----------

def _int(s: str) -> int:
    s = s.replace(",", "").strip()
    return int(s) if s else 0


def _last_part(url: str) -> str:
    return url.split("_")[-1].split(".")[0]


def _text(node: LexborNode | None, default: str = "") -> str:
    return node.text(strip=True) if node is not None else default


def parse_time(s: str, fmt: str = "%Y/%m/%d %H:%M") -> datetime:
    return datetime.strptime(s.strip(), fmt).replace(tzinfo=JST)


def difficulty_from(s: str) -> Difficulty:
    key = _last_part(s).lower()
    mapping = {
        "basic": Difficulty.BASIC,
        "advanced": Difficulty.ADVANCED,
        "expert": Difficulty.EXPERT,
        "master": Difficulty.MASTER,
        "ultima": Difficulty.ULTIMA,
        "ultimate": Difficulty.ULTIMA,
        "worldsend": Difficulty.WORLDS_END,
    }
    if key not in mapping:
        raise ParseError(f"未知难度: {s}")
    return mapping[key]


def rank_and_lamps(node: LexborNode | None) -> tuple[Rank, ClearLamp, ComboLamp]:
    if node is None:
        return Rank.D, ClearLamp.FAILED, ComboLamp.NONE

    rank = Rank.D
    if (img := node.css_first("img[src*=_rank_]")) is not None:
        try:
            rank = Rank(int(_last_part(str(img.attrs["src"]))))
        except (ValueError, KeyError):
            pass

    clear = ClearLamp.FAILED
    for key, lamp in (
        ("clear", ClearLamp.CLEAR),
        ("hard", ClearLamp.HARD),
        ("absolute", ClearLamp.ABSOLUTE),
        ("brave", ClearLamp.BRAVE),
        ("catastrophy", ClearLamp.CATASTROPHY),
    ):
        if node.css_first(f"img[src*={key}]") is not None:
            clear = lamp
            break

    combo = ComboLamp.NONE
    if node.css_first("img[src*=fullcombo]") is not None:
        combo = ComboLamp.FULL_COMBO
    elif node.css_first("img[src*=alljusticecritical]") is not None:
        combo = ComboLamp.ALL_JUSTICE_CRITICAL
    elif node.css_first("img[src*=alljustice]") is not None:
        combo = ComboLamp.ALL_JUSTICE

    return rank, clear, combo


# ---------- 错误页 ----------

def parse_error_page(soup: LexborHTMLParser) -> tuple[int, str] | None:
    """/mobile/error/ 页面 → (错误码, 描述)。"""
    blocks = soup.css(".block.text_l .font_small")
    if not blocks:
        return None
    try:
        code = int(blocks[0].text().split(":", 1)[1].strip())
    except (IndexError, ValueError):
        return None
    desc = blocks[1].text(strip=True) if len(blocks) > 1 else ""
    return code, desc


# ---------- 玩家资料 ----------

def _parse_rating_digits(soup: LexborHTMLParser | LexborNode) -> float:
    digits = ""
    for img in soup.css(".player_rating_num_block img"):
        part = _last_part(str(img.attrs.get("src", "")))
        digits += "." if part == "comma" else part[1:]
    if not digits:
        raise ParseError("找不到 rating 数字")
    return float(digits)


def _special_titles() -> dict[str, str]:
    p = Path(__file__).parent / "assets" / "titles.json"
    try:
        return {k: v["content"] for k, v in json.loads(p.read_text("utf-8")).items()}
    except (OSError, ValueError, KeyError):
        return {}


SPECIAL_TITLES = _special_titles()


def _parse_title(node: LexborNode) -> str | None:
    style = node.attrs.get("style") or ""
    m = _RE_BG_URL.search(str(style))
    filename = m.group("url").split("/")[-1] if m else ""
    if filename.startswith("honor_bg_noSet"):
        return None
    if filename and not filename.startswith("honor_bg_"):
        # 特殊称号是整张图片，没有文字
        return SPECIAL_TITLES.get(filename)
    span = node.css_first(".player_honor_text span, .honor_now_text span")
    text = _text(span)
    return text or None


def parse_profile(soup: LexborHTMLParser) -> Profile:
    """适用于 /mobile/home/ 和 /mobile/home/playerData。"""
    name_elem = soup.css_first(".player_name_in")
    if name_elem is None:
        raise ParseError("找不到玩家名（可能未登录或页面改版）")
    form = name_elem.css_first("form")
    name = _text(form.css_first("a")) if form is not None else _text(name_elem)

    op_value = op_pct = None
    if (op := soup.css_first(".player_overpower_text")) is not None:
        parts = op.text(strip=True).split(" ")
        try:
            op_value = float(parts[0])
            op_pct = float(parts[1].strip("()%"))
        except (IndexError, ValueError):
            pass

    last_played = None
    if (lp := soup.css_first(".player_lastplaydate_text")) is not None:
        try:
            last_played = parse_time(lp.text())
        except ValueError:
            pass

    profile = Profile(
        name=name,
        level=_int(_text(soup.css_first(".player_lv"), "0")),
        rating=_parse_rating_digits(soup),
        over_power=op_value,
        over_power_pct=op_pct,
        last_played=last_played,
        titles=[t for e in soup.css(".player_honor_short") if (t := _parse_title(e))],
        team=_text(soup.css_first(".player_team_name")) or None,
        reborn=_int(_text(soup.css_first(".player_reborn"), "0")),
    )

    if (pc := soup.css_first(".user_data_play_count .user_data_text")) is not None:
        profile.play_count = _int(pc.text())
    if (fc := soup.css_first(".user_data_friend_code .user_data_text span:not(.font_90)")) is not None:
        profile.friend_code = fc.text(strip=True)

    return profile


# ---------- 最近游玩 ----------

def _parse_recent_block(record: LexborNode) -> RecentScore:
    jacket_elem = record.css_first(".play_jacket_img img")
    jacket = None
    if jacket_elem is not None:
        jacket = jacket_elem.attrs.get("data-original") or jacket_elem.attrs.get("src")

    track = None
    if (t := record.css_first(".play_track_text")) is not None:
        try:
            track = int(t.text().split(" ")[1])
        except (IndexError, ValueError):
            pass

    played_at = None
    if (d := record.css_first(".play_datalist_date, .box_inner01")) is not None:
        try:
            played_at = parse_time(d.text())
        except ValueError:
            pass

    diff_img = record.css_first(".play_track_result img")
    if diff_img is None:
        raise ParseError("最近记录缺少难度图标")

    rank, clear, combo = rank_and_lamps(record.css_first(".play_musicdata_icon"))
    return RecentScore(
        song_id=None,
        title=_text(record.css_first(".play_musicdata_title")),
        difficulty=difficulty_from(str(diff_img.attrs["src"])),
        score=_int(_text(record.css_first(".play_musicdata_score_text"), "0")),
        rank=rank,
        clear_lamp=clear,
        combo_lamp=combo,
        jacket_url=jacket,
        played_at=played_at,
        track_no=track,
        is_new_record=record.css_first(".play_musicdata_score_img") is not None,
    )


def parse_recent(soup: LexborHTMLParser) -> list[RecentScore]:
    """/mobile/record/playlog"""
    return [_parse_recent_block(r) for r in soup.css(".frame02.w400")]


# ---------- 成绩列表（B30 / N20 / 按难度全曲） ----------

def parse_score_list(soup: LexborHTMLParser) -> list[Score]:
    """适用于 ratingDetailBest、ratingDetailRecent、musicGenre/sendXxx、musicLevel 等列表页。"""
    out: list[Score] = []
    for form in soup.css("form:has(.w388.musiclist_box)"):
        score_elem = form.css_first(".play_musicdata_highscore .text_b")
        if score_elem is None:
            continue  # 未游玩
        box = form.css_first(".w388.musiclist_box")
        idx = form.css_first("input[name=idx]")
        rank, clear, combo = rank_and_lamps(form.css_first(".play_musicdata_icon"))
        score_val = _int(score_elem.text())
        if rank == Rank.D and score_val > 0:
            rank = Rank.from_score(score_val)  # rating 页面没有评级图标
        out.append(
            Score(
                song_id=int(str(idx.attrs["value"])) if idx is not None else None,
                title=_text(form.css_first(".music_title, .musiclist_worldsend_title")),
                difficulty=difficulty_from(str(box.attrs["class"])),
                score=score_val,
                rank=rank,
                clear_lamp=clear,
                combo_lamp=combo,
            )
        )
    return out


# ---------- 单曲详情 ----------

def parse_music_detail(soup: LexborHTMLParser, song_id: int) -> list[Score]:
    """/mobile/record/musicGenre/sendMusicDetail/"""
    jacket_elem = soup.css_first(".play_jacket_img img")
    jacket = str(jacket_elem.attrs["src"]) if jacket_elem is not None else None
    title = _text(soup.css_first(".play_musicdata_title, .play_musicdata_worldsend_title"))

    out: list[Score] = []
    for block in soup.css(".music_box"):
        rank, clear, combo = rank_and_lamps(block.css_first(".play_musicdata_icon"))
        score_elem = block.css_first(".musicdata_score_num .text_b")
        pc_elem = block.css_first(
            ".musicdata_score_num .text_b:lexbor-contains(times), .block_icon_text span:not([class])"
        )
        out.append(
            Score(
                song_id=song_id,
                title=title,
                difficulty=difficulty_from(str(block.attrs["class"])),
                score=_int(score_elem.text()) if score_elem is not None else 0,
                rank=rank,
                clear_lamp=clear,
                combo_lamp=combo,
                jacket_url=jacket,
                play_count=_int(pc_elem.text().replace("times", "")) if pc_elem is not None else None,
            )
        )
    return out
