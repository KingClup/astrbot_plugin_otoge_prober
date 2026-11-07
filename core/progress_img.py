"""版本进度图（/查分 进度）：每个游戏、每个服现在是哪个版本、版本号、证据，定数来源统计。

数据由 main.OtogeScore._progress_data() 整理成 ProgressView，文字版（兜底）和图片版用同一份。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PIL import ImageDraw

try:
    from ..mai.render import fonts as F
    from ..mai.render import kit as K
    from .bindguide import _wrap
except ImportError:  # tests
    from mai.render import fonts as F
    from mai.render import kit as K
    from core.bindguide import _wrap

W, M = 1080, 32
try:
    from . import palette as P
except ImportError:  # tests
    from core import palette as P
MAI, CHU = P.MAI, P.CHU
PRIV = P.REGION["私服"]
GREEN = P.CORE                 # 段标题（不是游戏、不是区服）
WARN = P.REQ
TEXT = P.TEXT
REGION_COLORS = dict(P.REGION)


@dataclass
class ProgressRow:
    region: str                  # 日服 / 国际服 / 国服 / 私服
    version: str                 # 当前版本名
    number: str = ""             # 版本号：舞萌 5 位码（27004）、中二客户端号（2.50）、落雪版本码
    evidence: str = ""           # 官方曲目表 31 首 MAGiCAL · 公告 MAGiCAL · 曲库 MAGiCAL
    warn: str = ""               # 曲库落后之类


@dataclass
class ProgressView:
    when: str
    hour: int
    games: list[tuple[str, list[ProgressRow]]] = field(default_factory=list)   # (游戏名, 行)
    sections: list[tuple[str, list[str]]] = field(default_factory=list)        # (标题, 行)：补曲库、定数
    sources: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)


NUMBER_NOTE = ("版本号：舞萌是官方曲目表的 5 位版本码（27004 = 1.70 这一版的第 04 批新歌，国服是落雪的版本码）；"
               "中二官方不公开，只写确认过的客户端版本号。私服按每个玩家自己的客户端版本算，B50 图上会标 Ver.x.xx。")


def text(v: ProgressView) -> str:
    lines = [f"版本进度（上次核实 {v.when}，每天 {v.hour}:00 自动核实）"]
    if v.changes:
        lines += ["最近变化：" + "；".join(v.changes)]
    for game, rows in v.games:
        lines += ["", game]
        for r in rows:
            num = f" · {r.number}" if r.number else ""
            ev = f"（{r.evidence}）" if r.evidence else ""
            lines.append(f"· {r.region}：{r.version or '?'}{num}{ev}" + (f" ⚠ {r.warn}" if r.warn else ""))
    for title, ls in v.sections:
        lines += ["", title, *ls]
    if v.sources:
        lines += ["", "数据源：" + "；".join(v.sources)]
    return "\n".join(lines)


def _title(d, x, y, t, color):
    d.rounded_rectangle((x, y + 4, x + 8, y + 42), 4, fill=color)
    F.draw_text(d, (x + 22, y), t, "bold", 36, K.INK)


def _row_h(r: ProgressRow, iw: int) -> tuple[int, list[str]]:
    ev = _wrap(r.evidence, "regular", 23, iw - 40) if r.evidence else []
    return 58 + 32 * len(ev) + (34 if r.warn else 0) + 18, ev


def render(v: ProgressView, bot_name: str = "AstrBot", assets=None) -> bytes:
    iw = W - 2 * M - 64
    game_blocks = []
    for game, rows in v.games:
        hs = [_row_h(r, iw) for r in rows]
        game_blocks.append((game, rows, hs, 96 + sum(h for h, _ in hs) + 10))
    secs = [(t, [ln for x in ls for ln in _wrap(x, "regular", 24, iw)]) for t, ls in v.sections]
    note = _wrap(NUMBER_NOTE, "regular", 23, iw)
    src = [ln for x in v.sources for ln in _wrap("· " + x, "regular", 21, iw)]
    H = (30 + 170 + 24 + sum(b[3] + 24 for b in game_blocks)
         + sum(96 + 34 * len(ls) + 20 + 24 for _t, ls in secs)
         + (96 + 31 * len(src) + 20 + 24 if src else 0) + 40 + 32 * len(note) + 110)
    im = K.background(assets, "", W, H, seed=23)
    d = ImageDraw.Draw(im)

    # ---- title ----
    K.panel(im, (M, 30, W - M, 200), r=36)
    d.rounded_rectangle((M + 28, 62, M + 116, 150), 26, fill=P.CORE)
    F.draw_text(d, (M + 45, 72), "版", "bold", 54, (255, 255, 255))
    F.draw_text(d, (M + 140, 56), "版本进度", "bold", 50, K.INK)
    sub = f"上次核实 {v.when} · 每天 {v.hour}:00 自动核实"
    if v.changes:
        sub += " · 最近变化：" + "；".join(v.changes)
    F.draw_text(d, (M + 142, 124), F.fit(sub, "regular", 27, W - 2 * M - 170), "regular", 27, TEXT)
    y = 30 + 170 + 24

    # ---- one panel per game ----
    for game, rows, hs, ph in game_blocks:
        col = MAI if "舞萌" in game else CHU
        K.panel(im, (M, y, W - M, y + ph), r=32)
        _title(d, M + 28, y + 28, game, col)
        ry = y + 96
        for r, (h, ev) in zip(rows, hs):
            x0 = M + 36
            rc = REGION_COLORS.get(r.region, PRIV)
            x = K.pill(d, x0, ry, r.region, size=24, h=42, pad=16, fg=(255, 255, 255), bg=rc) + 18
            F.draw_text(d, (x, ry + 2), F.fit(r.version or "?", "bold", 32, 520), "bold", 32, K.INK)
            if r.number:
                nx = x + F.text_width(F.fit(r.version or "?", "bold", 32, 520), "bold", 32) + 16
                K.pill(d, nx, ry + 4, r.number, size=22, h=36, pad=12, fg=rc, bg=(255, 255, 255, 240), outline=rc)
            ty = ry + 54
            for line in ev:
                F.draw_text(d, (x0 + 8, ty), line, "regular", 23, TEXT)
                ty += 32
            if r.warn:
                F.draw_text(d, (x0 + 8, ty + 2), "注意：" + r.warn, "regular", 23, WARN)
            ry += h
        y += ph + 24

    # ---- sections: 补曲库 / 定数 ----
    for t, ls in secs:
        ph = 96 + 34 * len(ls) + 20
        K.panel(im, (M, y, W - M, y + ph), r=32)
        _title(d, M + 28, y + 28, t, GREEN)
        ty = y + 96
        for line in ls:
            F.draw_text(d, (M + 36, ty), line, "regular", 24, TEXT)
            ty += 34
        y += ph + 24

    # ---- sources ----
    if src:
        ph = 96 + 31 * len(src) + 20
        K.panel(im, (M, y, W - M, y + ph), r=32)
        _title(d, M + 28, y + 28, "数据源", K.SUB)
        ty = y + 96
        for line in src:
            F.draw_text(d, (M + 36, ty), line, "regular", 21, K.SUB)
            ty += 31
        y += ph + 24

    # ---- what the numbers mean ----
    ty = y + 10
    for line in note:
        F.draw_text(d, (M + 12, ty), line, "regular", 23, TEXT)
        ty += 32
    K.footer(im, bot_name, credit="")
    return K.to_png(im)
