"""CHUNITHM info cards: 查歌 (song detail), 定数查歌 (card list), 定数表 (jacket grid).

Same look as the maimai cards (shared kit), CHUNITHM colours, per-server constants with a red marker
where 国际服 / 日服 / 国服 disagree.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from ..mai.render import fonts as F
    from ..mai.render import kit as K
    from ..mai.render.b50img import placeholder_cover
except ImportError:  # tests import the subpackages top-level
    from mai.render import fonts as F
    from mai.render import kit as K
    from mai.render.b50img import placeholder_cover
from .logos import LogoStore
from .models import Difficulty
from .rating import song_rating
from .songdb import SongInfo

DIFF = {
    Difficulty.BASIC: ((34, 177, 76), "Basic"), Difficulty.ADVANCED: ((255, 152, 0), "Advanced"),
    Difficulty.EXPERT: ((230, 40, 60), "Expert"), Difficulty.MASTER: ((142, 36, 170), "Master"),
    Difficulty.ULTIMA: ((40, 40, 40), "Ultima"),
}
SERVER_NAMES = {"intl": "国际服", "jp": "日服", "cn": "国服"}
SERVER_SHORT = {"intl": "国际", "jp": "日", "cn": "国"}
LINES = (("SSS+", 1009000, (255, 120, 190)), ("SSS", 1007500, (255, 150, 60)), ("SS+", 1005000, (240, 170, 40)),
         ("SS", 1000000, (230, 160, 40)), ("S+", 990000, (240, 190, 60)), ("S", 975000, (240, 190, 60)))
CREDIT = "Data from chuni-penguin / Tachi / 水鱼查分器"
NOTE_KEYS = ("total", "tap", "hold", "slide", "air", "flick")


class _Assets:
    """Minimal asset adapter for the kit (chuni theme folder; no game icons needed here)."""

    def __init__(self, themes: Path):
        self.themes = str(themes)

    def theme_file(self, version, name):
        for v in (version, "default"):
            p = os.path.join(self.themes, str(v or "default"), name)
            if os.path.exists(p):
                return p
        return None

    def icon(self, name):
        return None


def _jacket(path: Path | None, title: str, size: int) -> Image.Image:
    if path is not None and Path(path).exists():
        try:
            return Image.open(path).convert("RGB").resize((size, size), Image.LANCZOS)
        except Exception:  # noqa: BLE001
            pass
    return placeholder_cover(title, size)


def _c(d, cx, y, text, size, fill, kind="bold"):
    tw = F.text_width(text, kind, size)
    F.draw_text(d, (cx - tw / 2, y), text, kind, size, fill)


def _diff_label(d, x, y, diff: Difficulty, size=30) -> int:
    col, name = DIFF.get(diff, ((60, 60, 60), str(diff)))
    return F.draw_text(d, (x, y), name, "latin", size, col, stroke=3, stroke_fill=(255, 255, 255))


class ChuCards:
    def __init__(self, data_dir: Path, bot_name: str = "AstrBot"):
        self.assets = _Assets(Path(data_dir) / "cards_theme")
        self.bot_name = bot_name
        self.logos = LogoStore(data_dir)

    # ---------------------------------------------------------------- 查歌
    def song(self, song: SongInfo, server: str, consts: dict[Difficulty, dict[str, float]],
             jacket: Path | None, version_label: str = "", aliases: list[str] | None = None) -> bytes:
        W = 1180
        charts = [song.charts[k] for k in sorted(song.charts)]
        has_notes = any(c.notes for c in charts)
        H_notes = 150 + len(charts) * 76 + 10
        line_charts = [c for c in charts if c.difficulty >= Difficulty.EXPERT]
        H_lines = 120 + len(line_charts) * 62 + 20 if line_charts else 0
        src = aliases if aliases is not None else song.aliases
        alias = [a for a in dict.fromkeys(src) if a and a.lower() != song.title.lower()][:15]
        H_alias = 110 + ((len(alias) + 4) // 5) * 62 if alias else 0
        H = 200 + 400 + 30 + H_notes + 30 + (H_lines + 30 if H_lines else 0) + (H_alias + 30 if H_alias else 0) + 110
        im = K.background(self.assets, "", W, H, seed=song.id, palette="chu")
        d = ImageDraw.Draw(im)
        K.pill(d, 44, 60, "CHUNITHM", size=34, fg=(40, 120, 220))
        K.pill(d, W - 230, 70, "谱面详情", size=28, fg=(255, 255, 255), bg=(60, 110, 190, 210))
        y = 200
        K.panel(im, (40, y, W - 40, y + 400))
        K.shadow(im, (70, y + 50, 370, y + 350), 26, offset=8, blur=10, alpha=90)
        K.paste_rounded(im, _jacket(jacket, song.title, 300), (70, y + 50), 26)
        x = 410
        px = x
        if song.genre:
            px = K.pill(d, px, y + 40, song.genre, size=22, h=44, bold=False) + 10
        lg = self.logos.fit(song.version, 230, 104) if song.version else None
        if lg is not None:
            im.alpha_composite(lg, (W - 66 - lg.width, y + 22))
        elif song.version:
            K.pill(d, px, y + 40, song.version, size=22, h=44, fg=(40, 120, 220))
        title_w = W - 90 - x - (lg.width + 20 if lg is not None else 0)
        F.draw_text(d, (x, y + 104), F.fit(song.title, "bold", 52, title_w), "bold", 52, K.INK)
        F.draw_text(d, (x, y + 176), F.fit(song.artist, "regular", 28, W - 90 - x), "regular", 28, K.SUB)
        d.line((x, y + 236, W - 90, y + 236), fill=(255, 255, 255, 230), width=3)
        rel = (song.release_date or "")[:10].replace("-", "/")
        sx = x
        for k, v in (("SONG ID", str(song.id)), ("BPM", f"{song.bpm:g}" if song.bpm else "-"), ("上线日期", rel or "-")):
            F.draw_text(d, (sx, y + 262), k, "regular", 20, K.SUB)
            end = F.draw_text(d, (sx, y + 292), v, "latin", 32, K.INK)
            sx = max(sx + 150, end + 56)
        avail = [SERVER_NAMES[s] for s in ("jp", "intl", "cn")
                 if (s == "intl" and song.intl) or any(s in consts.get(c.difficulty, {}) for c in charts)]
        ax = x
        for a in avail:
            ax = K.pill(d, ax, y + 344, a, size=18, h=32, pad=12, fg=K.ACCENT, bg=(255, 255, 255, 200)) + 8
        y += 430

        # ---- constants per server + notes ----
        K.panel(im, (40, y, W - 40, y + H_notes))
        multi_note = "" if any(len({round(v, 1) for v in consts.get(c.difficulty, {}).values()}) > 1 for c in charts) \
            else " · 各服相同"
        K.section_title(d, 70, y + 34, "定数", 34, f"当前显示 = {SERVER_NAMES[server]}{version_label}{multi_note}")
        hy = y + 96
        # one 定数 column unless some server really differs (missing on a server is not a difference)
        multi = any(len({round(v, 1) for v in consts.get(c.difficulty, {}).values()}) > 1 for c in charts)
        servers = ("intl", "jp", "cn") if multi else (server,)
        cols = {"diff": 76, "lv": 330, "intl": 470, "jp": 610, "cn": 750} if multi else \
            {"diff": 76, "lv": 330, server: 520}
        notes_x = 950 if multi else 830
        F.draw_text(d, (cols["diff"], hy), "难度", "regular", 22, K.SUB)
        _c(d, cols["lv"], hy, "等级", 22, K.SUB, "regular")
        for s in servers:
            _c(d, cols[s], hy, SERVER_NAMES[s] if multi else "定数", 22, K.ACCENT if s == server else K.SUB,
               "bold" if s == server else "regular")
        if has_notes:
            _c(d, notes_x, hy, "物量 / 谱师", 22, K.SUB, "regular")
        ry = hy + 44
        any_diff = False
        for c in charts:
            col, _ = DIFF.get(c.difficulty, ((60, 60, 60), ""))
            d.rounded_rectangle((60, ry, W - 60, ry + 66), 18, fill=(255, 255, 255, 140))
            d.rounded_rectangle((60, ry + 10, 66, ry + 56), 3, fill=col)
            _diff_label(d, cols["diff"], ry + 14, c.difficulty, 30)
            _c(d, cols["lv"], ry + 16, c.level, 30, K.INK, "latin")
            vals = consts.get(c.difficulty, {})
            shown = vals.get(server)
            for s in servers:
                v = vals.get(s)
                txt = f"{v:.1f}" if v is not None else "-"
                differs = v is not None and shown is not None and round(v, 1) != round(shown, 1)
                any_diff |= differs
                _c(d, cols[s], ry + 14, txt, 34 if s == server else 28,
                   col if s == server else ((230, 80, 60) if differs else K.SUB), "latin")
            if has_notes:
                tot = c.notes.get("total") or sum(v for v in c.notes.values() if isinstance(v, int))
                info = f"{tot or '-'} · {c.charter or '-'}"
                _c(d, notes_x, ry + 20, F.fit(info, "regular", 22, 300), 22, K.INK, "regular")
            ry += 76
        if any_diff:
            F.draw_text(d, (W - 60 - F.text_width("红字 = 和当前服不同", "regular", 18), y + 44),
                        "红字 = 和当前服不同", "regular", 18, (230, 80, 60))
        y += H_notes + 30

        # ---- score lines ----
        if line_charts:
            K.panel(im, (40, y, W - 40, y + H_lines))
            K.section_title(d, 70, y + 34, "分数线", 34, "分数对应的单曲 rating")
            lx0, lstep = 330, (W - 80 - 330) / len(LINES)
            hy = y + 96
            for i, (lab, _, colr) in enumerate(LINES):
                _c(d, int(lx0 + lstep * i + lstep / 2), hy - 2, lab, 26, colr, "latin")
            ry = hy + 42
            for c in line_charts:
                d.rounded_rectangle((60, ry, W - 60, ry + 52), 16, fill=(255, 255, 255, 140))
                _diff_label(d, 76, ry + 8, c.difficulty, 28)
                ds = consts.get(c.difficulty, {}).get(server)
                for i, (_, sc, _) in enumerate(LINES):
                    v = f"{song_rating(sc, ds):.2f}" if ds else "-"
                    _c(d, int(lx0 + lstep * i + lstep / 2), ry + 12, v, 24, K.INK, "latin")
                ry += 62
            y += H_lines + 30

        if alias:
            K.panel(im, (40, y, W - 40, y + H_alias))
            K.section_title(d, 70, y + 34, "别名", 34)
            ry, px = y + 96, 76
            for a in alias:
                if px + K.pill_width(a, 24, dot=True) > W - 70:
                    ry, px = ry + 62, 76
                px = K.pill(d, px, ry, a, size=24, h=48, dot=(90, 150, 255)) + 14
        K.footer(im, self.bot_name, credit=CREDIT)
        return K.to_png(im)

    # ---------------------------------------------------------------- 定数查歌
    def ds_list(self, entries, server: str, title: str, sub: str, jackets: dict) -> bytes:
        """entries: [(song, chart, shown_const, {server: const})]"""
        W = 1280
        cw, ch, gap = (W - 80 - 30) // 2, 270, 30
        H = 200 + ((len(entries) + 1) // 2) * (ch + gap) + 120
        im = K.background(self.assets, "", W, H, seed=len(entries), palette="chu")
        d = ImageDraw.Draw(im)
        self._title(im, d, W, title, sub)
        for i, (song, chart, shown, others) in enumerate(entries):
            x, y = 40 + (i % 2) * (cw + gap), 200 + (i // 2) * (ch + gap)
            K.panel(im, (x, y, x + cw, y + ch), r=26)
            K.paste_rounded(im, _jacket(jackets.get(song.id), song.title, 120), (x + 24, y + 24), 16)
            tx = x + 168
            F.draw_text(d, (tx, y + 26), F.fit(song.title, "bold", 32, cw - 190), "bold", 32, K.INK)
            F.draw_text(d, (tx, y + 72), F.fit(song.artist, "regular", 22, cw - 190), "regular", 22, K.SUB)
            ex = K.pill(d, tx, y + 108, str(song.id), size=18, h=32, pad=12, fg=(60, 110, 190), bold=False)
            if (lg := self.logos.fit(song.version, 130, 46)) is not None:
                im.alpha_composite(lg, (ex + 12, y + 101 + (46 - lg.height) // 2))
            diffs = [song.charts[k] for k in sorted(song.charts)]
            px, pw = x + 24, (cw - 48 - 40) // 5
            for c in diffs[:5]:
                col, _ = DIFF.get(c.difficulty, ((60, 60, 60), ""))
                hit = c is chart
                v = shown if hit else c.const
                box = (px, y + 162, px + pw, y + 208)
                if hit:
                    d.rounded_rectangle(box, 14, fill=col + (255,))
                else:
                    d.rounded_rectangle(box, 14, fill=(255, 255, 255, 190), outline=col, width=3)
                _c(d, px + pw // 2, y + 170, f"{v:.1f}" if v else c.level, 26, (255, 255, 255) if hit else col, "latin")
                px += pw + 10
            diff_txt = [f"{SERVER_SHORT[s]}服 {v:.1f}" for s, v in others.items()
                        if s != server and round(v, 1) != round(shown, 1)]
            F.draw_text(d, (x + 24, y + 226), F.fit(song.genre or "", "regular", 20, cw - 300), "regular", 20, K.SUB)
            if diff_txt:
                note = "其他服：" + " / ".join(diff_txt)
                F.draw_text(d, (x + cw - 24 - F.text_width(note, "bold", 18), y + 228), note, "bold", 18,
                            (230, 80, 60))
        K.footer(im, self.bot_name, credit=CREDIT)
        return K.to_png(im)

    # ---------------------------------------------------------------- 定数表
    def ds_table(self, entries, server: str, title: str, sub: str, jackets: dict) -> bytes:
        W, tile, gx, gy, x0 = 1600, 104, 14, 52, 170
        groups: dict[float, list] = {}
        for e in entries:
            groups.setdefault(round(e[2], 1), []).append(e)
        per_row = (W - 60 - x0 + gx) // (tile + gx)
        heights = {k: max(150, 34 + ((len(v) + per_row - 1) // per_row) * (tile + gy) + 6) for k, v in groups.items()}
        H = 200 + sum(h + 24 for h in heights.values()) + 110
        im = K.background(self.assets, "", W, H, seed=len(entries), palette="chu")
        d = ImageDraw.Draw(im)
        any_diff = any(any(s != server and round(v, 1) != round(e[2], 1) for s, v in e[3].items()) for e in entries)
        self._title(im, d, W, title, sub + ("　·　红标 = 其他服定数不同" if any_diff else ""))
        y = 200
        for ds in sorted(groups, reverse=True):
            lst = sorted(groups[ds], key=lambda e: (e[1].difficulty, e[0].id))
            hh = heights[ds]
            K.panel(im, (30, y, W - 30, y + hh), r=26, glow=False)
            d.rounded_rectangle((52, y + 30, 150, y + 100), 20, fill=(255, 255, 255, 230))
            F.draw_text(d, (68, y + 34), "LV", "regular", 16, K.SUB)
            _c(d, 101, y + 52, f"{ds:.1f}", 32, (40, 120, 220), "latin")
            F.draw_text(d, (60, y + 110), f"{len(lst)} 张", "regular", 18, K.SUB)
            for i, (song, chart, shown, others) in enumerate(lst):
                tx = x0 + (i % per_row) * (tile + gx)
                ty = y + 30 + (i // per_row) * (tile + gy)
                col, _ = DIFF.get(chart.difficulty, ((60, 60, 60), ""))
                d.rounded_rectangle((tx - 4, ty - 4, tx + tile + 4, ty + tile + 4), 14, fill=col)
                K.paste_rounded(im, _jacket(jackets.get(song.id), song.title, tile), (tx, ty), 10)
                od = [(s, v) for s, v in others.items() if s != server and round(v, 1) != round(shown, 1)]
                if od:
                    lab = " ".join(f"{SERVER_SHORT[s]}{v:.1f}" for s, v in od[:2])
                    lw = F.text_width(lab, "bold", 13) + 10
                    d.rounded_rectangle((tx + 2, ty + 2, tx + 2 + lw, ty + 20), 7, fill=(235, 70, 60, 230))
                    F.draw_text(d, (tx + 7, ty + 3), lab, "bold", 13, (255, 255, 255))
                idt = str(song.id)
                d.rounded_rectangle((tx + 4, ty + tile - 24, tx + 14 + F.text_width(idt, "latin", 15), ty + tile - 4),
                                    8, fill=(40, 30, 70, 190))
                F.draw_text(d, (tx + 9, ty + tile - 23), idt, "latin", 15, (255, 255, 255))
                _c(d, tx + tile // 2, ty + tile + 8, F.fit(song.title, "regular", 15, tile + 8), 15, K.INK, "regular")
            y += hh + 24
        K.footer(im, self.bot_name, credit=CREDIT)
        return K.to_png(im)

    def _title(self, im, d, W, title, sub):
        K.panel(im, (30, 40, W - 30, 160), r=34)
        d.rounded_rectangle((60, 62, 136, 138), 22, fill=(60, 140, 240))
        d.ellipse((80, 78, 108, 106), outline=(255, 255, 255), width=5)
        d.line((104, 102, 118, 118), fill=(255, 255, 255), width=6)
        F.draw_text(d, (160, 58), title, "bold", 40, K.INK)
        F.draw_text(d, (160, 112), sub, "regular", 22, K.SUB)
        K.pill(d, W - 260, 78, "CHUNITHM", size=30, fg=(40, 120, 220))
