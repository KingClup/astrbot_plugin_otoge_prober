"""中日文字体：系统里没有时自动下载一份思源黑体（Noto Sans CJK，SIL OFL 1.1，可自由分发）。

只在找不到任何中日文字体时才下载（Windows / macOS 一般都有，主要是 Linux / Docker）。
下载到 <插件数据目录>/fonts/，只下载一次；下载失败时退回原来的做法（中文可能显示成方框）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

log = logging.getLogger("chuni_intl.fonts")

FONT_NAME = "NotoSansCJKsc-Bold.otf"
FONT_URLS = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/" + FONT_NAME,
    "https://cdn.jsdelivr.net/gh/notofonts/noto-cjk@main/Sans/OTF/SimplifiedChinese/" + FONT_NAME,
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/" + FONT_NAME,
)
MIN_SIZE = 5_000_000  # 完整字体约 17 MB，太小说明下载的是错误页


def _usable(path: Path) -> bool:
    """能打开，并且确实有中文和假名字形。"""
    try:
        from PIL import ImageFont

        f = ImageFont.truetype(str(path), 32)
        for ch in ("中", "あ"):
            if f.getmask(ch).getbbox() is None:
                return False
        return True
    except Exception:  # noqa: BLE001
        return False


def system_has_cjk(font_override: str | None = None) -> bool:
    from . import b50img

    paths = [p for p, _ in b50img.BOLD_CANDIDATES + b50img.REGULAR_CANDIDATES]
    if font_override:
        paths.insert(0, font_override)
    if any(Path(p).exists() for p in paths):
        return True
    return bool(b50img._scan_cjk_fonts())


def register(path: Path) -> None:
    """让 B50 图片和文字卡片都能用上这份字体。"""
    from . import b50img, render

    b50img.register_font(str(path))
    if str(path) not in render.FONT_CANDIDATES:
        render.FONT_CANDIDATES.append(str(path))


async def ensure_cjk_font(data_dir: Path, *, font_override: str | None = None, proxy: str | None = None,
                          urls: tuple[str, ...] = FONT_URLS) -> Path | None:
    """返回下载好的字体路径；系统已有中日文字体时返回 None 且什么都不做。"""
    dest = data_dir / "fonts" / FONT_NAME
    if dest.exists() and dest.stat().st_size > MIN_SIZE and _usable(dest):
        register(dest)
        return dest
    if system_has_cjk(font_override):
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("没有找到中日文字体，开始下载思源黑体（约 17 MB，只下载一次）…")
    tmp = dest.with_suffix(".part")
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True,
                                         proxy=proxy or None) as c:
                async with c.stream("GET", url) as r:
                    r.raise_for_status()
                    with tmp.open("wb") as fh:
                        async for chunk in r.aiter_bytes(1 << 16):
                            fh.write(chunk)
            if tmp.stat().st_size > MIN_SIZE and _usable(tmp):
                tmp.replace(dest)
                register(dest)
                log.info("字体已下载：%s", dest)
                return dest
            log.warning("从 %s 下载的字体不可用，换下一个地址", url)
        except Exception as e:  # noqa: BLE001
            log.warning("字体下载失败（%s）：%s", url, e)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
    log.warning("字体自动下载失败。请手动安装中日文字体（例如 apt install fonts-noto-cjk），"
                "或在插件配置 font_path 里填字体文件路径，否则曲名里的中日文会显示成方框。")
    return None
