"""CHUNITHM version logos: version_logos/<slug>.png in the chuni data folder (from the local logo pack;
SEGA artwork, never shipped with the plugin).

  "CHUNITHM" → chunithm   "PLUS" / "CHUNITHM PLUS" → chunithm_plus   "AIR PLUS" / "AIR+" → air_plus
  "NEW!!" → new   "NEW PLUS!!" → new_plus   "PARADISE LOST" → paradise_lost   "X-VERSE-X" → xversex
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image


def slug(version: str | None) -> str:
    v = (version or "").upper().replace("!!", "").replace("＋", "+")
    v = re.sub(r"\bCHUNITHM\b", "", v).replace("+", " PLUS")
    v = re.sub(r"\s+", " ", v).strip()
    if v in ("", "ORIGINAL"):
        return "chunithm"
    if v == "PLUS":
        return "chunithm_plus"
    return v.lower().replace("-", "").replace(" ", "_")


class LogoStore:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir) / "version_logos"
        self._cache: dict[str, Image.Image | None] = {}

    def path(self, version: str | None) -> Path | None:
        if not version:
            return None
        p = self.dir / f"{slug(version)}.png"
        return p if p.exists() else None

    def image(self, version: str | None) -> Image.Image | None:
        p = self.path(version)
        if p is None:
            return None
        key = str(p)
        if key not in self._cache:
            try:
                im = Image.open(p).convert("RGBA")
                self._cache[key] = im.crop(im.getbbox()) if im.getbbox() else im
            except (OSError, ValueError):
                self._cache[key] = None
        return self._cache[key]

    def fit(self, version: str | None, max_w: int, max_h: int) -> Image.Image | None:
        im = self.image(version)
        if im is None:
            return None
        s = min(max_w / im.width, max_h / im.height)
        return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
