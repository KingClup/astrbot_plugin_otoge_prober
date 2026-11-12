"""SDVX VOLFORCE 50 图（手动传分的成绩）—— SDVX 自己的版式，不套舞萌 / 中二 / 音击那套。

  页头：左边切角名牌（六边形头像位 + 玩家名 + 小标签）；右边 VF 徽章（段位颜色的六边形 + ★×段数）
        + 段位颜色的大 VOLFORCE 数字 + 到下一档的进度条
  统计条：各种灯的张数（上面一条按比例分段的色条）、单曲平均 / 最高、离下一档还差多少
  卡片：切角深色卡片。第一行歌名占满整张卡片；左边曲绘（难度色描边，底边压「难度 等级」，左上角名次）；
        右边分数、评级 + 灯、EX SCORE；右下角是单曲 VF ×50（50 张平均 = 总 VF），颜色按这个值对应的段位
  背景：core/themebg.py 的 ∇ 绿色主题
曲绘来自 sdvx.in（按歌名对上才有），没有就画「?」。
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter

from . import calc as K

try:
    from ..chuni import b50img as CB
    from ..core import glyphs as G
    from ..core import themebg as TB
    from ..ongeki.b50img import _mascot
except ImportError:  # tests import packages top-level
    from chuni import b50img as CB
    from core import glyphs as G
    from core import themebg as TB
    from ongeki.b50img import _mascot

W = CB.W
MX = 40
COLS, GAP_X, GAP_Y = 5, 20, 20
CARD_W = (W - 2 * MX - (COLS - 1) * GAP_X) // COLS
CARD_H = 200
CUT = 18                      # 卡片左上 / 右下切掉的角
JK = 128
HEADER_H, STATS_H, FOOTER_H = 330, 104, 72
NEON = (70, 255, 160)

# 段位颜色（主色, 亮色）
CLASS_COLOR = {
    "SIENNA": ((176, 98, 58), (236, 160, 110)), "COBALT": ((44, 96, 220), (130, 175, 255)),
    "DANDELION": ((232, 186, 30), (255, 232, 120)), "CYAN": ((40, 196, 222), (150, 240, 255)),
    "SCARLET": ((224, 44, 66), (255, 130, 140)), "CORAL": ((250, 120, 154), (255, 196, 212)),
    "ARGENTO": ((170, 182, 200), (238, 244, 252)), "ELDORA": ((222, 168, 36), (255, 226, 130)),
    "CRIMSON": ((176, 16, 44), (255, 90, 110)), "IMPERIAL": ((140, 78, 240), (214, 180, 255)),
}
DIFF_COLOR = {"NOV": (124, 92, 230), "ADV": (226, 186, 32), "EXH": (226, 58, 72), "MXM": (190, 196, 210),
              "INF": (220, 60, 160), "GRV": (240, 128, 40), "HVN": (40, 178, 226), "VVD": (236, 88, 196),
              "XCD": (70, 120, 236), "NBL": (60, 220, 140), "ULT": (240, 200, 70)}
LAMP_STYLE = {"PUC": ("PUC", (255, 214, 90), (60, 40, 0)), "UC": ("UC", (255, 120, 200), (60, 0, 40)),
              "MXV": ("MAXXIVE", (90, 220, 255), (0, 40, 60)), "EXC": ("EX COMP", (255, 120, 90), (60, 10, 0)),
              "COMP": ("COMP", (120, 220, 130), (0, 50, 10)), "PLAY": ("PLAYED", (150, 150, 160), (20, 20, 24))}
GRADE_COLOR = {"S": (255, 214, 90), "AAA+": (255, 236, 160), "AAA": (255, 236, 160), "AA+": (196, 220, 255),
               "AA": (196, 220, 255)}
CARD_BG = (10, 22, 20)


def class_parts(total_k: int) -> tuple[str, int, tuple, tuple]:
    """→ (段位名, 段数 1–4, 主色, 亮色)"""
    name = K.vf_class(total_k)
    base, _, roman = name.partition(" ")
    stars = {"I": 1, "II": 2, "III": 3, "IV": 4}.get(roman, 1)
    c1, c2 = CLASS_COLOR.get(base, CLASS_COLOR["SIENNA"])
    return base, stars, c1, c2


# ---------------------------------------------------------------- 小部件
def _layer(img):
    return Image.new("RGBA", img.size, (0, 0, 0, 0))


def _star(d: ImageDraw.ImageDraw, cx, cy, r, fill, outline=None) -> None:
    pts = []
    for k in range(10):
        a = math.radians(-90 + 36 * k)
        rr = r if k % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=fill, outline=outline)


def _hexagon(cx, cy, r):
    return [(cx + r * math.cos(math.radians(30 + 60 * k)), cy + r * math.sin(math.radians(30 + 60 * k)))
            for k in range(6)]


def _gradient_text(text: str, font, c_top, c_bottom, stroke=0, stroke_fill=(0, 0, 0)) -> Image.Image:
    """竖向渐变色的字（带描边），返回 RGBA。"""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font, stroke_width=stroke)
    w, h = r - l + 4, b - t + 4
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((-l + 2, -t + 2), text, font=font, fill=255)
    grad = Image.new("RGBA", (w, h))
    gd = ImageDraw.Draw(grad)
    for y in range(h):
        k = y / max(h - 1, 1)
        gd.line([(0, y), (w, y)], fill=tuple(int(a + (b2 - a) * k) for a, b2 in zip(c_top, c_bottom)) + (255,))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if stroke:
        sm = Image.new("L", (w, h), 0)
        ImageDraw.Draw(sm).text((-l + 2, -t + 2), text, font=font, fill=255, stroke_width=stroke,
                                stroke_fill=255)
        out.paste(Image.new("RGBA", (w, h), stroke_fill + (255,)), (0, 0), sm)
    out.paste(grad, (0, 0), mask)
    return out


def _emblem(img: Image.Image, cx: int, cy: int, r: int, total_k: int) -> None:
    """段位徽章：段位色六边形 + ∇ + ★×段数。"""
    base, stars, c1, c2 = class_parts(total_k)
    glow = _layer(img)
    ImageDraw.Draw(glow).polygon(_hexagon(cx, cy, r + 18), fill=c1 + (150,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(22)))
    lay = _layer(img)
    d = ImageDraw.Draw(lay)
    d.polygon(_hexagon(cx, cy, r), fill=(14, 18, 22, 255))
    d.polygon(_hexagon(cx, cy, r - 8), fill=c1 + (255,))
    # 上半部提亮、下半部压暗（裁在六边形里）
    hexmask = Image.new("L", img.size, 0)
    ImageDraw.Draw(hexmask).polygon(_hexagon(cx, cy, r - 8), fill=255)
    shade = _layer(img)
    sd = ImageDraw.Draw(shade)
    for yy in range(int(cy - r), int(cy + r) + 1):
        k = (yy - (cy - r)) / (2 * r)
        col = c2 + (int(140 * (0.5 - k) * 2),) if k < 0.5 else (0, 0, 0, int(120 * (k - 0.5) * 2))
        sd.line([(cx - r, yy), (cx + r, yy)], fill=col)
    lay.alpha_composite(Image.composite(shade, Image.new("RGBA", img.size, (0, 0, 0, 0)), hexmask))
    d = ImageDraw.Draw(lay)
    d.polygon(_hexagon(cx, cy, r - 8), outline=c2 + (255,), width=3)
    # ∇
    tr = r * 0.42
    tri = [(cx + tr * math.cos(math.radians(90 + 120 * k)), cy - r * 0.12 + tr * math.sin(math.radians(90 + 120 * k)))
           for k in range(3)]
    d.line(tri + [tri[0]], fill=(255, 255, 255, 230), width=6, joint="curve")
    img.alpha_composite(lay)
    # ★
    d = ImageDraw.Draw(img)
    sr, gap = r * 0.13, r * 0.30
    x0 = cx - gap * (stars - 1) / 2
    for i in range(stars):
        _star(d, x0 + i * gap, cy + r * 0.55, sr, (255, 255, 255, 255), outline=(20, 20, 20, 255))


def _badge(img, x, y, text, bg, fg, font, pad=8, h=30, r=6) -> int:
    d = ImageDraw.Draw(img)
    w = int(d.textlength(text, font=font)) + pad * 2
    CB._overlay(img, lambda od: od.rounded_rectangle([x, y, x + w, y + h], r, fill=bg + (255,)))
    ImageDraw.Draw(img).text((x + pad, y + h / 2), text, font=font, fill=fg, anchor="lm")
    return w


def _parallelogram(x, y, w, h, s):
    return [(x + s, y), (x + w, y), (x + w - s, y + h), (x, y + h)]


def _cut(x, y, w, h, c):
    """左上、右下各切掉一个角的矩形。"""
    return [(x + c, y), (x + w, y), (x + w, y + h - c), (x + w - c, y + h), (x, y + h), (x, y + c)]


_card_bg: dict = {}


def _card_base(dc) -> Image.Image:
    """一张空卡片（按难度色缓存）：深色玻璃底，上亮下暗，难度色细边 + 左上角一小块难度色。"""
    if dc not in _card_bg:
        s = 2                                              # 画两倍再缩，切角的斜边才不毛
        w, h, c = CARD_W * s, CARD_H * s, CUT * s
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).polygon(_cut(0, 0, w - 1, h - 1, c), fill=255)
        body = Image.new("RGBA", (w, h))
        bd = ImageDraw.Draw(body)
        for yy in range(h):
            k = yy / (h - 1)
            bd.line([(0, yy), (w, yy)], fill=(int(20 - 10 * k), int(34 - 16 * k), int(36 - 16 * k), 236))
        tint = Image.new("RGBA", (w, h), (0, 0, 0, 0))     # 左上角透一点难度色的光
        ImageDraw.Draw(tint).ellipse([-w // 3, -h // 2, w // 2, h // 2], fill=dc + (70,))
        body.alpha_composite(tint.filter(ImageFilter.GaussianBlur(40 * s)))
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.paste(body, (0, 0), mask)
        od = ImageDraw.Draw(out)
        pts = _cut(0, 0, w - 1, h - 1, c)
        od.line(pts + [pts[0]], fill=dc + (190,), width=2 * s, joint="curve")
        od.polygon([(0, c), (c, 0), (c + 26 * s, 0), (0, c + 26 * s)], fill=dc + (255,))
        _card_bg[dc] = out.resize((CARD_W, CARD_H), Image.Resampling.LANCZOS)
    return _card_bg[dc]


def _card(img: Image.Image, r: K.SdvxRow, idx: int, x: int, y: int, jacket, font_path, show_ex: bool = True) -> None:
    dc = DIFF_COLOR.get(r.diff, (190, 196, 210))
    dark_on_dc = (15, 15, 20) if sum(dc) > 520 else (255, 255, 255)
    img.alpha_composite(_card_base(dc), (x, y))
    d = ImageDraw.Draw(img)
    right = x + CARD_W - 14

    # 第一行：歌名占满整张卡片
    c_title = CB._chain("bold", 24, font_path)
    G.draw(d, (x + 34, y + 10), CB._fit(d, r.title, c_title, right - (x + 34)), c_title, (255, 255, 255))

    # 曲绘：难度色描边，底边压一条「难度 等级」，左上角名次
    jx, jy = x + 16, y + 52
    CB._overlay(img, lambda od: od.rectangle([jx - 3, jy - 3, jx + JK + 3, jy + JK + 3], fill=dc + (255,)))
    img.paste(_jacket(jacket), (jx, jy))
    CB._overlay(img, lambda od: od.rectangle([jx, jy + JK - 30, jx + JK, jy + JK], fill=dc + (238,)))
    d = ImageDraw.Draw(img)
    d.text((jx + JK // 2, jy + JK - 16), f"{r.diff} {r.level}", font=CB._font("latin", 21), fill=dark_on_dc, anchor="mm")
    fn = CB._font("latin", 19)
    nw = int(d.textlength(f"#{idx + 1}", font=fn)) + 12
    CB._overlay(img, lambda od: od.polygon([(jx, jy), (jx + nw + 8, jy), (jx + nw, jy + 26), (jx, jy + 26)],
                                           fill=(6, 12, 12, 225)))
    d = ImageDraw.Draw(img)
    d.text((jx + 6, jy + 13), f"#{idx + 1}", font=fn, fill=(255, 255, 255), anchor="lm")

    # 右边：分数 → 评级 + 灯 → EX
    tx = jx + JK + 14
    _score_digits(d, tx, y + 88, r.score, 36, 23)
    g = r.grade
    fg_font = CB._font("latin", 24)
    d.text((tx, y + 110), g, font=fg_font, fill=GRADE_COLOR.get(g, (210, 210, 216)), anchor="lm")
    gw = d.textlength(g + " ", font=fg_font)
    name, bg, fg = LAMP_STYLE.get(r.lamp, LAMP_STYLE["COMP"])
    _badge(img, int(tx + gw), y + 97, name, bg, fg, CB._font("latin", 18), pad=7, h=26, r=13)
    d = ImageDraw.Draw(img)
    if show_ex and r.ex:
        d.text((tx, y + 142), "EX", font=CB._font("latin", 16), fill=(110, 170, 200), anchor="lm")
        d.text((tx + 26, y + 142), f"{r.ex:,}", font=CB._font("latin", 19), fill=(160, 222, 255), anchor="lm")
    if r.current == 0:
        G.draw(d, (tx, y + 172), "已删除", CB._chain("sc", 17), (255, 190, 140), anchor="lm")

    # 单曲 VF ×50（右下），颜色 = 这个值对应的段位
    _, _, c1, c2 = class_parts(r.vf * 50)
    num = _gradient_text(K.fmt_song(r.vf), CB._font("latin", 40), c2, c1, stroke=3, stroke_fill=(8, 10, 12))
    img.alpha_composite(num, (right - 6 - num.width, y + CARD_H - num.height - 8))


def _score_digits(d, x: int, baseline: int, score: int, big: int, small: int) -> int:
    """SDVX 机台的写法：8 位数，前 4 位大、后 4 位小，前面补的 0 调暗（9,912,345 → 0991 2345）。返回宽度。"""
    s8 = f"{max(0, min(int(score), 99_999_999)):08d}"
    fb, fs = CB._font("latin", big), CB._font("latin", small)
    lead = len(s8[:4]) - len(s8[:4].lstrip("0")) if s8[:4] != "0000" else 4
    if s8 == "00000000":
        lead = 7
    cx = x
    for i, ch in enumerate(s8):
        f = fb if i < 4 else fs
        dim = i < lead
        d.text((cx, baseline), ch, font=f, fill=(96, 110, 116) if dim else (255, 255, 255), anchor="ls")
        cx += d.textlength(ch, font=f) + (1 if i < 4 else 0)
        if i == 3:
            cx += 3
    return int(cx - x)


def _jacket(path) -> Image.Image:
    if path:
        try:
            with Image.open(path) as im:
                return im.convert("RGB").resize((JK, JK), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            pass
    ph = Image.new("RGB", (JK, JK), (22, 32, 32))
    d = ImageDraw.Draw(ph)
    d.text((JK / 2, JK / 2 - 12), "?", font=CB._font("latin", 56), fill=(86, 112, 104), anchor="mm")
    return ph


def _avatar(img: Image.Image, cx: int, cy: int, r: int, player: str) -> None:
    """名牌上的六边形头像位：手动传分没有游戏里的头像，放看板娘（包里没有这张图就写名字的第一个字）。"""
    hexa = [(cx + r * math.cos(math.radians(60 * k)), cy + r * math.sin(math.radians(60 * k))) for k in range(6)]
    glow = _layer(img)
    ImageDraw.Draw(glow).polygon(hexa, fill=NEON + (90,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(16)))
    s = 2
    size = r * 2 * s
    tile = Image.new("RGBA", (size, size), (16, 44, 40, 255))
    td = ImageDraw.Draw(tile)
    for yy in range(size):
        k = yy / size
        td.line([(0, yy), (size, yy)], fill=(int(30 - 14 * k), int(84 - 44 * k), int(74 - 38 * k), 255))
    girl = _mascot(int(size * 0.98), "hello", (0.5, 0.0, 0.60))     # 站着那张，只取头到胸口
    if girl is not None:
        tile.alpha_composite(girl, ((size - girl.width) // 2, int(size * 0.07)))
    else:
        ch = (player or "?").strip()[:1].upper() or "?"
        G.draw(ImageDraw.Draw(tile), (size // 2, size // 2), ch, CB._chain("bold", int(size * 0.5)), (220, 255, 236),
               anchor="mm")
    hx = [(size / 2 + (size / 2 - 2) * math.cos(math.radians(60 * k)), size / 2 + (size / 2 - 2) * math.sin(math.radians(60 * k)))
          for k in range(6)]
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(hx, fill=255)
    tile.putalpha(mask)
    ImageDraw.Draw(tile).line(hx + [hx[0], hx[1]], fill=NEON + (255,), width=5 * s, joint="curve")
    img.alpha_composite(tile.resize((r * 2, r * 2), Image.Resampling.LANCZOS), (cx - r, cy - r))


# ---------------------------------------------------------------- 主体
def render(rows: list[K.SdvxRow], out_path: Path, *, player: str = "", jackets: dict | None = None,
           font_path: str | None = None, tz: str = "Australia/Sydney", bg_path=None,
           footer_left: str = "Generated by AstrBot", count: int = 0, all_rows: list | None = None,
           max_kb: int = 3000, show_ex: bool = True) -> Path:
    jackets = jackets or {}
    rows = rows[:50]
    all_rows = all_rows if all_rows is not None else rows
    total = K.sdvx_total(rows)
    n = len(rows)
    nrows = (n + COLS - 1) // COLS
    cards_y = HEADER_H + STATS_H + 36
    h = cards_y + nrows * (CARD_H + GAP_Y) + 16 + FOOTER_H
    img = CB._background(h, bg_path if bg_path is not None else TB.background("sdvx", "nabla", h))
    base, stars, c1, c2 = class_parts(total)

    # ---- 页头左：切角名牌 ----
    px, py, pw, ph = MX, 44, 1010, 248
    CB._overlay(img, lambda od: od.polygon(_cut(px, py, pw, ph, 34), fill=(4, 14, 12, 222)))
    CB._overlay(img, lambda od: od.line(_cut(px, py, pw, ph, 34) + [(px + 34, py)], fill=NEON + (120,), width=2))
    CB._overlay(img, lambda od: od.polygon([(px + 34, py), (px + 420, py), (px + 412, py + 8), (px + 26, py + 8)],
                                           fill=NEON + (255,)))
    _avatar(img, px + 150, py + ph // 2 + 4, 96, player)
    d = ImageDraw.Draw(img)
    nx = px + 280
    d.text((nx, py + 52), "SOUND VOLTEX", font=CB._font("latin", 28), fill=(120, 255, 190), anchor="lm")
    lw = d.textlength("SOUND VOLTEX ", font=CB._font("latin", 28))
    G.draw(d, (nx + lw + 4, py + 52), "∇  VOLFORCE 50", CB._chain("sc", 26), (170, 220, 200), anchor="lm")
    c_name = CB._chain("bold", 74, font_path)
    G.draw(d, (nx, py + 124), CB._fit(d, player or "?", c_name, px + pw - 50 - nx), c_name, (255, 255, 255), anchor="lm")
    date = datetime.now(ZoneInfo(tz)).strftime("%Y/%m/%d")
    tx = nx
    for text in ("手动传分", f"已传 {count or n} 张", date):
        c_tag = CB._chain("sc", 23)
        tw = int(G.width(text, c_tag)) + 28
        CB._overlay(img, lambda od: od.rounded_rectangle([tx, py + 182, tx + tw, py + 218], 18, fill=(70, 255, 160, 34),
                                                         outline=NEON + (130,), width=2))
        G.draw(ImageDraw.Draw(img), (tx + tw // 2, py + 199), text, c_tag, (206, 250, 228), anchor="mm")
        tx += tw + 12

    # ---- 页头右：徽章 + 大数字 + 到下一档的进度 ----
    ex, ey, er = 1196, 165, 112
    _emblem(img, ex, ey, er, total)
    d = ImageDraw.Draw(img)
    d.text((1346, 46), "VOLFORCE", font=CB._font("latin", 32), fill=(225, 240, 232))
    big = _gradient_text(K.fmt_k(total), CB._font("latin", 124), c2, c1, stroke=6, stroke_fill=(8, 12, 12))
    glow = Image.new("RGBA", big.size, (0, 0, 0, 0))
    glow.paste(Image.new("RGBA", big.size, c2 + (110,)), (0, 0), big.getchannel("A"))
    gx = 1342
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(8)), (gx, 80))
    img.alpha_composite(big, (gx, 80))
    d = ImageDraw.Draw(img)
    d.text((gx + 4, 250), base, font=CB._font("latin", 36), fill=c2, anchor="lm")
    sx = gx + 30 + d.textlength(base, font=CB._font("latin", 36))
    for i in range(4):
        _star(d, sx + i * 34, 250, 14, c2 + (255,) if i < stars else (60, 70, 70, 255), outline=(10, 10, 10, 255))
    nxt = next((b for b, _ in reversed(K.CLASSES) if b > total), None)
    lo = max((b for b, _ in K.CLASSES if b <= total), default=0)
    bx0, bx1, by = gx + 4, W - MX - 6, 284
    CB._overlay(img, lambda od: od.rounded_rectangle([bx0, by, bx1, by + 10], 5, fill=(0, 0, 0, 150)))
    frac = 1.0 if nxt is None else max(0.02, min(1.0, (total - lo) / max(nxt - lo, 1)))
    CB._overlay(img, lambda od: od.rounded_rectangle([bx0, by, bx0 + int((bx1 - bx0) * frac), by + 10], 5, fill=c2 + (255,)))

    # ---- 统计条 ----
    sy = HEADER_H
    CB._overlay(img, lambda od: od.rounded_rectangle([MX, sy, W - MX, sy + STATS_H], 16, fill=(4, 14, 12, 208)))
    counts = {k: sum(1 for r in all_rows if r.lamp == k) for k in LAMP_STYLE}
    order = ("PUC", "UC", "MXV", "EXC", "COMP", "PLAY")
    x = MX + 26
    fl, fc = CB._font("latin", 21), CB._font("latin", 26)
    d = ImageDraw.Draw(img)
    for k in order:
        name, bg, fg = LAMP_STYLE[k]
        w = _badge(img, x, sy + 44, name, bg, fg, fl, pad=11, h=34, r=17)
        d = ImageDraw.Draw(img)
        d.text((x + w + 9, sy + 61), str(counts[k]), font=fc, fill=(255, 255, 255), anchor="lm")
        x += w + 9 + int(d.textlength(str(counts[k]), font=fc)) + 24
    bar_x0, bar_x1 = MX + 26, max(x - 24, MX + 300)
    tot = sum(counts.values())
    if tot:                                     # 上面一条按张数比例分段的色条
        cx = bar_x0
        span = bar_x1 - bar_x0
        segs = [(k, counts[k]) for k in order if counts[k]]
        for i, (k, c) in enumerate(segs):
            x1 = bar_x1 if i == len(segs) - 1 else cx + max(4, round(span * c / tot))
            CB._overlay(img, lambda od, a=cx, b=x1, col=LAMP_STYLE[k][1]: od.rounded_rectangle(
                [a, sy + 18, max(a + 2, b - 3), sy + 28], 4, fill=col + (255,)))
            cx = x1
    d = ImageDraw.Draw(img)
    avg = total // n if n else 0
    top = rows[0].vf if rows else 0
    stats = [("单曲平均", K.fmt_song(avg)), ("单曲最高", K.fmt_song(top))]
    if nxt is not None:
        stats.append((f"到 {K.vf_class(nxt)} 还差", f"{K.fmt_k(nxt - total)}"))
    x = W - MX - 28
    for i, (label, val) in enumerate(reversed(stats)):
        vw = d.textlength(val, font=CB._font("latin", 36))
        cw = int(max(vw, G.width(label, CB._chain("sc", 22))))
        d.text((x, sy + 86), val, font=CB._font("latin", 36), fill=c2 if i == 0 and nxt is not None else (255, 255, 255),
               anchor="rs")
        G.draw(d, (x, sy + 30), label, CB._chain("sc", 22), (150, 230, 190), anchor="rm")
        x -= cw + 26
        if i < len(stats) - 1:
            d.line([(x, sy + 22), (x, sy + STATS_H - 22)], fill=(70, 110, 96), width=2)
        x -= 26

    # ---- 卡片 ----
    for i, r in enumerate(rows):
        cx = MX + (i % COLS) * (CARD_W + GAP_X)
        cy = cards_y + (i // COLS) * (CARD_H + GAP_Y)
        _card(img, r, i, cx, cy, jackets.get(r.title), font_path, show_ex)

    # ---- 页脚 ----
    fy = h - FOOTER_H
    CB._overlay(img, lambda od: od.rectangle([0, fy, W, h], fill=(2, 10, 8, 200)))
    CB._overlay(img, lambda od: od.rectangle([0, fy, W, fy + 3], fill=NEON + (200,)))
    d = ImageDraw.Draw(img)
    fmid = fy + FOOTER_H // 2
    ff = CB._chain("latin_r", 28) if footer_left.isascii() else CB._chain("sc", 26)
    G.draw(d, (30, fmid), footer_left, ff, (210, 240, 225), anchor="lm")
    G.draw(d, (W - 30, fmid), "卡片右下 = 单曲 VF ×50（∇ 规则），50 张平均 = VOLFORCE · 曲库 Tachi · 曲绘 sdvx.in",
           CB._chain("sc", 24), (210, 240, 225), anchor="rm")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    data, _ = CB.encode_jpeg(img.convert("RGB"), max_kb)
    out_path.write_bytes(data)
    return out_path
