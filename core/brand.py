"""成绩图、帮助图底下那一条「去哪找我」：二维码 + 网站地址，右边是看板娘头像 + bot 的 QQ 号。

图是用户自己会转发的东西，转出去以后别的群的人得知道去哪弄。这一条接在原图下面（画布加高），不改原图。

v3.1.0 第二稿：不再是所有图一个样的藏青条，而是**跟着每张图长**——
  · 底色从原图最下面那几行接着往下铺（中二 / 音击 / SDVX 的页脚条等于变高了一截，帮助图就是接着白下去）；
  · 字的颜色、「QQ」小标签的样子、二维码的框，按游戏各用各图里本来就有的那套：
    舞萌是紫边白底的小牌子，中二是白字 + 黄色 [QQ]，音击是灰字 + 紫色小药丸 + 金色数字，
    SDVX 是切角框 + 黄色小药丸 + 紫色数字，帮助图是藏青字；
  · 不认识的图（没给主题）：看底色深浅自动挑白字或深色字。
"""
from __future__ import annotations

import io
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageDraw

try:
    from ..mai.render import fonts as F
except ImportError:                                          # 测试里按顶层包导入
    from mai.render import fonts as F  # type: ignore
from . import qr

NAVY = (27, 42, 74)
GOLD = (227, 193, 106)
FOG = (143, 178, 217)
WHITE = (255, 255, 255)
_ASSET_DIR = Path(__file__).resolve().parent.parent / "web" / "bind" / "img"

# 每个主题：fg 大字、sub 小字、num QQ 号的颜色、ring 头像圈、qr 二维码的深色、
# chip 「QQ」小标签（样子, 底色, 字色）、tile 二维码底板（round 圆角 / cut 切角 / square 直角）、
# plate 整块内容放不放在小牌子里（舞萌）、rule 顶上要不要一条细线（颜色带透明度）
THEMES: dict[str, dict] = {
    "mai": dict(plate=((126, 70, 200), WHITE), fg=(110, 60, 150), sub=(140, 100, 170), num=(110, 60, 150),
                ring=(126, 70, 200), qr=(74, 38, 120), chip=("pill", (126, 70, 200), WHITE), tile="round"),
    "chu": dict(fg=WHITE, sub=(225, 225, 235), num=(255, 222, 92), ring=(255, 222, 92), qr=(28, 26, 46),
                chip=("bracket", None, (255, 222, 92)), tile="square", rule=(255, 255, 255, 70)),
    "geki": dict(fg=(92, 88, 110), sub=(132, 130, 146), num=(214, 150, 22), ring=(236, 132, 178), qr=(70, 54, 108),
                 chip=("pill", (132, 84, 196), WHITE), tile="round", rule=(150, 130, 160, 60)),
    "sdvx": dict(fg=WHITE, sub=(196, 208, 202), num=(186, 150, 255), ring=(72, 196, 134), qr=(10, 22, 18),
                 chip=("pill", (255, 206, 72), (40, 30, 0)), tile="cut", rule=(72, 196, 134, 120)),
    "help": dict(fg=NAVY, sub=(107, 122, 153), num=NAVY, ring=GOLD, qr=NAVY,
                 chip=("plain", None, NAVY), tile="round"),
    "dark": dict(fg=WHITE, sub=(205, 214, 228), num=GOLD, ring=GOLD, qr=NAVY,
                 chip=("plain", None, GOLD), tile="round"),
    "light": dict(fg=NAVY, sub=(96, 110, 140), num=NAVY, ring=(143, 178, 217), qr=NAVY,
                  chip=("plain", None, NAVY), tile="round"),
}
_ALIAS = {"chuni": "chu", "ongeki": "geki", "core": "help", "more": "help"}
_FLAT = {"mai": (250, 214, 236), "chu": (86, 84, 76), "geki": (252, 244, 248), "sdvx": (8, 18, 16),
         "help": (255, 255, 255), "dark": NAVY, "light": (251, 252, 254)}
