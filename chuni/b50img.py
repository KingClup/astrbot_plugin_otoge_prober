"""B50 图片渲染（版式参考 chuni-penguin 的 B50 图，Design by Tukkun；致谢写在 README / WebUI）。

结构：页头（黑色名牌、RATING 数字框、原始平均值、版本 logo）→ OLD CHARTS 斜标签 + 日期标签 → 5 列卡片
→ NEW CHARTS → 页脚。背景 / logo / rating 数字图来自 ThemeStore（用户自己上传，不随插件分发），
缺素材时退回自绘的渐变背景、文字 logo 和字体数字。
"""

from __future__ import annotations

import math
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    from ..core import glyphs as G
except ImportError:  # tests import the subpackages top-level
    from core import glyphs as G
from .models import ComboLamp, Difficulty, Score
from .rating import B50, song_rating, whole_rating

W = 1872
HEADER_H = 220
TAB_Y_GAP = 80          # 页头下方到 OLD 标签
TAB_H = 80
CARDS_GAP = 25          # 标签到第一行卡片
CARD_W, CARD_H = 350, 215
GAP_X, GAP_Y = 15, 25
MARGIN_X = 30
JACKET = 110
SECTION_GAP = 60
FOOTER_H = 70

# 卡片配色：(主体, 标题栏, 底栏)
DIFF_STYLE = {
    Difficulty.BASIC: ((52, 120, 70), (36, 88, 50), (24, 60, 34)),
    Difficulty.ADVANCED: ((150, 96, 30), (112, 70, 20), (78, 48, 12)),
    Difficulty.EXPERT: ((140, 44, 62), (104, 30, 44), (72, 20, 30)),
    Difficulty.MASTER: ((86, 58, 120), (62, 42, 88), (40, 28, 58)),
    Difficulty.ULTIMA: ((34, 30, 36), (22, 20, 24), (14, 12, 16)),
    Difficulty.WORLDS_END: ((40, 80, 140), (28, 58, 104), (18, 40, 72)),
}

RATING_TIERS = [(17.00, 10), (16.00, 9), (15.25, 8), (14.50, 7), (13.25, 6),
                (12.00, 5), (10.00, 4), (7.00, 3), (4.00, 2)]
TIER_COLORS = {1: (70, 210, 120), 2: (255, 160, 50), 3: (255, 80, 80), 4: (185, 95, 255),
               5: (215, 140, 60), 6: (215, 222, 232), 7: (255, 214, 74), 8: (232, 246, 255)}
RAINBOW = [(255, 90, 90), (255, 190, 60), (250, 245, 90), (90, 230, 120),
           (80, 200, 255), (150, 110, 255), (255, 110, 220)]

