"""Community song nicknames (别名 / 外号) for maimai and CHUNITHM.

Sources, merged in this order (earlier wins only for ordering; every alias is kept):
  1. local_aliases.json   — added on this bot with 「/mai 加别名」「/chu 加别名」
  2. 落雪 (Lxns)          — https://maimai.lxns.net/api/v0/{maimai,chunithm}/alias/list
  3. Yuzuchan             — https://www.yuzuchan.moe/api/v2/aliases/{maimaidx,chunithm}/aliases (投票别名库)
  (maimai also keeps DXRating's own aliases, which come with the song catalogue.)

All lists are keyed by song id. maimai ids are folded to the base id (水鱼 / Yuzuchan use +10000 for DX
charts, 宴 ids ≥ 100000 are skipped); CHUNITHM ids are the official ones. A gzip snapshot ships with the
plugin so nicknames work before the first download; downloads refresh once a day, each source on its
own time budget, and a failed download keeps the previous file.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import time
from pathlib import Path

import httpx

log = logging.getLogger("astrbot")

SOURCES = {
    "mai": {"lxns": "https://maimai.lxns.net/api/v0/maimai/alias/list",
            "yuzu": "https://www.yuzuchan.moe/api/v2/aliases/maimaidx/aliases"},
    "chu": {"lxns": "https://maimai.lxns.net/api/v0/chunithm/alias/list",
            "yuzu": "https://www.yuzuchan.moe/api/v2/aliases/chunithm/aliases"},
}
SNAPSHOT = Path(__file__).with_name("aliases_snapshot.json.gz")


def parse(source: str, game: str, data) -> dict[int, list[str]]:
    """Lxns: {"aliases": [{"song_id", "aliases"}]}; Yuzuchan: [{"song_id", "name", "alias"}]."""
    rows = data.get("aliases", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    out: dict[int, list[str]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            sid = int(r.get("song_id"))
        except (TypeError, ValueError):
            continue
        if game == "mai":
            if sid >= 100000:          # 宴 charts
                continue
            sid %= 10000
        names = r.get("aliases") if "aliases" in r else r.get("alias")
        for a in names or []:
            a = str(a).strip()
            if a and len(a) <= 40:
                out.setdefault(sid, []).append(a)
    return out


def merge(*maps: dict[int, list[str]]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for m in maps:
        for sid, names in m.items():
            cur = out.setdefault(int(sid), [])
            low = {x.lower() for x in cur}
            for n in names:
                if n.lower() not in low:
                    cur.append(n)
                    low.add(n.lower())
    return out


class AliasStore:
    def __init__(self, cache_dir: str | Path, game: str, proxy: str | None = None):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.game = game
        self.proxy = proxy
        self.local_path = self.dir / "local_aliases.json"
        self.maps: dict[str, dict[int, list[str]]] = {}
        self.fetched_at = 0.0
        self.status: dict[str, str] = {}
        self.shared: dict[int, list[str]] = {}      # 共享外号库（core.aliasshare）里这个游戏的部分；不写进本机库
        self.load()

    # ---------- files ----------
    def _cache(self, source: str) -> Path:
        return self.dir / f"aliases_{source}.json"

    def load(self) -> None:
        snap = {}
        try:
            with gzip.open(SNAPSHOT, "rt", encoding="utf-8") as f:
                snap = json.load(f).get(self.game, {})
        except (OSError, ValueError):
            pass
        for source in SOURCES[self.game]:
            p = self._cache(source)
            m = None
            if p.exists():
                try:
                    m = parse(source, self.game, json.loads(p.read_text("utf-8")))
                    self.status[source] = f"缓存 {len(m)} 首"
                except (OSError, ValueError):
                    m = None
            if not m:
                m = {int(k): v for k, v in (snap.get(source) or {}).items()}
                self.status[source] = f"内置 {len(m)} 首" if m else "无"
            self.maps[source] = m

    def local(self) -> dict[str, int]:
        try:
            return {str(k): int(v) for k, v in json.loads(self.local_path.read_text("utf-8")).items()}
        except (OSError, ValueError):
            return {}

    def _save_local(self, d: dict[str, int]) -> None:
        tmp = self.local_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.local_path)

    def add_local(self, alias: str, song_id: int) -> None:
        d = self.local()
        d[alias.strip()] = int(song_id)
        self._save_local(d)

    def remove_local(self, alias: str) -> bool:
        d = self.local()
        hit = next((k for k in d if k.lower() == alias.strip().lower()), None)
        if hit is None:
            return False
        del d[hit]
        self._save_local(d)
        return True

    def merged(self) -> dict[int, list[str]]:
        loc: dict[int, list[str]] = {}
        for a, sid in self.local().items():
            loc.setdefault(sid, []).append(a)
        return merge(loc, self.shared, *(self.maps.get(s, {}) for s in SOURCES[self.game]))

    def count(self) -> int:
        return sum(len(v) for v in self.merged().values())

    # ---------- download ----------
    async def refresh(self, force: bool = False, hours: float = 24, budget: float = 40) -> bool:
        """Returns True when anything new was downloaded."""
        if not force and self.fetched_at and time.time() - self.fetched_at < hours * 3600:
            return False
        changed = False
        for source, url in SOURCES[self.game].items():
            p = self._cache(source)
            if not force and p.exists() and time.time() - p.stat().st_mtime < hours * 3600:
                continue
            try:
                await asyncio.wait_for(self._download(source, url, p), budget)
                changed = True
            except Exception as e:  # noqa: BLE001
                self.status[source] = f"下载失败（{type(e).__name__}），用{self.status.get(source, '旧数据')}"
                log.warning("[otoge] 别名库 %s/%s 下载失败：%s", self.game, source, e or type(e).__name__)
        self.fetched_at = time.time()
        if changed:
            self.load()
        return changed

    async def _download(self, source: str, url: str, p: Path) -> None:
        kw = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                     headers={"user-agent": "astrbot_plugin_otoge_prober"}, **kw) as c:
            r = await c.get(url)
            r.raise_for_status()
            m = parse(source, self.game, r.json())
            if len(m) < 50:
                raise ValueError(f"only {len(m)} songs")
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(r.content)
            os.replace(tmp, p)


def build_snapshot(src_dir: str, out: str | Path = SNAPSHOT) -> dict:
    """tools: build the bundled snapshot from downloaded lxns_mai.json / yuzu_mai.json / lxns_chu.json …"""
    snap: dict = {}
    for game, srcs in SOURCES.items():
        for source in srcs:
            p = Path(src_dir) / f"{source}_{game}.json"
            if p.exists():
                snap.setdefault(game, {})[source] = parse(source, game, json.loads(p.read_text("utf-8")))
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    return {g: {s: len(m) for s, m in d.items()} for g, d in snap.items()}
