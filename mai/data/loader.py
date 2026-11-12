"""Download / cache the DXRating catalog. A gzip snapshot ships with the plugin so it works offline."""
from __future__ import annotations

import gzip
import json
import os
import time

import httpx

from .songdb import SongDB

SOURCES = (
    "https://miruku.dxrating.net/api/v1/dxdata",
    "https://raw.githubusercontent.com/gekichumai/dxrating/main/packages/dxdata/snapshot.json",
)
BUNDLED = os.path.join(os.path.dirname(__file__), "dxrating_snapshot.json.gz")


def _valid(doc: dict) -> bool:
    return isinstance(doc, dict) and isinstance(doc.get("songs"), list) and len(doc["songs"]) > 500


class CatalogStore:
    def __init__(self, cache_dir: str, version_override: dict[str, str] | None = None):
        self.cache_path = os.path.join(cache_dir, "dxrating_catalog.json")
        self.version_override = {k: v for k, v in (version_override or {}).items() if v and v != "auto"}
        self.auto_versions: dict[str, str] = {}     # 进度核实（core/progress）给的；手动指定的优先
        self.post_load: list = []                   # 每次新建 SongDB 后调用（定数中心写回国服 / 日服定数）
        self.db: SongDB | None = None
        self.source = ""
        self.loaded_at = 0.0
        self.last_error = ""
        self.aliases: dict[int, list[str]] = {}

    def set_aliases(self, aliases: dict[int, list[str]]) -> None:
        """Community nicknames (see aliases.py); kept so every catalogue reload gets them again."""
        self.aliases = aliases or {}
        if self.db is not None:
            self.db.apply_aliases(self.aliases)

    def _after_load(self, db) -> None:
        for fn in self.post_load:
            try:
                fn(db)
            except Exception:  # noqa: BLE001
                pass

    def effective_versions(self) -> dict[str, str]:
        return {**self.auto_versions, **self.version_override}

    def set_version_override(self, override: dict[str, str]) -> None:
        self.version_override = {k: v for k, v in (override or {}).items() if v and v != "auto"}
        if self.db is not None:
            self.db.set_version_override(self.effective_versions())

    def set_auto_versions(self, versions: dict[str, str]) -> None:
        self.auto_versions = {k: v for k, v in (versions or {}).items() if v}
        if self.db is not None:
            self.db.set_version_override(self.effective_versions())

    def load_local(self) -> SongDB:
        doc = None
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    doc = json.load(f)
                self.source = "cache"
            except Exception as e:  # corrupted cache → fall back to bundled
                self.last_error = f"cache: {e}"
                doc = None
        if not _valid(doc or {}):
            with gzip.open(BUNDLED, "rt", encoding="utf-8") as f:
                doc = json.load(f)
            self.source = "bundled"
        self.db = SongDB(doc, self.effective_versions())
        if self.aliases:
            self.db.apply_aliases(self.aliases)
        self._after_load(self.db)
        self.loaded_at = time.time()
        return self.db

    async def refresh(self, timeout: float = 60.0, max_age_hours: float | None = None) -> SongDB:
        """max_age_hours：本地缓存比这还新就不下载（启动时用；每天定时刷新传 None 强制下载）。"""
        if max_age_hours is not None and self.db is not None:
            try:
                if time.time() - os.path.getmtime(self.cache_path) < max_age_hours * 3600:
                    self.source = self.source or "cache"
                    return self.db
            except OSError:
                pass
        errors = []
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"User-Agent": "astrbot_plugin_otoge_prober"}) as c:
            for url in SOURCES:
                try:
                    r = await c.get(url)
                    r.raise_for_status()
                    doc = r.json()
                    if isinstance(doc, dict) and "document" in doc and _valid(doc["document"]):
                        doc = doc["document"]
                    if not _valid(doc):
                        raise ValueError("unexpected catalog shape")
                    db = SongDB(doc, self.effective_versions())
                    if self.aliases:
                        db.apply_aliases(self.aliases)
                    self._after_load(db)
                    os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                    tmp = self.cache_path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(doc, f, ensure_ascii=False)
                    os.replace(tmp, self.cache_path)
                    self.db, self.source, self.loaded_at, self.last_error = db, url, time.time(), ""
                    return db
                except Exception as e:
                    errors.append(f"{url}: {type(e).__name__}: {e}")
        self.last_error = " | ".join(errors)
        if self.db is None:
            return self.load_local()
        return self.db
