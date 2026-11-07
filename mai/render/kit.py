"""Shared look for the info cards (查歌 / 定数查歌 / 定数表): pastel CiRCLE-style background,
frosted panels, pills, difficulty colours, optional game sprites from plugin_data/themes.

Theme files (all optional, never shipped with the plugin):
  themes/<version>/bg.png        page background (else drawn gradient)
  themes/<version>/logo.png      version logo at the top-left
  themes/logos/<slug>.png        small version logos for pills (slug = version lower, spaces→_ , e.g. circle_plus)
  themes/icons/note_<tap|hold|slide|touch|break>.png   column icons in the note table
  themes/icons/type_<dx|std>.png                      DX / スタンダード badges
  themes/deco/*.png              mascots / stickers sprinkled on the background
"""
from __future__ import annotations

import colorsys
import os
import random

from PIL import Image, ImageDraw, ImageFilter

from . import fonts as F

DIFF_COLORS = {
    "basic": (69, 193, 36), "advanced": (255, 186, 1), "expert": (255, 90, 102),
    "master": (159, 81, 220), "remaster": (219, 170, 255), "utage": (255, 111, 199),
}
DIFF_TEXT = {"remaster": (150, 70, 220)}
DIFF_NAMES = {"basic": "Basic", "advanced": "Advanced", "expert": "Expert", "master": "Master",
              "remaster": "Re:Master", "utage": "U·TA·GE"}
INK = (58, 44, 92)
SUB = (128, 112, 160)
ACCENT = (150, 90, 235)
PANEL = (255, 255, 255, 150)


def slug(version: str) -> str:
    return (version or "").lower().replace("maimaiでらっくす", "deluxe").replace(" ", "_")


def short_version(v: str | None) -> str:
    if not v:
        return ""
    return v.replace("maimaiでらっくす", "でらっくす").replace(" PLUS", "+")


def gradient(w, h, stops, horizontal=False) -> Image.Image:
    n = w if horizontal else h
    line = Image.new("RGB", (n, 1))
    px = line.load()
    k = len(stops) - 1
    for i in range(n):
        t = i / max(1, n - 1) * k
        a = min(int(t), k - 1) if k else 0
        f = t - a if k else 0
        c0, c1 = stops[a], stops[min(a + 1, k)]
        px[i, 0] = tuple(int(c0[j] + (c1[j] - c0[j]) * f) for j in range(3))
    if horizontal:
        return line.resize((w, h))
    return line.resize((h, 1)).rotate(90, expand=True).transpose(Image.FLIP_TOP_BOTTOM).resize((w, h))


def rounded_mask(w, h, r) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


def paste_rounded(base, im, xy, r) -> None:
    im = im.convert("RGBA")
    mask = rounded_mask(*im.size, r)
    alpha = im.split()[3]
    base.paste(im, xy, Image.composite(alpha, Image.new("L", im.size, 0), mask))


def shadow(base, box, r, offset=6, blur=12, alpha=70) -> None:
    x0, y0, x1, y1 = map(int, box)
    pad = blur * 3
    sh = Image.new("RGBA", (x1 - x0 + pad * 2, y1 - y0 + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad, pad + x1 - x0, pad + y1 - y0), r, fill=(110, 50, 140, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(sh, (x0 - pad, y0 - pad + offset))


def panel(base, box, r=30, fill=PANEL, border=(255, 255, 255, 210), glow=True) -> None:
    x0, y0, x1, y1 = map(int, box)
    if glow:
        shadow(base, box, r)
    # frosted glass: blur what is underneath, then veil it
    region = base.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(14))
    veil = Image.new("RGBA", region.size, fill)
    region = Image.alpha_composite(region.convert("RGBA"), veil)
    base.paste(region, (x0, y0), rounded_mask(x1 - x0, y1 - y0, r))
    ImageDraw.Draw(base).rounded_rectangle((x0, y0, x1 - 1, y1 - 1), r, outline=border, width=3)


def section_title(d, x, y, text, size=34, sub: str = "") -> None:
    d.rounded_rectangle((x, y + 6, x + 7, y + size + 2), 3, fill=INK)
    end = F.draw_text(d, (x + 20, y), text, "bold", size, INK)
    if sub:
        F.draw_text(d, (end + 18, y + size * 0.3), sub, "regular", int(size * 0.55), SUB)


def pill(d, x, y, text, *, size=24, fg=INK, bg=(255, 255, 255, 230), outline=None, pad=16, h=None,
         bold=True, dot=None) -> int:
    """Draw a rounded label; returns its right edge."""
    kind = "bold" if bold else "regular"
    tw = F.text_width(text, kind, size)
    h = h or int(size * 1.7)
    extra = int(size * 0.8) if dot else 0
    w = tw + pad * 2 + extra
    d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=bg, outline=outline, width=2 if outline else 0)
    if dot:
        r = size // 5
        cx, cy = x + pad + r, y + h // 2
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=dot)
    F.draw_text(d, (x + pad + extra, y + (h - size) / 2 - size * 0.12), text, kind, size, fg)
    return x + w


