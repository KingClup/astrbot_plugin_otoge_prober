"""很小的二维码生成器：只做字节模式、纠错等级 M、版本 1–5（最多 84 个字节，放一个网址够了）。

不想为了页脚上一个码多装一个依赖。返回 0/1 方阵（1 = 黑），不含四周留白。
"""
from __future__ import annotations

# 版本 → (总码字数, 每块纠错码字数, 块数)，等级 M
_SPEC = {1: (26, 10, 1), 2: (44, 16, 1), 3: (70, 26, 1), 4: (100, 18, 2), 5: (134, 24, 2)}
_ALIGN = {1: None, 2: 18, 3: 22, 4: 26, 5: 30}

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _rs(data: list[int], n: int) -> list[int]:
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, g in enumerate(gen):
            nxt[j] ^= g
            nxt[j + 1] ^= _EXP[_LOG[g] + i] if g else 0
        gen = nxt
    rem = [0] * n
    for b in data:
        f = b ^ rem[0]
        rem = rem[1:] + [0]
        if f:
            for j in range(n):
                if gen[j + 1]:
                    rem[j] ^= _EXP[_LOG[gen[j + 1]] + _LOG[f]]
    return rem


def _codewords(payload: bytes) -> tuple[int, list[int]]:
    for ver, (total, ec, blocks) in _SPEC.items():
        cap = total - ec * blocks
        if len(payload) + 2 <= cap:
            break
    else:
        raise ValueError("内容太长，放不进版本 5 的二维码")
    bits = [0, 1, 0, 0] + [(len(payload) >> i) & 1 for i in range(7, -1, -1)]
    for b in payload:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, cap * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(data) < cap:
        data.append(pad[(len(data) - (len(bits) // 8)) % 2])
    size = cap // blocks
    chunks = [data[i * size:(i + 1) * size] for i in range(blocks)]
    ecs = [_rs(c, ec) for c in chunks]
    out = [c[i] for i in range(size) for c in chunks] + [e[i] for i in range(ec) for e in ecs]
    return ver, out


def _format_bits(mask: int) -> int:
    d = mask                      # 等级 M = 00
    r = d << 10
    for i in range(14, 9, -1):
        if r >> i & 1:
            r ^= 0x537 << (i - 10)
    return ((d << 10) | r) ^ 0x5412


_MASKS = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
          lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
          lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
          lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]


def _penalty(m: list[list[int]]) -> int:
    n = len(m)
    p = 0
    for rows in (m, [list(col) for col in zip(*m)]):
        for row in rows:
            run = 1
            for i in range(1, n):
                if row[i] == row[i - 1]:
                    run += 1
                else:
                    if run >= 5:
                        p += run - 2
                    run = 1
            if run >= 5:
                p += run - 2
            s = "".join(map(str, row))
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                p += 3
    dark = sum(map(sum, m)) * 100 // (n * n)
    p += abs(dark - 50) // 5 * 10
    return p


def matrix(text: str | bytes, mask: int | None = None) -> list[list[int]]:
    payload = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    ver, words = _codewords(payload)
    n = 17 + 4 * ver
    m = [[0] * n for _ in range(n)]
    fixed = [[False] * n for _ in range(n)]

    def put(r, c, v):
        m[r][c] = 1 if v else 0
        fixed[r][c] = True

    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):          # 三个定位图案 + 白边
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = r0 + dr, c0 + dc
                if 0 <= r < n and 0 <= c < n:
                    inside = 0 <= dr <= 6 and 0 <= dc <= 6
                    put(r, c, inside and (dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4)))
    a = _ALIGN[ver]
    if a:
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                put(a + dr, a + dc, max(abs(dr), abs(dc)) != 1)
    for i in range(8, n - 8):                                 # 时序图案
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    put(n - 8, 8, 1)                                          # 固定黑点
    for i in range(9):                                        # 格式信息的位置先占住
        if not fixed[8][i]:
            put(8, i, 0)
        if not fixed[i][8]:
            put(i, 8, 0)
    for i in range(8):
        put(8, n - 1 - i, 0)
        put(n - 1 - i, 8, 0)
    put(n - 8, 8, 1)

    bits = [(w >> i) & 1 for w in words for i in range(7, -1, -1)]
    bits += [0] * 7
    idx = 0
    cells = []
    c = n - 1
    up = True
    while c > 0:
        if c == 6:
            c -= 1
        rng = range(n - 1, -1, -1) if up else range(n)
        for r in rng:
            for cc in (c, c - 1):
                if not fixed[r][cc]:
                    m[r][cc] = bits[idx] if idx < len(bits) else 0
                    idx += 1
                    cells.append((r, cc))
        up = not up
        c -= 2

    def apply(k: int) -> list[list[int]]:
        g = [row[:] for row in m]
        f = _MASKS[k]
        for r, cc in cells:
            if f(r, cc):
                g[r][cc] ^= 1
        fb = _format_bits(k)
        fbits = [(fb >> i) & 1 for i in range(14, -1, -1)]    # 高位在前
        pos1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
        pos2 = [(n - 1, 8), (n - 2, 8), (n - 3, 8), (n - 4, 8), (n - 5, 8), (n - 6, 8), (n - 7, 8),
                (8, n - 8), (8, n - 7), (8, n - 6), (8, n - 5), (8, n - 4), (8, n - 3), (8, n - 2), (8, n - 1)]
        for b, (r1, c1), (r2, c2) in zip(fbits, pos1, pos2):
            g[r1][c1] = b
            g[r2][c2] = b
        return g

    if mask is not None:
        return apply(mask)
    return min((apply(k) for k in range(8)), key=_penalty)


def image(text: str, scale: int = 6, border: int = 2, dark=(27, 42, 74), light=(255, 255, 255)):
    """PIL 图：scale = 每个小格几个像素，border = 四周留几格白。"""
    from PIL import Image
    g = matrix(text)
    n = len(g)
    im = Image.new("RGB", (n + border * 2, n + border * 2), light)
    px = im.load()
    for r in range(n):
        for c in range(n):
            if g[r][c]:
                px[c + border, r + border] = dark
    return im.resize((im.width * scale, im.height * scale), Image.NEAREST)
