"""按游戏 / 版本自绘的 B50 背景（不用任何官方素材，全是代码画的几何图形）。

  sdvx  · ∇            深绿 → 墨绿渐变，荧光绿的倒三角（∇）线框、细网格、斜向光带、光点
  sdvx  · 其他          （EXCEED GEAR 及更早）深蓝 + 银色，同一套装饰
  geki  · Re:Fresh 系   淡樱花粉，樱花瓣、白色丝带、散景圆、四角星
  geki  · bright 系     天蓝 → 靛蓝的「晴空」感，顶部光束、棱镜碎片（半透明彩色三角）、光点
  geki  · 更早          橙红夕阳

同一个 (游戏, 版本, 高度) 画一次就缓存住，出图时直接拿。随机数用固定种子，每次画出来一样。
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

W = 1872


def _gradient(h: int, stops: list[tuple[float, tuple[int, int, int]]]) -> Image.Image:
    img = Image.new("RGBA", (W, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / max(t1 - t0, 1e-6)
                col = tuple(int(a + (b - a) * k) for a, b in zip(c0, c1))
                break
        else:
            col = stops[-1][1]
        d.line([(0, y), (W, y)], fill=col + (255,))
    return img


def _glow(img: Image.Image, blobs, blur: int = 90) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for cx, cy, r, col in blobs:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _sparkles(img: Image.Image, rnd: random.Random, n: int, col, size=(3, 9)) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h = img.size
    for _ in range(n):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        r = rnd.uniform(*size)
        a = int(rnd.uniform(0.35, 1.0) * col[3])
        c = col[:3] + (a,)
        # 四角星：两条细长菱形
        d.polygon([(x, y - r * 2.4), (x + r * 0.35, y), (x, y + r * 2.4), (x - r * 0.35, y)], fill=c)
        d.polygon([(x - r * 2.4, y), (x, y + r * 0.35), (x + r * 2.4, y), (x, y - r * 0.35)], fill=c)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.6)))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(6)))


def _dots(img: Image.Image, rnd: random.Random, n: int, col, rmax: float = 3.0) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h = img.size
    for _ in range(n):
        x, y, r = rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(0.8, rmax)
        d.ellipse([x - r, y - r, x + r, y + r], fill=col[:3] + (int(rnd.uniform(0.3, 1) * col[3]),))
    img.alpha_composite(layer)


def _streaks(img: Image.Image, rnd: random.Random, n: int, col, angle: float = -28) -> None:
    """斜向光带。"""
    w, h = img.size
    layer = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x = rnd.uniform(0, w * 2)
        bw = rnd.uniform(6, 60)
        d.rectangle([x, 0, x + bw, h * 2], fill=col[:3] + (int(rnd.uniform(0.25, 1) * col[3]),))
    layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(14))
    img.alpha_composite(layer.crop((w // 2, h // 2, w // 2 + w, h // 2 + h)))


# ---------------------------------------------------------------- SDVX
def _nabla(d: ImageDraw.ImageDraw, cx, cy, size, col, width, rot=0.0) -> None:
    """倒三角 ∇ 线框。"""
    pts = []
    for k in range(3):
        a = math.radians(90 + 120 * k + rot)        # 尖朝下
        pts.append((cx + size * math.cos(a), cy + size * math.sin(a)))
    d.line(pts + [pts[0]], fill=col, width=width, joint="curve")


def _grid(img: Image.Image, step: int, col) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h = img.size
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=col, width=1)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=col, width=1)
    img.alpha_composite(layer)


def _sdvx(h: int, palette: str) -> Image.Image:
    rnd = random.Random(7)
    if palette == "nabla":
        img = _gradient(h, [(0, (6, 40, 32)), (0.45, (10, 70, 52)), (1, (4, 26, 24))])
        neon, soft, glow2 = (70, 255, 160), (150, 255, 200), (0, 200, 140)
    else:
        img = _gradient(h, [(0, (14, 24, 52)), (0.5, (24, 44, 92)), (1, (10, 16, 38))])
        neon, soft, glow2 = (120, 200, 255), (210, 225, 255), (60, 120, 255)
    _glow(img, [(W - 260, 160, 520, glow2 + (120,)), (220, h * 0.45, 600, glow2 + (70,)),
                (W - 420, h - 260, 640, neon + (50,))])
    _grid(img, 64, neon + (16,))
    _streaks(img, rnd, 14, soft + (40,))
    # 大大小小的 ∇ 线框
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    _nabla(d, W - 330, 340, 300, neon + (90,), 6)
    _nabla(d, W - 330, 340, 250, neon + (45,), 3)
    _nabla(d, 260, h - 360, 380, neon + (50,), 5, rot=8)
    for _ in range(max(6, h // 260)):
        _nabla(d, rnd.uniform(0, W), rnd.uniform(0, h), rnd.uniform(26, 120), soft + (int(rnd.uniform(25, 70)),),
               2, rot=rnd.uniform(-12, 12))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(5)))
    img.alpha_composite(layer)
    _dots(img, rnd, h // 6, soft + (150,))
    _sparkles(img, rnd, h // 120, (230, 255, 240, 200), (2, 6))
    # 暗角，让卡片更清楚
    _glow(img, [(W / 2, -400, 900, (0, 0, 0, 0))], 1)
    return img


# ---------------------------------------------------------------- オンゲキ
def _ribbons(img: Image.Image, rnd: random.Random, n: int, col) -> None:
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i in range(n):
        y0 = rnd.uniform(0, h)
        amp, per, ph = rnd.uniform(40, 160), rnd.uniform(700, 1500), rnd.uniform(0, 6.28)
        thick = rnd.uniform(18, 70)
        top = [(x, y0 + amp * math.sin(x / per * 6.28 + ph)) for x in range(-20, w + 40, 20)]
        bot = [(x, y + thick * (0.6 + 0.4 * math.sin(x / 300 + i))) for x, y in reversed(top)]
        d.polygon(top + bot, fill=col[:3] + (int(rnd.uniform(0.4, 1) * col[3]),))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(10)))


def _bokeh(img: Image.Image, rnd: random.Random, n: int, cols) -> None:
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y, r = rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(20, 110)
        c = rnd.choice(cols)
        d.ellipse([x - r, y - r, x + r, y + r], fill=c[:3] + (int(rnd.uniform(0.3, 1) * c[3]),))
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255, 40), width=2)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(4)))


def _prisms(img: Image.Image, rnd: random.Random, n: int) -> None:
    """棱镜碎片：半透明彩色三角，带白边。"""
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    hues = [(255, 170, 220), (170, 230, 255), (255, 240, 170), (200, 180, 255), (170, 255, 220)]
    for _ in range(n):
        cx, cy, s = rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(30, 150)
        a0 = rnd.uniform(0, 360)
        pts = [(cx + s * math.cos(math.radians(a0 + k * rnd.uniform(100, 140))),
                cy + s * math.sin(math.radians(a0 + k * rnd.uniform(100, 140)))) for k in range(3)]
        d.polygon(pts, fill=rnd.choice(hues) + (int(rnd.uniform(40, 90)),))
        d.line(pts + [pts[0]], fill=(255, 255, 255, 110), width=2)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(1.2)))


def _rays(img: Image.Image, origin, n: int, col) -> None:
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ox, oy = origin
    for k in range(n):
        a = math.radians(30 + 120 * k / max(n - 1, 1))
        spread = math.radians(2.2)
        far = max(w, h) * 1.6
        d.polygon([(ox, oy), (ox + far * math.cos(a - spread), oy + far * math.sin(a - spread)),
                   (ox + far * math.cos(a + spread), oy + far * math.sin(a + spread))], fill=col)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(18)))


def _petals(img: Image.Image, rnd: random.Random, n: int) -> None:
    """樱花瓣：五瓣小花和单片花瓣，淡粉带白边。"""
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y, r = rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(7, 22)
        rot = rnd.uniform(0, 360)
        col = rnd.choice([(255, 236, 242), (255, 210, 226), (255, 246, 250)])
        a = int(rnd.uniform(110, 210))
        if rnd.random() < 0.55:             # 单片花瓣（椭圆 + 缺口）
            pts = []
            for k in range(24):
                t = 2 * math.pi * k / 24
                px, py = r * 0.55 * math.cos(t), r * math.sin(t)
                if py < -r * 0.75 and abs(px) < r * 0.12:
                    py = -r * 0.6
                ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
                pts.append((x + px * ca - py * sa, y + px * sa + py * ca))
            d.polygon(pts, fill=col + (a,))
        else:                                # 五瓣花
            for k in range(5):
                t = math.radians(rot + 72 * k)
                cx, cy = x + r * 0.55 * math.cos(t), y + r * 0.55 * math.sin(t)
                d.ellipse([cx - r * 0.42, cy - r * 0.42, cx + r * 0.42, cy + r * 0.42], fill=col + (a,))
            d.ellipse([x - r * 0.18, y - r * 0.18, x + r * 0.18, y + r * 0.18], fill=(255, 170, 196, a))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.8)))


def _geki(h: int, family: str) -> Image.Image:
    rnd = random.Random(11)
    if family == "refresh":            # 樱花粉（淡）
        img = _gradient(h, [(0, (255, 214, 226)), (0.4, (252, 196, 214)), (0.8, (246, 176, 200)),
                            (1, (238, 160, 190))])
        _glow(img, [(W - 300, 200, 560, (255, 246, 250, 170)), (300, h * 0.5, 620, (255, 170, 200, 80)),
                    (W - 500, h - 300, 700, (255, 200, 220, 90))])
        _petals(img, rnd, max(30, h // 60))
        _ribbons(img, rnd, 6, (255, 255, 255, 70))
        _bokeh(img, rnd, max(12, h // 120), [(255, 230, 238, 90), (255, 255, 255, 70), (255, 190, 212, 70)])
        _sparkles(img, rnd, h // 70, (255, 255, 255, 230), (3, 8))
        _dots(img, rnd, h // 8, (255, 255, 255, 170))
    elif family == "bright":           # bright / bright MEMORY：晴空 + 棱镜
        img = _gradient(h, [(0, (150, 220, 255)), (0.3, (96, 160, 240)), (0.7, (70, 90, 200)),
                            (1, (40, 44, 120))])
        _rays(img, (W * 0.72, -120), 9, (255, 255, 255, 46))
        _glow(img, [(W * 0.72, 60, 520, (255, 255, 255, 150)), (240, h * 0.55, 600, (255, 170, 230, 70)),
                    (W - 300, h - 300, 600, (140, 230, 255, 80))])
        _prisms(img, rnd, max(18, h // 90))
        _sparkles(img, rnd, h // 70, (255, 255, 255, 230), (3, 9))
        _dots(img, rnd, h // 8, (255, 255, 255, 170))
    else:                               # SUMMER / R.E.D. 及更早：橙红
        img = _gradient(h, [(0, (255, 186, 120)), (0.4, (236, 100, 80)), (1, (90, 30, 60))])
        _glow(img, [(W - 300, 180, 520, (255, 240, 200, 150)), (300, h * 0.6, 600, (255, 120, 90, 80))])
        _ribbons(img, rnd, 5, (255, 240, 220, 55))
        _sparkles(img, rnd, h // 80, (255, 250, 230, 220), (3, 8))
    if family == "refresh":            # 樱花粉页头：玫瑰色压一层，白字看得清又不发紫
        _top_shade(img, 290, 235, (206, 78, 128), 0.8)
    else:
        _top_shade(img, 300, 170, {"bright": (16, 28, 90)}.get(family, (80, 20, 20)))
    return img


def _top_shade(img: Image.Image, height: int = 300, alpha: int = 150, col=(20, 10, 40), power: float = 1.4) -> None:
    """页头那一段压暗一点，页头右边的白字（游戏名 / 版本 / 日期）才看得清。"""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for y in range(height):
        d.line([(0, y), (img.width, y)], fill=col + (int(alpha * (1 - y / height) ** power),))
    img.alpha_composite(layer)


def geki_family(client: int | None) -> str:
    if client is None or client >= 150:
        return "refresh"
    if client >= 130:
        return "bright"
    return "old"


@lru_cache(maxsize=16)
def background(game: str, version: str, h: int) -> Image.Image:
    """返回 (W, h) 的 RGBA 背景。game: sdvx / geki；version: sdvx 用 nabla / exceed…，geki 用 refresh / bright / old。"""
    h = max(int(h), 200)
    if game == "sdvx":
        return _sdvx(h, "nabla" if version in ("nabla", "", None) else "other")
    return _geki(h, version or "refresh")