_qr_cache: dict = {}
_av_cache: dict = {}


def host_of(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if "//" not in u:
        u = "https://" + u
    p = urlsplit(u)
    return (p.netloc + p.path.rstrip("/")) if p.netloc else ""


def _lum(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _avatar(size: int, ring=GOLD) -> Image.Image | None:
    """看板娘的圆头像（包里没有这张图就不放）。"""
    key = (size, tuple(ring))
    if key in _av_cache:
        return _av_cache[key]
    try:
        with Image.open(_ASSET_DIR / "yume-p-wave.webp") as src:
            src = src.convert("RGBA")
            side = int(src.width * 0.50)
            x0 = int(src.width * 0.5 - side / 2)
            head = src.crop((x0, int(src.width * 0.045), x0 + side, int(src.width * 0.045) + side))
    except (OSError, ValueError):
        return None
    s = 4
    big = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.ellipse([0, 0, size * s - 1, size * s - 1], fill=(230, 239, 250, 255))
    face = head.resize((size * s, size * s), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size * s, size * s), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * s - 1, size * s - 1], fill=255)
    big.paste(face, (0, 0), Image.composite(face.getchannel("A"), Image.new("L", face.size, 0), mask))
    edge = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(edge).ellipse([s, s, size * s - 1 - s, size * s - 1 - s], outline=tuple(ring) + (255,),
                                 width=max(2, round(size * 0.03)) * s)
    big = Image.alpha_composite(big, edge)
    out = big.resize((size, size), Image.Resampling.LANCZOS)
    _av_cache[key] = out
    return out


