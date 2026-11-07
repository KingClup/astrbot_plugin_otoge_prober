"""Draw an SDVX chart from sdvx.in's chart JSON (the "drawLasers.v1" / KSON-like format its viewer paints
on a canvas) into a still image, laid out like sdvx.in's classic PNG chart pages: one column per wrap,
bottom → top, BT white, FX orange, lasers blue (left) / pink (right), measure numbers on the left, BPM in
green on the right.

JSON fields used: wraps (pulse where each column starts), totalPulses, bars[{len}], notes[{type, lane,
pulse}], holds[{type, lane, pulse, pulseEnd}], lasers{left,right: [[start, [[rel, v | [v0, v1]], …], wide]]},
bpm[{y, v}]. 960 pulses = one 4/4 measure. Laser value v ∈ [0, 1] spans a band a bit wider than the lanes.
"""
from __future__ import annotations

from bisect import bisect_right

from PIL import Image, ImageDraw, ImageFont

PX_PER_PULSE = 0.15          # 144 px per 4/4 measure, like the classic sdvx.in pages
LANE_W = 56                  # BT A-D area (4 × 14)
COL_GAP = 58                 # room for measure numbers / BPM labels and wide lasers between columns
TOP, BOTTOM = 24, 24
BLUE_FILL, BLUE_EDGE = (40, 210, 255, 95), (90, 235, 255, 255)
RED_FILL, RED_EDGE = (240, 48, 128, 105), (255, 105, 180, 255)
LANE_COL = {"A": 0, "B": 1, "C": 2, "D": 3}
FX_COL = {"L": 0, "R": 1}


