"""B50 图片主题素材：按版本存放的背景 / logo，以及 rating 数字图。

素材都放在 plugin_data/themes/ 下，由用户在 WebUI 上传（例如从自己的游戏数据里取），
**不随插件分发**（仓库里不包含任何 SEGA 素材）。logo 还可以从官方网站自动抓取候选图。

目录：
  themes/digits.png                 数字图（5 行颜色 × 11 个字形：0-9 + 逗号），自动按透明通道切开
  themes/<版本>/bg.png | logo.png     例如 themes/Mate/logo.png
"""

from __future__ import annotations

import base64
import io
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx
from PIL import Image

log = logging.getLogger("chuni_intl.theme")

LOGO_PAGES = ("https://chunithm.sega.com/", "https://info-chunithm.sega.com/", "https://chunithm.sega.jp/")
_IMG_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)
DIGIT_ROWS = ("silver", "red", "blue", "gold", "rainbow")

# rating 段位（1-10，见 b50img.RATING_TIERS）→ 数字图的颜色行
TIER_TO_ROW = {10: "rainbow", 9: "rainbow", 8: "silver", 7: "gold", 6: "silver",
               5: "red", 4: "blue", 3: "red", 2: "gold", 1: "blue"}


def version_key(version: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", version or "default").strip("_") or "default"


def thumb_data_url(path: Path, max_side: int = 360) -> str | None:
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except (OSError, ValueError):
        return None


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, v in enumerate(flags):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def slice_digit_sheet(sheet: Image.Image, threshold: int = 40) -> dict[str, list[Image.Image]]:
    """按透明通道找出 行 × 字形。要求 5 行、每行 11 个字形（0-9 + 逗号）。"""
    sheet = sheet.convert("RGBA")
    alpha = sheet.getchannel("A").point(lambda v: 255 if v > threshold else 0)
    w, h = alpha.size
    row_flags = [alpha.crop((0, y, w, y + 1)).getbbox() is not None for y in range(h)]
    bands = [b for b in _runs(row_flags) if b[1] - b[0] > 10]
    out: dict[str, list[Image.Image]] = {}
    for name, (y0, y1) in zip(DIGIT_ROWS, bands):
        band = alpha.crop((0, y0, w, y1))
        col_flags = [band.crop((x, 0, x + 1, y1 - y0)).getbbox() is not None for x in range(w)]
        glyphs = [g for g in _runs(col_flags) if g[1] - g[0] > 4]
        if len(glyphs) < 11:
            raise ValueError(f"数字图第 {len(out) + 1} 行只找到 {len(glyphs)} 个字形，应为 11 个")
        row = [sheet.crop((x0, y0, x1, y1)) for x0, x1 in glyphs[:11]]
        row.append(_dot_from_comma(row[10], row[0], row[1]))  # 索引 11 = 小数点
        out[name] = row
    if len(out) < len(DIGIT_ROWS):
        raise ValueError(f"数字图只找到 {len(out)} 行，应为 {len(DIGIT_ROWS)} 行")
    return out


def _dot_from_comma(comma: Image.Image, zero: Image.Image, one: Image.Image | None = None) -> Image.Image:
    """数字图只有逗号，没有句号：按游戏 txt_00 里 "." 的比例（边长≈数字高 40%，底边略高于基线）
    合成一个圆角方点。颜色不靠模糊，而是借 "1" 竖笔的横截面（描边→高光→填充）按到边距离铺色，
    这样描边粗细、渐变和数字一致。"""
    from PIL import ImageDraw

    zb = zero.getchannel("A").getbbox()
    if not zb:
        return comma
    digit_h = zb[3] - zb[1]
    side = max(6, round(digit_h * 0.38))
    src = one if one is not None and one.getchannel("A").getbbox() else zero
    sa = src.getchannel("A")
    sw, sh = src.size
    px = src.load()
    ap = sa.load()
    bottom = zb[3]
    lift = round(digit_h * 0.055)
    top = bottom - lift - side

    # 每一行找最宽的不透明段（"1" 的竖笔），取左半边当"距边距离→颜色"的剖面
    def profile(y: int) -> list[tuple[int, int, int, int]]:
        y = min(max(y, 0), sh - 1)
        best = (0, 0)
        run = None
        for x in range(sw + 1):
            on = x < sw and ap[x, y] > 40
            if on and run is None:
                run = x
            elif not on and run is not None:
                if x - run > best[1] - best[0]:
                    best = (run, x)
                run = None
        l, r = best
        if r - l < 4:
            return [(255, 255, 255, 255)]
        half = (r - l) // 2
        return [px[l + i, y] for i in range(half)]

    # 圆角方形 mask；每个像素到边缘的欧氏距离决定取剖面哪一格
    ss = 4
    big = Image.new("L", (side * ss, side * ss), 0)
    ImageDraw.Draw(big).rounded_rectangle([0, 0, side * ss - 1, side * ss - 1], radius=side * ss // 4, fill=255)
    mask = big.resize((side, side), Image.Resampling.LANCZOS)
    hard = mask.point(lambda v: 255 if v > 127 else 0)
    hp = hard.load()
    edge = [(x, y) for y in range(-1, side + 1) for x in range(-1, side + 1)
            if not (0 <= x < side and 0 <= y < side) or not hp[x, y]]

    # "1" 竖笔正中一行的左半边 = 从外到内的 描边→高光→填充 剖面，拉伸到点的半宽
    mid = (zb[1] + zb[3]) // 2
    prof = profile(mid)
    half = side / 2
    dot = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    dp = dot.load()
    for yy in range(side):
        for xx in range(side):
            if not hp[xx, yy]:
                continue
            dd = min(((xx - ex) ** 2 + (yy - ey) ** 2) for ex, ey in edge) ** 0.5 - 0.5
            c = prof[min(len(prof) - 1, max(0, int(dd / half * len(prof))))]
            dp[xx, yy] = (c[0], c[1], c[2], 255)
    dot.putalpha(mask)

    pad = max(2, round(digit_h * 0.04))
    out = Image.new("RGBA", (side + pad * 2, comma.height), (0, 0, 0, 0))
    out.alpha_composite(dot, (pad, max(0, top)))
    return out


class ThemeStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._digits: dict[str, list[Image.Image]] | None = None
        self._digits_mtime = 0.0

    # ---------- 路径 ----------

    def dir_for(self, version: str | None) -> Path:
        d = self.root / version_key(version)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def digits_path(self) -> Path:
        return self.root / "digits.png"

    def asset(self, version: str | None, kind: str) -> Path | None:
        """kind = bg | logo；当前版本没有就退回 default 目录。"""
        for v in (version, None):
            p = self.dir_for(v) / f"{kind}.png"
            if p.exists():
                return p
        return None

    # ---------- 数字图 ----------

    def digits(self) -> dict[str, list[Image.Image]] | None:
        p = self.digits_path
        if not p.exists():
            return None
        mt = p.stat().st_mtime
        if self._digits is None or mt != self._digits_mtime:
            try:
                with Image.open(p) as im:
                    self._digits = slice_digit_sheet(im)
                self._digits_mtime = mt
            except (OSError, ValueError) as e:
                log.warning("数字图切分失败: %s", e)
                self._digits = None
        return self._digits

    # ---------- 保存上传 ----------

    def save(self, kind: str, data: bytes, version: str | None = None) -> Path:
        if kind not in ("digits", "bg", "logo"):
            raise ValueError("kind 只能是 digits / bg / logo")
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            if kind == "digits":
                slice_digit_sheet(im)  # 先校验能切开
            img = im.convert("RGBA")
        dest = self.digits_path if kind == "digits" else self.dir_for(version) / f"{kind}.png"
        tmp = dest.with_suffix(".tmp")
        img.save(tmp, "PNG")
        tmp.replace(dest)
        if kind == "digits":
            self._digits = None
        return dest

    def status(self, version: str | None) -> dict:
        vk = version_key(version)
        out = {"version": version, "key": vk, "digits": None, "bg": None, "logo": None}
        if self.digits_path.exists():
            out["digits"] = {"ok": self.digits() is not None, "preview": thumb_data_url(self.digits_path, 300)}
        for kind in ("bg", "logo"):
            p = self.asset(version, kind)
            if p is not None:
                out[kind] = {"from": p.parent.name, "preview": thumb_data_url(p)}
        return out

    # ---------- 从官网抓 logo ----------

    async def logo_candidates(self, version: str | None, limit: int = 8) -> list[dict]:
        """抓官网首页里文件名带 logo 的图片，按"是否含版本名 + 尺寸"排序。"""
        slug = re.sub(r"[^a-z0-9]", "", (version or "").lower())
        found: dict[str, dict] = {}
        async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                     headers={"user-agent": "Mozilla/5.0 astrbot-plugin-chuni-intl"}) as c:
            for page in LOGO_PAGES:
                try:
                    html = (await c.get(page)).text
                except httpx.HTTPError:
                    continue
                for src in _IMG_RE.findall(html):
                    url = urljoin(page, src)
                    if "logo" not in url.lower() or url in found or len(found) >= 30:
                        continue
                    try:
                        r = await c.get(url)
                        with Image.open(io.BytesIO(r.content)) as im:
                            w, h = im.size
                    except Exception:  # noqa: BLE001
                        continue
                    if w < 120 or h < 50:
                        continue  # 太小的一般是图标
                    name = re.sub(r"[^a-z0-9]", "", url.lower().rsplit("/", 1)[-1])
                    score = (2 if slug and slug in name else 0) + min(w * h, 600_000) / 600_000
                    found[url] = {"url": url, "w": w, "h": h, "score": round(score, 3), "_bytes": r.content}
        cands = sorted(found.values(), key=lambda x: -x["score"])[:limit]
        for c_ in cands:
            buf = io.BytesIO()
            with Image.open(io.BytesIO(c_.pop("_bytes"))) as im:
                im = im.convert("RGBA")
                im.thumbnail((320, 320))
                im.save(buf, "PNG")
            c_["preview"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        return cands

    async def use_logo_url(self, url: str, version: str | None) -> Path:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
        return self.save("logo", r.content, version)

    async def auto_logo(self, version: str | None) -> Path | None:
        """当前版本还没有 logo 时，自动选一个文件名里带版本名的候选。"""
        if not version or (self.dir_for(version) / "logo.png").exists():
            return None
        cands = await self.logo_candidates(version, limit=5)
        # 国际服官网的主视觉 logo（/assets/img/top/kv_logo.png）每个大版本都会换成新版本的
        best = next((c for c in cands if c["score"] >= 2), None) or next(
            (c for c in cands if "kv_logo" in c["url"] and "chunithm.sega.com" in c["url"]), None)
        if best is None:
            return None
        log.info("自动获取 %s 的 logo：%s", version, best["url"])
        return await self.use_logo_url(best["url"], version)
