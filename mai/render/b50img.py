"""Best 50 image, layout A (portrait, modelled on the 该隐 bot): header + 35 old + 15 new, 5 columns.

No SEGA artwork ships with the plugin. Optional assets are read from <data>/themes/:
  themes/<version>/bg.png, themes/<version>/logo.png   (falls back to themes/default/…)
  themes/icons/rank_<sssp|sss|…>.png, fc_<fc|fcp|ap|app>.png, fs_<sync|fs|fsp|fsd|fsdp>.png
  themes/fonts/{bold,regular,latin}.{ttf,otf,ttc}
Covers come from DXRating's CDN (cached under <data>/jackets/); missing ones get a placeholder.
"""
from __future__ import annotations

import colorsys
import hashlib
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFilter

from ..calc.rating import Best50
from ..consts import API_REGIONS, FLAG_LABEL, RANK_LABEL, REGION_NAMES, catalog_region, dx_stars, fmt_ach
from ..data.songdb import COVER_URL, SongDB
from ..models import Profile, Score
from . import fonts as F

W = 2200
SIDE = 38
CARD_W, CARD_H = 412, 228
GAP_X, GAP_Y = 16, 44
HEADER_H = 452               # 没有背景（frame）时的页头高；有背景时用 HEADER_H_FRAME
HEADER_H_FRAME = 596
BANNER_H = 110
FOOTER_H = 120

DIFF_COLORS = {
    "basic": ((66, 190, 92), (34, 140, 60)),
    "advanced": ((244, 186, 40), (214, 140, 10)),
    "expert": ((240, 84, 98), (196, 40, 66)),
    "master": ((164, 84, 226), (112, 44, 178)),
    "remaster": ((236, 222, 255), (196, 170, 240)),
    "utage": ((246, 104, 190), (200, 50, 150)),
}
RANK_COLORS = {
    "sssp": [(255, 214, 90), (255, 120, 190), (120, 200, 255)], "sss": [(255, 220, 90), (255, 160, 60)],
    "ssp": [(255, 226, 120), (240, 170, 50)], "ss": [(255, 226, 120), (240, 170, 50)],
    "sp": [(255, 190, 110), (240, 120, 50)], "s": [(255, 190, 110), (240, 120, 50)],
}
FC_COLORS = {"fc": (60, 190, 90), "fcp": (30, 160, 70), "ap": (255, 150, 40), "app": (255, 190, 30)}
FS_COLORS = {"sync": (110, 190, 240), "fs": (60, 130, 240), "fsp": (40, 100, 220),
             "fsd": (170, 90, 240), "fsdp": (130, 60, 220)}


def rom_short(rom: str | None) -> str:
    """'1.55.00' → '1.55'（私服玩家的客户端版本号）。"""
    import re
    m = re.match(r"^\s*(\d+\.\d{2})", rom or "")
    return m.group(1) if m else ""


def _version_short(v: str | None) -> str:
    if not v:
        return ""
    s = v.replace("maimaiでらっくす", "DX").replace(" PLUS", "+")
    return s


def _tier_color(r: int):
    for lim, c in ((1000, (210, 210, 210)), (2000, (70, 140, 230)), (4000, (80, 190, 90)),
                   (7000, (240, 200, 40)), (10000, (230, 70, 70)), (12000, (150, 80, 210)),
                   (13000, (180, 110, 60)), (14000, (170, 180, 195)), (14500, (232, 182, 40)),
                   (15000, (130, 210, 225))):
        if r < lim:
            return c
    return None  # rainbow


RATING_CELLS = (306, 575)   # x-range of the 5 digit cells on every UI_CMN_DXRating_NN sprite
RATING_CELLS_Y = (28, 100)


def draw_rating_plate(canvas: Image.Image, plate: Image.Image, rating: int, x: int, y: int, h: int) -> None:
    """Game DX RATING plate with one digit centred in each of its five cells."""
    s = h / plate.height
    pl = plate.resize((int(plate.width * s), h), Image.LANCZOS)
    canvas.alpha_composite(pl, (x, y))
    d = ImageDraw.Draw(canvas)
    x0, x1 = RATING_CELLS
    cw = (x1 - x0) / 5
    cy0, cy1 = RATING_CELLS_Y
    size = int((cy1 - cy0) * s * 0.78)
    digits = str(max(0, min(99999, int(rating)))).rjust(5)
    for i, ch in enumerate(digits):
        if ch == " ":
            continue
        cx = x + (x0 + cw * (i + 0.5)) * s
        tw = F.text_width(ch, "latin", size)
        top = y + (cy0 + cy1) / 2 * s - size * 0.62
        F.draw_text(d, (cx - tw / 2, top), ch, "latin", size, (255, 255, 255), stroke=2, stroke_fill=(40, 30, 60))


def _rating_tier(r: int) -> int:
    """UI_CMN_DXRating_NN plate for a rating (white … rainbow)."""
    tier = 1
    for i, lim in enumerate((1000, 2000, 4000, 7000, 10000, 12000, 13000, 14000, 14500, 15000, 16000), start=2):
        if r >= lim:
            tier = i
    return tier


def _gradient(w: int, h: int, stops, horizontal: bool = False) -> Image.Image:
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


