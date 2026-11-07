"""Constants shared by every module: difficulties, ranks, flags, regions."""
from __future__ import annotations

import re

try:
    from ..core.privsrv import servers as _priv
except ImportError:  # tests import mai as a top-level package
    from core.privsrv import servers as _priv

REGIONS = ("intl", "jp", "cn")        # servers with their own song catalog (versions / constants)
NET_REGIONS = ("intl", "jp")          # served by SEGA maimai DX NET; cn goes through 水鱼 / 落雪查分器
# 私服（MuNET …）：成绩来自私服网站，曲库借日服的
PRIV_REGIONS = tuple(k for k in _priv.KEYS if _priv.supports(k, "mai"))
# 「API 区服」：成绩来自查分接口，B35 / B15 分组和定数由对方给好（国服查分器、私服）；没有 NET 页面
API_REGIONS = ("cn", *PRIV_REGIONS)
BIND_REGIONS = (*REGIONS, *PRIV_REGIONS)
REGION_NAMES = {"intl": "国际服", "jp": "日服", "cn": "国服", **{k: _priv.NAMES[k] for k in PRIV_REGIONS}}
REGION_ALIASES = {
    "intl": "intl", "国际服": "intl", "国际": "intl", "国服外": "intl", "int": "intl", "international": "intl",
    "jp": "jp", "日服": "jp", "日本": "jp", "japan": "jp",
    "cn": "cn", "国服": "cn", "中国": "cn", "china": "cn", "水鱼": "cn",
    "落雪": "cn", "lxns": "cn", "luoxue": "cn",
    **{a: k for a, k in _priv.ALIASES.items() if k in PRIV_REGIONS},
}


def catalog_region(region: str | None) -> str | None:
    """查曲库 / 定数 / 版本用哪个服：私服借日服，其余是自己。"""
    return "jp" if region in PRIV_REGIONS else region
NET_BASE = {
    "intl": "https://maimaidx-eng.com",
    "jp": "https://maimaidx.jp",
}

# NET difficulty index → name
DIFFS = ("basic", "advanced", "expert", "master", "remaster")
DIFF_INDEX = {d: i for i, d in enumerate(DIFFS)}
DIFF_INDEX["utage"] = 10
DIFF_LABEL = {"basic": "BASIC", "advanced": "ADVANCED", "expert": "EXPERT",
              "master": "MASTER", "remaster": "Re:MASTER", "utage": "宴"}
DIFF_ALIASES = {
    "绿": "basic", "basic": "basic", "bsc": "basic",
    "黄": "advanced", "advanced": "advanced", "adv": "advanced",
    "红": "expert", "expert": "expert", "exp": "expert",
    "紫": "master", "master": "master", "mas": "master",
    "白": "remaster", "remaster": "remaster", "re:master": "remaster", "rem": "remaster", "re": "remaster",
}

# Achievement is stored as an integer in 1/10000 percent (100.5000% → 1005000).
ACH_SCALE = 10000

# (min achievement in units, coefficient ×10, rank key). Same table as DXRating's
# SCORE_COEFFICIENT_TABLE; the x.9999 rows are the "just below the next rank" caps.
SCORE_COEFFICIENTS: tuple[tuple[int, int, str], ...] = (
    (0, 0, "d"),
    (100000, 16, "d"),
    (200000, 32, "d"),
    (300000, 48, "d"),
    (400000, 64, "d"),
    (500000, 80, "c"),
    (600000, 96, "b"),
    (700000, 112, "bb"),
    (750000, 120, "bbb"),
    (799999, 128, "bbb"),
    (800000, 136, "a"),
    (900000, 152, "aa"),
    (940000, 168, "aaa"),
    (969999, 176, "aaa"),
    (970000, 200, "s"),
    (980000, 203, "sp"),
    (989999, 206, "sp"),
    (990000, 208, "ss"),
    (995000, 211, "ssp"),
    (999999, 214, "ssp"),
    (1000000, 216, "sss"),
    (1004999, 222, "sss"),
    (1005000, 224, "sssp"),
)
ACH_CAP = 1005000
RANK_LABEL = {"d": "D", "c": "C", "b": "B", "bb": "BB", "bbb": "BBB", "a": "A", "aa": "AA",
              "aaa": "AAA", "s": "S", "sp": "S+", "ss": "SS", "ssp": "SS+", "sss": "SSS", "sssp": "SSS+"}