BOLD_CANDIDATES = [
    (r"C:\Windows\Fonts\YuGothB.ttc", 0), (r"C:\Windows\Fonts\meiryob.ttc", 0),
    (r"C:\Windows\Fonts\msyhbd.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 0),
    ("/System/Library/Fonts/PingFang.ttc", 0),
]
REGULAR_CANDIDATES = [
    (r"C:\Windows\Fonts\YuGothM.ttc", 0), (r"C:\Windows\Fonts\meiryo.ttc", 0),
    (r"C:\Windows\Fonts\msyh.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 0),
    ("/System/Library/Fonts/PingFang.ttc", 0),
]
# simplified Chinese first (国际服 / 鱼 / 查 are missing from the Japanese fonts above)
SC_BOLD_CANDIDATES = [
    (r"C:\Windows\Fonts\msyhbd.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", 2),
    ("/System/Library/Fonts/PingFang.ttc", 0),
]
LATIN_BOLD_CANDIDATES = [
    (r"C:\Windows\Fonts\segoeuib.ttf", 0), (r"C:\Windows\Fonts\arialbd.ttf", 0),
    ("/usr/share/fonts/opentype/inter/Inter-Bold.otf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]
LATIN_REGULAR_CANDIDATES = [
    (r"C:\Windows\Fonts\segoeui.ttf", 0), (r"C:\Windows\Fonts\arial.ttf", 0),
    ("/usr/share/fonts/opentype/inter/Inter-Regular.otf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]
# 逐字回退：主字体缺的字（简体「论」、✓ ♭ ℝ、韩文、古波斯文…）去这些字体里找
FALLBACK_CANDIDATES = [
    (r"C:\Windows\Fonts\msyhbd.ttc", 0), (r"C:\Windows\Fonts\YuGothB.ttc", 0),
    (r"C:\Windows\Fonts\seguisym.ttf", 0), (r"C:\Windows\Fonts\cambria.ttc", 0),
    (r"C:\Windows\Fonts\seguihis.ttf", 0), (r"C:\Windows\Fonts\malgunbd.ttf", 0),
    (r"C:\Windows\Fonts\msgothic.ttc", 0), (r"C:\Windows\Fonts\simsun.ttc", 0),
    (r"C:\Windows\Fonts\seguiemj.ttf", 0), (r"C:\Windows\Fonts\segoeuib.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/System/Library/Fonts/Apple Symbols.ttf", 0),
]
_font_cache: dict[tuple, ImageFont.FreeTypeFont] = {}
_chain_cache: dict[tuple, list] = {}
_registered: list[str] = []  # 插件自动下载的字体（fonts.py），排在系统字体之后


def register_font(path: str) -> None:
    if path not in _registered:
        _registered.append(path)
        _font_cache.clear()
        _chain_cache.clear()


def _chain(kind: str, size: int, override: str | None = None) -> list:
    """[主字体, 回退字体…]，按文件去重。"""
    key = (kind, size, override)
    if key in _chain_cache:
        return _chain_cache[key]
    main = _font(kind, size, override)
    out, seen = [main], {(str(getattr(main, "path", "")), int(getattr(main, "index", 0) or 0))}
    for path, idx in FALLBACK_CANDIDATES + [(p, 0) for p in _registered]:
        if (path, idx) in seen or not Path(path).exists():
            continue
        try:
            out.append(ImageFont.truetype(path, size, index=idx))
            seen.add((path, idx))
        except OSError:
            continue
    _chain_cache[key] = out
    return out


def _font(kind: str, size: int, override: str | None = None):
    key = (kind, size, override)
    if key in _font_cache:
        return _font_cache[key]
    cands = {"bold": BOLD_CANDIDATES, "regular": REGULAR_CANDIDATES, "sc": SC_BOLD_CANDIDATES + BOLD_CANDIDATES,
             "latin": LATIN_BOLD_CANDIDATES + BOLD_CANDIDATES,
             "latin_r": LATIN_REGULAR_CANDIDATES + REGULAR_CANDIDATES}[kind]
    if override and kind in ("bold", "regular"):
        cands = [(override, 0)] + cands
    cands = cands + [(p, 0) for p in _registered]
    for path, idx in cands:
        if Path(path).exists():
            try:
                f = ImageFont.truetype(path, size, index=idx)
                _font_cache[key] = f
                return f
            except OSError:
                continue
    # 最后在系统字体目录里找任意 CJK 字体（Linux 服务器 / Docker 常见情况）
    for path in _scan_cjk_fonts():
        try:
            f = ImageFont.truetype(str(path), size)
            _font_cache[key] = f
            return f
        except OSError:
            continue
    f = ImageFont.load_default(size)  # 没有中日文字体：中文会显示成方框，请装字体或配置 font_path
    _font_cache[key] = f
    return f


_scanned: list[Path] | None = None


def _scan_cjk_fonts() -> list[Path]:
    global _scanned
    if _scanned is None:
        found: list[Path] = []
        for root in ("/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"),
                     str(Path.home() / ".local/share/fonts")):
            r = Path(root)
            if not r.is_dir():
                continue
            for pat in ("*CJK*", "*cjk*", "*wqy*", "*SourceHan*", "*Hei*", "*Gothic*"):
                found.extend(p for p in r.rglob(pat) if p.suffix.lower() in (".ttc", ".otf", ".ttf"))
        _scanned = found
    return _scanned


def rating_tier(r: float) -> int:
    for th, tier in RATING_TIERS:
        if r >= th:
            return tier
    return 1


# ---------- 工具 ----------

def _overlay(img: Image.Image, draw_fn) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    img.alpha_composite(layer)


def _fit(draw, text, font, width):
    """font 可以是单个字体或回退链（链按逐字回退量宽度）。"""
    w = (lambda t: G.width(t, font)) if isinstance(font, list) else (lambda t: draw.textlength(t, font=font))
    if w(text) <= width:
        return text
    while text and w(text + "...") > width:
        text = text[:-1]
    return text + "..."


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.Resampling.LANCZOS)
    x0, y0 = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x0, y0, x0 + w, y0 + h))


def _background(h: int, bg_path: Path | None) -> Image.Image:
    if bg_path is not None:
        try:
            with Image.open(bg_path) as src:
                base = src.convert("RGBA")
            # 背景图通常是横图：按宽铺满后纵向平铺，模糊 + 半透明白色罩层（和例图一样偏亮）
            tile = base.resize((W, max(1, int(base.height * W / base.width))), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (W, h), (255, 255, 255, 255))
            for y in range(0, h, tile.height):
                canvas.alpha_composite(tile if (y // tile.height) % 2 == 0
                                       else tile.transpose(Image.Transpose.FLIP_TOP_BOTTOM), (0, y))
            canvas = canvas.filter(ImageFilter.GaussianBlur(5))
            canvas.alpha_composite(Image.new("RGBA", (W, h), (255, 255, 255, 70)))
            return canvas
        except (OSError, ValueError):
            pass
    # 自绘默认背景
    top, bottom = (40, 36, 70), (86, 52, 104)
    base = Image.new("RGBA", (W, h))
    d = ImageDraw.Draw(base)
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    glow = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for cx, cy, r, col in [(260, 180, 380, (120, 90, 255, 50)), (W - 200, 600, 460, (255, 90, 180, 40)),
                           (400, h - 500, 520, (80, 200, 255, 34)), (W - 300, h - 200, 360, (255, 200, 90, 30))]:
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))
    return base


def _gradient_text(img, xy, text, font, colors, stroke=0, stroke_fill=(0, 0, 0)):
    xy = (int(xy[0]), int(xy[1]))
    d = ImageDraw.Draw(img)
    l, t, r, b = (int(v) for v in d.textbbox(xy, text, font=font))
    if stroke:
        d.text(xy, text, font=font, fill=stroke_fill, stroke_width=stroke, stroke_fill=stroke_fill)
    w, h = max(r - l, 1), max(b - t, 1)
    grad = Image.new("RGBA", (w, h))
    gd = ImageDraw.Draw(grad)
    n = len(colors) - 1
    for x in range(w):
        p = x / max(w - 1, 1) * n
        i = min(int(p), n - 1)
        f = p - i
        gd.line([(x, 0), (x, h)], fill=tuple(int(colors[i][k] + (colors[i + 1][k] - colors[i][k]) * f)
                                             for k in range(3)) + (255,))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=font, fill=255)
    full = Image.new("RGBA", img.size, (0, 0, 0, 0))
    full.paste(grad, (l, t))
    img.paste(full, (0, 0), mask)