def _font(size: int):
    for p in ("C:\\Windows\\Fonts\\consola.ttf", "C:\\Windows\\Fonts\\arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


class _Layout:
    def __init__(self, chart: dict):
        total = int(chart.get("totalPulses") or 0)
        wraps = sorted({int(w) for w in (chart.get("wraps") or [0])} | {0})
        if not total:
            ends = [n.get("pulseEnd") or n.get("pulse") or 0 for n in (chart.get("notes") or []) + (chart.get("holds") or [])]
            total = (max(ends) // 960 + 1) * 960 if ends else 960 * 4
        wraps = [w for w in wraps if w < total] or [0]
        self.starts = wraps
        self.ends = wraps[1:] + [total]
        self.total = total
        self.height = max(e - s for s, e in zip(self.starts, self.ends))
        self.col_w = LANE_W + COL_GAP
        self.W = COL_GAP // 2 + len(self.starts) * self.col_w + COL_GAP // 2
        self.H = TOP + int(self.height * PX_PER_PULSE) + BOTTOM

    def col(self, pulse: float) -> int:
        return max(0, min(len(self.starts) - 1, bisect_right(self.starts, pulse) - 1))

    def x0(self, c: int) -> float:
        return COL_GAP // 2 + c * self.col_w + COL_GAP / 2

    def y(self, c: int, pulse: float) -> float:
        return self.H - BOTTOM - (pulse - self.starts[c]) * PX_PER_PULSE

    def split(self, p0: float, p1: float):
        """Split a pulse span across columns → [(col, a, b)]."""
        out = []
        a = p0
        while a < p1 - 1e-6:
            c = self.col(a)
            b = min(p1, self.ends[c])
            if b <= a:
                break
            out.append((c, a, b))
            a = b
        return out


def render(chart: dict) -> Image.Image:
    L = _Layout(chart)
    img = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 255))
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    o = ImageDraw.Draw(over)
    f_small, f_bpm = _font(11), _font(12)

    # ---- lanes ----
    for c, (s, e) in enumerate(zip(L.starts, L.ends)):
        x = L.x0(c)
        yb, yt = L.y(c, s), L.y(c, e)
        d.rectangle([x, yt, x + LANE_W, yb], fill=(14, 14, 22))
        for k in (1, 3):
            d.line([x + k * LANE_W / 4, yt, x + k * LANE_W / 4, yb], fill=(36, 36, 48))
        d.line([x + LANE_W / 2, yt, x + LANE_W / 2, yb], fill=(52, 52, 66))
        d.line([x - 1, yt, x - 1, yb], fill=(40, 90, 200), width=3)
        d.line([x + LANE_W + 1, yt, x + LANE_W + 1, yb], fill=(190, 40, 110), width=3)

    # ---- measures ----
    pulse, num = 0, 1
    bars = chart.get("bars") or [{"len": 960}] * (L.total // 960 + 1)
    for b in bars:
        if pulse >= L.total:
            break
        c = L.col(pulse)
        y = L.y(c, pulse)
        x = L.x0(c)
        d.line([x, y, x + LANE_W, y], fill=(110, 110, 130))
        d.text((x - 6, y), f"{num:02d}" if num < 100 else str(num), font=f_small, fill=(150, 150, 160), anchor="rm")
        # beat lines
        for k in range(1, max(1, int(b.get("num") or 4))):
            pb = pulse + k * int(b.get("len") or 960) / max(1, int(b.get("num") or 4))
            if pb < L.ends[c]:
                yy = L.y(c, pb)
                d.line([x, yy, x + LANE_W, yy], fill=(40, 40, 54))
        pulse += int(b.get("len") or 960)
        num += 1

    # ---- holds (under chips) ----
    for h in chart.get("holds") or []:
        p0, p1 = float(h.get("pulse") or 0), float(h.get("pulseEnd") or 0)
        for c, a, b in L.split(p0, p1):
            x = L.x0(c)
            ya, yb = L.y(c, a), L.y(c, b)
            if h.get("type") == "FX_HOLD":
                i = FX_COL.get(h.get("lane"), 0)
                o.rectangle([x + i * LANE_W / 2 + 2, yb, x + (i + 1) * LANE_W / 2 - 2, ya], fill=(255, 150, 20, 120))
            else:
                i = LANE_COL.get(h.get("lane"), 0)
                o.rectangle([x + i * LANE_W / 4 + 2, yb, x + (i + 1) * LANE_W / 4 - 2, ya], fill=(235, 235, 245, 235))
    img = Image.alpha_composite(img, over)

    # ---- lasers ----
    las = chart.get("lasers") or {}
    for side, fill, edge in (("left", BLUE_FILL, BLUE_EDGE), ("right", RED_FILL, RED_EDGE)):
        lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        for sec in las.get(side) or []:
            try:
                start = float(sec[0])
                pts = sec[1] or []
            except (TypeError, IndexError, ValueError):
                continue
            # sdvx.in: x = (v - 0.5) × 404 on a 220-px lane, squeezed so the laser edge stays inside ±202
            half = LANE_W * (202 - 18 - 2) / 220

            def xv(c, v):
                return L.x0(c) + LANE_W / 2 + (float(v) - 0.5) * 2 * half

            parsed = []
            for p in pts:
                rel = float(p[0] or 0)
                v = p[1]
                v0, v1 = (v[0], v[1]) if isinstance(v, (list, tuple)) else (v, v)
                parsed.append((start + rel, float(v0), float(v1), isinstance(v, (list, tuple))))
            for i, (pa, v0, v1, slam) in enumerate(parsed):
                if slam:
                    c = L.col(pa)
                    y = L.y(c, pa)
                    xa, xb = sorted((xv(c, v0), xv(c, v1)))
                    ld.rectangle([xa - 4, y - 6, xb + 4, y], fill=fill[:3] + (200,), outline=edge)
                if i + 1 >= len(parsed):
                    continue
                pb, w0, _w1, _s = parsed[i + 1]
                if pb <= pa:
                    continue
                for c, a, b in L.split(pa, pb):
                    ta, tb = (a - pa) / (pb - pa), (b - pa) / (pb - pa)
                    va, vb = v1 + (w0 - v1) * ta, v1 + (w0 - v1) * tb
                    xa, xb = xv(c, va), xv(c, vb)
                    ya, yb = L.y(c, a), L.y(c, b)
                    hw = 4.5
                    ld.polygon([(xa - hw, ya), (xa + hw, ya), (xb + hw, yb), (xb - hw, yb)], fill=fill)
                    ld.line([(xa - hw, ya), (xb - hw, yb)], fill=edge, width=1)
                    ld.line([(xa + hw, ya), (xb + hw, yb)], fill=edge, width=1)
        img = Image.alpha_composite(img, lay)

    # ---- chips ----
    d = ImageDraw.Draw(img)
    for n in chart.get("notes") or []:
        p = float(n.get("pulse") or 0)
        c = L.col(p)
        x, y = L.x0(c), L.y(c, p)
        t = n.get("type")
        if t == "BT":
            i = LANE_COL.get(n.get("lane"), 0)
            d.rectangle([x + i * LANE_W / 4 + 1, y - 3, x + (i + 1) * LANE_W / 4 - 1, y], fill=(250, 250, 255),
                        outline=(120, 120, 140))
        elif t in ("FX", "EX"):
            i = FX_COL.get(n.get("lane"), 0)
            col = (255, 150, 20) if t == "FX" else (255, 220, 60)
            d.rectangle([x + i * LANE_W / 2 + 1, y - 4, x + (i + 1) * LANE_W / 2 - 1, y], fill=col, outline=(120, 60, 0))

    # ---- BPM ----
    last = None
    for b in chart.get("bpm") or []:
        p = float(b.get("y") or 0)
        v = b.get("v")
        if v is None or v == last or p >= L.total:
            continue
        last = v
        c = L.col(p)
        d.text((L.x0(c) + LANE_W + 6, L.y(c, p)), f"{v:g}" if isinstance(v, (int, float)) else str(v), font=f_bpm,
               fill=(120, 255, 90), anchor="lm")
    return img.convert("RGB")


def measure_rects(chart: dict, pad: int = 10) -> list[tuple[int, int, int, int]]:
    """Measure boxes (left, top, right, bottom) on the picture render() draws, in play order.
    A measure that wraps into the next column is cut at the column end (its tail starts the next column)."""
    L = _Layout(chart)
    out = []
    pulse = 0
    bars = chart.get("bars") or [{"len": 960}] * (L.total // 960 + 1)
    for b in bars:
        if pulse >= L.total:
            break
        length = int(b.get("len") or 960)
        end = min(pulse + length, L.total)
        for c, a, z in L.split(pulse, end):
            x = L.x0(c)
            top, bottom = L.y(c, z), L.y(c, a)
            if bottom - top >= 8:
                out.append((int(x - pad), int(top), int(x + LANE_W + pad), int(round(bottom))))
            break                       # only the part in the column where the measure starts
        pulse = end
    return out
