"""Find the measures on an sdvx.in chart picture (CHUNITHM / ONGEKI / PJSK / old SDVX pages).

sdvx.in pages stack three transparent layers: bg (lanes, beat lines and the brighter measure lines), notes, and
bar (measure numbers, BPM labels in the margins). The picture is a row of lane columns read left → right, each
column read bottom → top. So: lanes = x-runs where the bg layer is opaque; measure lines = rows inside a lane
whose bg brightness stands well above the lane's usual (beat lines are dimmer than measure lines).

Checked against real pages from every game (11-07): CHUNITHM 240 px / 4-4 measure, lanes 150 px wide.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

Rect = tuple[int, int, int, int]


def _runs(mask: np.ndarray, min_len: int, gap: int = 3) -> list[tuple[int, int]]:
    out = []
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            s = i
            while i < n and mask[i]:
                i += 1
            if out and s - out[-1][1] <= gap:
                out[-1] = (out[-1][0], i)
            else:
                out.append((s, i))
        else:
            i += 1
    return [(a, b) for a, b in out if b - a >= min_len]


def lanes(bg: np.ndarray) -> list[tuple[int, int]]:
    """x-ranges of the lane columns (bg alpha present in a good share of the rows)."""
    alpha = bg[:, :, 3] > 0
    cover = alpha.mean(axis=0)
    return _runs(cover > 0.15, min_len=24)


def measure_lines(bg: np.ndarray, x0: int, x1: int) -> tuple[list[int], tuple[int, int]]:
    """y of the measure lines in one lane, top → bottom, plus the lane's vertical extent."""
    w = x1 - x0
    inner = bg[:, x0 + w // 5: x1 - w // 5]
    present = (inner[:, :, 3] > 0).mean(axis=1) > 0.5
    ext = _runs(present, min_len=10, gap=2)
    if not ext:
        return [], (0, 0)
    top, bottom = ext[0][0], ext[-1][1]
    rgb = inner[top:bottom, :, :3].astype(np.float32)
    a = inner[top:bottom, :, 3:4].astype(np.float32) / 255.0
    row = (rgb * a).mean(axis=2).mean(axis=1)          # brightness as drawn over black, per row
    base = float(np.median(row))
    # the first / last measure line sits right on the lane's edge: pad so it can still be a peak
    row = np.concatenate(([base], row, [base]))
    # local peaks above the lane colour: beat lines (≈34) and measure lines (≈70–125, 2–4× brighter)
    peaks = [y - 1 for y in range(1, len(row) - 1)
             if row[y] > row[y - 1] and row[y] >= row[y + 1] and row[y] > base + 5]
    row = row[1:-1]
    if not peaks:
        return [], (top, bottom)
    top_val = max(float(row[y]) for y in peaks)
    cut = base + 0.6 * (top_val - base)
    hits = [y for y in peaks if row[y] >= cut]
    lines: list[list[int]] = []
    for y in hits:
        y = int(y) + top
        if lines and y - lines[-1][-1] <= 3:
            lines[-1].append(y)
        else:
            lines.append([y])
    return [int(round(sum(g) / len(g))) for g in lines], (top, bottom)


def measures(bg_img: Image.Image, min_h: int = 30, pad: int = 0) -> list[Rect]:
    """Measure boxes in play order: lanes left → right, inside a lane bottom → top."""
    bg = np.asarray(bg_img.convert("RGBA"))
    out: list[Rect] = []
    for x0, x1 in lanes(bg):
        ys, (top, bottom) = measure_lines(bg, x0, x1)
        if len(ys) < 2:
            continue
        ys = sorted(ys)
        # typical measure height in this lane; a gap much bigger than that is not one measure
        gaps = [b - a for a, b in zip(ys, ys[1:]) if b - a >= min_h]
        if not gaps:
            continue
        for a, b in reversed(list(zip(ys, ys[1:]))):      # bottom → top
            if b - a < min_h:
                continue
            out.append((max(0, x0 - pad), a, x1 + pad, b + 1))
    return out


def fallback_measures(img: Image.Image, per_col: int = 8) -> list[Rect]:
    """No usable bg layer: split every non-black column into equal parts."""
    arr = np.asarray(img.convert("RGB")).astype(np.int32).sum(axis=2)
    cols = _runs((arr > 30).mean(axis=0) > 0.15, min_len=24)
    out = []
    h = img.height
    for x0, x1 in cols:
        step = h / per_col
        for i in range(per_col):
            b = int(h - i * step)
            a = int(h - (i + 1) * step)
            out.append((x0, max(0, a), x1, b))
    return out