def pill_width(text, size=24, pad=16, bold=True, dot=False) -> int:
    return F.text_width(text, "bold" if bold else "regular", size) + pad * 2 + (int(size * 0.8) if dot else 0)


def diff_label(d, x, y, diff, size=30) -> int:
    """'Master' in the difficulty colour with a white outline, like the game."""
    c = DIFF_COLORS.get(diff, INK)
    return F.draw_text(d, (x, y), DIFF_NAMES.get(diff, diff), "latin", size, c, stroke=3,
                       stroke_fill=(255, 255, 255))


def type_badge(assets, type_: str, h=30) -> Image.Image:
    ic = assets.icon("type_" + ("dx" if type_ == "dx" else "std")) if assets else None
    if ic is not None:
        ic = ic.copy()
        ic.thumbnail((h * 4, h), Image.LANCZOS)
        return ic
    label = "DX" if type_ == "dx" else "SD"
    stops = [(255, 120, 60), (255, 70, 150)] if type_ == "dx" else [(60, 160, 255), (40, 110, 230)]
    w = int(h * 1.6)
    g = gradient(w, h, stops, horizontal=True).convert("RGBA")
    g.putalpha(rounded_mask(w, h, h // 3))
    dd = ImageDraw.Draw(g)
    tw = F.text_width(label, "latin", int(h * 0.62))
    F.draw_text(dd, ((w - tw) / 2, h * 0.14), label, "latin", int(h * 0.62), (255, 255, 255))
    return g


def version_badge(assets, version: str, h=44) -> Image.Image:
    p = os.path.join(assets.themes, "logos", slug(version) + ".png") if assets else ""
    if p and os.path.exists(p):
        im = Image.open(p).convert("RGBA")
        im.thumbnail((h * 4, h), Image.LANCZOS)
        return im
    text = short_version(version)
    size = int(h * 0.48)
    w = F.text_width(text, "latin", size) + h
    hue = (abs(hash(version)) % 360) / 360
    c0 = tuple(int(v * 255) for v in colorsys.hsv_to_rgb(hue, 0.35, 1.0))
    c1 = tuple(int(v * 255) for v in colorsys.hsv_to_rgb((hue + 0.12) % 1, 0.55, 0.95))
    g = gradient(w, h, [c0, c1], horizontal=True).convert("RGBA")
    g.putalpha(rounded_mask(w, h, h // 2))
    dd = ImageDraw.Draw(g)
    dd.rounded_rectangle((0, 0, w - 1, h - 1), h // 2, outline=(255, 255, 255), width=3)
    F.draw_text(dd, (h / 2, (h - size) / 2 - size * 0.1), text, "latin", size, (255, 255, 255), stroke=2,
                stroke_fill=tuple(max(0, v - 60) for v in c1))
    return g


PALETTES = {
    "mai": [(180, 205, 255), (240, 190, 245), (255, 170, 215), (225, 180, 255), (170, 210, 255)],
    "chu": [(160, 225, 255), (190, 205, 255), (255, 236, 170), (175, 235, 235), (165, 200, 255)],
}


def background(assets, version: str, w: int, h: int, seed: int = 0, palette: str = "mai") -> Image.Image:
    p = (assets.theme_file(version, "bg.png") or assets.theme_file(version, "bg.jpg")) if assets else None
    if p:
        bg = Image.open(p).convert("RGBA")
        scale = max(w / bg.width, h / bg.height)
        bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1), Image.LANCZOS)
        bg = bg.crop(((bg.width - w) // 2, 0, (bg.width - w) // 2 + w, h))
        return Image.alpha_composite(bg, Image.new("RGBA", (w, h), (255, 240, 250, 70)))
    bg = gradient(w, h, PALETTES.get(palette, PALETTES["mai"])).convert("RGBA")
    deco = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    rnd = random.Random(seed or w * 31 + h)
    # perspective grid like the CiRCLE stage floor
    for i in range(-h, w + h, 110):
        dd.line((i, 0, i + h * 0.35, h), fill=(255, 255, 255, 34), width=3)
    for j in range(0, h, 110):
        dd.line((0, j, w, j + 40), fill=(255, 255, 255, 26), width=3)
    for _ in range(max(4, h // 500)):
        cx, cy, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(140, 360)
        dd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 60), width=12)
    for _ in range(max(6, h // 260)):  # pink checker blocks
        x, y, s = rnd.randint(0, w), rnd.randint(0, h), rnd.choice((26, 34, 42))
        for k in range(4):
            dd.rectangle((x + k * s * 1.2, y - k * s * 1.2, x + k * s * 1.2 + s, y - k * s * 1.2 + s),
                         fill=(255, 120, 190, 70))
    bg = Image.alpha_composite(bg, deco.filter(ImageFilter.GaussianBlur(1)))
    # optional stickers from the theme
    ddir = os.path.join(assets.themes, "deco") if assets and getattr(assets, "themes", "") else ""
    if ddir and os.path.isdir(ddir):
        files = sorted(f for f in os.listdir(ddir) if f.lower().endswith(".png"))
        for k, f in enumerate(files[: max(2, h // 900)]):
            try:
                st = Image.open(os.path.join(ddir, f)).convert("RGBA")
            except Exception:
                continue
            st.thumbnail((int(w * 0.22), int(w * 0.22)), Image.LANCZOS)
            a = st.split()[3].point(lambda v: int(v * 0.55))
            st.putalpha(a)
            # tuck mascots into the margins: top-right corner and bottom-left corner
            x = w - st.width + st.width // 5 if k % 2 == 0 else -st.width // 5
            y = (40 if k % 2 == 0 else h - st.height - 20) + (k // 2) * st.height
            bg.alpha_composite(st, (max(0, x), max(0, min(h - st.height, y))))
    return bg


def logo(assets, version: str, max_w=360, max_h=150) -> Image.Image | None:
    if not assets:
        return None
    # this version's own theme logo → its logo from the shared version-logo set → the default theme logo
    # (never another version's theme logo: a 国服 page must not show the 国际服 version name)
    p = os.path.join(assets.themes, version or "default", "logo.png")
    im = Image.open(p).convert("RGBA") if os.path.exists(p) else None
    if im is None and hasattr(assets, "version_logo"):
        im = assets.version_logo(version)
        if im is not None:
            im = im.copy()
            if im.getbbox():
                im = im.crop(im.getbbox())
            s = min(max_w / im.width, max_h / im.height)
            if s > 1:
                im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    if im is None:
        p = os.path.join(assets.themes, "default", "logo.png")
        if not os.path.exists(p):
            return None
        im = Image.open(p).convert("RGBA")
    im.thumbnail((max_w, max_h), Image.LANCZOS)
    return im


def footer(base, bot_name: str, y=None, credit: str = "Data from DXRating") -> None:
    w, h = base.size
    d = ImageDraw.Draw(base)
    text = f"Generated by {bot_name}  ·  {credit}" if credit else f"Generated by {bot_name}"
    size = 24
    tw = F.text_width(text, "bold", size)
    y = h - 74 if y is None else y
    x = (w - tw) // 2 - 30
    d.rounded_rectangle((x, y, x + tw + 60, y + 50), 25, fill=(70, 60, 110, 200), outline=(255, 255, 255, 160),
                        width=2)
    F.draw_text(d, (x + 30, y + 10), text, "bold", size, (255, 255, 255))


def to_png(im: Image.Image, max_side: int = 0) -> bytes:
    import io
    im = im.convert("RGB")
    if max_side and max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=False, compress_level=6)
    return buf.getvalue()
