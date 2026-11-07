"""字体里到底有没有某个字：直接读字体文件的 cmap 表（不靠「画出来像不像方框」去猜）。

支持 .ttf / .otf / .ttc（cmap format 4 和 12）。用来给标题、名字这类混着简体字 / 假名 / ♭ ✓ ∀ 之类
符号的文字逐字挑字体：主字体没有的字交给后备字体（中文 → 日文 → 符号）。
"""
from __future__ import annotations

import struct
from functools import lru_cache

from PIL import ImageDraw, ImageFont


@lru_cache(maxsize=64)
def codepoints(path: str, index: int = 0) -> frozenset[int]:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return frozenset()
    try:
        return frozenset(_parse(data, index))
    except (struct.error, IndexError, ValueError):
        return frozenset()


def _parse(data: bytes, index: int) -> set[int]:
    base = 0
    if data[:4] == b"ttcf":
        n = struct.unpack_from(">I", data, 8)[0]
        base = struct.unpack_from(">I", data, 12 + 4 * min(index, n - 1))[0]
    num = struct.unpack_from(">H", data, base + 4)[0]
    cmap = None
    for i in range(num):
        tag, _cs, off, _ln = struct.unpack_from(">4sIII", data, base + 12 + 16 * i)
        if tag == b"cmap":
            cmap = off
            break
    if cmap is None:
        return set()
    n = struct.unpack_from(">H", data, cmap + 2)[0]
    subs = {}
    for i in range(n):
        pid, eid, off = struct.unpack_from(">HHI", data, cmap + 4 + 8 * i)
        subs[(pid, eid)] = cmap + off
    for key in ((3, 10), (0, 6), (0, 4), (3, 1), (0, 3), (0, 1), (0, 0)):
        if key not in subs:
            continue
        off = subs[key]
        fmt = struct.unpack_from(">H", data, off)[0]
        if fmt == 12:
            return _fmt12(data, off)
        if fmt == 4:
            return _fmt4(data, off)
    return set()


def _fmt12(data: bytes, off: int) -> set[int]:
    n = struct.unpack_from(">I", data, off + 12)[0]
    out: set[int] = set()
    for i in range(n):
        start, end, gid = struct.unpack_from(">III", data, off + 16 + 12 * i)
        if gid == 0:
            start += 1
        out.update(range(start, end + 1))
    return out


def _fmt4(data: bytes, off: int) -> set[int]:
    seg2 = struct.unpack_from(">H", data, off + 6)[0]
    seg = seg2 // 2
    ends = struct.unpack_from(f">{seg}H", data, off + 14)
    starts = struct.unpack_from(f">{seg}H", data, off + 16 + seg2)
    deltas = struct.unpack_from(f">{seg}h", data, off + 16 + 2 * seg2)
    ro_pos = off + 16 + 3 * seg2
    ranges = struct.unpack_from(f">{seg}H", data, ro_pos)
    out: set[int] = set()
    for i in range(seg):
        s, e, d, r = starts[i], ends[i], deltas[i], ranges[i]
        if s == 0xFFFF:
            continue
        for c in range(s, e + 1):
            if r == 0:
                g = (c + d) & 0xFFFF
            else:
                p = ro_pos + 2 * i + r + 2 * (c - s)
                g = struct.unpack_from(">H", data, p)[0]
                if g:
                    g = (g + d) & 0xFFFF
            if g:
                out.add(c)
    return out


def has(font: ImageFont.FreeTypeFont, ch: str) -> bool:
    if ch.isspace() or ord(ch) < 0x20:
        return True
    path = getattr(font, "path", None)
    if not path:
        return True
    cps = codepoints(str(path), int(getattr(font, "index", 0) or 0))
    return not cps or ord(ch) in cps          # unreadable font → assume it has everything


# 只拿来补个别符号的字体：不当整行的底字体（英文字母在它们里面又细又不一样）
SYMBOL_FONTS = ("seguisym", "seguiemj", "seguihis", "cambria", "malgun", "symbol", "emoji", "dejavu")


def is_symbol_font(font) -> bool:
    name = str(getattr(font, "path", "") or "").lower().replace("\\", "/").rsplit("/", 1)[-1]
    return any(k in name for k in SYMBOL_FONTS)


def pick_base(text: str, chain: list, candidates: int = 3):
    """整行用同一个字体：在链前面几个正文字体里挑覆盖这行字最多的那个（一样多取靠前的）。
    「理论最高」在日文字体里缺「论」→ 整行换成中文字体，不会只有一个字长得不一样。"""
    chars = [c for c in text if not c.isspace() and ord(c) >= 0x20]
    if not chars:
        return chain[0]
    best, best_n = chain[0], -1
    for f in [f for f in chain if not is_symbol_font(f)][:candidates]:
        n = sum(1 for c in chars if has(f, c))
        if n > best_n:
            best, best_n = f, n
        if n == len(chars):
            break
    return best


def runs(text: str, chain: list[ImageFont.FreeTypeFont]) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    """把文字切成 (片段, 字体)：整行先用 pick_base 选出的字体，它没有的字再去链里找；谁都没有就用底字体。"""
    base = pick_base(text, chain)
    out: list[tuple[str, ImageFont.FreeTypeFont]] = []
    for ch in text:
        pick = base if has(base, ch) else next((f for f in chain if has(f, ch)), base)
        if out and out[-1][1] is pick:
            out[-1] = (out[-1][0] + ch, pick)
        else:
            out.append((ch, pick))
    return out


def width(text: str, chain: list[ImageFont.FreeTypeFont]) -> float:
    return sum(f.getlength(t) for t, f in runs(text, chain))


def draw(d: ImageDraw.ImageDraw, xy, text: str, chain: list[ImageFont.FreeTypeFont], fill, anchor: str = "la",
         **kw) -> float:
    """像 ImageDraw.text 一样画（支持 l/m/r × a/m/s 锚点），只是逐字换字体；返回画完的右边 x。"""
    x, y = xy
    parts = runs(text, chain)
    total = sum(f.getlength(t) for t, f in parts)
    h, v = (anchor + "la")[0], (anchor + "la")[1]
    x = x - total / 2 if h == "m" else x - total if h == "r" else x
    base = chain[0]
    asc, desc = base.getmetrics()
    by = y + asc if v == "a" else y + (asc - desc) / 2 if v == "m" else y   # → baseline
    for t, f in parts:
        d.text((x, by), t, font=f, fill=fill, anchor="ls", **kw)
        x += f.getlength(t)
    return x
