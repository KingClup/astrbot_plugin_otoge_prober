"""MuNET（portal.mumur.net）客户端。

只用公开接口，不登录，按网站用户名查（2026-11-06 用公开主页实测；接口取自 MuNET 网页前端，
不是公开文档，可能会变）：
  GET /api/v3/public/u/{用户名}?game=mai2|chusan   资料 + 隐私设置
  GET /api/v3/public/u/{用户名}/mai2/rating        B35 / B15 + 成绩明细 + 带「按版本定数」的曲目信息
  GET /api/v3/public/u/{用户名}/mai2/playlog       最近 50 条
  GET /api/v3/public/u/{用户名}/chusan/rating      B30 / N20 / R10 + 成绩明细 + 曲目信息
  GET /api/v3/public/u/{用户名}/chusan/playlog     最近 50 条（每条带一个很大的 user 对象，约 2.5MB）

服务器自己按玩家客户端版本分好了新旧曲；用它给的定数算出来和网站显示的 rating 一致
（实测舞萌 / 中二都一致），所以这里直接用服务器的分组和定数。

两层：parse_* 是纯函数（测试只测这层）；MunetClient 只管发请求。
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import quote

from .models import (
    MAI_FC, MAI_FS, ChuBest, ChuPlay, ChuScore, MaiBest, MaiPlay, MaiScore,
    PrivError, PrivHidden, PrivNotFound, PrivProfile,
)

KEY = "munet"
NAME = "MuNET"
DEFAULT_BASE = "https://apidashboard3-cf.mumur.net"

# 网站隐私设置（user.privacy 位标志）里查分会碰到的几位
HIDE_GAME_INFO = 1
HIDE = {"mai2": 2, "chusan": 4}
MAI2_HIDE_RATING, MAI2_HIDE_B35, MAI2_HIDE_B15, MAI2_HIDE_PLAYLOG = 32, 256, 512, 1024
CHU_HIDE_RATING, CHU_HIDE_B30, CHU_HIDE_N20, CHU_HIDE_PLAYLOG = 16384, 131072, 262144, 1048576

GAME_NAMES = {"mai2": "舞萌", "chusan": "中二"}


# ---------------------------------------------------------------- 资料

def parse_profile(js: Any, username: str, game: str) -> tuple[PrivProfile, int]:
    """返回 (资料, 隐私位)。没这个人 / 没玩过这个游戏 / 整个游戏被隐藏时抛错。"""
    gname = GAME_NAMES.get(game, game)
    if not isinstance(js, dict) or js.get("error", 0) != 0 or not js.get("user"):
        raise PrivNotFound(f"{NAME} 上找不到用户「{username}」。用户名是网站个人主页地址 /u/ 后面那段")
    privacy = int(js["user"].get("privacy") or 0)
    if privacy & HIDE_GAME_INFO or privacy & HIDE.get(game, 0):
        raise PrivHidden(NAME, f"{gname}游戏数据")
    home = ((js.get("homepage") or {}).get(game)) or {}
    brief = ((js.get("data") or {}).get(game)) or {}
    if not home and not brief:
        raise PrivNotFound(f"「{username}」在 {NAME} 上还没有{gname}记录")
    plate = home.get("nameplate") or {}
    box = home.get("userBox") or {}
    rating = home.get("rating", box.get("rating", brief.get("rating")))
    return PrivProfile(
        server=KEY, game=game,
        username=js["user"].get("username") or username,
        name=home.get("name") or box.get("name") or brief.get("name") or "",
        rating=int(rating or 0),
        rating_highest=home.get("ratingHighest"),
        server_rank=home.get("serverRank"),
        rom_version=plate.get("lastRomVersion") or home.get("lastVersion") or "",
        last_play=str(home.get("lastPlay") or brief.get("lastPlay") or ""),
        plays=home.get("plays"),
    ), privacy


# ---------------------------------------------------------------- 定数按版本取

def mai_const_version(rom: str) -> Optional[int]:
    """舞萌客户端版本 → MuNET 定数表的 version：1.60→25、1.65→26、1.70→27（13 + 小版本 // 5）。"""
    m = re.match(r"^\s*1\.(\d{2})", rom or "")
    return 13 + int(m.group(1)) // 5 if m else None