def _rainbow(w: int, h: int) -> Image.Image:
    stops = [tuple(int(c * 255) for c in colorsys.hsv_to_rgb(i / 6, 0.55, 1.0)) for i in range(7)]
    return _gradient(w, h, stops, horizontal=True)


def _rounded_mask(w: int, h: int, r: int) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


def _paste_rounded(base: Image.Image, im: Image.Image, xy, r: int) -> None:
    im = im.convert("RGBA")
    mask = _rounded_mask(*im.size, r)
    if im.mode == "RGBA":
        alpha = im.split()[3]
        mask = Image.composite(alpha, Image.new("L", im.size, 0), mask)
    base.paste(im, xy, mask)


def _shadow(base: Image.Image, box, r: int, offset: int = 6, blur: int = 10, alpha: int = 90) -> None:
    x0, y0, x1, y1 = box
    pad = blur * 3
    sh = Image.new("RGBA", (x1 - x0 + pad * 2, y1 - y0 + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad, pad + x1 - x0, pad + y1 - y0), r, fill=(60, 20, 80, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(sh, (x0 - pad + offset // 2, y0 - pad + offset))


class AssetStore:
    # current 国际服 / 日服 versions, refreshed by the renderers: any page whose own version has no artwork
    # (国服 included) borrows theirs before falling back to themes/default/
    shared_versions: tuple[str, ...] = ()

    def __init__(self, data_dir: str):
        self.themes = os.path.join(data_dir, "themes")
        self.jackets = os.path.join(data_dir, "jackets")
        self.avatars = os.path.join(data_dir, "avatars")
        self.hdd_jackets = os.path.join(data_dir, "jackets_hdd")
        for d in (self.themes, self.jackets, self.avatars):
            os.makedirs(d, exist_ok=True)
        F.THEME_ROOT = self.themes
        self._icon_cache: dict[str, Image.Image | None] = {}
        self._miss: dict[str, float] = {}       # CDN 上没有的曲绘 / NET 图：12 小时内不再去取
        self.miss_ttl = 12 * 3600

    def _missed(self, key: str) -> bool:
        t = self._miss.get(key)
        return t is not None and time.time() - t < self.miss_ttl

    def theme_file(self, version: str, name: str, fallbacks: tuple[str, ...] = ()) -> str | None:
        """themes/<version>/<name>, then the other servers' current versions (国服 shares the 日服 / 国际服
        artwork — there are no separate 国服 themes), then themes/default/."""
        for v in dict.fromkeys((version, *fallbacks, *AssetStore.shared_versions, "default")):
            p = os.path.join(self.themes, v or "default", name)
            if os.path.exists(p):
                return p
        return None

    def icon(self, name: str) -> Image.Image | None:
        if name not in self._icon_cache:
            p = os.path.join(self.themes, "icons", name + ".png")
            self._icon_cache[name] = Image.open(p).convert("RGBA") if os.path.exists(p) else None
        return self._icon_cache[name]

    def version_logo(self, version: str) -> Image.Image | None:
        slug = (version or "").lower().replace("maimaiでらっくす", "deluxe").replace(" ", "_")
        return self.icon_path(os.path.join(self.themes, "logos", slug + ".png"))

    def icon_path(self, p: str) -> Image.Image | None:
        if p not in self._icon_cache:
            self._icon_cache[p] = Image.open(p).convert("RGBA") if os.path.exists(p) else None
        return self._icon_cache[p]

    # ---------- covers ----------
    def _cover_path(self, image: str) -> str:
        return os.path.join(self.jackets, f"{image}.jpg")

    def prefetch(self, images: list[str], timeout: float = 8.0) -> None:
        missing = [i for i in dict.fromkeys(images)
                   if i and not os.path.exists(self._cover_path(i)) and not self._missed("cover:" + i)]
        if not missing:
            return
        try:
            import httpx
        except Exception:  # pragma: no cover
            return

        def get(img: str) -> None:
            try:
                r = httpx.get(COVER_URL.format(image=img), timeout=timeout, follow_redirects=True,
                              headers={"User-Agent": "astrbot_plugin_otoge_prober"})
                if r.status_code == 200 and r.content[:3] in (b"\xff\xd8\xff", b"\x89PN", b"RIF"):
                    tmp = self._cover_path(img) + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(r.content)
                    os.replace(tmp, self._cover_path(img))
                elif r.status_code in (403, 404, 410):
                    self._miss["cover:" + img] = time.time()
            except Exception:
                pass

        with ThreadPoolExecutor(8) as ex:
            list(ex.map(get, missing))

    def cover(self, image: str | None, title: str, size: int, music_id: int | None = None) -> Image.Image:
        if music_id:
            p = os.path.join(self.hdd_jackets, f"{int(music_id) % 10000:06d}.png")
            if os.path.exists(p):
                try:
                    return Image.open(p).convert("RGB").resize((size, size), Image.LANCZOS)
                except Exception:
                    pass
        if image:
            p = self._cover_path(image)
            if os.path.exists(p):
                try:
                    return Image.open(p).convert("RGB").resize((size, size), Image.LANCZOS)
                except Exception:
                    pass
        return placeholder_cover(title, size)

    def avatar(self, url: str, size: int) -> Image.Image | None:
        """NET images (avatar / 段位 / class) cached by the service during sync; square-resized."""
        im = self.net_image(url)
        return im.resize((size, size), Image.LANCZOS) if im is not None else None

    def net_image(self, url: str) -> Image.Image | None:
        if not url:
            return None
        p = os.path.join(self.avatars, hashlib.sha1(url.encode()).hexdigest() + ".png")
        if not os.path.exists(p):
            if self._missed("net:" + url):
                return None
            try:  # direct fetch as a fallback (works when NET serves the image without a session)
                import httpx
                from ..net.client import ssl_context
                r = httpx.get(url, timeout=6, follow_redirects=True, verify=ssl_context())
                if r.status_code == 200 and r.content[:4] == b"\x89PNG":
                    tmp = p + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(r.content)
                    os.replace(tmp, p)
                else:
                    self._miss["net:" + url] = time.time()
                    return None
            except Exception:
                self._miss["net:" + url] = time.time()      # 取不到就别让每次出图都等 6 秒
                return None
        try:
            return Image.open(p).convert("RGBA")
        except Exception:
            return None


def song_of(db: SongDB, s) -> "object | None":
    """成绩对应的歌：先按游戏内 ID，没有就按 song_id，再按歌名 + 谱面。"""
    song = db.by_music_id(s.music_id) if s.music_id else None
    if song is None and getattr(s, "song_id", None):
        song = next((x for x in db.songs if x.id == s.song_id), None)
    if song is None and getattr(s, "title", ""):
        ch = db.find_chart(s.title, s.type, s.diff)
        song = ch.song if ch is not None else None
    return song


def fill_dx_max(b: Best50, db: SongDB) -> None:
    """水鱼 / 落雪 / 私服只给 DX 分不给满分：按谱面物量 ×3 补上，这样哪个服的图都能显示「DX 分/满分」和星。"""
    show = getattr(b, "show_dx", True)
    for s in b.old + b.new:
        s._show_dx = show                       # type: ignore[attr-defined]
        if s.dx_max or not s.dx:
            continue
        song = song_of(db, s)
        ch = song.chart(s.type, s.diff) if song is not None else None
        total = (ch.notes or {}).get("total") if ch is not None else None
        if total and s.dx <= total * 3:
            s.dx_max = int(total) * 3


def placeholder_cover(title: str, size: int) -> Image.Image:
    h = int(hashlib.md5(title.encode("utf-8")).hexdigest()[:6], 16)
    hue = (h % 360) / 360
    c0 = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.45, 0.95))
    c1 = tuple(int(c * 255) for c in colorsys.hsv_to_rgb((hue + 0.12) % 1, 0.65, 0.7))
    im = _gradient(size, size, [c0, c1]).convert("RGBA")
    d = ImageDraw.Draw(im)
    ch = (title.strip() or "?")[0]
    s = int(size * 0.5)
    tw = F.text_width(ch, "bold", s)
    F.draw_text(d, ((size - tw) // 2, int(size * 0.2)), ch, "bold", s, (255, 255, 255, 230))
    return im.convert("RGB")


# ---------------- badges ----------------
def _badge_text(w: int, h: int, label: str, stops, size: int) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    tw = F.text_width(label, "latin", size)
    F.draw_text(md, ((w - tw) // 2, (h - size) // 2 - 4), label, "latin", size, 255, stroke=1, stroke_fill=255)
    outline = mask.filter(ImageFilter.MaxFilter(7))
    im.paste((70, 30, 110, 255), (0, 0), outline)
    fill = _gradient(w, h, stops, horizontal=True).convert("RGBA")
    im.paste(fill, (0, 0), mask)
    return im


def rank_badge(assets: AssetStore, rank: str | None, w: int = 104, h: int = 46) -> Image.Image:
    rank = rank or "d"
    ic = assets.icon(f"rank_{rank}")
    if ic is not None:
        ic = ic.copy()
        ic.thumbnail((w, h), Image.LANCZOS)
        return ic
    stops = RANK_COLORS.get(rank, [(230, 230, 240), (180, 180, 200)])
    return _badge_text(w, h, RANK_LABEL.get(rank, rank.upper()), stops, 34 if len(RANK_LABEL.get(rank, "")) <= 3 else 30)


def flag_badge(assets: AssetStore, kind: str, flag: str | None, d: int = 46) -> Image.Image:
    if flag:
        ic = assets.icon(f"{kind}_{flag}")
        if ic is not None:
            ic = ic.copy()
            ic.thumbnail((d, d), Image.LANCZOS)
            return ic
    im = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    if not flag:
        dr.ellipse((3, 3, d - 4, d - 4), fill=(238, 232, 246, 255), outline=(214, 204, 230, 255), width=2)
        return im
    col = (FC_COLORS if kind == "fc" else FS_COLORS).get(flag, (200, 200, 200))
    if flag in ("app", "fsdp"):
        ring = _rainbow(d, d).convert("RGBA")
        m = Image.new("L", (d, d), 0)
        ImageDraw.Draw(m).ellipse((0, 0, d - 1, d - 1), fill=255)
        im.paste(ring, (0, 0), m)
        dr.ellipse((4, 4, d - 5, d - 5), fill=col)
    else:
        dr.ellipse((1, 1, d - 2, d - 2), fill=(255, 255, 255, 255))
        dr.ellipse((4, 4, d - 5, d - 5), fill=col)
    label = FLAG_LABEL[flag].replace("SYNC", "SYNC")
    size = 17 if len(label) <= 2 else (13 if len(label) <= 3 else 11)
    tw = F.text_width(label, "latin", size)
    F.draw_text(dr, ((d - tw) // 2, (d - size) // 2 - 3), label, "latin", size, (255, 255, 255),
                stroke=1, stroke_fill=tuple(max(0, c - 70) for c in col))
    return im


# ---------------- card ----------------
# 白色信息面板上的字色：按难度取一个深色（达成率、歌名都用它，在白底上够清楚）
DIFF_INK = {"basic": (22, 110, 52), "advanced": (166, 104, 0), "expert": (176, 30, 56), "master": (96, 36, 160),
            "remaster": (122, 82, 190), "utage": (176, 36, 130)}


def draw_card(canvas: Image.Image, x: int, y: int, s: Score, no: int, db: SongDB, assets: AssetStore,
              region: str) -> None:
    top, bottom = DIFF_COLORS.get(s.diff, DIFF_COLORS["master"])
    light = s.diff == "remaster"
    ink = DIFF_INK.get(s.diff, DIFF_INK["master"])
    soft = (126, 110, 146)
    left_ink = (96, 56, 160) if light else (255, 255, 255)
    _shadow(canvas, (x, y, x + CARD_W, y + CARD_H), 18)
    # No. tab
    tab = Image.new("RGBA", (100, 34), (0, 0, 0, 0))
    ImageDraw.Draw(tab).rounded_rectangle((0, 0, 99, 40), 10, fill=bottom if not light else (150, 110, 210))
    canvas.alpha_composite(tab, (x + CARD_W - 112, y - 28))
    F.draw_text(ImageDraw.Draw(canvas), (x + CARD_W - 62 - F.text_width(f"No.{no}", "latin", 20) // 2, y - 27),
                f"No.{no}", "latin", 20, (255, 255, 255))
    body = _gradient(CARD_W, CARD_H, [top, bottom]).convert("RGBA")
    bd = ImageDraw.Draw(body)
    # 右边的信息面板：白底深色字（原来是半透明面板上压白字，达成率看不清）
    bd.rounded_rectangle((156, 10, CARD_W - 10, CARD_H - 10), 14, fill=(255, 255, 255, 244))
    if light:
        bd.rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), 18, outline=(176, 150, 226), width=3)
    _paste_rounded(canvas, body, (x, y), 18)
    d = ImageDraw.Draw(canvas)
    # cover + id/type + version (left column)
    song = song_of(db, s)
    cov = assets.cover(song.image if song else None, s.title, 128, s.music_id)
    _paste_rounded(canvas, Image.new("RGBA", (136, 136), (255, 255, 255, 255)), (x + 12, y + 12), 12)
    _paste_rounded(canvas, cov, (x + 16, y + 16), 9)
    F.draw_text(d, (x + 14, y + 154), str(s.music_id or "-"), "latin", 20, left_ink)
    tic = assets.icon("type_dx" if s.type == "dx" else "type_std") if s.type != "utage" else None
    if tic is not None:
        ti = tic.resize((int(tic.width * 22 / tic.height), 22), Image.LANCZOS)
        canvas.alpha_composite(ti, (x + 146 - ti.width, y + 120))
    else:
        tag = "DX" if s.type == "dx" else ("宴" if s.type == "utage" else "SD")
        tag_col = (255, 140, 40) if s.type == "dx" else (60, 140, 230)
        d.rounded_rectangle((x + 98, y + 154, x + 148, y + 180), 8, fill=tag_col)
        F.draw_text(d, (x + 123 - F.text_width(tag, "latin", 19) // 2, y + 155), tag, "latin", 19, (255, 255, 255))
    v = _version_short(s.version)
    vlogo = assets.version_logo(s.version) if s.version else None
    if vlogo is not None:
        vl = vlogo.copy()
        vl.thumbnail((140, 36), Image.LANCZOS)
        canvas.alpha_composite(vl, (x + 82 - vl.width // 2, y + 186))
    elif v:
        v = F.fit(v, "latin", 17, 120)
        vw = F.text_width(v, "latin", 17) + 16
        d.rounded_rectangle((x + 12, y + 190, x + 12 + vw, y + 214), 8,
                            fill=(255, 255, 255, 210) if not light else (150, 110, 210))
        F.draw_text(d, (x + 20, y + 191), v, "latin", 17, bottom if not light else (255, 255, 255))
    # text column
    tx = x + 170
    right = x + CARD_W - 24
    tw_max = right - tx
    F.draw_text(d, (tx, y + 17), F.fit(s.title, "bold", 25, tw_max), "bold", 25, (52, 40, 70))
    ach = fmt_ach(s.ach)
    size = 44
    while size > 28 and F.text_width(ach, "latin", size) > tw_max:
        size -= 2
    F.draw_text(d, (tx, y + 52 + (44 - size) // 2), ach, "latin", size, ink)
    # 定数（难度色小牌）→ 单曲 rating（靠右、大一号）
    ds_txt = (f"{s.ds:.1f}" if s.ds is not None else "?") + ("" if s.ds_exact else "≈")
    cw = F.text_width(ds_txt, "latin", 22) + 20
    d.rounded_rectangle((tx, y + 110, tx + cw, y + 140), 15, fill=bottom if not light else (150, 110, 210))
    F.draw_text(d, (tx + 10, y + 111), ds_txt, "latin", 22, (255, 255, 255))
    F.draw_text(d, (right, y + 103), str(s.rating), "latin", 34, ink, anchor_right=True)
    rw = F.text_width(str(s.rating), "latin", 34)
    F.draw_text(d, (right - rw - 8, y + 116), "Ra", "latin", 17, soft, anchor_right=True)
    show_dx = getattr(s, "_show_dx", True)
    stars = dx_stars(s.dx, s.dx_max) if show_dx else 0
    d.line((tx, y + 149, right, y + 149), fill=(232, 224, 242), width=2)
    if s.dx_max and show_dx:
        F.draw_text(d, (tx, y + 153), f"DX {s.dx}/{s.dx_max}", "latin", 16, soft)
    sic = assets.icon("dxstar_3" if stars >= 5 else "dxstar_2" if stars >= 3 else "dxstar_1") if stars else None
    if stars and sic is not None:
        si = sic.resize((18, 18), Image.LANCZOS)
        for k in range(stars):
            canvas.alpha_composite(si, (right - (k + 1) * 16 - 2, y + 153))
    elif stars:
        star_col = (232, 170, 20) if stars >= 5 else ((240, 140, 40) if stars >= 3 else (60, 170, 90))
        F.draw_text(d, (right, y + 151), "✦" * stars, "symbol", 16, star_col, anchor_right=True)
    by = y + 174
    canvas.alpha_composite(rank_badge(assets, s.rank, 96, 42), (tx - 4, by))
    canvas.alpha_composite(flag_badge(assets, "fc", s.fc, 42), (tx + 102, by))
    canvas.alpha_composite(flag_badge(assets, "fs", s.fs, 42), (tx + 150, by))


# ---------------- page ----------------
def share_versions(db: SongDB | None) -> None:
    if db is not None:
        AssetStore.shared_versions = tuple(v for r in ("intl", "jp") if (v := db.current_version.get(r)))


def _fallbacks(db: SongDB, region: str) -> tuple[str, ...]:
    order = {"cn": ("intl", "jp"), "intl": ("jp",), "jp": ("intl",)}.get(region, ("jp", "intl"))
    return tuple(v for r in order if (v := db.current_version.get(r)))


def _background(assets: AssetStore, version: str, w: int, h: int, fallbacks: tuple[str, ...] = ()) -> Image.Image:
    p = assets.theme_file(version, "bg.png", fallbacks) or assets.theme_file(version, "bg.jpg", fallbacks)
    if p:
        bg = Image.open(p).convert("RGBA")
        scale = max(w / bg.width, h / bg.height)
        bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1), Image.LANCZOS)
        bg = bg.crop((0, 0, w, h))
        veil = Image.new("RGBA", (w, h), (255, 255, 255, 60))
        return Image.alpha_composite(bg, veil)
    bg = _gradient(w, h, [(255, 222, 240), (236, 196, 255), (196, 184, 255), (255, 210, 236)]).convert("RGBA")
    deco = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    for i in range(0, w + h, 90):
        dd.line((i, 0, i - h, h), fill=(255, 255, 255, 38), width=26)
    for cx, cy, r in ((260, 900, 420), (1950, 1700, 520), (600, 2900, 380), (1800, 3200, 300)):
        dd.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 70), width=14)
    return Image.alpha_composite(bg, deco)


def _frame_background(frame: Image.Image, w: int, h: int) -> Image.Image:
    """有背景（frame）时，整张图的底色跟着它走：放大、糊开、罩一层白，再压几条斜纹。"""
    small = frame.convert("RGB").resize((64, max(8, int(64 * h / w))), Image.LANCZOS)
    bg = small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(40)).convert("RGBA")
    bg = Image.alpha_composite(bg, Image.new("RGBA", (w, h), (255, 255, 255, 138)))
    deco = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    for i in range(0, w + h, 90):
        dd.line((i, 0, i - h, h), fill=(255, 255, 255, 30), width=26)
    return Image.alpha_composite(bg, deco)


def _logo(assets: AssetStore, version: str) -> Image.Image | None:
    p = os.path.join(assets.themes, version or "default", "logo.png")
    if os.path.exists(p):
        im = Image.open(p).convert("RGBA")
    else:   # the version logo from the shared logo set (themes/logos/<slug>.png), then the default theme logo
        im = assets.version_logo(version)
        if im is None:
            p = assets.theme_file("default", "logo.png")
            if not p:
                return None
            im = Image.open(p).convert("RGBA")
        im = im.copy()
        if im.getbbox():
            im = im.crop(im.getbbox())
        s = min(560 / im.width, 170 / im.height)       # small tab logos are scaled up to header size
        if s > 1:
            im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    im.thumbnail((620, 250), Image.LANCZOS)
    return im


PLATE_W, PLATE_H = 1080, 174          # 姓名框原图 720×116，放大 1.5 倍


def _net_or_icon(assets: AssetStore, ref: str) -> Image.Image | None:
    """段位 / 阶级小图：NET 给的是图片地址；落雪给的是编号，写成 icon:class_NN 用本地图。"""
    if not ref:
        return None
    if ref.startswith("icon:"):
        return assets.icon(ref[5:])
    return assets.net_image(ref)


def _player_block(canvas: Image.Image, x: int, y: int, b: Best50, profile: Profile | None, assets: AssetStore) -> None:
    """游戏上屏左上角那一块：姓名框（没有就画白底）里放头像、rating 牌、段位 / 阶级、名字；下面一条称号。"""
    d = ImageDraw.Draw(canvas)
    plate = assets.net_image(profile.plate_url) if profile and profile.plate_url else None
    _shadow(canvas, (x, y, x + PLATE_W, y + PLATE_H), 18, blur=12, alpha=80)
    if plate is not None:
        _paste_rounded(canvas, plate.resize((PLATE_W, PLATE_H), Image.LANCZOS), (x, y), 16)
    else:
        _paste_rounded(canvas, Image.new("RGBA", (PLATE_W, PLATE_H), (255, 255, 255, 226)), (x, y), 16)
    av = assets.avatar(profile.icon_url, 150) if profile and profile.icon_url else None
    if av is None:
        av = placeholder_cover(profile.name if profile else "?", 150).convert("RGBA")
    _paste_rounded(canvas, Image.new("RGBA", (158, 158), (255, 255, 255, 255)), (x + 8, y + 8), 16)
    _paste_rounded(canvas, av, (x + 12, y + 12), 13)
    nx = x + 178
    rating = profile.rating if profile and profile.rating else b.total
    rp = assets.icon(f"rating_{_rating_tier(rating):02d}")
    if rp is not None:
        draw_rating_plate(canvas, rp, rating, nx, y + 8, 76)
        bx = nx + int(rp.width * 76 / rp.height) + 14
    else:
        col = _tier_color(rating)
        rb = _rainbow(360, 64) if col is None else _gradient(360, 64, [tuple(min(255, c + 40) for c in col), col], True)
        _paste_rounded(canvas, rb.convert("RGBA"), (nx, y + 14), 14)
        F.draw_text(d, (nx + 16, y + 20), "DX RATING", "latin", 18, (255, 255, 255), stroke=2, stroke_fill=(80, 40, 120))
        F.draw_text(d, (nx + 344, y + 16), str(rating), "latin", 48, (255, 255, 255),
                    anchor_right=True, stroke=3, stroke_fill=(80, 40, 120))
        bx = nx + 374
    # 段位 (course) and class badges beside the rating plate
    right = x + PLATE_W - 14
    for ref in ((profile.course_rank, profile.class_rank) if profile else ()):
        im = _net_or_icon(assets, ref)
        if im is None or not im.getbbox():
            continue
        im = im.crop(im.getbbox())
        h = 68
        w = max(1, int(im.width * h / im.height))
        if w > 220:
            w, h = 220, max(1, int(im.height * 220 / im.width))
        if bx + w > right:
            break
        canvas.alpha_composite(im.resize((w, h), Image.LANCZOS), (bx, y + 12 + (68 - h) // 2))
        bx += w + 12
    name = profile.name if profile else "-"
    d.rounded_rectangle((nx, y + 92, nx + 560, y + 164), 14, fill=(255, 255, 255), outline=(206, 190, 226), width=3)
    F.draw_text(d, (nx + 20, y + 100), F.fit(name, "bold", 46, 520), "bold", 46, (40, 30, 60))
    # 称号
    kind = profile.title_kind if profile else "normal"
    tstops = {"rainbow": None, "gold": [(255, 226, 120), (232, 170, 40)], "silver": [(235, 240, 248), (170, 182, 200)],
              "bronze": [(232, 180, 130), (180, 110, 60)]}.get(kind, [(250, 250, 250), (210, 210, 220)])
    ty = y + PLATE_H + 12
    tb = _rainbow(740, 50) if tstops is None else _gradient(740, 50, tstops, True)
    _shadow(canvas, (nx, ty, nx + 740, ty + 50), 12, offset=4, blur=6, alpha=60)
    _paste_rounded(canvas, tb.convert("RGBA"), (nx, ty), 12)
    ImageDraw.Draw(canvas).rounded_rectangle((nx, ty, nx + 739, ty + 49), 12, outline=(255, 255, 255), width=2)
    title = profile.title if profile and profile.title else ""
    if title:
        t = F.fit(title, "bold", 27, 700)
        F.draw_text(ImageDraw.Draw(canvas), (nx + 370 - F.text_width(t, "bold", 27) // 2, ty + 6), t, "bold", 27,
                    (60, 40, 70))


def _stats(canvas: Image.Image, box, cells, cols: int) -> None:
    """统计格子：cols 列排开，每格一张白卡（小标签 / 大数字 / 一行说明）。"""
    x0, y0, x1, y1 = box
    rows = (len(cells) + cols - 1) // cols
    gap = 14
    cw = (x1 - x0 - gap * (cols - 1)) // cols
    ch = (y1 - y0 - gap * (rows - 1)) // rows
    for i, (k, v, sub, accent) in enumerate(cells):
        r, c = divmod(i, cols)
        cx, cy = x0 + c * (cw + gap), y0 + r * (ch + gap)
        _shadow(canvas, (cx, cy, cx + cw, cy + ch), 20, offset=4, blur=8, alpha=60)
        _paste_rounded(canvas, Image.new("RGBA", (cw, ch), (255, 255, 255, 228)), (cx, cy), 20)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((cx + 18, cy + 20, cx + 26, cy + ch - 20), 4, fill=accent)
        F.draw_text(d, (cx + 42, cy + 12), F.fit(k, "bold", 22, cw - 60), "bold", 22, (140, 100, 176))
        size = 50
        while size > 30 and F.text_width(v, "latin", size) > cw - 60:
            size -= 2
        F.draw_text(d, (cx + 42, cy + 40 + (50 - size) // 2), v, "latin", size, (64, 38, 104))
        if sub:
            F.draw_text(d, (cx + 42, cy + ch - 34), F.fit(sub, "bold", 20, cw - 60), "bold", 20, (126, 104, 150))


def _frame_image(assets: AssetStore, profile: Profile | None) -> Image.Image | None:
    return assets.net_image(profile.frame_url) if profile and profile.frame_url else None


def _header(canvas: Image.Image, b: Best50, profile: Profile | None, db: SongDB, assets: AssetStore,
            at: int | None, frame: Image.Image | None = None) -> None:
    """有背景（frame，目前国服落雪才有）：左边一整张背景图，上面压姓名框那一块，右边 logo + 四格统计。
    没有背景：姓名框那一块 + 右边 logo，下面一横排统计。"""
    version = b.version or db.current_version.get(catalog_region(b.region), "")
    cells = []
    net = profile.rating if profile else 0
    cells.append(("RATING", str(net or b.total), f"计算值 {b.total}" + (f"（{b.total - net:+d}）" if net and b.total != net else " ✓"),
                  (240, 120, 170)))
    avg_old = b.old_total / len(b.old) if b.old else 0
    avg_new = b.new_total / len(b.new) if b.new else 0
    cells.append(("BEST 35 · 旧曲", str(b.old_total), f"平均 {avg_old:.1f} · 底分 {b.old_floor}", (128, 110, 236)))
    news = "/".join(_version_short(v) for v in sorted(db.new_versions(b.region), key=db.version_index))
    cells.append((f"BEST 15 · {news}" if news else "BEST 15 · 新曲", str(b.new_total),
                  f"平均 {avg_new:.1f} · 底分 {b.new_floor}", (240, 160, 60)))
    pc = "-"
    if profile and profile.play_count_version is not None:
        pc = f"{profile.play_count_version} / {profile.play_count_total}"
    elif profile and profile.play_count_total is not None:          # 私服只给累计
        pc = f"- / {profile.play_count_total}"
    stars = f"★ {profile.stars}" if profile and profile.stars is not None else ""
    if pc == "-" and stars:                                         # 国服（落雪）没有游玩次数，只有觉醒数
        cells.append(("搭档觉醒", stars, "", (90, 190, 150)))
    else:
        cells.append(("本版本 / 累计游玩", pc, stars, (90, 190, 150)))

    if frame is not None:
        fw, fh = 1240, HEADER_H_FRAME - 30 - 47            # 1240×519，和原图 1080×452 同比例
        fx, fy = SIDE, 30
        _shadow(canvas, (fx, fy, fx + fw, fy + fh), 28, blur=14, alpha=100)
        _paste_rounded(canvas, frame.convert("RGB").resize((fw, fh), Image.LANCZOS), (fx, fy), 28)
        ImageDraw.Draw(canvas).rounded_rectangle((fx, fy, fx + fw - 1, fy + fh - 1), 28, outline=(255, 255, 255), width=4)
        _player_block(canvas, fx + 24, fy + 24, b, profile, assets)
        rx0, bottom = fx + fw + 24, fy + fh
    else:
        _player_block(canvas, SIDE, 36, b, profile, assets)
        rx0, bottom = SIDE + PLATE_W + 24, 36 + PLATE_H + 62
    # 右边：logo + 时间 / 服务器
    d = ImageDraw.Draw(canvas)
    rx = W - SIDE
    logo = _logo(assets, version)
    ly = 24
    if logo is not None:
        lg = logo.copy()
        lg.thumbnail((rx - rx0, 196), Image.LANCZOS)
        canvas.alpha_composite(lg, (rx - lg.width, ly + (196 - lg.height) // 2))
    else:
        F.draw_text(d, (rx, ly + 50), f"maimai DX {_version_short(version)}", "latin", 70, (255, 255, 255), anchor_right=True,
                    stroke=6, stroke_fill=(190, 70, 170))
    stamp = time.strftime("%Y/%m/%d %H:%M", time.localtime(at or time.time()))
    src = b.source or ("maimai DX NET" if b.region not in API_REGIONS else "")
    reg = f"{REGION_NAMES.get(b.region, b.region)} · {version}" + (f" · {src}" if src else "")
    if getattr(b, "rom", "") and (rv := rom_short(b.rom)):
        reg += f" · Ver.{rv}"          # 私服：玩家客户端版本号，定数 / 新旧曲按它算
    reg = F.fit(reg + f" · {stamp}", "bold", 28, rx - rx0 - 44)
    pw = F.text_width(reg, "bold", 28) + 44
    my = ly + 204
    _paste_rounded(canvas, Image.new("RGBA", (pw, 46), (255, 255, 255, 214)), (rx - pw, my), 23)
    F.draw_text(ImageDraw.Draw(canvas), (rx - pw + 22, my + 4), reg, "bold", 28, (112, 70, 160))
    if frame is not None:
        _stats(canvas, (rx0, my + 46 + 18, rx, bottom), cells, 2)
    else:
        _stats(canvas, (SIDE, bottom + 18, W - SIDE, HEADER_H - 30), cells, 4)


def _banner(canvas: Image.Image, y: int, label: str, total: int, sub: str) -> None:
    d = ImageDraw.Draw(canvas)
    w, h = 760, 70
    x = (W - w) // 2
    _shadow(canvas, (x, y + 18, x + w, y + 18 + h), 35)
    pill = _gradient(w, h, [(120, 90, 230), (210, 90, 200)], True).convert("RGBA")
    _paste_rounded(canvas, pill, (x, y + 18), 35)
    F.draw_text(d, (x + 36, y + 30), label, "latin", 38, (255, 255, 255))
    F.draw_text(d, (x + w - 36, y + 26), str(total), "latin", 46, (255, 255, 255), anchor_right=True)
    tw = F.text_width(sub, "bold", 22)
    F.draw_text(d, ((W - tw) // 2, y + 18 + h + 6), sub, "bold", 22, (110, 60, 150))


def _grid(canvas, y0, scores, db, assets, region) -> int:
    for i, s in enumerate(scores):
        r, c = divmod(i, 5)
        x = SIDE + c * (CARD_W + GAP_X)
        y = y0 + r * (CARD_H + GAP_Y)
        draw_card(canvas, x, y, s, i + 1, db, assets, region)
    rows = (len(scores) + 4) // 5
    return y0 + rows * (CARD_H + GAP_Y)


class B50Renderer:
    def __init__(self, data_dir: str, bot_name: str = "AstrBot"):
        self.assets = AssetStore(data_dir)
        self.bot_name = bot_name

    def __call__(self, b: Best50, profile: Profile | None, db: SongDB, at: int | None = None) -> bytes:
        share_versions(db)
        fill_dx_max(b, db)
        images = []
        for s in b.old + b.new:
            song = song_of(db, s)       # 新歌 DXRating 还没有游戏内 ID：按 song_id / 歌名找曲绘，别只认 music_id
            hdd = s.music_id and os.path.exists(
                os.path.join(self.assets.hdd_jackets, f"{int(s.music_id) % 10000:06d}.png"))
            if song is not None and not hdd:
                images.append(song.image)
        self.assets.prefetch(images)
        rows_old = max(1, (len(b.old) + 4) // 5)
        rows_new = max(1, (len(b.new) + 4) // 5)
        frame = _frame_image(self.assets, profile)
        head = HEADER_H_FRAME if frame is not None else HEADER_H
        h = head + 2 * (BANNER_H + 56) + (rows_old + rows_new) * (CARD_H + GAP_Y) + FOOTER_H
        version = b.version or db.current_version.get(catalog_region(b.region), "")
        canvas = (_frame_background(frame, W, h) if frame is not None
                  else _background(self.assets, version, W, h, _fallbacks(db, b.region)))
        _header(canvas, b, profile, db, self.assets, at, frame)
        y = head
        _banner(canvas, y, "BEST 35", b.old_total, f"旧曲 · {len(b.old)} 张")
        y = _grid(canvas, y + BANNER_H + 56, b.old, db, self.assets, b.region)
        news = " / ".join(sorted(db.new_versions(b.region), key=db.version_index))
        _banner(canvas, y, "BEST 15", b.new_total, (f"新曲（{news}）" if news else "新曲") + f" · {len(b.new)} 张")
        y = _grid(canvas, y + BANNER_H + 56, b.new, db, self.assets, b.region)
        d = ImageDraw.Draw(canvas)
        foot = f"Generated by {self.bot_name} · Data from DXRating (dxrating.net)"   # same on every server
        note = "≈ 表示定数未收录、按等级下限估算" if any(not s.ds_exact for s in b.old + b.new) else ""
        F.draw_text(d, (W // 2 - F.text_width(foot, "bold", 28) // 2, h - FOOTER_H + 30), foot, "bold", 28,
                    (110, 60, 150))
        if note:
            F.draw_text(d, (W // 2 - F.text_width(note, "bold", 22) // 2, h - FOOTER_H + 72), note, "bold", 22,
                        (140, 100, 170))
        out = io.BytesIO()
        canvas.convert("RGB").save(out, "PNG", optimize=True)
        return out.getvalue()


def render_best50(b: Best50, profile: Profile | None, db: SongDB, at: int | None = None,
                  data_dir: str | None = None) -> bytes:
    import tempfile
    return B50Renderer(data_dir or os.path.join(tempfile.gettempdir(), "mai_net"))(b, profile, db, at)