def _draw_rating_number(img, box, value: float, digits) -> None:
    """在 box 里居中画 rating：有数字图就拼图（小数点用合成的 "." ），否则用字体。"""
    x0, y0, x1, y1 = box
    text = f"{value:.2f}"
    tier = rating_tier(value)
    if digits is not None:
        from .theme import TIER_TO_ROW

        row = digits.get(TIER_TO_ROW[tier]) or next(iter(digits.values()))
        target_h = int((y1 - y0) * 0.86)
        glyphs = []
        for ch in text:
            g = (row[11] if len(row) > 11 else row[10]) if ch == "." else row[int(ch)]
            s = target_h / g.height
            glyphs.append(g.resize((max(1, int(g.width * s)), target_h), Image.Resampling.LANCZOS))
        gap = max(1, int(target_h * 0.02))  # 游戏里数字之间留一点空，不挤在一起
        total = sum(g.width for g in glyphs) + gap * (len(glyphs) - 1)
        limit = int((x1 - x0) * 0.94)
        if total > limit:  # 太宽就整体等比缩小
            k = limit / total
            target_h = int(target_h * k)
            glyphs = [g.resize((max(1, int(g.width * k)), target_h), Image.Resampling.LANCZOS) for g in glyphs]
            gap = max(1, int(gap * k))
            total = sum(g.width for g in glyphs) + gap * (len(glyphs) - 1)
        x = x0 + (x1 - x0 - total) // 2
        y = y0 + (y1 - y0 - target_h) // 2
        for g in glyphs:
            img.alpha_composite(g, (x, y))
            x += g.width + gap
        return
    # 没有上传数字图：自己画一套「游戏风格」的段位色数字（渐变填充 + 白色内描边 + 深色外描边 + 高光）
    g = _drawn_number(text, tier, int((y1 - y0) * 0.86))
    if g.width > (x1 - x0) * 0.94:
        k = (x1 - x0) * 0.94 / g.width
        g = g.resize((int(g.width * k), int(g.height * k)), Image.Resampling.LANCZOS)
    img.alpha_composite(g, (x0 + (x1 - x0 - g.width) // 2, y0 + (y1 - y0 - g.height) // 2))


# 段位配色（上 → 下渐变），彩虹段位单独处理
TIER_GRADIENTS = {
    1: ((190, 255, 190), (30, 170, 80)),     # 绿
    2: ((255, 226, 150), (240, 120, 20)),    # 橙
    3: ((255, 180, 180), (210, 30, 50)),     # 红
    4: ((235, 190, 255), (140, 50, 220)),    # 紫
    5: ((255, 214, 170), (165, 88, 40)),     # 铜
    6: ((255, 255, 255), (140, 152, 170)),   # 银
    7: ((255, 250, 190), (225, 155, 15)),    # 金
    8: ((255, 255, 250), (232, 200, 150)),   # 白金
}


def _drawn_number(text: str, tier: int, height: int) -> Image.Image:
    ss = 3  # 先画大图再缩小，边缘更平滑
    f = _font("latin", height * ss)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    outer, inner = max(2, height * ss // 14), max(1, height * ss // 28)
    gap = height * ss // 30
    # 逐字排版，字距放宽一点（游戏里数字之间有空隙）
    widths = [probe.textlength(ch, font=f) for ch in text]
    w = int(sum(widths) + gap * (len(text) - 1) + outer * 2 + 4)
    bb = probe.textbbox((0, 0), "0123456789", font=f)
    h = int(bb[3] - bb[1] + outer * 2 + 4)
    oy = outer + 2 - bb[1]

    def mask(stroke: int) -> Image.Image:
        m = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(m)
        x = outer + 2
        for ch, cw in zip(text, widths):
            md.text((x, oy), ch, font=f, fill=255, stroke_width=stroke, stroke_fill=255)
            x += cw + gap
        return m

    m_fill, m_inner, m_outer = mask(0), mask(inner), mask(inner + outer)

    fill = Image.new("RGBA", (w, h))
    fd = ImageDraw.Draw(fill)
    if tier >= 9:  # 彩虹：斜向彩色条纹
        n = len(RAINBOW)
        period = h * 1.3
        for x in range(-h, w + h):
            p = ((x % period) / period) * n
            i = int(p) % n
            t = p - int(p)
            c0, c1 = RAINBOW[i], RAINBOW[(i + 1) % n]
            col = tuple(int((c0[k] + (c1[k] - c0[k]) * t) * 0.72 + 255 * 0.28) for k in range(3)) + (255,)  # 偏粉彩
            fd.line([(x, h), (x + h, 0)], fill=col, width=2)
    else:
        top, bot = TIER_GRADIENTS.get(tier, TIER_GRADIENTS[6])
        for y in range(h):
            t = y / max(1, h - 1)
            fd.line([(0, y), (w, y)], fill=tuple(int(top[k] + (bot[k] - top[k]) * t) for k in range(3)) + (255,))
    # 上半部分高光
    gloss = Image.new("L", (w, h), 0)
    ImageDraw.Draw(gloss).rectangle([0, 0, w, int(h * 0.46)], fill=70)
    fill = Image.composite(Image.new("RGBA", (w, h), (255, 255, 255, 255)), fill, gloss)

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste((30, 22, 40, 255), (0, 0), m_outer)        # 深色外描边
    out.paste((255, 255, 255, 255), (0, 0), m_inner)     # 白色内描边
    out.paste(fill, (0, 0), m_fill)                      # 渐变填充
    out = out.resize((max(1, w // ss), max(1, h // ss)), Image.Resampling.LANCZOS)
    return out


def _jacket(path: Path | None) -> Image.Image:
    if path is not None:
        try:
            with Image.open(path) as im:
                return im.convert("RGB").resize((JACKET, JACKET), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            pass
    ph = Image.new("RGB", (JACKET, JACKET), (30, 28, 40))
    ImageDraw.Draw(ph).text((JACKET // 2, JACKET // 2), "?", font=_font("latin", 48),
                            fill=(110, 110, 130), anchor="mm")
    return ph


def _card(img: Image.Image, s: Score, idx: int, x: int, y: int, jacket: Path | None, font_override,
          logo: Image.Image | None = None):
    body, title_c, bottom_c = DIFF_STYLE.get(s.difficulty, DIFF_STYLE[Difficulty.MASTER])
    layer = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rectangle([0, 0, CARD_W, CARD_H], fill=body + (235,))
    ld.rectangle([0, 0, CARD_W, 46], fill=title_c + (245,))
    ld.polygon([(CARD_W - 46, 0), (CARD_W, 0), (CARD_W, 46)], fill=tuple(min(255, c + 30) for c in title_c) + (255,))
    ld.rectangle([0, CARD_H - 40, CARD_W, CARD_H], fill=bottom_c + (245,))
    if s.difficulty == Difficulty.ULTIMA:  # 例图里 ULTIMA 是黑底红色斜条
        # 斜条只在右上角三角区，半透明，不压住标题和分数的主要区域
        for k in range(3):
            off = 70 + k * 30
            ld.polygon([(CARD_W - off, 0), (CARD_W - off + 14, 0), (CARD_W, off - 14), (CARD_W, off)],
                       fill=(210, 30, 50, 150))
    img.alpha_composite(layer, (x, y))

    d = ImageDraw.Draw(img)
    _font("bold", 30, font_override)
    f_score = _font("latin", 32)
    f_rank = _font("latin_r", 23)
    f_lamp = _font("latin", 23)
    f_const = _font("latin_r", 27)
    f_rating = _font("latin", 40)
    f_idx = _font("latin", 26)

    c_title = _chain("bold", 30, font_override)
    G.draw(d, (x + 10, y + 4), _fit(d, s.title, c_title, CARD_W - 20), c_title, (255, 255, 255))
    img.paste(_jacket(jacket), (x + 10, y + 56))

    tx = x + 132
    d.text((tx, y + 52), f"{s.score:,}", font=f_score, fill=(255, 255, 255))
    rank_txt = f"[{s.rank}]"
    d.text((tx, y + 92), rank_txt, font=f_rank, fill=(214, 214, 226))
    lx = tx + d.textlength(rank_txt + " ", font=f_rank)
    combo = {ComboLamp.ALL_JUSTICE_CRITICAL: ("[AJC]", (255, 223, 117)),
             ComboLamp.ALL_JUSTICE: ("[AJ]", (255, 223, 117)),
             ComboLamp.FULL_COMBO: ("[FC]", (40, 243, 26))}.get(s.combo_lamp)
    if combo:
        d.text((lx, y + 92), combo[0], font=f_lamp, fill=combo[1])

    # 定数小黑框 + 箭头
    const_txt = f"{s.const:.1f}" if s.const is not None else "?"
    cw = d.textlength(const_txt, font=f_const)
    _overlay(img, lambda od: od.rectangle([tx - 4, y + 126, tx + cw + 8, y + 164], fill=(0, 0, 0, 110)))
    d = ImageDraw.Draw(img)
    d.text((tx + 2, y + 128), const_txt, font=f_const, fill=(240, 240, 250))
    ax = tx + cw + 18
    d.polygon([(ax, y + 139), (ax + 7, y + 145), (ax, y + 151)], fill=(150, 150, 170))

    rating_txt = f"{song_rating(s.score, s.const):.2f}" if s.const is not None else "—"
    rw = d.textlength(rating_txt, font=f_rating)
    d.text((x + CARD_W - 10 - rw, y + 116), rating_txt, font=f_rating,
           fill=(250, 255, 165) if s.score >= 1_009_000 else (255, 255, 255))

    it = f"#{idx + 1}"
    d.text((x + CARD_W - 10 - d.textlength(it, font=f_idx), y + CARD_H - 36), it, font=f_idx,
           fill=(255, 255, 255))
    if logo is not None:   # version logo in the bottom bar, like the game's song select
        img.alpha_composite(logo, (x + 8, y + CARD_H - 20 - logo.height // 2))


def _avg4(scores: list[Score], slots: int) -> Decimal:
    total = sum(whole_rating(s.score, s.const) // 100 * 100 for s in scores if s.const is not None)
    return (Decimal(total) / 10000 / slots).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


def _section_tab(img: Image.Image, y: int, label: str, avg: str, color) -> None:
    def draw(od):
        od.polygon([(0, y), (400, y), (330, y + TAB_H), (0, y + TAB_H)], fill=color + (255,))
        od.polygon([(400, y), (680, y), (610, y + TAB_H), (330, y + TAB_H)], fill=(255, 255, 255, 255))
    _overlay(img, draw)
    d = ImageDraw.Draw(img)
    d.text((40, y + 16), label, font=_font("latin", 42), fill=(255, 255, 255))
    d.text((420, y + 14), avg, font=_font("latin", 46), fill=(10, 10, 20))


def _logo(img: Image.Image, logo_path: Path | None, version: str | None) -> None:
    box = (1430, 14, MARGIN_X + 5 * CARD_W + 4 * GAP_X, HEADER_H - 14)  # 页头内、右边和卡片右缘对齐
    bw, bh = box[2] - box[0], box[3] - box[1]
    if logo_path is not None:
        try:
            with Image.open(logo_path) as im:
                lg = im.convert("RGBA")
            s = min(bw / lg.width, bh / lg.height)
            lg = lg.resize((max(1, int(lg.width * s)), max(1, int(lg.height * s))), Image.Resampling.LANCZOS)
            img.alpha_composite(lg, (box[0] + (bw - lg.width) // 2, box[1] + (bh - lg.height) // 2))
            return
        except (OSError, ValueError):
            pass
    # 没有 logo 素材：写版本名
    d = ImageDraw.Draw(img)
    f1, f2 = _font("latin", 34), _font("latin", 64)
    t1, t2 = "CHUNITHM", (version or "INTERNATIONAL")
    while d.textlength(t2, font=f2) > bw and f2.size > 28:
        f2 = _font("latin", f2.size - 4)
    cx = box[0] + bw / 2
    d.text((cx - d.textlength(t1, font=f1) / 2, 70), t1, font=f1, fill=(255, 255, 255),
           stroke_width=3, stroke_fill=(40, 30, 60))
    _gradient_text(img, (cx - d.textlength(t2, font=f2) / 2, 112), t2, f2, RAINBOW, stroke=4,
                   stroke_fill=(40, 30, 60))


def render_b50(
    name: str,
    b50: B50,
    out_path: Path,
    jackets: dict[int, Path] | None = None,
    *,
    font_path: str | None = None,
    tz: str = "Asia/Shanghai",
    version: str | None = None,
    bg_path: Path | None = None,
    logo_path: Path | None = None,
    digits=None,
    footer_left: str = "Generated by AstrBot",
    max_kb: int = 3000,
    server: str = "intl",
    card_logos: dict[int, Image.Image] | None = None,
    region_label: str = "",
) -> Path:
    cn = server == "cn"   # 国服（水鱼）：Best 30 + Recent 10，rating = 40 首平均；落雪（cn_lx）按 VERSE 规则 B30 + N20
    jackets = jackets or {}
    best, new = b50.best[:30], b50.new[:(10 if server == "cn" else 20)]  # B50 已按单曲 rating 排好
    rows_old = max(1, math.ceil(len(best) / 5))
    rows_new = math.ceil(len(new) / 5)
    sec = lambda rows: TAB_H + CARDS_GAP + rows * (CARD_H + GAP_Y)  # noqa: E731
    h = HEADER_H + TAB_Y_GAP + sec(rows_old) + (SECTION_GAP + sec(rows_new) if new else 0) + 40 + FOOTER_H

    img = _background(h, bg_path)

    # ---- 页头：半透明深色斜带 ----
    _overlay(img, lambda od: od.polygon([(0, 0), (1340, 0), (1120, HEADER_H), (0, HEADER_H)], fill=(20, 20, 28, 150)))
    _overlay(img, lambda od: od.rounded_rectangle([30, 42, 750, 178], 10, fill=(12, 12, 16, 245)))
    d = ImageDraw.Draw(img)
    c_name = _chain("bold", 64, font_path)
    nm = _fit(d, name, c_name, 680)
    G.draw(d, (390, 110), nm, c_name, (255, 255, 255), anchor="mm")  # 名字框 (30..750, 42..178) 正中

    d.text((790, 18), "RATING", font=_font("latin_r", 32), fill=(225, 225, 235))
    _overlay(img, lambda od: od.rounded_rectangle([790, 62, 1090, 156], 8, fill=(12, 12, 16, 245)))
    shown = b50.displayed_rating if b50.displayed_rating is not None else float(b50.total)
    _draw_rating_number(img, (798, 66, 1082, 152), shown, digits)
    d = ImageDraw.Draw(img)
    raw = f"({_avg4(best + new, 40 if cn else 50)})"
    f_raw = _font("latin_r", 32)
    d.text((1090 - d.textlength(raw, font=f_raw), 162), raw, font=f_raw, fill=(225, 225, 235))
    if b50.displayed_rating is not None and abs(float(b50.total) - b50.displayed_rating) >= 0.01:
        warn = f"计算值 {b50.total}"
        G.draw(d, (790, 166), warn, _chain("sc", 22), (255, 190, 120))

    _logo(img, logo_path, version)
    if region_label:   # small server tag above the name plate: 国际服 · Mate / 国服 · X-VERSE · 落雪查分器
        cr_ = _chain("sc", 24)
        d = ImageDraw.Draw(img)
        tw = G.width(region_label, cr_)
        _overlay(img, lambda od: od.rounded_rectangle([30, 8, 30 + tw + 24, 38], 8, fill=(255, 255, 255, 40)))
        d = ImageDraw.Draw(img)
        G.draw(d, (42, 23), region_label, cr_, (235, 235, 245), anchor="lm")

    # ---- OLD ----
    y = HEADER_H + TAB_Y_GAP
    _section_tab(img, y, "BEST 30" if cn else "OLD CHARTS", f"{_avg4(best, 30)}", (36, 140, 230))
    date = datetime.now(ZoneInfo(tz)).strftime("%Y/%m/%d")
    _overlay(img, lambda od: od.polygon([(1490, y + 8), (W, y + 8), (W, y + TAB_H - 8), (1440, y + TAB_H - 8)],
                                        fill=(60, 60, 70, 170)))
    d = ImageDraw.Draw(img)
    fd = _font("latin", 42)
    d.text((W - 40 - d.textlength(date, font=fd), y + 14), date, font=fd, fill=(225, 225, 235))

    def cards(scores, y0):
        for i, s in enumerate(scores):
            cx = MARGIN_X + (i % 5) * (CARD_W + GAP_X)
            cy = y0 + (i // 5) * (CARD_H + GAP_Y)
            _card(img, s, i, cx, cy, jackets.get(s.song_id) if s.song_id is not None else None, font_path,
                  (card_logos or {}).get(s.song_id))

    cards(best, y + TAB_H + CARDS_GAP)
    y += sec(rows_old)

    # ---- NEW ----
    if new:
        y += SECTION_GAP
        _section_tab(img, y, "RECENT 10" if cn else "NEW CHARTS", f"{_avg4(new, 10 if cn else 20)}", (24, 190, 130))
        cards(new, y + TAB_H + CARDS_GAP)

    # ---- 页脚 ----
    fy = h - FOOTER_H
    _overlay(img, lambda od: (od.rectangle([0, fy - 2, W, fy], fill=(0, 0, 0, 200)),
                              od.rectangle([0, fy, W, h], fill=(0, 0, 0, 120))))
    d = ImageDraw.Draw(img)
    # 页脚可能带中文（如预览的「示例数据」），拉丁字体没有中文字形会显示成方框
    ff = _chain("latin_r", 30) if footer_left.isascii() else _chain("sc", 28)
    fmid = fy + FOOTER_H // 2
    G.draw(d, (30, fmid), footer_left, ff, (225, 225, 235), anchor="lm")
    # same footer on every server; the server itself is the small tag in the header
    right = "CHUNITHM" + (f" {version}" if version else "")
    if b50.missing_const:
        right = f"{len(b50.missing_const)} 首缺少定数，未计入  ·  " + right
    G.draw(d, (W - 30, fmid), right, _chain("sc", 26), (225, 225, 235), anchor="rm")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    data, _info = encode_jpeg(img.convert("RGB"), max_kb)
    out_path.write_bytes(data)
    return out_path


def encode_jpeg(img: Image.Image, max_kb: int = 3000) -> tuple[bytes, dict]:
    """按目标大小压缩成 JPEG。max_kb <= 0 表示原图（质量 95、不缩放）。
    先在原尺寸下二分查找质量（最低 45），还是太大就按比例缩小尺寸再试。"""
    import io

    def enc(im: Image.Image, q: int) -> bytes:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        return buf.getvalue()

    if max_kb <= 0:
        data = enc(img, 95)
        return data, {"quality": 95, "width": img.width, "height": img.height, "kb": len(data) // 1024}
    limit = max_kb * 1024
    cur = img
    while True:
        best = None
        lo, hi = 45, 92
        top = enc(cur, hi)
        if len(top) <= limit:
            best = (hi, top)
        else:
            while lo <= hi:
                mid = (lo + hi) // 2
                d = enc(cur, mid)
                if len(d) <= limit:
                    best, lo = (mid, d), mid + 1
                else:
                    hi = mid - 1
        if best is not None or cur.width <= 600:
            q, data = best if best is not None else (45, enc(cur, 45))
            return data, {"quality": q, "width": cur.width, "height": cur.height, "kb": len(data) // 1024}
        # 质量降到底也超标：按面积比例缩小（留一点余量）
        k = max(0.5, min(0.92, (limit / len(enc(cur, 45))) ** 0.5 * 0.95))
        cur = cur.resize((int(cur.width * k), int(cur.height * k)), Image.Resampling.LANCZOS)
