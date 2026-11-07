"""AquaDX（aquadx.net）客户端。

公开接口，按网站用户名查，不用登录（2026-11-07 用公开排行榜上的玩家实测；接口见 MewoLab/AquaDX 源码）：
  POST /aqua/api/v2/game/{mai2|chu3}/user-summary?username=  → name、rating、ratingHighest、serverRank、plays、
       lastVersion（客户端版本）、ratingComposition、recent（最近 100 条游玩）；没这个人 → 404「User not found」
  POST /aqua/api/v2/game/mai2/user-rating?username=           → best35 / best15：[[musicId, level, romVersion, achievement]]
                                                                + musicList（这 50 张的 UserMusicDetail：FC / FS / DX 分）
  POST /aqua/api/v2/game/chu3/user-rating?username=           → best30 / recent10（旧规则）+ musicList（FC / AJ）
                                                                没有构成时 400「No rating found」
  GET  /d/{mai2|chu3}/00/all-music.json                       → AquaDX 自己的曲目表 {id: {name, notes: [{lv}]}}（只有一个版本的定数）
中二用 user-summary 的 ratingComposition.best30（旧曲）+ new（新曲 N20），字符串 'musicId:level:score,…'。

服务器不给定数：
- 舞萌：插件曲库里「玩家客户端版本」的定数（1.55 的玩家用 PRiSM PLUS 的），没有再用 AquaDX 曲目表的；
  核对：排行榜第 13 名（1.55）算出 16551 = 显示值（1.55 还没有 AP +1）。
- 中二：AquaDX 曲目表的定数；核对：排行榜前 5 名算出来都和显示值一样。
有些玩家的 B50 里有官方曲库和 AQUA 曲目表里都没有的谱（自制谱？），这些没有定数，列成「未知谱面」。
"""
from __future__ import annotations

import time
from typing import Any

from .models import (
    MAI_FC, MAI_FS, ChuBest, ChuPlay, ChuScore, MaiBest, MaiPlay, MaiScore,
    PrivError, PrivNotFound, PrivProfile,
)

KEY = "aqua"
NAME = "AquaDX"
DEFAULT_BASE = "https://aquadx.net"
GAME = {"mai2": "mai2", "chusan": "chu3"}
GAME_NAMES = {"mai2": "舞萌", "chusan": "中二"}
MUSIC_TTL = 24 * 3600


# ---------------------------------------------------------------- 解析

def parse_profile(js: Any, game: str, username: str) -> PrivProfile:
    if not isinstance(js, dict) or "rating" not in js:
        raise PrivNotFound(f"「{username}」在 {NAME} 上还没有{'舞萌' if game == 'mai2' else '中二'}记录")
    user = js.get("aquaUser") or {}
    try:
        rank = int(js.get("serverRank")) if js.get("serverRank") not in (None, "") else None
    except (TypeError, ValueError):
        rank = None
    return PrivProfile(server=KEY, game=game, username=user.get("username") or username, name=str(js.get("name") or ""),
                       rating=int(js.get("rating") or 0), rating_highest=js.get("ratingHighest"), server_rank=rank,
                       rom_version=str(js.get("lastVersion") or ""), last_play=str(js.get("lastSeen") or ""),
                       plays=js.get("plays"))


def _lv(music: dict | None, mid: int, level: int) -> float | None:
    """all-music.json 里某张谱的定数；舞萌 DX 谱也可能按基础 ID 存。"""
    if not music:
        return None
    for key in (str(mid), str(mid % 10000)):
        notes = (music.get(key) or {}).get("notes") or []
        if 0 <= level < len(notes) and (notes[level] or {}).get("lv"):
            return float(notes[level]["lv"])
    return None


def _title(music: dict | None, mid: int) -> str:
    if not music:
        return ""
    return str((music.get(str(mid)) or music.get(str(mid % 10000)) or {}).get("name") or "")


