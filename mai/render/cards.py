"""Info-card images: 查歌 (song detail), 定数查歌 (card list) and 定数表 (jacket grid).

Layout follows the 该隐/McMai cards the user pointed at: pastel CiRCLE background, frosted panels,
jacket + metadata header, note table, designer + score lines, constant history, aliases.
"""
from __future__ import annotations

from collections import OrderedDict

from PIL import Image, ImageDraw

from ..calc.rating import chart_rating
from ..consts import REGION_NAMES
from ..data.songdb import Chart, Song, SongDB
from . import fonts as F
from . import kit as K
from .b50img import AssetStore, share_versions

NOTE_KEYS = ("total", "tap", "hold", "slide", "touch", "break")
NOTE_HEAD = {"total": "TOTAL", "tap": "TAP", "hold": "HOLD", "slide": "SLIDE", "touch": "TOUCH",
             "break": "BREAK"}
LINES = (("SSS+", 1005000, (255, 120, 190)), ("SSS", 1000000, (255, 150, 60)), ("SS+", 995000, (240, 170, 40)),
         ("SS", 990000, (230, 160, 40)), ("S+", 980000, (240, 190, 60)), ("S", 970000, (240, 190, 60)))
DIFF_ORDER = ("basic", "advanced", "expert", "master", "remaster", "utage")
REGION_SHORT = {"jp": "日", "intl": "国际", "usa": "美", "cn": "国"}


SERVER_SHORT = {"intl": "国际", "jp": "日", "cn": "国"}


def other_ds(c: Chart, db: SongDB, region: str) -> list[tuple[str, float]]:
    """Servers (where the chart exists) whose current constant differs from the one shown."""
    base = c.ds_in(region, db.current_version.get(region))
    out = []
    for r in ("intl", "jp", "cn"):
        if r == region or not c.available(r):
            continue
        v = c.ds_in(r, db.current_version.get(r))
        if v is not None and base is not None and round(v, 1) != round(base, 1):
            out.append((r, v))
    return out


def _ds_text(c: Chart, region: str, db: SongDB) -> str:
    ds = c.ds_in(region, db.current_version.get(region))
    return f"{ds:.1f}" if ds is not None else "?"


def fmt_date(s: str) -> str:
    """2022-10-21 / 20221021 / 2022-10-21T.. → 2022/10/21"""
    s = (s or "").strip()[:10]
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}/{digits[4:6]}/{digits[6:]}"
    return s.replace("-", "/") or "-"


