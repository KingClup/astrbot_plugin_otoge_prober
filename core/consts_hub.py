"""定数中心：把多个社区定数表合到一起，按游戏 / 区服选最可信的那个。

为什么要多个来源：每个表都有落后的时候（Tachi 到现在还没有 Mate；DXRating 的国服定数和水鱼 / 落雪
对不上 51 张），单靠一个必然出错。2026-11 实测各来源（MASTER / ULTIMA / Re:MASTER）：

  中二 日服   reiwa 定数表、otoge-db、beerpsi、zetaraku 四家 100% 一致（都是 Mate）；Tachi 差 40 张（停在 X-VERSE-X）
  中二 国际服 国际服和日服同版本时定数一样（Tachi 两边 0 差异）→ 同版本就用日服最新的
  中二 国服   水鱼 / 落雪
  舞萌 日服   DXRating、otoge-db、zetaraku 基本一致（1 张不同）
  舞萌 国服   水鱼和落雪 100% 一致，DXRating 有 51 张不同 → 以落雪 / 水鱼为准
  舞萌 国际服 DXRating（按版本记录定数，国际服落后日服时只有它对）

结构上不绑定游戏：来源 = (名字, 游戏, 区服, 下载地址, 解析函数)，谱面的键由解析函数决定
（中二 / 音击 = (曲目 ID, 难度序号)，舞萌 = (歌名, dx|std, 难度序号)）。以后加音击、私服只要多注册来源。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

import httpx

log = logging.getLogger("astrbot")


def norm_title(t: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(t or ""))).lower()


# ---------- 解析函数：原始 JSON → {(谱面键): 定数} ----------
_CHU_D = {"BAS": 0, "ADV": 1, "EXP": 2, "MAS": 3, "ULT": 4,
          "basic": 0, "advanced": 1, "expert": 2, "master": 3, "ultima": 4,
          "BASIC": 0, "ADVANCED": 1, "EXPERT": 2, "MASTER": 3, "ULTIMA": 4}
_MAI_D = {"basic": 0, "advanced": 1, "expert": 2, "master": 3, "remaster": 4}


def parse_reiwa_chu(d) -> dict:
    """reiwa.f5.si/chunithm_record.json：[{idx, diff, const, unknown}]；unknown=1 是估计值，不要。"""
    out = {}
    for x in d or []:
        i = _CHU_D.get(x.get("diff"))
        if i is None or not str(x.get("idx", "")).isdigit() or x.get("unknown"):
            continue
        try:
            out[(int(x["idx"]), i)] = float(x["const"])
        except (TypeError, ValueError):
            continue
    return out


def parse_otoge_chu(d) -> dict:
    out = {}
    for x in d or []:
        if not str(x.get("id", "")).isdigit():
            continue
        for k, i in (("bas", 0), ("adv", 1), ("exp", 2), ("mas", 3), ("ult", 4)):
            try:
                v = float(x.get(f"lev_{k}_i") or "")
            except ValueError:
                continue
            out[(int(x["id"]), i)] = v
    return out


def parse_beerpsi_chu(d) -> dict:
    out = {}
    for s in d or []:
        if not str(s.get("id", "")).isdigit():
            continue
        for c in s.get("charts") or []:
            i = _CHU_D.get(c.get("difficulty"))
            if i is not None and c.get("const"):
                out[(int(s["id"]), i)] = float(c["const"])
    return out


def parse_df_chu(d) -> dict:
    out = {}
    for m in d or []:
        if not str(m.get("id", "")).isdigit() or int(m["id"]) >= 8000:
            continue
        for i, v in enumerate(m.get("ds") or []):
            if i <= 4 and v:
                out[(int(m["id"]), i)] = float(v)
    return out


def parse_lx_chu(d) -> dict:
    out = {}
    for s in (d or {}).get("songs") or []:
        sid = s.get("id")
        if not isinstance(sid, int) or sid >= 8000:
            continue
        for c in s.get("difficulties") or []:
            li = c.get("difficulty")
            if isinstance(li, int) and li <= 4 and c.get("level_value"):
                out[(sid, li)] = float(c["level_value"])
    return out


_TACHI_ORDER = ["paradiselost", "new", "newplus", "sun", "sunplus", "luminous", "luminousplus", "verse", "xverse",
                "xversex", "mate", "matex", "next"]


def make_tachi_parser(region: str):
    """Tachi charts-chunithm.json：取这个服最新版本标签下的定数（日服标签不带后缀，国际服是 -intl）。"""
    def rank(tag: str) -> int:
        base = tag[:-len("-intl")] if tag.endswith("-intl") else tag
        return _TACHI_ORDER.index(base) if base in _TACHI_ORDER else -1

    def parse(d) -> dict:
        tags = {v for c in d or [] for v in c.get("versions", [])
                if (v.endswith("-intl") if region == "intl" else "-" not in v)}
        if not tags:
            return {}
        latest = max(tags, key=rank)
        out = {}
        for c in d:
            i = _CHU_D.get(c.get("difficulty"))
            data = c.get("data") or {}
            sid = data.get("inGameID")
            if i is None or sid is None or latest not in c.get("versions", []) or not c.get("isPrimary", True):
                continue
            v = ((data.get("levelHistory") or {}).get(latest) or {}).get("levelNum", c.get("levelNum"))
            if v:
                out[(int(sid), i)] = float(v)
        return out
    return parse


def make_zeta_parser(game: str, region: str, id_by_title: Callable[[], dict] | None = None):
    """zetaraku arcade-songs data.json：internalLevel 为空时 internalLevelValue 只是按等级估的，不要。"""
    def parse(d) -> dict:
        out = {}
        ids = id_by_title() if id_by_title else None
        dmap = _MAI_D if game == "mai" else _CHU_D
        for s in (d or {}).get("songs") or []:
            for sh in s.get("sheets") or []:
                i = dmap.get(sh.get("difficulty"))
                if i is None or not (sh.get("regions") or {}).get(region):
                    continue
                ov = (sh.get("regionOverrides") or {}).get(region) or {}
                v = ov.get("internalLevelValue")
                if v is None and sh.get("internalLevel") not in (None, ""):
                    v = sh.get("internalLevelValue")
                if v is None:
                    continue
                if game == "mai":
                    t = sh.get("type")
                    if t not in ("dx", "std"):
                        continue
                    out[(norm_title(s.get("title")), t, i)] = float(v)
                else:
                    sid = (ids or {}).get(norm_title(s.get("title")))
                    if sid is not None:
                        out[(sid, i)] = float(v)
        return out
    return parse


def parse_otoge_mai(d) -> dict:
    out = {}
    for x in d or []:
        for t, pre in (("dx", "dx_lev_"), ("std", "lev_")):
            for k, i in (("bas", 0), ("adv", 1), ("exp", 2), ("mas", 3), ("remas", 4)):
                try:
                    v = float(x.get(f"{pre}{k}_i") or "")
                except ValueError:
                    continue
                out[(norm_title(x.get("title")), t, i)] = v
    return out


def parse_df_mai(d) -> dict:
    out = {}
    for s in d or []:
        if not str(s.get("id", "")).isdigit() or int(s["id"]) >= 100000:
            continue
        t = "dx" if s.get("type") == "DX" else "std"
        for i, v in enumerate(s.get("ds") or []):
            if v:
                out[(norm_title(s.get("title") or (s.get("basic_info") or {}).get("title")), t, i)] = float(v)
    return out


def parse_lx_mai(d) -> dict:
    out = {}
    for s in (d or {}).get("songs") or []:
        if int(s.get("id") or 0) >= 100000:
            continue
        for t, lst in (s.get("difficulties") or {}).items():
            if t not in ("dx", "standard"):
                continue
            for c in lst or []:
                if c.get("level_value") and isinstance(c.get("difficulty"), int):
                    out[(norm_title(s.get("title")), "dx" if t == "dx" else "std", c["difficulty"])] = \
                        float(c["level_value"])
    return out


@dataclass
class Source:
    name: str                 # 显示名
    game: str                 # mai / chu / ongeki …
    region: str               # jp / intl / cn（同版本时日服的也能给国际服用，见 priority）
    url: str
    parse: Callable
    cache: str                # 缓存文件名
    shared_cache: str = ""    # 别的模块已经下载好的文件（有就直接读，不重复下载）


@dataclass
class Merged:
    values: dict = field(default_factory=dict)        # 谱面键 → 定数
    chosen: dict = field(default_factory=dict)        # 来源名 → 用了多少张
    conflicts: int = 0                                # 别的来源给了不同数值的谱面数
    examples: list = field(default_factory=list)


def merge(cands: list[tuple[str, dict]]) -> Merged:
    """按顺序取第一个有值的来源；其他来源数值不同就记一次冲突。"""
    m = Merged()
    keys = set()
    for _n, d in cands:
        keys |= set(d)
    for k in keys:
        vals = [(n, d[k]) for n, d in cands if k in d]
        n0, v0 = vals[0]
        m.values[k] = v0
        m.chosen[n0] = m.chosen.get(n0, 0) + 1
        if any(abs(v - v0) > 0.001 for _n, v in vals[1:]):
            m.conflicts += 1
            if len(m.examples) < 5:
                m.examples.append((k, vals))
    return m


class ConstsHub:
    def __init__(self, root: str, proxy: str | None = None, transport=None):
        self.dir = os.path.join(root, "consts")
        os.makedirs(self.dir, exist_ok=True)
        self.proxy, self.transport = proxy, transport
        self.sources: list[Source] = []
        self.data: dict[str, dict] = {}            # 来源名 → 解析后的 {键: 定数}
        self.status: dict[str, str] = {}
        self.merged: dict[tuple[str, str], Merged] = {}
        self._lock = asyncio.Lock()

    def register(self, src: Source) -> None:
        self.sources.append(src)

    # ---------- load / download ----------
    def _raw(self, src: Source):
        for p in filter(None, (src.shared_cache, os.path.join(self.dir, src.cache))):
            try:
                with open(p, encoding="utf-8-sig") as f:
                    return json.load(f), os.path.getmtime(p)
            except Exception:  # noqa: BLE001
                continue
        return None, 0

    def load_cached(self) -> None:
        for src in self.sources:
            raw, mt = self._raw(src)
            self._parse(src, raw, mt, "缓存")

    def _parse(self, src: Source, raw, mtime: float, how: str) -> None:
        if raw is None:
            self.data.setdefault(src.name, {})
            self.status.setdefault(src.name, "还没下载")
            return
        try:
            self.data[src.name] = src.parse(raw)
            self.status[src.name] = f"{len(self.data[src.name])} 张 · {how} {time.strftime('%m-%d %H:%M', time.localtime(mtime))}"
        except Exception as e:  # noqa: BLE001
            self.status[src.name] = f"解析失败（{type(e).__name__}）"
            log.warning(f"[otoge] 定数来源 {src.name} 解析失败：{e}")

    async def download(self, max_age_hours: float | None = None) -> None:
        """max_age_hours：自己的缓存文件比这还新的来源不再下载（启动时 6 小时；每天定时传 None）。"""
        async with self._lock:
            kw = {"transport": self.transport} if self.transport is not None else (
                {"proxy": self.proxy} if self.proxy else {})
            async with httpx.AsyncClient(timeout=60, follow_redirects=True,
                                         headers={"User-Agent": "Mozilla/5.0 (astrbot_plugin_otoge_prober)"}, **kw) as c:
                fetched: dict[str, object] = {}          # 同一次里同一个地址只下载一次（Tachi 日服 / 国际服共用一个文件）
                for src in self.sources:
                    if src.url in fetched:
                        self._parse(src, fetched[src.url], time.time(), "下载")
                        continue
                    if src.shared_cache and os.path.exists(src.shared_cache) and \
                            time.time() - os.path.getmtime(src.shared_cache) < 6 * 3600:
                        raw, mt = self._raw(src)          # 别的模块刚下载过，直接用
                        self._parse(src, raw, mt, "共用")
                        continue
                    own = os.path.join(self.dir, src.cache)
                    if max_age_hours is not None and os.path.exists(own) and \
                            time.time() - os.path.getmtime(own) < max_age_hours * 3600:
                        raw, mt = self._raw(src)
                        if raw is not None:
                            self._parse(src, raw, mt, "缓存")
                            continue
                    try:
                        r = await c.get(src.url)
                        r.raise_for_status()
                        raw = json.loads(r.content.decode("utf-8-sig"))
                        p = os.path.join(self.dir, src.cache)
                        with open(p + ".tmp", "w", encoding="utf-8") as f:
                            json.dump(raw, f, ensure_ascii=False)
                        os.replace(p + ".tmp", p)
                        fetched[src.url] = raw
                        self._parse(src, raw, time.time(), "下载")
                    except Exception as e:  # noqa: BLE001
                        raw, mt = self._raw(src)
                        self._parse(src, raw, mt, "缓存")
                        self.status[src.name] = f"下载失败（{type(e).__name__}）" + (
                            f"，用缓存 {len(self.data.get(src.name) or {})} 张" if raw is not None else "")
                        log.warning(f"[otoge] 定数来源 {src.name} 下载失败：{e}")

    # ---------- merge ----------
    def build(self, plan: dict[tuple[str, str], list[str]]) -> dict[tuple[str, str], Merged]:
        """plan: (游戏, 区服) → 来源名的优先顺序。"""
        out = {}
        for key, names in plan.items():
            out[key] = merge([(n, self.data[n]) for n in names if self.data.get(n)])
        self.merged = out
        return out

    def summary(self, game: str, region: str) -> str:
        m = self.merged.get((game, region))
        if m is None or not m.values:
            return ""
        used = " · ".join(f"{n} {c}" for n, c in sorted(m.chosen.items(), key=lambda kv: -kv[1]))
        return f"{len(m.values)} 张（{used}）" + (f"，{m.conflicts} 张来源说法不一" if m.conflicts else "")
