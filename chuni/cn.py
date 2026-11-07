"""中二节奏国服（水鱼查分器）+ per-server chart constants."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from .models import ComboLamp, Difficulty, Profile, Rank, Score

log = logging.getLogger("chuni.cn")

TACHI_CHARTS = "https://raw.githubusercontent.com/zkldi/Tachi/refs/heads/main/db/seeds/charts-chunithm.json"
DF_MUSIC = "https://www.diving-fish.com/api/chunithmprober/music_data"
_TACHI_DIFF = {"BASIC": Difficulty.BASIC, "ADVANCED": Difficulty.ADVANCED, "EXPERT": Difficulty.EXPERT,
               "MASTER": Difficulty.MASTER, "ULTIMA": Difficulty.ULTIMA}
# Tachi version tags in release order (JP tags have no suffix; -intl / -omni are other servers)
TACHI_ORDER = ("paradiselost", "new", "newplus", "sun", "sunplus", "luminous", "luminousplus", "verse", "xverse",
               "xversex", "mate", "matex", "next")


class CNBindings:
    """QQ → 水鱼 username / QQ (no secrets, plain JSON)."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "cn_bindings.json"
        try:
            self.d: dict[str, dict] = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.d = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.path)

    def get(self, qq: str) -> dict | None:
        return self.d.get(str(qq))

    def set(self, qq: str, binding: dict, name: str = "") -> None:
        self.d[str(qq)] = {**binding, "name": name, "bound_at": int(time.time())}
        self._save()

    def remove(self, qq: str) -> bool:
        if self.d.pop(str(qq), None) is None:
            return False
        self._save()
        return True

    def items(self) -> list[dict]:
        return [{"qq": k, "name": v.get("name"), "bound_at": v.get("bound_at")} for k, v in sorted(self.d.items())]

    def __contains__(self, qq: object) -> bool:
        return str(qq) in self.d


_FC = {"fullcombo": ComboLamp.FULL_COMBO, "fc": ComboLamp.FULL_COMBO, "alljustice": ComboLamp.ALL_JUSTICE,
       "aj": ComboLamp.ALL_JUSTICE, "alljusticecritical": ComboLamp.ALL_JUSTICE_CRITICAL,
       "ajc": ComboLamp.ALL_JUSTICE_CRITICAL}


def df_score(r: dict) -> Score:
    li = int(r.get("level_index") or 0)
    diff = Difficulty(li) if 0 <= li <= 4 else Difficulty.MASTER
    sc = int(r.get("score") or 0)
    s = Score(song_id=int(r["mid"]) if str(r.get("mid", "")).isdigit() else None, title=r.get("title") or "",
              difficulty=diff, score=sc, rank=Rank.from_score(sc),
              combo_lamp=_FC.get(str(r.get("fc") or "").lower().replace(" ", ""), ComboLamp.NONE))
    s.const = float(r["ds"]) if r.get("ds") is not None else None
    s.level = str(r.get("level") or "") or None
    return s


# 国服 has its own version names (中二节奏 2026 …). The plugin never shows them: B50 artwork, logos and the
# version label use the 日服 / 国际服 version the 国服 build is based on (its UI / rating rules).
CN_BASE_VERSIONS = (       # (国服 release date, 日服 version it is based on)
    ("2024-09-12", "LUMINOUS"),     # 中二节奏 2025
    ("2025-09-16", "VERSE"),        # 中二节奏 2026: VERSE UI and rating (B30 + 新曲 20)
    ("2026-09-10", "X-VERSE"),      # 中二节奏 2027: songs from the X-VERSE range (players call it X-VERSE)
)


def cn_base_version(today: str | None = None) -> str:
    today = today or time.strftime("%Y-%m-%d")
    cur = CN_BASE_VERSIONS[0][1]
    for date, ver in CN_BASE_VERSIONS:
        if today >= date:
            cur = ver
    return cur


_LX_FC = {"fullcombo": ComboLamp.FULL_COMBO, "alljustice": ComboLamp.ALL_JUSTICE,
          "alljusticecritical": ComboLamp.ALL_JUSTICE_CRITICAL}


def lx_score(r: dict) -> Score | None:
    """One 落雪 CHUNITHM score → Score (WORLD'S END skipped: not rated)."""
    try:
        li = int(r.get("level_index") or 0)
        sid = int(r.get("id"))
    except (TypeError, ValueError):
        return None
    if not 0 <= li <= 4:
        return None
    sc = int(r.get("score") or 0)
    s = Score(song_id=sid, title=r.get("song_name") or "", difficulty=Difficulty(li), score=sc,
              rank=Rank.from_score(sc), combo_lamp=_LX_FC.get(str(r.get("full_combo") or "").lower(), ComboLamp.NONE))
    s.level = str(r.get("level") or "") or None
    return s