class CardRenderer:
    def __init__(self, data_dir: str, bot_name: str = "AstrBot"):
        self.assets = AssetStore(data_dir)
        self.bot_name = bot_name

    # ------------------------------------------------------------------ 查歌
    def song(self, song: Song, db: SongDB, region: str) -> bytes:
        share_versions(db)
        A, W = self.assets, 1180
        rv = db.current_version.get(region, "")
        charts = [c for c in song.charts if c.type != "utage" or True]
        charts.sort(key=lambda c: (0 if c.type == "dx" else 1 if c.type == "std" else 2, DIFF_ORDER.index(c.diff)
                                   if c.diff in DIFF_ORDER else 9))
        types = list(OrderedDict.fromkeys(c.type for c in charts))
        A.prefetch([song.image])

        # ---- measure ----
        note_rows = len(charts) + (len(types) - 1)
        line_charts = [c for c in charts if c.diff in ("expert", "master", "remaster") and c.type != "utage"]
        hist = [c for c in charts if c.diff in ("master", "remaster") and len(set(c.multiver.values())) > 1]
        H = 210 + 400 + 30
        H_notes = 150 + note_rows * 76 + (len(types) - 1) * 10 + 10
        H_lines = (120 + len(line_charts) * 62 + 20) if line_charts else 0
        H_hist = (110 + len(hist) * 64) if hist else 0
        alias = [a for a in dict.fromkeys(song.aliases) if a and a.lower() != song.title.lower()][:16]
        alias_rows = self._pill_rows(alias, W - 140, 26) if alias else []
        H_alias = (110 + len(alias_rows) * 62) if alias else 0
        H += sum(x + 30 for x in (H_notes, H_lines, H_hist, H_alias) if x) + 110
        im = K.background(A, rv, W, H, seed=hash(song.id) & 0xffff)
        d = ImageDraw.Draw(im)

        # ---- top bar ----
        lg = K.logo(A, rv, 340, 130)
        if lg:
            im.alpha_composite(lg, (40, 30))
        else:
            K.pill(d, 44, 60, f"maimai DX · {K.short_version(rv)}", size=30, fg=K.ACCENT)
        K.pill(d, W - 230, 70, "谱面详情", size=28, fg=(255, 255, 255), bg=(110, 90, 170, 200))
        y = 200

        # ---- header panel ----
        K.panel(im, (40, y, W - 40, y + 400))
        cv = A.cover(song.image, song.title, 300, next(iter(sorted(song.music_ids())), None))
        K.shadow(im, (70, y + 50, 370, y + 350), 26, offset=8, blur=10, alpha=90)
        K.paste_rounded(im, cv, (70, y + 50), 26)
        x = 410
        bx = x
        for t in types:
            if t == "utage":
                continue
            b = K.type_badge(A, t, 36)
            im.alpha_composite(b, (bx, y + 44))
            bx += b.width + 12
        if song.category:
            K.pill(d, bx + 6, y + 40, song.category, size=22, h=44, bold=False)
        F.draw_text(d, (x, y + 104), F.fit(song.title, "bold", 52, W - 90 - x), "bold", 52, K.INK)
        F.draw_text(d, (x, y + 176), F.fit(song.artist, "regular", 28, W - 90 - x), "regular", 28, K.SUB)
        d.line((x, y + 236, W - 90, y + 236), fill=(255, 255, 255, 230), width=3)
        ids = "/".join(str(i) for i in sorted(song.music_ids())) or "-"
        release = min((c.release for c in charts if c.release), default="")
        stats = [("SONG ID", ids), ("BPM", f"{song.bpm:g}" if song.bpm else "-"),
                 ("上线日期", fmt_date(release))]
        sx = x
        for k, v in stats:
            F.draw_text(d, (sx, y + 262), k, "regular", 20, K.SUB)
            end = F.draw_text(d, (sx, y + 292), v, "latin", 32, K.INK)
            sx = max(sx + 150, end + 56)
        vb = K.version_badge(A, song.version, 92)
        im.alpha_composite(vb, (W - 70 - vb.width, y + 24))
        avail = [REGION_SHORT[r] for r in ("jp", "intl", "cn") if any(c.available(r) for c in charts)]
        ax = x
        for a in avail:
            ax = K.pill(d, ax, y + 344, a + "服", size=18, h=32, pad=12, fg=K.ACCENT,
                        bg=(255, 255, 255, 200)) + 8
        y += 430

        # ---- note table ----
        K.panel(im, (40, y, W - 40, y + H_notes))
        K.section_title(d, 70, y + 34, "Note 分布", 34, f"定数 = {REGION_NAMES.get(region, region)} {K.short_version(rv)}")
        cols = {"diff": 76, "ds": 330, "total": 470}
        step = (W - 110 - 590) / 5
        for i, k in enumerate(NOTE_KEYS[1:]):
            cols[k] = int(590 + step * i + step / 2)
        hy = y + 96
        F.draw_text(d, (cols["diff"], hy), "难度", "regular", 22, K.SUB)
        self._center(d, cols["ds"], hy, "定数", 22, K.SUB)
        for k in NOTE_KEYS:
            ic = A.icon("note_" + k) if k != "total" else None
            if ic is not None:
                ic = ic.copy()
                ic.thumbnail((54, 54), Image.LANCZOS)
                im.alpha_composite(ic, (cols[k] - ic.width // 2, hy - 16))
            else:
                self._center(d, cols[k], hy, NOTE_HEAD[k], 22, K.SUB)
        ry = hy + 44
        last_t = None
        any_diff = False
        for c in charts:
            if last_t is not None and c.type != last_t:
                ry += 10
            last_t = c.type
            d.rounded_rectangle((60, ry, W - 60, ry + 66), 18, fill=(255, 255, 255, 140))
            dc = K.DIFF_COLORS.get(c.diff, K.INK)
            d.rounded_rectangle((60, ry + 10, 66, ry + 56), 3, fill=dc)
            end = K.diff_label(d, cols["diff"], ry + 6, c.diff, 30)
            if len(types) > 1 and c.type != "utage":
                tb = K.type_badge(A, c.type, 22)
                im.alpha_composite(tb, (end + 10, ry + 12))
            F.draw_text(d, (cols["diff"], ry + 40), f"Lv {c.level_in(region)}", "regular", 18, K.SUB)
            od = other_ds(c, db, region)
            self._center(d, cols["ds"], ry + (4 if od else 14), _ds_text(c, region, db), 34 if not od else 30,
                         K.DIFF_TEXT.get(c.diff, dc), kind="latin")
            if od:
                txt = " ".join(f"{SERVER_SHORT[r]}{v:.1f}" for r, v in od)
                self._center(d, cols["ds"], ry + 42, txt, 17, (230, 80, 60))
                any_diff = True
            for k in NOTE_KEYS:
                v = c.notes.get(k)
                self._center(d, cols[k], ry + 18, "-" if v is None else str(v), 28 if k == "total" else 26,
                             K.INK, kind="latin")
            ry += 76
        if any_diff:
            F.draw_text(d, (W - 60 - F.text_width("红字 = 其他服的定数不同", "regular", 18), y + 44),
                        "红字 = 其他服的定数不同", "regular", 18, (230, 80, 60))
        y += H_notes + 30

        # ---- designer + score lines ----
        if line_charts:
            K.panel(im, (40, y, W - 40, y + H_lines))
            K.section_title(d, 70, y + 34, "谱师 与 分数线", 34, "达成率对应的单曲 rating")
            lx0 = 640
            lstep = (W - 80 - lx0) / len(LINES)
            hy = y + 96
            F.draw_text(d, (76, hy), "难度", "regular", 22, K.SUB)
            F.draw_text(d, (300, hy), "谱师", "regular", 22, K.SUB)
            for i, (lab, _, col) in enumerate(LINES):
                self._center(d, int(lx0 + lstep * i + lstep / 2), hy - 2, lab, 26, col, kind="latin", stroke=2)
            ry = hy + 42
            for c in line_charts:
                d.rounded_rectangle((60, ry, W - 60, ry + 52), 16, fill=(255, 255, 255, 140))
                end = K.diff_label(d, 76, ry + 8, c.diff, 28)
                if len(types) > 1:
                    im.alpha_composite(K.type_badge(A, c.type, 20), (end + 8, ry + 14))
                F.draw_text(d, (300, ry + 12), F.fit(c.designer or "-", "regular", 24, lx0 - 320), "regular", 24,
                            K.INK)
                ds = c.ds_in(region, rv)
                for i, (_, ach, _) in enumerate(LINES):
                    v = chart_rating(ds, ach) if ds else "-"
                    self._center(d, int(lx0 + lstep * i + lstep / 2), ry + 12, str(v), 26, K.INK, kind="latin")
                ry += 62
            y += H_lines + 30

        # ---- constant history ----
        if hist:
            K.panel(im, (40, y, W - 40, y + H_hist))
            K.section_title(d, 70, y + 34, "定数变化", 34, "按版本")
            ry = y + 96
            for c in hist:
                end = K.diff_label(d, 76, ry + 4, c.diff, 26)
                if len(types) > 1:
                    im.alpha_composite(K.type_badge(A, c.type, 20), (end + 8, ry + 8))
                px = 300
                prev = None
                for v in sorted(c.multiver, key=db.version_index):
                    val = c.multiver[v]
                    if prev is not None and val == prev:
                        continue
                    txt = f"{K.short_version(v)} {val:.1f}"
                    up = prev is not None and val > prev
                    if px + K.pill_width(txt, 20) > W - 80:
                        break
                    px = K.pill(d, px, ry, txt, size=20, h=40,
                                fg=(220, 60, 90) if up else (60, 120, 220) if prev is not None else K.INK) + 10
                    prev = val
                ry += 64
            y += H_hist + 30

        # ---- aliases ----
        if alias:
            K.panel(im, (40, y, W - 40, y + H_alias))
            K.section_title(d, 70, y + 34, "别名", 34)
            ry = y + 96
            for row in alias_rows:
                px = 76
                for a in row:
                    px = K.pill(d, px, ry, a, size=24, h=48, dot=(90, 150, 255)) + 14
                ry += 62
            y += H_alias + 30

        K.footer(im, self.bot_name)
        return K.to_png(im)

    # ------------------------------------------------------------------ 定数查歌（卡片列表）
    def ds_list(self, charts: list[Chart], db: SongDB, region: str, title: str, sub: str) -> bytes:
        share_versions(db)
        A, W = self.assets, 1280
        rv = db.current_version.get(region, "")
        A.prefetch([c.song.image for c in charts])
        cw, ch, gap = (W - 80 - 30) // 2, 300, 30
        rows = (len(charts) + 1) // 2
        H = 200 + rows * (ch + gap) + 120
        im = K.background(A, rv, W, H, seed=len(charts))
        d = ImageDraw.Draw(im)
        self._title_bar(im, d, W, title, sub, rv)
        for i, c in enumerate(charts):
            x = 40 + (i % 2) * (cw + gap)
            y = 200 + (i // 2) * (ch + gap)
            self._chart_card(im, d, x, y, cw, ch, c, db, region)
        K.footer(im, self.bot_name)
        return K.to_png(im)

    def _chart_card(self, im, d, x, y, w, h, c: Chart, db: SongDB, region: str):
        A = self.assets
        db.current_version.get(region, "")
        K.panel(im, (x, y, x + w, y + h), r=26)
        cv = A.cover(c.song.image, c.song.title, 120, c.music_id)
        K.paste_rounded(im, cv, (x + 24, y + 24), 16)
        tb = K.type_badge(A, c.type, 26)
        im.alpha_composite(tb, (x + 24 + 60 - tb.width // 2, y + 128))
        tx = x + 168
        F.draw_text(d, (tx, y + 26), F.fit(c.song.title, "bold", 32, w - 190), "bold", 32, K.INK)
        F.draw_text(d, (tx, y + 72), F.fit(c.song.artist, "regular", 22, w - 190), "regular", 22, K.SUB)
        K.pill(d, tx, y + 108, str(c.music_id or "-"), size=18, h=32, pad=12, fg=(120, 110, 200),
               bg=(255, 255, 255, 200), bold=False)
        # one pill per difficulty of this type, the matched one filled
        same = [s for s in c.song.charts if s.type == c.type]
        same.sort(key=lambda s: DIFF_ORDER.index(s.diff) if s.diff in DIFF_ORDER else 9)
        px, py = x + 24, y + 172
        pw = (w - 48 - 10 * 4) // 5
        for s in same[:5]:
            col = K.DIFF_COLORS.get(s.diff, K.INK)
            hit = s is c
            box = (px, py, px + pw, py + 46)
            if hit:
                d.rounded_rectangle(box, 14, fill=(180, 110, 245, 255) if s.diff == "remaster" else col + (255,))
                fg = (255, 255, 255)
            else:
                d.rounded_rectangle(box, 14, fill=(255, 255, 255, 190), outline=col, width=3)
                fg = K.DIFF_TEXT.get(s.diff, col)
            self._center(d, px + pw // 2, py + 8, _ds_text(s, region, db), 26, fg, kind="latin")
            px += pw + 10
        od = other_ds(c, db, region)
        if od:
            note = "其他服：" + " / ".join(f"{SERVER_SHORT[r]}服 {v:.1f}" for r, v in od)
            F.draw_text(d, (x + w - 24 - F.text_width(note, "bold", 18), y + 112), note, "bold", 18, (230, 80, 60))
        d.line((x + 24, y + 236, x + w - 24, y + 236), fill=(255, 255, 255, 220), width=2)
        F.draw_text(d, (x + 24, y + 246), "BPM", "regular", 16, K.SUB)
        F.draw_text(d, (x + 24, y + 264), f"{c.song.bpm:g}" if c.song.bpm else "-", "latin", 24, K.INK)
        F.draw_text(d, (x + 110, y + 246), "分类", "regular", 16, K.SUB)
        F.draw_text(d, (x + 110, y + 264), F.fit(c.song.category, "regular", 22, w - 380), "regular", 22, K.INK)
        vb = K.version_badge(A, c.version_in(region), 44)
        im.alpha_composite(vb, (x + w - 24 - vb.width, y + 244))

    # ------------------------------------------------------------------ 定数表（曲绘网格）
    def ds_table(self, charts: list[Chart], db: SongDB, region: str, title: str, sub: str) -> bytes:
        share_versions(db)
        A, W = self.assets, 1600
        rv = db.current_version.get(region, "")
        groups: dict[float, list[Chart]] = {}
        for c in charts:
            groups.setdefault(round(c.ds_in(region, rv) or 0, 1), []).append(c)
        A.prefetch([c.song.image for c in charts])
        tile, gx, gy = 104, 14, 52
        x0 = 170
        per_row = (W - 60 - x0 + gx) // (tile + gx)
        H = 200
        heights = {}
        for ds, lst in groups.items():
            rows = (len(lst) + per_row - 1) // per_row
            heights[ds] = max(150, 34 + rows * (tile + gy) + 6)
            H += heights[ds] + 24
        H += 110
        im = K.background(A, rv, W, H, seed=int(sum(groups) * 10))
        d = ImageDraw.Draw(im)
        diff_seen = any(other_ds(c, db, region) for c in charts)
        self._title_bar(im, d, W, title, sub + ("　·　红标 = 其他服定数不同" if diff_seen else ""), rv)
        y = 200
        for ds in sorted(groups, reverse=True):
            lst = sorted(groups[ds], key=lambda c: (DIFF_ORDER.index(c.diff) if c.diff in DIFF_ORDER else 9,
                                                    c.music_id or 0))
            hh = heights[ds]
            K.panel(im, (30, y, W - 30, y + hh), r=26, glow=False)
            d.rounded_rectangle((52, y + 30, 150, y + 100), 20, fill=(255, 255, 255, 230))
            F.draw_text(d, (68, y + 34), "LV", "regular", 16, K.SUB)
            self._center(d, 101, y + 52, f"{ds:.1f}", 32, K.ACCENT, kind="latin")
            F.draw_text(d, (60, y + 110), f"{len(lst)} 张", "regular", 18, K.SUB)
            for i, c in enumerate(lst):
                tx = x0 + (i % per_row) * (tile + gx)
                ty = y + 30 + (i // per_row) * (tile + gy)
                col = K.DIFF_COLORS.get(c.diff, K.INK)
                d.rounded_rectangle((tx - 4, ty - 4, tx + tile + 4, ty + tile + 4), 14, fill=col)
                K.paste_rounded(im, A.cover(c.song.image, c.song.title, tile, c.music_id), (tx, ty), 10)
                if c.type == "dx":
                    tb = K.type_badge(A, "dx", 18)
                    if tb.width > tile - 8:
                        tb.thumbnail((tile - 8, 18), Image.LANCZOS)
                    im.alpha_composite(tb, (tx + tile - tb.width - 3, ty + 3))
                od = other_ds(c, db, region)
                if od:
                    lab = " ".join(f"{SERVER_SHORT[r]}{v:.1f}" for r, v in od[:2])
                    lw = F.text_width(lab, "bold", 13) + 10
                    d.rounded_rectangle((tx + 2, ty + 2, tx + 2 + lw, ty + 20), 7, fill=(235, 70, 60, 230))
                    F.draw_text(d, (tx + 7, ty + 3), lab, "bold", 13, (255, 255, 255))
                    diff_seen = True
                idt = str(c.music_id or "")
                d.rounded_rectangle((tx + 4, ty + tile - 24, tx + 14 + F.text_width(idt, "latin", 15), ty + tile - 4),
                                    8, fill=(40, 30, 70, 190))
                F.draw_text(d, (tx + 9, ty + tile - 23), idt, "latin", 15, (255, 255, 255))
                self._center(d, tx + tile // 2, ty + tile + 8, F.fit(c.song.title, "regular", 15, tile + 8), 15,
                             K.INK)
            y += hh + 24
        K.footer(im, self.bot_name)
        return K.to_png(im)

    # ------------------------------------------------------------------ helpers
    def _title_bar(self, im, d, W, title, sub, version=""):
        K.panel(im, (30, 40, W - 30, 160), r=34)
        d.rounded_rectangle((60, 62, 136, 138), 22, fill=(130, 100, 255))
        d.ellipse((80, 78, 108, 106), outline=(255, 255, 255), width=5)
        d.line((104, 102, 118, 118), fill=(255, 255, 255), width=6)
        F.draw_text(d, (160, 58), title, "bold", 40, K.INK)
        F.draw_text(d, (160, 112), sub, "regular", 22, K.SUB)
        lg = K.logo(self.assets, version, 220, 90)
        if lg:
            im.alpha_composite(lg, (W - 60 - lg.width, 100 - lg.height // 2))

    @staticmethod
    def _center(d, cx, y, text, size, fill, kind="bold", stroke=0):
        tw = F.text_width(text, kind, size)
        F.draw_text(d, (cx - tw / 2, y), text, kind, size, fill, stroke=stroke,
                    stroke_fill=(255, 255, 255) if stroke else None)

    @staticmethod
    def _pill_rows(items, max_w, size):
        rows, cur, w = [], [], 0
        for a in items:
            pw = K.pill_width(a, size, dot=True) + 14
            if cur and w + pw > max_w:
                rows.append(cur)
                cur, w = [], 0
            cur.append(a)
            w += pw
        if cur:
            rows.append(cur)
        return rows
