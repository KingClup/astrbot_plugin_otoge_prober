"""Font lookup with per-character fallback (song titles mix CJK, kana, symbols like ♭ ✪ ☆)."""
from __future__ import annotations

import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

_CANDIDATES = {
    "bold": [
        "themes/fonts/bold.ttf", "themes/fonts/bold.otf", "themes/fonts/bold.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ],
    "regular": [
        "themes/fonts/regular.ttf", "themes/fonts/regular.otf", "themes/fonts/regular.ttc",
        r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\YuGothM.ttc", r"C:\Windows\Fonts\meiryo.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ],
    # 宋体（帮助图的标题，和绑定网站一个味道）：Win11 自带的是 SimSun；装了 Office 会有华文中宋，更好看
    "serif": [
        "themes/fonts/serif.ttf", "themes/fonts/serif.otf", "themes/fonts/serif.ttc",
        r"C:\Windows\Fonts\STZHONGS.TTF", r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Medium.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ],
    "symbol": [
        r"C:\Windows\Fonts\seguisym.ttf", r"C:\Windows\Fonts\cambria.ttc", r"C:\Windows\Fonts\seguihis.ttf",
        r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\msgothic.ttc", r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\seguiemj.ttf", r"C:\Windows\Fonts\arialuni.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "latin": [
        "themes/fonts/latin.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
}

THEME_ROOT = ""  # set by the renderer so themes/fonts/* resolves under plugin_data


def _resolve(path: str) -> str:
    if path.startswith("themes/") and THEME_ROOT:
        return os.path.join(THEME_ROOT, path[len("themes/"):])
    return path


@lru_cache(maxsize=None)
def _paths(kind: str) -> tuple[str, ...]:
    return tuple(p for p in map(_resolve, _CANDIDATES[kind]) if os.path.exists(p))


@lru_cache(maxsize=256)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for p in _paths(kind) + _paths("regular") + _paths("symbol"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


@lru_cache(maxsize=64)
def _chain(kind: str, size: int) -> tuple[ImageFont.FreeTypeFont, ...]:
    out = []
    for k in (kind, "regular", "symbol", "latin"):
        for p in _paths(k):
            try:
                f = ImageFont.truetype(p, size)
            except OSError:
                continue
            if all(getattr(f, "path", None) != getattr(g, "path", None) for g in out):
                out.append(f)
    return tuple(out) or (ImageFont.load_default(size),)


@lru_cache(maxsize=8192)
def _has_glyph(path: str, size: int, ch: str) -> bool:
    """Reads the font's cmap (the old "does it look like the tofu box" test misses on Windows fonts)."""
    if ch.isspace():
        return True
    try:
        from ...core.glyphs import codepoints
    except ImportError:
        from core.glyphs import codepoints
    cps = codepoints(path, 0)
    return not cps or ord(ch) in cps


def runs(text: str, kind: str, size: int) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    """整行先用覆盖最多字的正文字体（见 core.glyphs.pick_base），缺的字再逐个回退。"""
    try:
        from ...core.glyphs import runs as _runs
    except ImportError:
        from core.glyphs import runs as _runs
    return _runs(text, list(_chain(kind, size)))


def text_width(text: str, kind: str, size: int) -> int:
    return int(sum(f.getlength(t) for t, f in runs(text, kind, size)))


def draw_text(draw: ImageDraw.ImageDraw, xy, text: str, kind: str, size: int, fill, *,
              anchor_right: bool = False, stroke: int = 0, stroke_fill=None) -> int:
    x, y = xy
    if anchor_right:
        x -= text_width(text, kind, size)
    base = font(kind, size)
    asc = base.getmetrics()[0]
    for t, f in runs(text, kind, size):
        dy = asc - f.getmetrics()[0]
        draw.text((x, y + dy), t, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        x += f.getlength(t)
    return int(x)


def fit(text: str, kind: str, size: int, max_w: int) -> str:
    if text_width(text, kind, size) <= max_w:
        return text
    ell = "…"
    while text and text_width(text + ell, kind, size) > max_w:
        text = text[:-1]
    return text + ell


def blank(w: int, h: int, color=(0, 0, 0, 0)) -> Image.Image:
    return Image.new("RGBA", (w, h), color)