def _qr_tile(url: str, side: int, dark, shape: str, edge=None) -> Image.Image:
    """白底板 + 二维码。四周留两格白边；格子永远是整数像素，缩小了也扫得出来。"""
    full = url if "//" in url else "https://" + url.strip()
    if full not in _qr_cache:
        _qr_cache[full] = qr.matrix(full)
    g = _qr_cache[full]
    n = len(g) + 4
    sc = max(1, side // n)
    s = 4
    tile = Image.new("RGBA", (side * s, side * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    m = side * s - 1
    if shape == "cut":                                       # SDVX 卡片那种：左上、右下各切一个角
        c = round(side * s * 0.11)
        d.polygon([(c, 0), (m, 0), (m, m - c), (m - c, m), (0, m), (0, c)], fill=WHITE + (255,))
    elif shape == "square":
        d.rectangle([0, 0, m, m], fill=WHITE + (255,))
    else:
        d.rounded_rectangle([0, 0, m, m], max(4, side // 10) * s, fill=WHITE + (255,),
                            outline=(tuple(edge) + (255,)) if edge else None, width=2 * s if edge else 0)
    tile = tile.resize((side, side), Image.Resampling.LANCZOS)
    code = Image.new("L", (n, n), 0)                         # 只把深色格子贴上去，底板的形状（切角、圆角）留着
    cp = code.load()
    for r, row in enumerate(g):
        for c, v in enumerate(row):
            if v:
                cp[c + 2, r + 2] = 255
    mask = code.resize((n * sc, n * sc), Image.Resampling.NEAREST)
    off = (side - n * sc) // 2
    tile.paste(Image.new("RGBA", mask.size, tuple(dark) + (255,)), (off, off), mask)
    return tile


def _continue(base: Image.Image, h: int) -> tuple[Image.Image, tuple]:
    """把原图最下面几行接着往下铺 h 高：横向保留颜色变化（抹掉条纹和噪点），头上一小段从原样渐变过来。

    原图最底下要是正好切在内容上（不是干净的底色 / 页脚条），就不照抄那一行，只取个大概的颜色再压一层，免得拉出竖条。"""
    w = base.width
    src = base.convert("RGB")
    last = src.crop((0, src.height - 4, w, src.height)).resize((w, 1), Image.Resampling.BOX)
    smooth = last.resize((max(6, w // 64), 1), Image.Resampling.BOX).resize((w, 1), Image.Resampling.BICUBIC)
    a, b = last.resize((256, 1), Image.Resampling.BOX).tobytes(), smooth.resize((256, 1), Image.Resampling.BOX).tobytes()
    busy = sum(abs(x - y) for x, y in zip(a, b)) / len(a) > 3
    if busy:
        smooth = last.resize((4, 1), Image.Resampling.BOX).resize((w, 1), Image.Resampling.BICUBIC)
    bg = smooth.resize((w, h), Image.Resampling.NEAREST)
    mean = smooth.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    if busy:
        veil = (0, 0, 0) if _lum(mean) < 140 else (255, 255, 255)
        bg = Image.blend(bg, Image.new("RGB", bg.size, veil), 0.45)
        mean = tuple(round(c * 0.55 + v * 0.45) for c, v in zip(mean, veil))
    else:
        fade = max(6, min(h // 3, 44))
        ramp = Image.linear_gradient("L").rotate(180).resize((w, fade))      # 上 255 → 下 0
        bg.paste(last.resize((w, fade), Image.Resampling.NEAREST), (0, 0), ramp)
    return bg, mean


def _pick(theme: str, mean) -> dict:
    name = _ALIAS.get(theme, theme)
    t = THEMES.get(name)
    auto = THEMES["dark"] if _lum(mean) < 140 else THEMES["light"]
    if t is None:
        return auto
    if "plate" not in t and abs(_lum(t["fg"]) - _lum(mean)) < 85:            # 这张图的底色和预想的不一样：别硬套
        return auto
    return t


def strip(width: int, url: str = "", qq: str = "", bot_name: str = "AstrBot", theme: str = "",
          base: Image.Image | None = None) -> Image.Image | None:
    """宽 width 的那一条；网址和 QQ 号都没有就返回 None。base 是要接在它下面的那张图（用来接底色）。"""
    host = host_of(url)
    qq = "".join(ch for ch in str(qq or "") if ch.isdigit())
    if not host and not qq:
        return None
    h = max(110, round(width * 0.084))
    if base is not None:
        bg, mean = _continue(base, h)
    else:
        mean = _FLAT.get(_ALIAS.get(theme, theme), NAVY)
        bg = Image.new("RGB", (width, h), mean)
    t = _pick(theme, mean)
    im = bg.convert("RGBA")
    over = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    px = round(width * 0.016)
    if t.get("rule"):
        d.line([(px, 0), (width - px, 0)], fill=t["rule"], width=max(1, round(h * 0.012)))
    plate = t.get("plate")
    py = round(h * (0.08 if plate else 0.12))
    box = h - 2 * py - (round(h * 0.06) if plate else 0)                                         # 内容那一行的高度
    inset = round(box * 0.085) if plate else 0               # 小牌子里面再缩一圈
    side = box - 2 * inset
    cy = py + inset
    big, small = round(side * 0.42), round(side * 0.245)
    gap = round(side * 0.22)
    line1, line2 = cy + round(side * 0.07), cy + round(side * 0.63)
    cap1 = "扫码打开 · 绑定账号、传分都在这里"
    cap2 = "加好友或拉进群，发 /查分帮助"
    kind1 = "bold"
    kind2 = "bold" if plate else "regular"

    def card(x0: int, x1: int):                              # 舞萌的小牌子：紫边、白底、底边厚一点
        edge, fill = plate
        r = round(box * 0.16)
        d.rounded_rectangle([x0, py + 3, x1, py + box + 5], r, fill=(70, 30, 120, 60))
        d.rounded_rectangle([x0, py, x1, py + box], r, fill=tuple(edge) + (255,))
        b = max(3, round(box * 0.03))
        d.rounded_rectangle([x0 + b, py + b, x1 - b, py + box - b - b], max(2, r - b), fill=tuple(fill) + (255,))

    pad = round(side * 0.20) if plate else 0
    if host:
        tw = max(F.text_width(host, kind1, big), F.text_width(cap1, kind2, small))
        x = px + pad
        if plate:
            card(px, x + side + gap + tw + pad + inset)
        edge = t["sub"] if (not plate and _lum(mean) > 200) else None        # 白底上的白底板：描一圈才看得出边
        tile = _qr_tile(url, side, t["qr"], t.get("tile", "round"), edge)
        over.alpha_composite(tile, (x, cy))
        x += side + gap
        F.draw_text(d, (x, line1), host, kind1, big, t["fg"])
        F.draw_text(d, (x, line2), cap1, kind2, small, t["sub"])
    if qq:
        style, cbg, cfg = t["chip"]
        chip_txt = "[QQ]" if style == "bracket" else "QQ"
        chip_size = round(big * (0.62 if style == "pill" else 1.0))
        chip_w = F.text_width(chip_txt, "bold", chip_size) + (round(big * 0.56) if style == "pill" else 0)
        sp = round(big * 0.30)
        w_name = F.text_width(bot_name, "bold", big)
        w_num = F.text_width(qq, "bold", big)
        w1 = w_name + sp + chip_w + round(sp * 0.7) + w_num
        tw = max(w1, F.text_width(cap2, kind2, small))
        tx = width - px - pad - tw
        ax = tx - gap - side
        if plate:
            card(ax - pad - inset, width - px)
        av = _avatar(side, t["ring"])
        if av is not None:
            over.alpha_composite(av, (ax, cy))
        F.draw_text(d, (tx, line1), bot_name, "bold", big, t["fg"])
        x = tx + w_name + sp
        if style == "pill":
            ch = round(big * 0.86)
            top = line1 + round(big * 0.26)
            d.rounded_rectangle([x, top, x + chip_w, top + ch], ch // 2, fill=tuple(cbg) + (255,))
            F.draw_text(d, (x + (chip_w - F.text_width(chip_txt, "bold", chip_size)) // 2,
                            top + (ch - round(chip_size * 1.42)) // 2), chip_txt, "bold", chip_size, cfg)
        else:
            F.draw_text(d, (x, line1), chip_txt, "bold", chip_size, cfg)
        x += chip_w + round(sp * 0.7)
        F.draw_text(d, (x, line1), qq, "bold", big, t["num"])
        F.draw_text(d, (tx, line2), cap2, kind2, small, t["sub"])
    return Image.alpha_composite(im, over).convert("RGB")


def stamp(data: bytes, url: str = "", qq: str = "", bot_name: str = "AstrBot", max_kb: int = 0,
          theme: str = "") -> bytes:
    """在图片底下接上那一条；出问题就原样返回，不让一张成绩图因为页脚发不出去。"""
    try:
        with Image.open(io.BytesIO(data)) as src:
            fmt = (src.format or "PNG").upper()
            src.load()
            base = src.convert("RGB") if fmt == "JPEG" or src.mode not in ("RGB", "RGBA") else src.copy()
        if base.width < 700:                                 # 小图（表情、头像一类）不接
            return data
        s = strip(base.width, url, qq, bot_name, theme, base)
        if s is None:
            return data
        out = Image.new(base.mode, (base.width, base.height + s.height), (255, 255, 255))
        out.paste(base, (0, 0))
        out.paste(s, (0, base.height))
        buf = io.BytesIO()
        if fmt == "JPEG":
            q = 92
            out.save(buf, "JPEG", quality=q, optimize=True)
            while max_kb and buf.tell() > max_kb * 1024 and q > 60:
                q -= 6
                buf = io.BytesIO()
                out.save(buf, "JPEG", quality=q, optimize=True)
        else:
            out.save(buf, "PNG", optimize=False)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return data
