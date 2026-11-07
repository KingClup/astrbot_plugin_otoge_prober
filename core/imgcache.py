"""生成图片的磁盘缓存：帮助图、查歌卡、定数表、理论最高 B50 这类和个人成绩无关的图，画一次存起来。

- 键 = 种类 + 参数（+ 插件版本；daily=True 的再加上日期，曲库每天刷新后自然换新图）。
- 放在插件数据目录的 imgcache/ 下；超过 max_mb 或 max_age_days 没被用过的自动删。
- 个人 B50 / 资料卡不缓存（成绩随时会变）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable


class ImageCache:
    def __init__(self, root: str | os.PathLike, *, version: str = "", max_mb: int = 300, max_age_days: float = 3):
        self.dir = Path(root) / "imgcache"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.version = version
        self.max_bytes = max_mb * 1024 * 1024
        self.max_age = max_age_days * 86400
        self.hits = self.misses = 0
        self._inflight: dict[Path, asyncio.Future] = {}     # 同一张图同时被两个人要：只画一次

    def _path(self, kind: str, parts: tuple, daily: bool) -> Path:
        stamp = [self.version] + ([time.strftime("%Y-%m-%d")] if daily else [])
        raw = json.dumps([kind, *stamp, *parts], ensure_ascii=False, default=str, sort_keys=True)
        return self.dir / f"{kind}_{hashlib.sha1(raw.encode()).hexdigest()[:20]}.img"

    def get(self, kind: str, *parts: Any, daily: bool = True) -> bytes | None:
        p = self._path(kind, parts, daily)
        try:
            data = p.read_bytes()
        except OSError:
            self.misses += 1
            return None
        try:
            os.utime(p)          # 最近用过：清理时最后才删
        except OSError:
            pass
        self.hits += 1
        return data

    def put(self, kind: str, data: bytes | None, *parts: Any, daily: bool = True) -> None:
        if not data:
            return
        p = self._path(kind, parts, daily)
        tmp = p.with_suffix(".tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(p)
        except OSError:
            pass

    async def cached(self, kind: str, parts: tuple, make: Callable[[], Awaitable[bytes | None]],
                     daily: bool = True) -> bytes | None:
        if (hit := self.get(kind, *parts, daily=daily)) is not None:
            return hit
        p = self._path(kind, parts, daily)
        if (fut := self._inflight.get(p)) is not None:
            return await asyncio.shield(fut)
        fut = asyncio.get_running_loop().create_future()
        self._inflight[p] = fut
        try:
            data = await make()
            self.put(kind, data, *parts, daily=daily)
            fut.set_result(data)
            return data
        except BaseException:
            if not fut.done():
                fut.set_result(None)          # 等着的人拿到 None（出图失败），自己这边照常抛错
            raise
        finally:
            self._inflight.pop(p, None)

    def clear(self) -> int:
        """素材 / 主题换了：缓存的图全部作废。"""
        n = 0
        for p in self.dir.glob("*.img"):
            p.unlink(missing_ok=True)
            n += 1
        return n

    def prune(self) -> dict:
        now = time.time()
        files = []
        for p in self.dir.glob("*.img"):
            try:
                st = p.stat()
            except OSError:
                continue
            if now - st.st_mtime > self.max_age:
                p.unlink(missing_ok=True)
                continue
            files.append((st.st_mtime, st.st_size, p))
        total = sum(f[1] for f in files)
        removed = 0
        for _mt, size, p in sorted(files):        # 最久没用的先删
            if total <= self.max_bytes:
                break
            p.unlink(missing_ok=True)
            total -= size
            removed += 1
        return {"files": len(files) - removed, "bytes": total, "removed": removed}

    async def prune_async(self) -> dict:
        return await asyncio.to_thread(self.prune)
