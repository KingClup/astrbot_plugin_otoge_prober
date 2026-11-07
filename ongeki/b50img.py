"""音击 B50 图（Re:Fresh：新曲 10 + 旧曲 50 + P 分 50；旧版：新曲 15 + 旧曲 30 + 最近 10）。

版式沿用中二 B50 图（chuni/b50img.py）：页头名牌 + RATING 数字 → 斜标签分段 → 5 列卡片 → 页脚。
曲绘来自 sdvx.in 的音击曲绘（按歌名对到 sdvx.in 的曲目），取不到就画「?」占位。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from .models import GekiBest, GekiChart
from .rating import fmt

try:
    from ..chuni import b50img as CB
    from ..core import glyphs as G
except ImportError:  # tests import packages top-level
    from chuni import b50img as CB
    from core import glyphs as G

W = CB.W
MARGIN_X, CARD_W, CARD_H, GAP_X, GAP_Y = CB.MARGIN_X, CB.CARD_W, 204, CB.GAP_X, 22
JACKET = CB.JACKET
HEADER_H, TAB_H, TAB_GAP, CARDS_GAP, SECTION_GAP, FOOTER_H = 250, 76, 50, 22, 50, 70

# 卡片配色（主体, 标题栏, 底栏）：BAS 绿 / ADV 橙 / EXP 红 / MAS 紫 / LUN 黑白
DIFF_STYLE = {
    "BAS": ((48, 130, 72), (34, 96, 52), (22, 64, 34)),
    "ADV": ((176, 112, 26), (134, 82, 16), (92, 56, 10)),
    "EXP": ((150, 40, 64), (112, 28, 46), (76, 18, 30)),
    "MAS": ((96, 52, 132), (70, 36, 98), (46, 24, 64)),
    "LUN": ((44, 44, 52), (26, 26, 32), (16, 16, 20)),
}
SECTION_COLORS = {"new": (255, 120, 170), "best": (60, 150, 235), "plat": (235, 180, 40), "recent": (24, 190, 130)}


def rating_tier(r: float) -> int:
    """数字配色（只是装饰）：越高越亮，21 以上彩虹。"""
    for th, tier in ((21.0, 9), (20.0, 8), (19.0, 7), (18.0, 6), (17.0, 5), (15.0, 4), (13.0, 3), (11.0, 2)):
        if r >= th:
            return tier
    return 1


def _rating_box(img: Image.Image, box, value: float) -> None:
    x0, y0, x1, y1 = box
    g = CB._drawn_number(f"{value:.3f}", rating_tier(value), int((y1 - y0) * 0.86))
    if g.width > (x1 - x0) * 0.94:
        k = (x1 - x0) * 0.94 / g.width
        g = g.resize((int(g.width * k), int(g.height * k)), Image.Resampling.LANCZOS)
    img.alpha_composite(g, (x0 + (x1 - x0 - g.width) // 2, y0 + (y1 - y0 - g.height) // 2))


def _jacket(path) -> Image.Image:
    if path:
        try:
            with Image.open(path) as im:
                return im.convert("RGB").resize((JACKET, JACKET), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            pass
    ph = Image.new("RGB", (JACKET, JACKET), (30, 28, 40))
    ImageDraw.Draw(ph).text((JACKET // 2, JACKET // 2), "?", font=CB._font("latin", 48), fill=(110, 110, 130),
                            anchor="mm")
    return ph


def _card(img: Image.Image, c: GekiChart, idx: int, x: int, y: int, jacket, plat: bool, font_path) -> None:
    body, title_c, bottom_c = DIFF_STYLE.get(c.diff_name, DIFF_STYLE["MAS"])
    layer = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rectangle([0, 0, CARD_W, CARD_H], fill=body + (235,))
    ld.rectangle([0, 0, CARD_W, 46], fill=title_c + (245,))
    ld.rectangle([0, CARD_H - 38, CARD_W, CARD_H], fill=bottom_c + (245,))
    if c.diff_name == "LUN":                 # LUNATIC：右上角白色斜条
        for k in range(3):
            off = 70 + k * 30
            ld.polygon([(CARD_W - off, 0), (CARD_W - off + 14, 0), (CARD_W, off - 14), (CARD_W, off)],
                       fill=(235, 235, 245, 150))
    img.alpha_composite(layer, (x, y))
    d = ImageDraw.Draw(img)
    c_title = CB._chain("bold", 30, font_path)
    G.draw(d, (x + 10, y + 4), CB._fit(d, c.title, c_title, CARD_W - 20), c_title, (255, 255, 255))
    img.paste(_jacket(jacket), (x + 10, y + 52))

    tx = x + 132
    f_score, f_small, f_const, f_rate = CB._font("latin", 32), CB._font("latin_r", 23), CB._font("latin_r", 26), \
        CB._font("latin", 34)
    if plat:
        stars = min(c.stars, 5)
        st = "★" * stars + "☆" * (5 - stars)
        G.draw(d, (tx, y + 52), st, CB._chain("sc", 30), (255, 214, 74) if c.stars < 6 else (255, 150, 230))
        d.text((tx, y + 92), f"{c.score:,}", font=f_small, fill=(214, 214, 226))
    else:
        d.text((tx, y + 50), f"{c.score:,}", font=f_score, fill=(255, 255, 255))
        marks = [m for m in (c.lamp, "FB" if c.fb else "") if m]
        d.text((tx, y + 90), f"[{c.rank}]", font=f_small, fill=(214, 214, 226))
        lx = tx + d.textlength(f"[{c.rank}] ", font=f_small)
        for m in marks:
            col = (255, 223, 117) if m.startswith("AB") else (40, 243, 26) if m == "FC" else (120, 210, 255)
            d.text((lx, y + 90), m, font=f_small, fill=col)
            lx += d.textlength(m + " ", font=f_small)

    const_txt = f"{c.diff_name} {c.const:.1f}" if c.const is not None else f"{c.diff_name} ?"
    cw = d.textlength(const_txt, font=f_const)
    CB._overlay(img, lambda od: od.rectangle([tx - 4, y + 122, tx + cw + 8, y + 156], fill=(0, 0, 0, 110)))
    d = ImageDraw.Draw(img)
    d.text((tx + 2, y + 124), const_txt, font=f_const, fill=(240, 240, 250))

    value = c.ps if plat else c.rate
    vt = fmt(value) if value is not None else "—"
    gold = (not plat and c.score >= 1_007_500) or (plat and c.stars >= 5)
    bar = y + CARD_H - 19                      # 底栏中线：左边序号，右边单曲 rating
    d.text((x + CARD_W - 12, bar), vt, font=f_rate, fill=(250, 255, 165) if gold else (255, 255, 255),
           anchor="rm")
    d.text((tx, bar), f"#{idx + 1}", font=CB._font("latin", 26), fill=(225, 225, 235), anchor="lm")
    note = "BONUS" if c.bonus else ("无定数" if c.const is None else "")
    if note:
        G.draw(d, (x + 10, bar), note, CB._chain("sc", 22), (255, 190, 120), anchor="lm")


def _tab(img: Image.Image, y: int, label: str, value: str, color) -> None:
    def draw(od):
        od.polygon([(0, y), (420, y), (350, y + TAB_H), (0, y + TAB_H)], fill=color + (255,))
        od.polygon([(420, y), (1010, y), (940, y + TAB_H), (350, y + TAB_H)], fill=(255, 255, 255, 255))
    CB._overlay(img, draw)
    d = ImageDraw.Draw(img)
    d.text((40, y + 14), label, font=CB._font("latin", 42), fill=(255, 255, 255))
    d.text((440, y + 12), value, font=CB._font("latin", 46), fill=(10, 10, 20))


def _sorted(charts: list[GekiChart], plat: bool) -> list[GekiChart]:
    key = (lambda c: c.ps or 0) if plat else (lambda c: c.rate or 0)
    return sorted(charts, key=lambda c: (c.known, key(c)), reverse=True)


def render(b: GekiBest, out_path: Path, *, jackets: dict | None = None, font_path: str | None = None,
           tz: str = "Asia/Shanghai", bg_path=None, footer_left: str = "Generated by AstrBot",
           region_label: str = "", max_kb: int = 3000) -> Path:
    jackets = jackets or {}
    if b.refresh:
        st = b.frame_stats()
        def tag(k):
            # 正好 50 张的段：平均 = 合计 ÷ 50 = 贡献，只写一个数
            if st[k]["avg"] == st[k]["contrib"]:
                return f"AVG +{fmt(st[k]['avg'])}"
            return f"AVG {fmt(st[k]['avg'])}   +{fmt(st[k]['contrib'])}"
        sections = [("NEW 10", "new", _sorted(b.new, False), tag("new"), False),
                    ("BEST 50", "best", _sorted(b.best, False), tag("best"), False),
                    ("PLATINUM 50", "plat", _sorted(b.plat, True), tag("plat"), True)]
    else:
        sections = [("BEST 30", "best", _sorted(b.best, False), "", False),
                    ("NEW 15", "new", _sorted(b.new, False), "", False),
                    ("RECENT 10", "recent", _sorted(b.recent, False), "", False)]
    sections = [s for s in sections if s[2]]
    rows = lambda n: (n + 4) // 5  # noqa: E731
    sec_h = lambda n: TAB_H + CARDS_GAP + rows(n) * (CARD_H + GAP_Y)  # noqa: E731
    h = HEADER_H + sum(TAB_GAP + sec_h(len(s[2])) for s in sections) + SECTION_GAP + FOOTER_H
    img = CB._background(h, bg_path)

    # ---- 页头 ----
    CB._overlay(img, lambda od: od.polygon([(0, 0), (1340, 0), (1120, HEADER_H), (0, HEADER_H)],
                                           fill=(20, 20, 28, 150)))
    CB._overlay(img, lambda od: od.rounded_rectangle([30, 48, 750, 184], 10, fill=(12, 12, 16, 245)))
    d = ImageDraw.Draw(img)
    c_name = CB._chain("bold", 64, font_path)
    G.draw(d, (390, 116), CB._fit(d, b.player or "?", c_name, 680), c_name, (255, 255, 255), anchor="mm")
    if region_label:
        cr = CB._chain("sc", 24)
        tw = G.width(region_label, cr)
        CB._overlay(img, lambda od: od.rounded_rectangle([30, 10, 30 + tw + 24, 40], 8, fill=(255, 255, 255, 40)))
        d = ImageDraw.Draw(img)
        G.draw(d, (42, 25), region_label, cr, (235, 235, 245), anchor="lm")

    d.text((790, 22), "RATING", font=CB._font("latin_r", 32), fill=(225, 225, 235))
    CB._overlay(img, lambda od: od.rounded_rectangle([790, 66, 1130, 160], 8, fill=(12, 12, 16, 245)))
    shown = b.shown if b.shown is not None else b.calc
    if shown is not None:
        _rating_box(img, (798, 70, 1122, 156), shown / 1000)
    d = ImageDraw.Draw(img)
    calc = b.calc
    if calc is not None and b.shown is not None and calc != b.shown:
        diff = calc - b.shown
        G.draw(d, (790, 172), f"计算值 {fmt(calc)}（{'+' if diff > 0 else '-'}{fmt(abs(diff))}）",
               CB._chain("sc", 24), (255, 190, 120))
    elif calc is None:
        G.draw(d, (790, 172), "旧版规则：只显示服务器的值", CB._chain("sc", 24), (225, 225, 235))
    unknown = b.unknown
    if unknown:
        G.draw(d, (790, 206), f"{len(unknown)} 张谱没有定数，没算进去", CB._chain("sc", 24), (255, 190, 120))
    # 右上：游戏名 + 版本
    G.draw(d, (W - 40, 70), "O.N.G.E.K.I.", CB._chain("latin", 54), (255, 255, 255), anchor="rm")
    ver = b.version_name + (f"  Ver.{b.client // 100}.{b.client % 100:02d}" if b.client else "")
    G.draw(d, (W - 40, 130), ver, CB._chain("sc", 32), (235, 235, 245), anchor="rm")
    date = datetime.now(ZoneInfo(tz)).strftime("%Y/%m/%d")
    d.text((W - 40 - d.textlength(date, font=CB._font("latin_r", 30)), 172), date,
           font=CB._font("latin_r", 30), fill=(225, 225, 235))

    # ---- 分段 ----
    y = HEADER_H
    for label, kind, charts, value, plat in sections:
        y += TAB_GAP
        _tab(img, y, label, value, SECTION_COLORS[kind])
        y0 = y + TAB_H + CARDS_GAP
        for i, c in enumerate(charts):
            cx = MARGIN_X + (i % 5) * (CARD_W + GAP_X)
            cy = y0 + (i // 5) * (CARD_H + GAP_Y)
            _card(img, c, i, cx, cy, jackets.get(c.title), plat, font_path)
        y += sec_h(len(charts))

    # ---- 页脚 ----
    fy = h - FOOTER_H
    CB._overlay(img, lambda od: (od.rectangle([0, fy - 2, W, fy], fill=(0, 0, 0, 200)),
                                 od.rectangle([0, fy, W, h], fill=(0, 0, 0, 120))))
    d = ImageDraw.Draw(img)
    fmid = fy + FOOTER_H // 2
    ff = CB._chain("latin_r", 30) if footer_left.isascii() else CB._chain("sc", 28)
    G.draw(d, (30, fmid), footer_left, ff, (225, 225, 235), anchor="lm")
    right = ("AVG 平均 · + 给 rating 加的分（合计 ÷ 50）；满 50 张的段两者相同只写一个" if b.refresh else "") + "  ·  曲绘：sdvx.in"
    G.draw(d, (W - 30, fmid), right.strip(" ·"), CB._chain("sc", 26), (225, 225, 235), anchor="rm")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    data, _ = CB.encode_jpeg(img.convert("RGB"), max_kb)
    out_path.write_bytes(data)
    return out_path

