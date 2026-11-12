"""音击 B50 图（Re:Fresh：新曲 10 + 旧曲 50 + P 分 50；旧版：新曲 15 + 旧曲 30 + 最近 10）。

v2.4.0 重画：白色页头（头像位 + 名字 + 渐变 RATING + 各段小结）→ 圆角分段标签 → 5 列白色卡片 → 页脚。
字体、背景、JPEG 压缩这些公共部件还是用中二 B50 图（chuni/b50img.py）的。
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
    from ..core import themebg as TB
    from ..core import glyphs as G
except ImportError:  # tests import packages top-level
    from chuni import b50img as CB
    from core import themebg as TB
    from core import glyphs as G

W = CB.W
MARGIN_X, CARD_W, CARD_H, GAP_X, GAP_Y = CB.MARGIN_X, CB.CARD_W, 192, CB.GAP_X, 20
JACKET = 124
HEADER_H, TAB_H, TAB_GAP, CARDS_GAP, SECTION_GAP, FOOTER_H = 372, 68, 44, 22, 46, 74

# v2.4.0 重画：白色圆角卡片放在樱花底上。难度只用一个色块（曲绘下面的难度条 + 曲绘描边）来表示，
# 不再整张卡片涂成难度色——50 张紫色卡片挤在一起太闷，分数和 rating 反而看不清。
INK, MUTE, PINK, PLUM = (43, 33, 64), (124, 111, 134), (229, 80, 143), (59, 42, 85)
DIFF_COLOR = {"BAS": (47, 154, 85), "ADV": (232, 140, 20), "EXP": (212, 52, 79), "MAS": (138, 70, 196), "LUN": (34, 34, 42)}
SECTION_COLORS = {"new": (240, 98, 160), "best": (70, 140, 235), "plat": (226, 168, 28), "recent": (24, 176, 124)}
# 评级小牌子：(底色, 字色)
RANK_CHIP = {"SSS+": ((246, 197, 68), (74, 48, 0)), "SSS": ((240, 98, 160), (255, 255, 255)), "SS": ((244, 148, 62), (255, 255, 255)),
             "S": ((86, 152, 236), (255, 255, 255))}
LAMP_CHIP = {"AB+": ((255, 244, 200), (176, 112, 0), (240, 190, 60)), "AB": ((255, 244, 200), (176, 112, 0), (240, 190, 60)),
             "FC": ((226, 246, 232), (30, 138, 70), (108, 200, 140)), "FB": ((226, 240, 255), (40, 108, 200), (120, 176, 240))}
_ASSET_DIR = Path(__file__).resolve().parent.parent / "web" / "bind" / "img"
_sprites: dict = {}


def rating_tier(r: float) -> int:
    """数字配色（只是装饰）：越高越亮，21 以上彩虹。"""
    for th, tier in ((21.0, 9), (20.0, 8), (19.0, 7), (18.0, 6), (17.0, 5), (15.0, 4), (13.0, 3), (11.0, 2)):
        if r >= th:
            return tier
    return 1


# 页头大数字的渐变（上 → 下）：按 rating 档位换色
_TIER_GRAD = {1: ((150, 150, 165), (110, 110, 128)), 2: ((92, 170, 240), (60, 120, 220)), 3: ((70, 190, 150), (30, 150, 110)),
              4: ((244, 168, 60), (226, 120, 30)), 5: ((240, 110, 110), (214, 60, 90)), 6: ((200, 110, 230), (150, 70, 200)),
              7: ((250, 200, 80), (232, 150, 30)), 8: ((255, 150, 190), (229, 80, 143)), 9: ((255, 130, 180), (120, 110, 240))}


def _shadow(w: int, h: int, r: int, blur: int = 14, alpha: int = 70, col=(150, 60, 110)) -> Image.Image:
    key = ("sh", w, h, r, blur, alpha, col)
    if key not in _sprites:
        from PIL import ImageFilter
        pad = blur * 2
        im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle([pad, pad + 6, pad + w, pad + h + 6], r, fill=col + (alpha,))
        _sprites[key] = (im.filter(ImageFilter.GaussianBlur(blur)), pad)
    return _sprites[key]


def _panel(img: Image.Image, box, r: int, fill=(255, 255, 255, 244), shadow: bool = True) -> None:
    x0, y0, x1, y1 = box
    if shadow:
        sh, pad = _shadow(x1 - x0, y1 - y0, r)
        img.alpha_composite(sh, (x0 - pad, y0 - pad))
    CB._overlay(img, lambda od: od.rounded_rectangle([x0, y0, x1, y1], r, fill=fill))


def _rounded(im: Image.Image, r: int) -> Image.Image:
    im = im.convert("RGBA")
    mask = Image.new("L", (im.width * 2, im.height * 2), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, mask.width - 1, mask.height - 1], r * 2, fill=255)
    im.putalpha(mask.resize(im.size, Image.Resampling.LANCZOS))
    return im


def _jacket(path) -> Image.Image:
    if path:
        try:
            with Image.open(path) as im:
                return im.convert("RGB").resize((JACKET, JACKET), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            pass
    ph = Image.new("RGB", (JACKET, JACKET), (250, 226, 236))
    ImageDraw.Draw(ph).text((JACKET // 2, JACKET // 2), "?", font=CB._font("latin", 52), fill=(232, 170, 196),
                            anchor="mm")
    return ph


def _chip(img: Image.Image, x: int, y: int, text: str, bg, fg, border=None, h: int = 30, font=None) -> int:
    """小圆角牌子，返回右边界 x。"""
    font = font or CB._font("latin", 21)
    d = ImageDraw.Draw(img)
    w = int(d.textlength(text, font=font)) + 20
    CB._overlay(img, lambda od: od.rounded_rectangle([x, y, x + w, y + h], h // 2, fill=bg + (255,),
                                                     outline=(border + (255,)) if border else None, width=2 if border else 0))
    ImageDraw.Draw(img).text((x + w // 2, y + h // 2 - 1), text, font=font, fill=fg, anchor="mm")
    return x + w


def _mascot(size: int, pose: str = "peace", crop: tuple | None = None) -> Image.Image | None:
    """页头头像位：手动传分没有游戏里的头像，放看板娘（包里没有这张图就不放）。
    pose 是 web/bind/img/yume-<pose>.webp；crop = (中心 x, 顶边 y, 边长)，都按图宽的比例，不给就取上方居中的最大正方形。
    音击用比耶那张，SDVX 用站着那张的脸——两张图别用同一个姿势。"""
    key = ("girl", size, pose, crop)
    if key not in _sprites:
        im = None
        try:
            with Image.open(_ASSET_DIR / f"yume-{pose}.webp") as src:
                src = src.convert("RGBA")
                if crop:
                    side = int(src.width * crop[2])
                    x0 = int(src.width * crop[0] - side / 2)
                    y0 = int(src.width * crop[1])
                else:
                    side = min(src.width, src.height)
                    x0, y0 = (src.width - side) // 2, 0
                x0 = max(0, min(x0, src.width - side))
                im = src.crop((x0, y0, x0 + side, y0 + side)).resize((size, size), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            im = None
        _sprites[key] = im
    return _sprites[key]


def _card(img: Image.Image, c: GekiChart, idx: int, x: int, y: int, jacket, plat: bool, font_path,
          show_plat: bool = True) -> None:
    dc = DIFF_COLOR.get(c.diff_name, DIFF_COLOR["MAS"])
    sh, pad = _shadow(CARD_W, CARD_H, 22, blur=10, alpha=46)
    img.alpha_composite(sh, (x - pad, y - pad))
    CB._overlay(img, lambda od: od.rounded_rectangle([x, y, x + CARD_W, y + CARD_H], 22, fill=(255, 255, 255, 246)))
    d = ImageDraw.Draw(img)
    # 第一行：歌名占满整张卡片的宽度（歌名被截断是最影响看图的）
    c_title = CB._chain("bold", 25, font_path)
    G.draw(d, (x + 16, y + 9), CB._fit(d, c.title, c_title, CARD_W - 32), c_title, INK)
    # 曲绘：难度色描边，底边压一条「难度 定数」
    jx, jy = x + 16, y + 50
    CB._overlay(img, lambda od: od.rounded_rectangle([jx - 4, jy - 4, jx + JACKET + 4, jy + JACKET + 4], 18, fill=dc + (255,)))
    jk = _jacket(jacket).convert("RGBA")
    strip = Image.new("RGBA", (JACKET, 32), dc + (238,))
    jk.alpha_composite(strip, (0, JACKET - 32))
    img.alpha_composite(_rounded(jk, 14), (jx, jy))
    d = ImageDraw.Draw(img)
    const_txt = f"{c.diff_name} {c.const:.1f}" if c.const is not None else f"{c.diff_name} ?"
    d.text((jx + JACKET // 2, jy + JACKET - 17), const_txt, font=CB._font("latin", 22), fill=(255, 255, 255), anchor="mm")

    tx = jx + JACKET + 20
    if plat:
        stars = min(c.stars, 5)
        st = "★" * stars + "☆" * (5 - stars)
        G.draw(d, (tx, y + 48), st, CB._chain("sc", 30), (238, 176, 36) if c.stars < 6 else (236, 92, 190))
        if show_plat and c.platinum:             # P 分框：白金分是主角，技术分放后面
            d.text((tx, y + 88), f"P {c.platinum:,}", font=CB._font("latin", 23), fill=(176, 112, 0))
            d.text((x + CARD_W - 14, y + 95), f"{c.score:,}", font=CB._font("latin_r", 15), fill=MUTE, anchor="ra")
        else:
            d.text((tx, y + 90), f"{c.score:,}", font=CB._font("latin_r", 24), fill=MUTE)
    else:
        d.text((tx, y + 44), f"{c.score:,}", font=CB._font("latin", 36), fill=PLUM)
        bg, fg = RANK_CHIP.get(c.rank, ((228, 224, 234), MUTE))
        cx = _chip(img, tx, y + 92, c.rank, bg, fg) + 6
        for m in (c.lamp, "FB" if c.fb else ""):
            if m:
                cb, cf, cbd = LAMP_CHIP.get(m, LAMP_CHIP["FC"])
                cx = _chip(img, cx, y + 92, m, cb, cf, cbd) + 6
        d = ImageDraw.Draw(img)

    value = c.ps if plat else c.rate
    vt = fmt(value) if value is not None else "—"
    gold = (not plat and c.score >= 1_007_500) or (plat and c.stars >= 5)
    base = y + CARD_H - 32                     # 最后一行：左边序号，右边单曲 rating
    d.text((x + CARD_W - 16, base), vt, font=CB._font("latin", 38), fill=(214, 140, 0) if gold else PINK, anchor="rm")
    d.text((tx, base + 2), f"#{idx + 1}", font=CB._font("latin_r", 24), fill=(180, 170, 190), anchor="lm")
    note = "BONUS" if c.bonus else ("无定数" if c.const is None else "")
    if note:
        nw = d.textlength(f"#{idx + 1} ", font=CB._font("latin_r", 24))
        G.draw(d, (tx + nw + 4, base + 2), note, CB._chain("sc", 20), (214, 120, 40), anchor="lm")


def _tab(img: Image.Image, y: int, label: str, value: str, color) -> None:
    d = ImageDraw.Draw(img)
    f = CB._font("latin", 38)
    lw = int(d.textlength(label, font=f)) + 64
    sh, pad = _shadow(lw, TAB_H, TAB_H // 2, blur=10, alpha=60, col=color)
    img.alpha_composite(sh, (MARGIN_X - pad, y - pad))
    CB._overlay(img, lambda od: (od.rounded_rectangle([MARGIN_X, y, MARGIN_X + lw, y + TAB_H], TAB_H // 2, fill=color + (255,)),
                                 od.rounded_rectangle([MARGIN_X + lw + 26, y + TAB_H // 2 - 2, W - MARGIN_X, y + TAB_H // 2 + 2], 2,
                                                      fill=(255, 255, 255, 190))))
    d = ImageDraw.Draw(img)
    d.text((MARGIN_X + lw // 2, y + TAB_H // 2 - 2), label, font=f, fill=(255, 255, 255), anchor="mm")
    if value:
        fv = CB._font("latin", 32)
        vw = int(d.textlength(value, font=fv)) + 40
        vx = MARGIN_X + lw + 18
        CB._overlay(img, lambda od: od.rounded_rectangle([vx, y + 8, vx + vw, y + TAB_H - 8], (TAB_H - 16) // 2, fill=(255, 255, 255, 240)))
        ImageDraw.Draw(img).text((vx + vw // 2, y + TAB_H // 2 - 2), value, font=fv, fill=INK, anchor="mm")


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
    if bg_path is None:                            # 没上传背景：按版本画（Re:Fresh 粉 / bright 晴空棱镜 / 更早橙红）
        bg_path = TB.background("geki", TB.geki_family(b.client), h)
    img = CB._background(h, bg_path)
    img.alpha_composite(Image.new("RGBA", (W, h), (255, 255, 255, 56)))      # 罩一层淡白：白卡片放上去不抢

    # ---- 页头：一整块白色圆角面板。左：头像位 + 名字 + 小标签；右：RATING 大数字；底下一排三段的小结 ----
    px0, py0, px1, py1 = MARGIN_X, 30, W - MARGIN_X, HEADER_H - 22
    _panel(img, (px0, py0, px1, py1), 44)
    d = ImageDraw.Draw(img)
    ax, ay, asz = px0 + 36, py0 + 30, 176
    CB._overlay(img, lambda od: (od.ellipse([ax - 8, ay - 8, ax + asz + 8, ay + asz + 8], fill=PINK + (255,)),
                                 od.ellipse([ax - 3, ay - 3, ax + asz + 3, ay + asz + 3], fill=(255, 255, 255, 255)),
                                 od.ellipse([ax, ay, ax + asz, ay + asz], fill=(253, 227, 238, 255))))
    girl = _mascot(asz)
    if girl is not None:
        mask = Image.new("L", (asz * 2, asz * 2), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, asz * 2 - 1, asz * 2 - 1], fill=255)
        g2 = girl.copy()
        g2.putalpha(Image.composite(g2.split()[3], Image.new("L", g2.size, 0), mask.resize(g2.size, Image.Resampling.LANCZOS)))
        img.alpha_composite(g2, (ax, ay))
    else:
        d = ImageDraw.Draw(img)
        G.draw(d, (ax + asz // 2, ay + asz // 2), (b.player or "?")[:1], CB._chain("bold", 90, font_path), PINK, anchor="mm")
    d = ImageDraw.Draw(img)
    nx = ax + asz + 36
    c_name = CB._chain("bold", 70, font_path)
    G.draw(d, (nx, py0 + 34), CB._fit(d, b.player or "?", c_name, 760), c_name, INK)
    ver = ("Re:Fresh" if b.client is None and b.server == "manual" else b.version_name) + \
        (f"  Ver.{b.client // 100}.{b.client % 100:02d}" if b.client else "")
    date = datetime.now(ZoneInfo(tz)).strftime("%Y/%m/%d")
    cx = nx
    f_tag = CB._chain("sc", 25)
    for text, bg, fg in ((("オンゲキ " + ver).strip(), PINK, (255, 255, 255)), (region_label, (253, 227, 238), (176, 52, 110)),
                         (date, (240, 236, 246), MUTE)):
        if not text:
            continue
        tw = int(G.width(text, f_tag)) + 30
        CB._overlay(img, lambda od, cx=cx, tw=tw, bg=bg: od.rounded_rectangle([cx, py0 + 136, cx + tw, py0 + 176], 20, fill=bg + (255,)))
        d = ImageDraw.Draw(img)
        G.draw(d, (cx + tw // 2, py0 + 155), text, f_tag, fg, anchor="mm")
        cx += tw + 10

    # RATING
    shown = b.shown if b.shown is not None else b.calc
    rx1 = px1 - 44
    d.text((rx1, py0 + 34), "RATING", font=CB._font("latin", 30), fill=PINK, anchor="ra")
    if shown is not None:
        txt = f"{shown / 1000:.3f}"
        f_big = CB._font("latin", 118)
        tw = d.textlength(txt, font=f_big)
        CB._gradient_text(img, (rx1 - tw, py0 + 58), txt, f_big, list(_TIER_GRAD[rating_tier(shown / 1000)]))
        d = ImageDraw.Draw(img)
    calc = b.calc
    note = ""
    if calc is not None and b.shown is not None and calc != b.shown:
        diff = calc - b.shown
        note = f"计算值 {fmt(calc)}（{'+' if diff > 0 else '-'}{fmt(abs(diff))}）"
    elif calc is None:
        note = "旧版规则：只显示服务器的值"
    if b.unknown:
        note = (note + "  ·  " if note else "") + f"{len(b.unknown)} 张谱没有定数，没算进去"
    if note:
        G.draw(d, (rx1, py0 + 204), note, CB._chain("sc", 22), (214, 120, 40), anchor="rm")

    # 小结：每段一格（标签色条 + 张数 + 平均 / 贡献）
    sy0, sy1 = py0 + 232, py1 - 24
    n_sec = max(1, len(sections))
    gap = 18
    sw = (px1 - px0 - 72 - gap * (n_sec - 1)) // n_sec
    for i, (label, kind, charts, value, _plat) in enumerate(sections):
        sx = px0 + 36 + i * (sw + gap)
        col = SECTION_COLORS[kind]
        CB._overlay(img, lambda od, sx=sx, col=col: (od.rounded_rectangle([sx, sy0, sx + sw, sy1], 18, fill=(250, 244, 248, 255)),
                                                     od.rounded_rectangle([sx, sy0, sx + 10, sy1], 5, fill=col + (255,))))
        d = ImageDraw.Draw(img)
        mid = (sy0 + sy1) // 2
        d.text((sx + 30, mid), label, font=CB._font("latin", 28), fill=col, anchor="lm")
        lw = d.textlength(label + "  ", font=CB._font("latin", 28))
        G.draw(d, (sx + 30 + lw, mid + 1), f"{len(charts)} 张", CB._chain("sc", 24), MUTE, anchor="lm")
        if value:
            d.text((sx + sw - 22, mid), value, font=CB._font("latin", 30), fill=INK, anchor="rm")

    # ---- 分段 ----
    y = HEADER_H
    for label, kind, charts, value, plat in sections:
        y += TAB_GAP
        _tab(img, y, label, value, SECTION_COLORS[kind])
        y0 = y + TAB_H + CARDS_GAP
        for i, c in enumerate(charts):
            cx = MARGIN_X + (i % 5) * (CARD_W + GAP_X)
            cy = y0 + (i // 5) * (CARD_H + GAP_Y)
            _card(img, c, i, cx, cy, jackets.get(c.title), plat, font_path, getattr(b, "show_plat", True))
        y += sec_h(len(charts))

    # ---- 页脚 ----
    fy = h - FOOTER_H
    CB._overlay(img, lambda od: od.rectangle([0, fy, W, h], fill=(255, 255, 255, 214)))
    d = ImageDraw.Draw(img)
    fmid = fy + FOOTER_H // 2
    ff = CB._chain("latin_r", 28) if footer_left.isascii() else CB._chain("sc", 26)
    G.draw(d, (MARGIN_X + 6, fmid), footer_left, ff, MUTE, anchor="lm")
    right = ("AVG 平均 · + 给 rating 加的分（合计 ÷ 50）；满 50 张的段两者相同只写一个" if b.refresh else "") + "  ·  曲绘：sdvx.in"
    G.draw(d, (W - MARGIN_X - 6, fmid), right.strip(" ·"), CB._chain("sc", 24), MUTE, anchor="rm")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    data, _ = CB.encode_jpeg(img.convert("RGB"), max_kb)
    out_path.write_bytes(data)
    return out_path