def lx_profile(d: dict) -> Profile:
    return Profile(name=d.get("name") or "", level=int(d.get("level") or 0), rating=float(d.get("rating") or 0),
                   friend_code=str(d.get("friend_code") or "") or None,
                   play_count=d.get("total_play_count"), uploaded_at=str(d.get("upload_time") or ""))


def df_profile(data: dict) -> Profile:
    return Profile(name=data.get("nickname") or data.get("username") or "", level=0,
                   rating=float(data.get("rating") or 0))


class ServerConsts:
    """(song_id, Difficulty) → {"jp": x, "cn": y}; 国际服 constants come from the main song DB."""

    def __init__(self, cache_dir: Path, proxy: str | None = None):
        self.proxy = proxy
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jp: dict[tuple[int, Difficulty], float] = {}
        self.cn: dict[tuple[int, Difficulty], float] = {}
        self.bpm: dict[int, float] = {}
        self.jp_version = ""
        self.loaded_at = 0.0
        self.fetched_at = 0.0
        self.post_load: list = []          # 加载完调用：用 otoge-db 补日服新歌定数（core/progress）

    async def ensure_loaded(self, force: bool = False, refresh_hours: float = 24) -> None:
        if not force and self.fetched_at and time.time() - self.fetched_at < refresh_hours * 3600:
            return
        # 水鱼 first: it is small (≈1 MB) and is the only source of 国服 constants. Tachi's chart file is ≈10 MB
        # and changes rarely, so it is refreshed less often; each download has its own time budget so a slow
        # GitHub never blocks 水鱼.
        for name, url, hours, budget in (("df-chu-music.json", DF_MUSIC, refresh_hours, 45),
                                         ("tachi-charts.json", TACHI_CHARTS, refresh_hours * 3, 180)):
            p = self.dir / name
            if force or not p.exists() or time.time() - p.stat().st_mtime > hours * 3600:
                try:
                    await asyncio.wait_for(self._download(url, p), budget)
                except Exception as e:  # noqa: BLE001
                    log.warning("下载 %s 失败：%s", name, e or type(e).__name__)
        self.fetched_at = time.time()
        self.load_files()

    async def _download(self, url: str, p: Path) -> None:
        kw = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(headers={"user-agent": "astrbot_plugin_otoge_prober"}, timeout=60,
                                     follow_redirects=True, **kw) as c:
            r = await c.get(url)
            r.raise_for_status()
            json.loads(r.content)            # don't replace a good cache with an error page
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(r.content)
            tmp.replace(p)

    def load_files(self) -> None:
        p = self.dir / "tachi-charts.json"
        if p.exists():
            try:
                self.load_tachi(json.loads(p.read_text("utf-8")))
            except Exception as e:  # noqa: BLE001
                log.warning("Tachi 定数解析失败：%s", e)
        p = self.dir / "df-chu-music.json"
        if p.exists():
            try:
                self.load_df(json.loads(p.read_text("utf-8")))
            except Exception as e:  # noqa: BLE001
                log.warning("水鱼定数解析失败：%s", e)
        for fn in self.post_load:
            try:
                fn(self)
            except Exception as e:  # noqa: BLE001
                log.warning("定数补充失败：%s", e)
        self.loaded_at = time.time()

    def load_tachi(self, charts: list[dict]) -> None:
        tags = {v for c in charts for v in c.get("versions", []) if "-" not in v}
        latest = max(tags, key=lambda t: TACHI_ORDER.index(t) if t in TACHI_ORDER else -1) if tags else ""
        self.jp_version = latest
        out = {}
        for c in charts:
            diff = _TACHI_DIFF.get(c.get("difficulty", ""))
            data = c.get("data") or {}
            sid = data.get("inGameID")
            if diff is None or sid is None or not c.get("isPrimary", True):
                continue
            hist = (data.get("levelHistory") or {}).get(latest) or None
            if latest in c.get("versions", []):
                v = (hist or {}).get("levelNum", c.get("levelNum"))
                if v:
                    out[(int(sid), diff)] = float(v)
        self.jp = out

    def load_df(self, music: list[dict]) -> None:
        out = {}
        bpm = {}
        for m in music:
            sid = m.get("id")
            if not str(sid).isdigit():
                continue
            try:
                b = float((m.get("basic_info") or {}).get("bpm") or 0)
                if b > 0:
                    bpm[int(sid)] = b
            except (TypeError, ValueError):
                pass
            for i, ds in enumerate(m.get("ds") or []):
                if i <= 4 and ds:
                    out[(int(sid), Difficulty(i))] = float(ds)
        self.cn = out
        self.bpm = bpm

    def get(self, song_id: int, diff: Difficulty) -> dict[str, float]:
        out = {}
        if (v := self.jp.get((song_id, diff))) is not None:
            out["jp"] = v
        if (v := self.cn.get((song_id, diff))) is not None:
            out["cn"] = v
        return out