def chu_const_version(rom: str) -> Optional[int]:
    """中二客户端版本 → MuNET 定数表的 version：2.45→24500、2.50→25000。"""
    m = re.match(r"^\s*(\d)\.(\d{2})", rom or "")
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 if m else None


def pick_const(constants: Any, want: Optional[int]) -> Optional[float]:
    """want 版本及以前最新的那个；认不出版本或都比它新时取最新的。"""
    rows = sorted((int(c["version"]), float(c["constant"])) for c in constants or []
                  if isinstance(c, dict) and c.get("version") is not None and c.get("constant") is not None)
    if not rows:
        return None
    if want is not None and (older := [r for r in rows if r[0] <= want]):
        return older[-1][1]
    return rows[-1][1]


def _data(js: Any, ok_key: str, what: str) -> dict:
    if not isinstance(js, dict) or js.get(ok_key, 0) != 0 or not isinstance(js.get("data"), dict):
        raise PrivError(f"{NAME} 返回了看不懂的{what}，可能接口改了")
    return js["data"]


# ---------------------------------------------------------------- 舞萌

def parse_mai_rating(js: Any, rom: str = "") -> MaiBest:
    data = _data(js, "error", "舞萌 B50")
    want = mai_const_version(rom)
    songs = {int(m["id"]): m for m in data.get("musicDetails") or [] if "id" in m}
    details = {(int(u["musicId"]), int(u["level"])): u for u in data.get("userDetails") or []}

    def chart_of(mid: int, level: int) -> dict:
        kind = 1 if mid >= 10000 else 0
        for c in (songs.get(mid % 10000) or {}).get("charts") or []:
            # utageId ≠ 0 是宴谱，难度序号会和普通谱撞，必须排掉
            if c.get("difficulty") == level and c.get("kind", kind) == kind and not c.get("utageId"):
                return c
        return {}

    def conv(e: dict) -> MaiScore:
        mid, lv = int(e["musicId"]), int(e["level"])
        det = details.get((mid, lv)) or {}
        return MaiScore(
            music_id=mid, level_index=lv, achievement=int(e["achievement"]),
            title=(songs.get(mid % 10000) or {}).get("name") or "",
            const=pick_const(chart_of(mid, lv).get("constants"), want),
            fc=MAI_FC.get(det.get("comboStatus"), ""), fs=MAI_FS.get(det.get("syncStatus"), ""),
            dx_score=det.get("deluxscoreMax"), play_count=det.get("playCount"),
            rom_version=e.get("romVersion"),
        )

    return MaiBest(old=[conv(e) for e in data.get("b35") or []], new=[conv(e) for e in data.get("b15") or []])


def parse_mai_playlog(js: Any) -> list[MaiPlay]:
    data = _data(js, "code", "舞萌游玩记录")
    names = {int(m["id"]): m.get("name") or "" for m in data.get("musicData") or [] if "id" in m}
    return [MaiPlay(
        music_id=int(p["musicId"]), level_index=int(p["level"]), achievement=int(p["achievement"]),
        title=names.get(int(p["musicId"]) % 10000, ""), dx_score=int(p.get("deluxscore") or 0),
        fc=MAI_FC.get(p.get("comboStatus"), ""), fs=MAI_FS.get(p.get("syncStatus"), ""),
        new_record=bool(p.get("isAchieveNewRecord")), rating_after=p.get("afterDeluxRating"),
        played_at=p.get("userPlayDate") or "", track=p.get("trackNo"),
    ) for p in data.get("playlog") or []]


# ---------------------------------------------------------------- 中二

def parse_chu_rating(js: Any, rom: str = "") -> ChuBest:
    data = _data(js, "error", "中二 B50")
    want = chu_const_version(rom)
    songs = {int(m["id"]): m for m in data.get("musicDetails") or [] if "id" in m}
    details = {(int(u["musicId"]), int(u["level"])): u for u in data.get("userDetails") or []}

    def conv(e: dict) -> ChuScore:
        mid, lv = int(e["musicId"]), int(e["level"])
        song = songs.get(mid) or {}
        chart = next((c for c in song.get("charts") or [] if c.get("difficulty") == lv), {})
        det = details.get((mid, lv)) or {}
        return ChuScore(
            music_id=mid, level_index=lv, score=int(e["achievement"]), title=song.get("name") or "",
            const=pick_const(chart.get("constants"), want),
            full_combo=bool(det.get("isFullCombo")), all_justice=bool(det.get("isAllJustice")),
            play_count=det.get("playCount"),
        )

    return ChuBest(best=[conv(e) for e in data.get("b30") or []], new=[conv(e) for e in data.get("n20") or []])