def parse_mai_rating(js: Any, music: dict | None = None) -> MaiBest:
    if not isinstance(js, dict):
        raise PrivError(f"{NAME} 返回了看不懂的舞萌 B50，可能接口改了")
    lamps = {(int(m["musicId"]), int(m["level"])): m for m in js.get("musicList") or []}

    def conv(e) -> MaiScore:
        mid, lv, rom, ach = (int(x) for x in e[:4])
        m = lamps.get((mid, lv)) or {}
        return MaiScore(music_id=mid, level_index=lv, achievement=ach, title=_title(music, mid),
                        fc=MAI_FC.get(m.get("comboStatus"), ""), fs=MAI_FS.get(m.get("syncStatus"), ""),
                        dx_score=m.get("deluxscoreMax"), play_count=m.get("playCount"), rom_version=rom,
                        const_hint=_lv(music, mid, lv))
    return MaiBest(old=[conv(e) for e in js.get("best35") or []], new=[conv(e) for e in js.get("best15") or []])


def _triples(s: Any) -> list[tuple[int, int, int]]:
    out = []
    for part in str(s or "").split(","):
        bits = part.strip().split(":")
        if len(bits) >= 3 and all(b.lstrip("-").isdigit() for b in bits[:3]):
            out.append((int(bits[0]), int(bits[1]), int(bits[2])))
    return out


def parse_chu_best(summary: Any, rating: Any = None, music: dict | None = None) -> ChuBest:
    """VERSE 起：ratingComposition.best30 + new；没有新曲构成（老客户端）时退回 user-rating 的 best30 + recent10。"""
    rc = (summary or {}).get("ratingComposition") or {} if isinstance(summary, dict) else {}
    best, new = _triples(rc.get("best30")), _triples(rc.get("new"))
    if not best and isinstance(rating, dict):
        best = [tuple(int(x) for x in e[:3]) for e in rating.get("best30") or []]
        new = [tuple(int(x) for x in e[:3]) for e in rating.get("recent10") or []]
    if not best and not new:
        raise PrivNotFound(f"{NAME} 上还没有你的中二 rating 构成（客户端太旧，或者还没上机同步过），打一局再查")
    lamps = {(int(m["musicId"]), int(m["level"])): m for m in (rating or {}).get("musicList") or []} \
        if isinstance(rating, dict) else {}

    def conv(t) -> ChuScore:
        mid, lv, score = t
        m = lamps.get((mid, lv)) or {}
        return ChuScore(music_id=mid, level_index=lv, score=score, title=_title(music, mid), const=_lv(music, mid, lv),
                        full_combo=bool(m.get("isFullCombo")), all_justice=bool(m.get("isAllJustice")),
                        play_count=m.get("playCount"))
    return ChuBest(best=[conv(t) for t in best], new=[conv(t) for t in new])


def parse_mai_recent(summary: Any, music: dict | None = None) -> list[MaiPlay]:
    rows = (summary or {}).get("recent") or [] if isinstance(summary, dict) else []
    return [MaiPlay(music_id=int(p["musicId"]), level_index=int(p["level"]), achievement=int(p.get("achievement") or 0),
                    title=_title(music, int(p["musicId"])), dx_score=int(p.get("deluxscore") or 0),
                    fc=MAI_FC.get(p.get("comboStatus"), ""), fs=MAI_FS.get(p.get("syncStatus"), ""),
                    new_record=bool(p.get("isAchieveNewRecord")), rating_after=p.get("afterDeluxRating"),
                    played_at=str(p.get("userPlayDate") or "").removesuffix(".0").replace(" ", "T"),
                    track=p.get("trackNo")) for p in rows]


def parse_chu_recent(summary: Any, music: dict | None = None) -> list[ChuPlay]:
    rows = (summary or {}).get("recent") or [] if isinstance(summary, dict) else []
    return [ChuPlay(music_id=int(p["musicId"]), level_index=int(p["level"]),
                    score=int(p.get("achievement", p.get("score")) or 0), title=_title(music, int(p["musicId"])),
                    full_combo=bool(p.get("isFullCombo")), all_justice=bool(p.get("isAllJustice")),
                    new_record=bool(p.get("isNewRecord")), played_at=str(p.get("userPlayDate") or ""),
                    track=p.get("track")) for p in rows]


