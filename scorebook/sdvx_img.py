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
import os
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
PROFILE_H = 420                # 名片条（六维图 + 领航员），两样都没填就没有这一条
RADAR_AXES = ("NOTES", "PEAK", "TSUMAMI", "TRICKY", "HAND-TRIP", "ONE-HAND")
RADAR_COLORS = ((64, 224, 216), (255, 56, 96), (240, 60, 200), (232, 228, 48), (150, 84, 255), (56, 224, 80))
RADAR_LABELS = ("NOTES", "PEAK", "TSUMAMI", "TRICKY", "HAND TRIP", "ONE HAND")       # 游戏个人卡上的写法（没有连字符）
RADAR_FILL = (255, 96, 32)     # 游戏个人卡上那个六维图：橙红色，圈是 100，超过 100 的角会伸到圈外面（爆表）
RADAR_OVER = 1.75              # 爆表最多画到圈半径的这么多倍，再大就顶到名片条外面了
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


def _nav_face(nav: str | None, size: int) -> Image.Image | None:
    """头像：网站上单独框过的（领航员图旁边的 <QQ>_face.png）就用它；没有就从领航员图取上方居中的一块（脸一般在上面）。"""
    if not nav:
        return None
    face = nav[:-4] + "_face.png" if nav.endswith(".png") else ""
    if face and os.path.exists(face):
        try:
            with Image.open(face) as src:
                return src.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            pass
    try:
        with Image.open(nav) as src:
            src = src.convert("RGBA")
            side = int(min(src.width * 0.62, src.height * 0.62))
            x0 = (src.width - side) // 2
            y0 = int(src.height * 0.06)
            y0 = max(0, min(y0, src.height - side))
            return src.crop((x0, y0, x0 + side, y0 + side)).resize((size, size), Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        return None


def _avatar(img: Image.Image, cx: int, cy: int, r: int, player: str, nav: str | None = None) -> None:
    """名牌上的六边形头像位：传了领航员图就放领航员的脸；没有就放看板娘（包里没有这张图就写名字的第一个字）。"""
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
    face = _nav_face(nav, size)
    girl = None if face is not None else _mascot(int(size * 0.98), "hello", (0.5, 0.0, 0.60))   # 站着那张，只取头到胸口
    if face is not None:
        tile.alpha_composite(face)
    elif girl is not None:
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


# 游戏里六维图旁边的字是一种方头方脑的等线字。不带字体文件，自己用折线描：每个字是几条折线，坐标在 1 × 1 的格子里
# （x 往右、y 往下，0.5 是中线），画的时候按字高和宽高比拉开，线头是圆的、拐角削成小圆角。
# 照游戏个人卡量的：数字细、每个数字占一样宽（1 是一根竖线，站在格子正中）、数字之间空得很开，小数点塞在两个数字中间；
# 轴名粗、字挨得近。字宽、字高都把笔画的粗细算在里面（折线画在往里缩半个笔画的框里），所以字和字不会糊在一起。
_SEG = {
    "0": [[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]],
    "1": [[(.5, 0), (.5, 1)]],
    "2": [[(0, 0), (1, 0), (1, .5), (0, .5), (0, 1), (1, 1)]],
    "3": [[(0, 0), (1, 0), (1, 1), (0, 1)], [(.3, .5), (1, .5)]],
    "4": [[(.8, 1), (.8, 0), (0, .7), (1, .7)]],
    "5": [[(1, 0), (0, 0), (0, .5), (1, .5), (1, 1), (0, 1)]],
    "6": [[(1, 0), (0, 0), (0, 1), (1, 1), (1, .5), (0, .5)]],
    "7": [[(0, 0), (1, 0), (.4, 1)]],
    "8": [[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], [(0, .5), (1, .5)]],
    "9": [[(1, .5), (0, .5), (0, 0), (1, 0), (1, 1), (0, 1)]],
    ".": [[(.5, .98), (.5, 1.08)]],
    "+": [[(0, .5), (1, .5)], [(.5, .16), (.5, .84)]],
    "-": [[(.1, .5), (.9, .5)]],
    "A": [[(0, 1), (.32, 0), (.68, 0), (1, 1)], [(.17, .64), (.83, .64)]],
    "C": [[(1, 0), (0, 0), (0, 1), (1, 1)]],
    "D": [[(0, 0), (.62, 0), (1, .3), (1, .7), (.62, 1), (0, 1), (0, 0)]],
    "E": [[(1, 0), (0, 0), (0, 1), (1, 1)], [(0, .5), (.82, .5)]],
    "H": [[(0, 0), (0, 1)], [(1, 0), (1, 1)], [(0, .5), (1, .5)]],
    "I": [[(.5, 0), (.5, 1)]],
    "K": [[(0, 0), (0, 1)], [(1, 0), (.06, .5), (1, 1)]],
    "M": [[(0, 1), (0, 0), (.5, .58), (1, 0), (1, 1)]],
    "N": [[(0, 1), (0, 0), (1, 1), (1, 0)]],
    "O": [[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]],
    "P": [[(0, 1), (0, 0), (1, 0), (1, .52), (0, .52)]],
    "R": [[(0, 1), (0, 0), (1, 0), (1, .52), (0, .52)], [(.45, .52), (1, 1)]],
    "S": [[(1, 0), (0, 0), (0, .5), (1, .5), (1, 1), (0, 1)]],
    "T": [[(0, 0), (1, 0)], [(.5, 0), (.5, 1)]],
    "U": [[(0, 0), (0, 1), (1, 1), (1, 0)]],
    "Y": [[(0, 0), (.5, .5), (1, 0)], [(.5, .5), (.5, 1)]],
}
_SEG_W = {"I": .2, "M": 1.2, " ": .5, "+": .8, "-": .8}      # 窄字 / 宽字占多宽（别的都是 1；数字全是 1，对得齐）
_SEG_DOT = 0.24                # 小数点：不单独占一格，只把两个数字之间多撑开这么多（占一个字宽的比例）


def _seg_round(pts: list, rr: float) -> list:
    """把折线的拐弯削成小圆角（拐点换成前后各退 rr 的两个点，线的接头再是圆的，看起来就是圆角方块字）。"""
    closed = len(pts) > 2 and pts[0] == pts[-1]
    core = pts[:-1] if closed else pts
    n = len(core)
    out = []
    for i, p in enumerate(core):
        if not closed and i in (0, n - 1):
            out.append(p)
            continue
        a, b = core[i - 1], core[(i + 1) % n]
        for q in (a, b):
            dx, dy = q[0] - p[0], q[1] - p[1]
            ln = math.hypot(dx, dy) or 1.0
            k = min(rr, ln * 0.45) / ln
            out.append((p[0] + dx * k, p[1] + dy * k))
    if closed:
        out.append(out[0])
    return out


def _seg_layout(text: str, cap: float, aspect: float, gap: float) -> tuple[list, float]:
    """每个字放哪：[(字, 这格的左边, 这格的宽)]，和整行的宽。"""
    w = cap * aspect
    x = 0.0
    out = []
    for ch in text:
        if ch == "." and out:                       # 塞在前后两个字的空当正中
            out.append((ch, x - gap * w / 2 + _SEG_DOT * w / 2 - 0.5 * w, w))
            x += _SEG_DOT * w
            continue
        gw = _SEG_W.get(ch, 1.0) * w
        out.append((ch, x, gw))
        x += gw + gap * w
    return out, max(0.0, x - gap * w)


def _seg_width(text: str, cap: float, aspect: float, gap: float = 0.2) -> float:
    return _seg_layout(text, cap, aspect, gap)[1]


def _seg_text(img: Image.Image, x: float, y: float, text: str, cap: float, fill, *, weight: float = 0.2,
              aspect: float = 0.77, gap: float = 0.2, anchor: str = "l", outline=(8, 10, 22), ow: float | None = None,
              rr: float = 0.18) -> float:
    """在 (x, y) 画一行方头字：y 是字顶，cap 是字高，weight 是笔画粗细（占字高的比例），gap 是字距（占字宽的比例），
    anchor l / m / r。返回这一行的宽。"""
    cells, total = _seg_layout(text, cap, aspect, gap)
    x0 = x - (total / 2 if anchor == "m" else total if anchor == "r" else 0)
    s = 4
    sw = max(1.0, cap * weight)
    ow = max(1.2, cap * 0.075) if ow is None else ow
    pad = int(sw + ow + 3)
    lay = Image.new("RGBA", (int((total + pad * 2) * s), int((cap * 1.14 + pad * 2) * s)), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    w = cap * aspect
    strokes = []
    for ch, cx, gw in cells:
        iw = max(0.0, gw - sw)                      # 折线画在往里缩半个笔画的框里：字的外沿正好是这一格
        for line in _SEG.get(ch, []):
            pts = [((pad + cx + (gw - iw) / 2 + px * iw) * s, (pad + sw / 2 + py * (cap - sw)) * s) for px, py in line]
            strokes.append(_seg_round(pts, w * rr * s))
    for width, color in (((sw + ow * 2) * s, tuple(outline) + (255,)), (sw * s, tuple(fill) + (255,))):
        r = width / 2
        for pts in strokes:
            d.line(pts, fill=color, width=max(1, round(width)), joint="curve")
            for px, py in pts:                                     # 圆线头、圆拐角
                d.ellipse([px - r, py - r, px + r, py + r], fill=color)
    small = lay.resize((max(1, lay.width // s), max(1, lay.height // s)), Image.Resampling.LANCZOS)
    img.alpha_composite(small, (round(x0 - pad), round(y - pad)))
    return total


def _radar_panel(img: Image.Image, x0: int, y0: int, w: int, h: int, vals: list | None) -> None:
    """照游戏个人卡上那个六维图画：黑色的圆底，六条带小刻度的细轴，数据是橙红色的一块（中间亮、边上红）；
    圈 = 100，超过 100 的角伸到圈外面（爆表）。每个角外面两行：轴名（各用各的颜色）和两位小数的数值（白字），都是方头字带深色描边。
    从上面顺时针 NOTES / PEAK / TSUMAMI / TRICKY / HAND TRIP / ONE HAND。vals 是 None：只画空的 + 提示怎么填。"""
    empty = not vals
    vals = [max(0.0, float(v)) for v in (vals or [0] * 6)]
    r = int(min((h - 8) / 2.96, w / 3.5))            # 照游戏的比例：上下的字各伸出去半径的 0.47 倍，两侧 0.64 倍
    cx, cy = x0 + w // 2, y0 + h // 2
    ang = [math.radians(-90 + 60 * k) for k in range(6)]
    pt = lambda k, f: (cx + r * f * math.cos(ang[k]), cy + r * f * math.sin(ang[k]))     # noqa: E731
    s = 4                                           # 先放大画再缩小，边缘更顺
    mg = int(r * (RADAR_OVER - 1)) + 8              # 这一层比名片条大一圈：爆表的角画得出去
    bx, by = cx - r - mg, cy - r - mg
    side = (r + mg) * 2
    S = lambda p: ((p[0] - bx) * s, (p[1] - by) * s)                                     # noqa: E731
    lay = Image.new("RGBA", (side * s, side * s), (0, 0, 0, 0))
    ImageDraw.Draw(lay).ellipse([S((cx - r, cy - r)), S((cx + r, cy + r))], fill=(0, 0, 0, 236))

    lw, tick = max(1.3, r * 0.012), max(2.5, r * 0.022)        # 轴线粗细、刻度半长：跟着半径走

    def axes(alpha: int, color=(214, 214, 220)) -> Image.Image:
        a = Image.new("RGBA", lay.size, (0, 0, 0, 0))
        ad = ImageDraw.Draw(a)
        for k in range(6):                          # 轴画到圈边；25 / 50 / 75 各一道和轴垂直的小刻度
            ad.line([S((cx, cy)), S(pt(k, 1))], fill=color + (alpha,), width=round(lw * s))
            nx, ny = -math.sin(ang[k]), math.cos(ang[k])
            for f in (0.25, 0.5, 0.75):
                px, py = pt(k, f)
                ad.line([S((px - nx * tick, py - ny * tick)), S((px + nx * tick, py + ny * tick))], fill=color + (alpha,),
                        width=round(lw * s))
        return a

    lay = Image.alpha_composite(lay, axes(200))
    if not empty:
        poly = [S(pt(k, max(0.03, min(RADAR_OVER, vals[k] / 100)))) for k in range(6)]
        shape = Image.new("L", lay.size, 0)
        ImageDraw.Draw(shape).polygon(poly, fill=255)
        n = 64                                      # 中间亮橙、往外变红：小图上按离中心的远近算，再放大
        g = Image.new("RGB", (n, n))
        gp = g.load()
        for yy in range(n):
            for xx in range(n):
                t = min(1.0, math.hypot(xx - n / 2 + .5, yy - n / 2 + .5) / (n / 2) * (r + mg) / (r * 1.05))
                gp[xx, yy] = tuple(round(a + (b - a) * t) for a, b in zip((255, 108, 34), (234, 50, 28)))
        fill = g.resize(lay.size, Image.Resampling.BICUBIC).convert("RGBA")
        fill.putalpha(shape.point(lambda v: 244 if v else 0))
        lay = Image.alpha_composite(lay, fill)
        over = axes(135, (255, 214, 190))            # 轴在橙块上还看得见，颜色淡一点
        over.putalpha(Image.composite(over.getchannel("A"), Image.new("L", lay.size, 0), shape))
        lay = Image.alpha_composite(lay, over)
        ImageDraw.Draw(lay).line(poly + [poly[0], poly[1]], fill=(255, 150, 84, 255), width=round(lw * 1.1 * s),
                                 joint="curve")
    disc = lay.resize((side, side), Image.Resampling.LANCZOS)
    # 贴到图上：只留名片条这一块里的（爆表的角可以伸到条内任何地方，但不出条）
    clip = Image.new("RGBA", img.size, (0, 0, 0, 0))
    clip.paste(disc, (bx, by), disc)
    keep = Image.new("L", img.size, 0)
    ImageDraw.Draw(keep).rectangle([x0, y0 - 8, x0 + w, y0 + h + 8], fill=255)
    clip.putalpha(Image.composite(clip.getchannel("A"), Image.new("L", img.size, 0), keep))
    img.alpha_composite(clip)
    if empty:
        d = ImageDraw.Draw(img)
        G.draw(d, (cx, cy - r * 0.15), "还没填六维图", CB._chain("sc", max(12, round(r * 0.2))), (236, 240, 238), anchor="mm")
        G.draw(d, (cx, cy + r * 0.17), "/sdvx 雷达 + 6 个数", CB._chain("sc", max(11, round(r * 0.165))), (160, 206, 188),
               anchor="mm")
    # 字的位置和大小都是照游戏个人卡量出来的（以圆心为原点、半径为 1）：轴名字高 0.145、数值字高 0.164；
    # 上下两项在圈外居中；两侧四项的中心在 ±1.14，上面两项贴着圈的上沿往上放、下面两项往下放。字压在橙块上面。
    name_h, val_h = r * 0.155, r * 0.178
    spots = ((0, -1.39, -1.14), (1.12, -0.95, -0.69), (1.14, 0.67, 0.92), (0, 1.13, 1.38), (-1.14, 0.67, 0.92),
             (-1.13, -0.95, -0.69))
    for k, (fx, fy_name, fy_val) in enumerate(spots):
        txt = "--.--" if empty else f"{vals[k]:.2f}"
        mx = cx + fx * r
        _seg_text(img, mx, cy + fy_name * r - name_h / 2, RADAR_LABELS[k], name_h, RADAR_COLORS[k], weight=0.19,
                  aspect=0.8, gap=0.15, anchor="m", rr=0.07)
        _seg_text(img, mx, cy + fy_val * r - val_h / 2, txt, val_h, (238, 240, 246), weight=0.13, aspect=0.76,
                  gap=0.36, anchor="m", rr=0.13)


def _nav_panel(img: Image.Image, x0: int, y0: int, w: int, h: int, nav: str, name: str) -> None:
    """领航员图：铺满这一块（按高度放，脸在上面，所以从上往下取），斜切边框 + 荧光线。"""
    try:
        with Image.open(nav) as src:
            src = src.convert("RGBA")
            k = max(w / src.width, h / src.height)
            im = src.resize((max(w, int(src.width * k)), max(h, int(src.height * k))), Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        return
    left = (im.width - w) // 2
    top = int((im.height - h) * 0.18)               # 偏上取，脸不被切掉
    tile = im.crop((left, top, left + w, top + h))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(_cut(0, 0, w, h, 26), fill=255)
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for yy in range(h // 2, h):                     # 底部压暗，写名字
        sd.line([(0, yy), (w, yy)], fill=(0, 0, 0, int(190 * (yy - h // 2) / (h // 2))))
    tile = Image.alpha_composite(tile, shade)
    tile.putalpha(Image.composite(tile.getchannel("A"), Image.new("L", (w, h), 0), mask))
    img.alpha_composite(tile, (x0, y0))
    CB._overlay(img, lambda od: od.line(_cut(x0, y0, w, h, 26) + [_cut(x0, y0, w, h, 26)[0]], fill=NEON + (200,), width=3))
    d = ImageDraw.Draw(img)
    d.text((x0 + 26, y0 + h - 58), "NAVIGATOR", font=CB._font("latin", 22), fill=(150, 255, 200), anchor="lm")
    if name:
        c = CB._chain("bold", 40)
        G.draw(d, (x0 + 26, y0 + h - 24), CB._fit(d, name, c, w - 52), c, (255, 255, 255), anchor="lm")


def _profile_band(img: Image.Image, y: int, radar: list | None, nav: str | None, nav_name: str) -> None:
    h = PROFILE_H - 18
    CB._overlay(img, lambda od: od.polygon(_cut(MX, y, W - 2 * MX, h, 26), fill=(4, 14, 12, 214)))
    CB._overlay(img, lambda od: od.line(_cut(MX, y, W - 2 * MX, h, 26) + [_cut(MX, y, W - 2 * MX, h, 26)[0]],
                                        fill=NEON + (110,), width=2))
    inner_y, inner_h = y + 14, h - 28
    if radar and nav:
        rw = 760
        _radar_panel(img, MX + 20, inner_y, rw, inner_h, radar)
        _nav_panel(img, MX + 20 + rw + 24, inner_y, W - 2 * MX - 40 - rw - 24, inner_h, nav, nav_name)
    elif radar:
        _radar_panel(img, MX + 20, inner_y, 760, inner_h, radar)
        d = ImageDraw.Draw(img)
        G.draw(d, (W - MX - 30, y + h - 26), "六维图是自己填的：/sdvx 雷达 6 个数", CB._chain("sc", 22), (130, 190, 165),
               anchor="rm")
    else:                                           # 只有领航员：左边空的六维图，版式和两样都有时一样
        rw = 760
        _radar_panel(img, MX + 20, inner_y, rw, inner_h, None)
        _nav_panel(img, MX + 20 + rw + 24, inner_y, W - 2 * MX - 40 - rw - 24, inner_h, nav, nav_name)


# ---------------------------------------------------------------- 主体
def render(rows: list[K.SdvxRow], out_path: Path, *, player: str = "", jackets: dict | None = None,
           font_path: str | None = None, tz: str = "Australia/Sydney", bg_path=None,
           footer_left: str = "Generated by AstrBot", count: int = 0, all_rows: list | None = None,
           max_kb: int = 3000, show_ex: bool = True, radar: list | None = None, nav: str | None = None,
           nav_name: str = "", tags: tuple | None = None) -> Path:
    jackets = jackets or {}
    rows = rows[:50]
    all_rows = all_rows if all_rows is not None else rows
    total = K.sdvx_total(rows)
    n = len(rows)
    nrows = (n + COLS - 1) // COLS
    radar = list(radar)[:6] if radar and len(radar) >= 6 else None
    band = PROFILE_H if (radar or nav) else 0
    cards_y = HEADER_H + band + STATS_H + 36
    h = cards_y + nrows * (CARD_H + GAP_Y) + 16 + FOOTER_H
    img = CB._background(h, bg_path if bg_path is not None else TB.background("sdvx", "nabla", h))
    base, stars, c1, c2 = class_parts(total)

    # ---- 页头左：切角名牌 ----
    px, py, pw, ph = MX, 44, 1010, 248
    CB._overlay(img, lambda od: od.polygon(_cut(px, py, pw, ph, 34), fill=(4, 14, 12, 222)))
    CB._overlay(img, lambda od: od.line(_cut(px, py, pw, ph, 34) + [(px + 34, py)], fill=NEON + (120,), width=2))
    CB._overlay(img, lambda od: od.polygon([(px + 34, py), (px + 420, py), (px + 412, py + 8), (px + 26, py + 8)],
                                           fill=NEON + (255,)))
    _avatar(img, px + 150, py + ph // 2 + 4, 96, player, nav)
    d = ImageDraw.Draw(img)
    nx = px + 280
    d.text((nx, py + 52), "SOUND VOLTEX", font=CB._font("latin", 28), fill=(120, 255, 190), anchor="lm")
    lw = d.textlength("SOUND VOLTEX ", font=CB._font("latin", 28))
    G.draw(d, (nx + lw + 4, py + 52), "∇  VOLFORCE 50", CB._chain("sc", 26), (170, 220, 200), anchor="lm")
    c_name = CB._chain("bold", 74, font_path)
    G.draw(d, (nx, py + 124), CB._fit(d, player or "?", c_name, px + pw - 50 - nx), c_name, (255, 255, 255), anchor="lm")
    date = datetime.now(ZoneInfo(tz)).strftime("%Y/%m/%d")
    tx = nx
    for text in ((*tags, date) if tags else ("手动传分", f"已传 {count or n} 张", date)):
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

    # ---- 名片条：六维图 + 领航员 ----
    if band:
        _profile_band(img, HEADER_H - 6, radar, nav, nav_name)

    # ---- 统计条 ----
    sy = HEADER_H + band
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