def parse_chu_playlog(js: Any) -> list[ChuPlay]:
    data = _data(js, "code", "中二游玩记录")
    names = {int(m["id"]): m.get("name") or "" for m in data.get("musicData") or [] if "id" in m}
    return [ChuPlay(
        music_id=int(p["musicId"]), level_index=int(p["level"]), score=int(p.get("score") or 0),
        title=names.get(int(p["musicId"]), ""), full_combo=bool(p.get("isFullCombo")),
        all_justice=bool(p.get("isAllJustice")), new_record=bool(p.get("isNewRecord")),
        played_at=str(p.get("userPlayDate") or ""), track=p.get("track"),
    ) for p in data.get("playlog") or []]


# ---------------------------------------------------------------- 客户端

GetJson = Callable[[str], Awaitable[tuple[int, Any]]]


class MunetClient:
    """get_json(url) -> (HTTP 状态码, 解析后的 JSON 或 None)。"""

    key, name = KEY, NAME

    def __init__(self, get_json: GetJson, base: str = DEFAULT_BASE):
        self._get = get_json
        self.base = base.rstrip("/")

    async def _fetch(self, path: str) -> Any:
        status, js = await self._get(self.base + path)
        if status == 404:
            raise PrivNotFound(f"{NAME} 上找不到这个用户")
        if status in (403, 418):
            # 2026-11-07 实测：MuNET 只接受从它自己网站页面发出的请求，机器人一律 418。不去伪装绕过。
            raise PrivError(f"{NAME} 现在不允许第三方查分工具读取数据（HTTP {status}），暂时查不了；"
                            "成绩可以去 portal.mumur.net 网站上看")
        if status != 200:
            raise PrivError(f"{NAME} 暂时连不上（HTTP {status}），稍后再试")
        return js

    @staticmethod
    def _u(cred) -> str:
        """cred：绑定记录 {"username": …}，或直接一个用户名。"""
        username = cred.get("username", "") if isinstance(cred, dict) else str(cred)
        return "/api/v3/public/u/" + quote(username.strip().lstrip("@"), safe="")

    async def profile(self, cred, game: str) -> tuple[PrivProfile, int]:
        js = await self._fetch(f"{self._u(cred)}?game={game}")
        return parse_profile(js, cred.get("username", "") if isinstance(cred, dict) else str(cred), game)

    async def mai_best(self, username) -> tuple[PrivProfile, MaiBest]:
        prof, privacy = await self.profile(username, "mai2")
        if privacy & MAI2_HIDE_RATING:
            raise PrivHidden(NAME, "舞萌 Rating")
        if privacy & (MAI2_HIDE_B35 | MAI2_HIDE_B15):
            raise PrivHidden(NAME, "舞萌 B35 / B15")
        js = await self._fetch(f"{self._u(username)}/mai2/rating")
        return prof, parse_mai_rating(js, prof.rom_version)

    async def mai_recent(self, username) -> tuple[PrivProfile, list[MaiPlay]]:
        prof, privacy = await self.profile(username, "mai2")
        if privacy & MAI2_HIDE_PLAYLOG:
            raise PrivHidden(NAME, "舞萌游玩记录")
        return prof, parse_mai_playlog(await self._fetch(f"{self._u(username)}/mai2/playlog"))

    async def chu_best(self, username) -> tuple[PrivProfile, ChuBest]:
        prof, privacy = await self.profile(username, "chusan")
        if privacy & CHU_HIDE_RATING:
            raise PrivHidden(NAME, "中二 Rating")
        if privacy & (CHU_HIDE_B30 | CHU_HIDE_N20):
            raise PrivHidden(NAME, "中二 B30 / N20")
        js = await self._fetch(f"{self._u(username)}/chusan/rating")
        return prof, parse_chu_rating(js, prof.rom_version)

    async def chu_recent(self, username) -> tuple[PrivProfile, list[ChuPlay]]:
        prof, privacy = await self.profile(username, "chusan")
        if privacy & CHU_HIDE_PLAYLOG:
            raise PrivHidden(NAME, "中二游玩记录")
        return prof, parse_chu_playlog(await self._fetch(f"{self._u(username)}/chusan/playlog"))