# ---------------------------------------------------------------- 客户端

class AquadxClient:
    """hub 提供 request(method, url) -> (状态码, JSON 或 None)。"""

    key, name = KEY, NAME

    def __init__(self, hub, base: str = DEFAULT_BASE):
        self.hub = hub
        self.base = base.rstrip("/")
        self._music: dict[str, tuple[float, dict]] = {}

    @staticmethod
    def _name(cred) -> str:
        from urllib.parse import quote
        u = cred.get("username", "") if isinstance(cred, dict) else str(cred)
        return quote(u.strip().lstrip("@"), safe="")

    async def _post(self, game: str, what: str, cred, *, missing_ok: bool = False) -> Any:
        status, js = await self.hub.request("POST", f"{self.base}/aqua/api/v2/game/{GAME[game]}/{what}?username={self._name(cred)}")
        if status == 404:
            # AquaDX 对「有这个人但没玩过这个游戏」也回 404；用 card/user-games 分一下
            if await self._user_exists(cred):
                raise PrivNotFound(f"{NAME} 上的「{self._name(cred)}」还没有{GAME_NAMES[game]}记录（上机打一局再查）")
            raise PrivNotFound(f"{NAME} 上找不到用户「{self._name(cred)}」（用户名是 aquadx.net 个人主页 /u/ 后面那段）")
        if status == 400 and missing_ok:
            return None
        if status != 200:
            raise PrivError(f"{NAME} 暂时连不上（HTTP {status}），稍后再试")
        return js

    async def _user_exists(self, cred) -> bool:
        try:
            status, _js = await self.hub.request("POST", f"{self.base}/aqua/api/v2/card/user-games?username={self._name(cred)}")
        except PrivError:
            return False
        return status == 200

    async def music(self, game: str) -> dict:
        """AquaDX 自己的曲目表（缓存一天；拉不到就当空的，只是少了兜底定数）。"""
        hit = self._music.get(game)
        if hit and time.time() - hit[0] < MUSIC_TTL:
            return hit[1]
        try:
            status, js = await self.hub.request("GET", f"{self.base}/d/{GAME[game]}/00/all-music.json")
        except PrivError:
            status, js = 0, None
        data = js if status == 200 and isinstance(js, dict) else (hit[1] if hit else {})
        self._music[game] = (time.time(), data)
        return data

    async def profile(self, cred, game: str) -> tuple[PrivProfile, int]:
        js = await self._post(game, "user-summary", cred)
        return parse_profile(js, game, self._name(cred)), 0

    async def mai_best(self, cred) -> tuple[PrivProfile, MaiBest]:
        summary = await self._post("mai2", "user-summary", cred)
        prof = parse_profile(summary, "mai2", self._name(cred))
        rating = await self._post("mai2", "user-rating", cred, missing_ok=True)
        if rating is None:
            raise PrivNotFound(f"{NAME} 上还没有你的舞萌 rating 构成，打一局再查")
        return prof, parse_mai_rating(rating, await self.music("mai2"))

    async def mai_recent(self, cred) -> tuple[PrivProfile, list[MaiPlay]]:
        summary = await self._post("mai2", "user-summary", cred)
        return parse_profile(summary, "mai2", self._name(cred)), parse_mai_recent(summary, await self.music("mai2"))

    async def chu_best(self, cred) -> tuple[PrivProfile, ChuBest]:
        summary = await self._post("chusan", "user-summary", cred)
        prof = parse_profile(summary, "chusan", self._name(cred))
        rating = await self._post("chusan", "user-rating", cred, missing_ok=True)
        return prof, parse_chu_best(summary, rating, await self.music("chusan"))

    async def chu_recent(self, cred) -> tuple[PrivProfile, list[ChuPlay]]:
        summary = await self._post("chusan", "user-summary", cred)
        return parse_profile(summary, "chusan", self._name(cred)), parse_chu_recent(summary, await self.music("chusan"))