# Combo / sync flags. NET uses several file-name spellings for the same icon
# (music_icon_fcp.png on the score list, fcplus.png on the play log), so every
# spelling is normalised here.
FC_FLAGS = ("fc", "fcp", "ap", "app")
FS_FLAGS = ("sync", "fs", "fsp", "fsd", "fsdp")
FLAG_LABEL = {"fc": "FC", "fcp": "FC+", "ap": "AP", "app": "AP+",
              "sync": "SYNC", "fs": "FS", "fsp": "FS+", "fsd": "FDX", "fsdp": "FDX+"}
_FLAG_SPELLINGS = {
    "fc": "fc", "fcp": "fcp", "fcplus": "fcp",
    "ap": "ap", "app": "app", "applus": "app",
    "sync": "sync", "fs": "fs", "fsp": "fsp", "fsplus": "fsp",
    "fsd": "fsd", "fdx": "fsd", "fsdp": "fsdp", "fsdplus": "fsdp", "fdxp": "fsdp", "fdxplus": "fsdp",
}
_RANK_SPELLINGS = {k: k for k in RANK_LABEL} | {"sssplus": "sssp", "ssplus": "ssp", "splus": "sp"}


def icon_stem(src: str | None) -> str:
    """'https://…/img/music_icon_fcp.png?ver=1.50' → 'fcp'; '…/playlog/fsdplus.png' → 'fsdplus'."""
    if not src:
        return ""
    name = src.split("?")[0].rsplit("/", 1)[-1]
    name = name.rsplit(".", 1)[0].lower()
    for prefix in ("music_icon_", "playlog_", "icon_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def flag_from_icon(src: str | None) -> tuple[str | None, str | None]:
    """Return (kind, flag) where kind is 'fc', 'fs' or None."""
    stem = _FLAG_SPELLINGS.get(icon_stem(src))
    if stem in FC_FLAGS:
        return "fc", stem
    if stem in FS_FLAGS:
        return "fs", stem
    return None, None


def rank_from_icon(src: str | None) -> str | None:
    return _RANK_SPELLINGS.get(icon_stem(src))


_DIFF_RE = re.compile(r"diff_(basic|advanced|expert|master|remaster|utage)")


def diff_from_icon(src: str | None) -> str | None:
    m = _DIFF_RE.search(src or "")
    return m.group(1) if m else None


def type_from_icon(src: str | None) -> str | None:
    s = src or ""
    if "music_dx" in s:
        return "dx"
    if "music_standard" in s:
        return "std"
    if "utage" in s:
        return "utage"
    return None


def parse_achievement(text: str) -> int | None:
    """'100.5329%' → 1005329; tolerant of spaces, commas, a missing percent sign."""
    m = re.search(r"(\d{1,3})\.(\d{1,4})", text or "")
    if not m:
        m2 = re.search(r"(\d{1,3})\s*%", text or "")
        return int(m2.group(1)) * ACH_SCALE if m2 else None
    return int(m.group(1)) * ACH_SCALE + int(m.group(2).ljust(4, "0"))


def fmt_ach(units: int) -> str:
    return f"{units // ACH_SCALE}.{units % ACH_SCALE:04d}%"


def parse_pair(text: str) -> tuple[int, int] | None:
    """'2,829 / 3,090' → (2829, 3090)."""
    m = re.search(r"([\d,]+)\s*/\s*([\d,]+)", text or "")
    if not m:
        return None
    return int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))


# DX star thresholds on the DX score ratio (85/90/93/95/97%).
DX_STAR_THRESHOLDS = (0.85, 0.90, 0.93, 0.95, 0.97)


def dx_stars(score: int, total: int) -> int:
    if not total:
        return 0
    r = score / total
    return sum(1 for t in DX_STAR_THRESHOLDS if r >= t)
