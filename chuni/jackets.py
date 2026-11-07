"""曲绘（封面）缓存。

索引：SEGA 官方 music.json（曲目 ID → 图片文件名），和 CHUNITHM-NET 的曲目 ID 一致。
图片：先试日服 CDN，再试国际服 CDN；都没有（国际服独占、已删除的曲子）时，用曲库 beerpsi
（chuni-penguin）给的 jacket_url 兜底。下载后缓存在 data/jackets/<id>.jpg，不打包进插件。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger("chuni_intl.jackets")

MUSIC_JSON = "https://chunithm.sega.jp/storage/json/music.json"
JACKET_BASES = (
    "https://new.chunithm-net.com/chuni-mobile/html/mobile/img",
    "https://chunithm-net-eng.com/mobile/img",
)


def _is_image(b: bytes) -> bool:
    return b[:3] == b"\xff\xd8\xff" or b[:4] == b"\x89PNG" or (b[:4] == b"RIFF" and b[8:12] == b"WEBP")


class JacketStore:
    def __init__(self, cache_dir: Path, refresh_hours: float = 24):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "music.json"
        self.refresh_seconds = refresh_hours * 3600
        self.index: dict[int, str] = {}
        self._loaded_at = 0.0
        self._sem = asyncio.Semaphore(8)
        self._miss: dict[int, float] = {}       # 全部来源都没有这张曲绘：12 小时内不再去问（每张 B50 都重试太浪费）
        self.miss_ttl = 12 * 3600

    def _load_index_file(self) -> None:
        try:
            data = json.loads(self.index_path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        out: dict[int, str] = {}
        for s in data:
            try:
                if s.get("image"):
                    out[int(s["id"])] = str(s["image"])
            except (TypeError, ValueError):
                continue
        self.index = out
        self._loaded_at = time.time()

    async def ensure_index(self, force: bool = False) -> None:
        fresh = self.index_path.exists() and time.time() - self.index_path.stat().st_mtime < self.refresh_seconds
        if not force and self.index and time.time() - self._loaded_at < self.refresh_seconds:
            return
        if force or not fresh:
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
                    r = await c.get(MUSIC_JSON)
                    r.raise_for_status()
                    json.loads(r.content)  # 校验
                    tmp = self.index_path.with_suffix(".tmp")
                    tmp.write_bytes(r.content)
                    tmp.replace(self.index_path)
            except Exception as e:  # noqa: BLE001
                log.warning("曲绘索引下载失败，继续用旧缓存: %s", e)
        self._load_index_file()

    def path_for(self, song_id: int) -> Path:
        return self.dir / f"{song_id}.jpg"

    async def _fetch_one(self, client: httpx.AsyncClient, song_id: int, fallback: str | None = None) -> Path | None:
        dest = self.path_for(song_id)
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        if (t := self._miss.get(song_id)) is not None and time.time() - t < self.miss_ttl:
            return None
        image = self.index.get(song_id)
        urls = [f"{base}/{image}" for base in JACKET_BASES] if image else []
        if fallback:
            urls.append(fallback)
        if not urls:
            return None
        answered = True
        async with self._sem:
            for url in urls:
                try:
                    r = await client.get(url)
                    if r.status_code == 200 and _is_image(r.content):
                        tmp = dest.with_suffix(".tmp")
                        tmp.write_bytes(r.content)
                        tmp.replace(dest)
                        self._miss.pop(song_id, None)
                        return dest
                except httpx.HTTPError:
                    answered = False          # 网络问题不算「没有」，下次还要试
                    continue
        if answered:
            self._miss[song_id] = time.time()
        return None

    async def get_many(self, song_ids: list[int], fallbacks: dict[int, str] | None = None) -> dict[int, Path]:
        """返回能拿到的曲绘路径；拿不到的不在结果里（渲染时用占位图）。fallbacks：曲目 ID → 备用图片地址。"""
        fallbacks = fallbacks or {}
        try:
            await self.ensure_index()
        except Exception:  # noqa: BLE001
            pass
        ids = sorted({i for i in song_ids if i is not None})
        out: dict[int, Path] = {}
        async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                     headers={"user-agent": "astrbot-plugin-chuni-intl"}) as c:
            results = await asyncio.gather(*(self._fetch_one(c, i, fallbacks.get(i)) for i in ids),
                                           return_exceptions=True)
        for i, r in zip(ids, results):
            if isinstance(r, Path):
                out[i] = r
        return out
