"""RinNET（portal.naominet.live）客户端。

RinNET 没有公开主页，要用玩家自己的登录（2026-11-07 读网页前端代码 + 用户本人登录后实测中二接口）：
  POST /api/auth/signin        {usernameOrEmail, password}            → {status:{code}, data:{tokenType, accessToken, refreshToken}}
                               开了两步验证时 code=34014，data={totpToken}
  POST /api/auth/signin/totp   {totpToken, code}                      → 同上
  POST /api/auth/refresh       {refreshToken}                         → data={accessToken}（refreshToken 不轮换）
  GET  /api/user/me            Authorization: Bearer <accessToken>    → data={username, cards[{extId, default}], games[]}
  GET  /api/game/chuni/v2/profile?aimeId=<卡 extId>                   → {userName, playerRating(×100), lastRomVersion, …}
  GET  /api/game/chuni/v2/verse-rating?aimeId=…                       → {old:[…], new:[…]}，每条 {musicId, level, score,
                                                                         ratingBase(定数×100), rating(×100), musicName}
  GET  /api/game/chuni/v2/recent?aimeId=…&page=0                      → {content:[UserPlaylog…], totalElements}
  GET  /api/game/maimai2/profile?aimeId=…                             （舞萌：只按前端代码写，还没用真号核对）
  GET  /api/game/maimai2/rating | new_rating?aimeId=…                 → {data:"musicId:level:romVersion:achievement,…"}
  GET  /api/game/maimai2/recent?aimeId=…&page=0
accessToken 只活 5 分钟；refreshToken 一直能用到玩家退出登录 / 改密码。机器人只存 refreshToken（加密），不存密码。

两层：parse_* 纯函数（测试只测这层）；RinClient 管登录、续期、发请求。
"""
from __future__ import annotations

import re
import time
from typing import Any

from .models import (
    MAI_FC, MAI_FS, ChuBest, ChuPlay, ChuScore, MaiBest, MaiPlay, MaiScore,
    PrivError, PrivNotFound, PrivProfile,
)

KEY = "rin"
NAME = "RinNET"
DEFAULT_BASE = "https://portal.naominet.live"

OK = 92001
LOGIN_FAILED, TOTP_REQUIRED, ACCOUNT_BANNED, EULA_REQUIRED = 34011, 34014, 34031, 34033
ACCESS_TTL = 240          # accessToken 活 300 秒，留点余量

GAME_PATH = {"mai2": "maimai2", "chusan": "chuni/v2"}
GAME_NAMES = {"mai2": "舞萌", "chusan": "中二"}


class RinLoginExpired(PrivError):
    def __init__(self):
        super().__init__(f"{NAME} 的登录失效了（可能在网站上退出登录或改了密码），私聊重新绑定一次：绑定 rin <账号> <密码>")


class RinTotpRequired(PrivError):
    def __init__(self):
        super().__init__(f"你的 {NAME} 开了两步验证：把验证器上的 6 位验证码加在最后，再发一次「绑定 rin <账号> <密码> <验证码>」")


def _status(js: Any) -> tuple[int, str]:
    st = js.get("status") if isinstance(js, dict) else None
    if not isinstance(st, dict):
        return 0, ""
    return int(st.get("code") or 0), str(st.get("message") or "")


def _signin_error(code: int, msg: str) -> PrivError:
    if code == LOGIN_FAILED:
        return PrivError(f"{NAME} 账号或密码不对")
    if code == TOTP_REQUIRED:
        return RinTotpRequired()
    if code == ACCOUNT_BANNED:
        return PrivError(f"{NAME} 说这个账号被封禁了" + (f"：{msg}" if msg else ""))
    if code == EULA_REQUIRED:
        return PrivError(f"先去 {NAME} 网站登录一次、同意新的用户协议，再来绑定")
    return PrivError(f"{NAME} 登录失败" + (f"：{msg}" if msg else f"（{code}）"))


# ---------------------------------------------------------------- 解析

def parse_me(js: Any) -> tuple[str, str, list[str]]:
    """/api/user/me → (网站用户名, 默认卡 extId, 有数据的游戏)。"""
    code, msg = _status(js)
    if code != OK or not isinstance(js.get("data"), dict):
        raise PrivError(f"{NAME} 读不到账号信息" + (f"：{msg}" if msg else ""))
    d = js["data"]
    cards = d.get("cards") or []
    card = next((c for c in cards if c.get("default")), cards[0] if cards else None)
    if not card or card.get("extId") is None:
        raise PrivError(f"你的 {NAME} 账号还没有绑卡（网站「卡片」里绑一张 Aime 再来）")
    return str(d.get("username") or ""), str(card["extId"]), list(d.get("games") or [])


def parse_profile(js: Any, game: str, username: str = "") -> PrivProfile:
    if not isinstance(js, dict) or not (js.get("userName") or js.get("playerRating") is not None):
        raise PrivNotFound(f"你在 {NAME} 上还没有{GAME_NAMES.get(game, game)}记录")
    return PrivProfile(
        server=KEY, game=game, username=username, name=str(js.get("userName") or ""),
        rating=int(js.get("playerRating") or 0), rating_highest=js.get("highestRating"),
        rom_version=str(js.get("lastRomVersion") or ""), last_play=str(js.get("lastPlayDate") or ""),
        plays=js.get("playCount"),
    )


def parse_chu_verse(js: Any) -> ChuBest:
    if not isinstance(js, dict):
        raise PrivError(f"{NAME} 返回了看不懂的中二 B50，可能接口改了")

    def conv(e: dict) -> ChuScore:
        base = e.get("ratingBase")
        return ChuScore(music_id=int(e["musicId"]), level_index=int(e["level"]), score=int(e["score"]),
                        title=str(e.get("musicName") or ""), const=(base / 100) if base else None)
    return ChuBest(best=[conv(e) for e in js.get("old") or []], new=[conv(e) for e in js.get("new") or []])


def parse_chu_old_rating(best: Any, recent: Any) -> ChuBest:
    """2.30（VERSE）以前的客户端：B30 + R10，同样的条目格式。"""
    return parse_chu_verse({"old": best or [], "new": recent or []})


def parse_mai_rating_string(raw: Any) -> list[MaiScore]:
    """'musicId:level:romVersion:achievement,…'（游戏内 recent_rating 的格式）→ 成绩；定数不在这里，之后按曲库补。"""
    s = str((raw or {}).get("data") if isinstance(raw, dict) else raw or "")
    out = []
    for part in s.split(","):
        bits = part.strip().split(":")
        if len(bits) < 4 or not all(re.fullmatch(r"-?\d+", b) for b in bits[:4]):
            continue
        mid, lv, rom, ach = (int(b) for b in bits[:4])
        out.append(MaiScore(music_id=mid, level_index=lv, achievement=ach, rom_version=rom))
    return out


def _content(js: Any) -> list[dict]:
    if isinstance(js, dict):
        return list(js.get("content") or [])
    return list(js or []) if isinstance(js, list) else []


def parse_chu_recent(js: Any) -> list[ChuPlay]:
    return [ChuPlay(music_id=int(p["musicId"]), level_index=int(p["level"]), score=int(p.get("score") or 0),
                    full_combo=bool(p.get("isFullCombo")), all_justice=bool(p.get("isAllJustice")),
                    new_record=bool(p.get("isNewRecord")), played_at=str(p.get("userPlayDate") or ""),
                    track=p.get("track")) for p in _content(js)]


def parse_mai_recent(js: Any) -> list[MaiPlay]:
    return [MaiPlay(music_id=int(p["musicId"]), level_index=int(p["level"]), achievement=int(p.get("achievement") or 0),
                    dx_score=int(p.get("deluxscore") or 0), fc=MAI_FC.get(p.get("comboStatus"), ""),
                    fs=MAI_FS.get(p.get("syncStatus"), ""), new_record=bool(p.get("isAchieveNewRecord")),
                    rating_after=p.get("afterDeluxRating"), played_at=str(p.get("userPlayDate") or ""),
                    track=p.get("trackNo")) for p in _content(js)]


def _rom_tuple(rom: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", rom or "")[:3]) or (0,)


# ---------------------------------------------------------------- 客户端

class RinClient:
    """hub 提供 request(method, url, json=None, headers=None) -> (状态码, JSON)。"""

    key, name = KEY, NAME

    def __init__(self, hub, base: str = DEFAULT_BASE):
        self.hub = hub
        self.base = base.rstrip("/")
        self._access: dict[str, tuple[float, str]] = {}      # refreshToken → (时间, accessToken)

    # ---------- 登录 ----------
    async def _signin_result(self, status: int, js: Any) -> str:
        code, msg = _status(js)
        if code == OK and isinstance(js.get("data"), dict) and js["data"].get("refreshToken"):
            d = js["data"]
            self._access[d["refreshToken"]] = (time.time(), d.get("accessToken") or "")
            return d["refreshToken"]
        if code == 0 and status >= 500:
            raise PrivError(f"{NAME} 暂时连不上（HTTP {status}）")
        raise _signin_error(code, msg)

    async def login(self, account: str, password: str, totp_code: str = "") -> dict:
        """账号密码登录一次，返回要存的 cred（不含密码）。开了两步验证时 totp_code 要给。"""
        status, js = await self.hub.request("POST", self.base + "/api/auth/signin",
                                            json={"usernameOrEmail": account, "password": password})
        code, _ = _status(js)
        if code == TOTP_REQUIRED:
            token = ((js or {}).get("data") or {}).get("totpToken")
            if not totp_code or not token:
                raise RinTotpRequired()
            status, js = await self.hub.request("POST", self.base + "/api/auth/signin/totp",
                                                json={"totpToken": token, "code": totp_code})
        refresh = await self._signin_result(status, js)
        return await self.login_token(refresh)

    async def login_token(self, refresh: str) -> dict:
        """用 refreshToken 绑定（第三方登录的号没有密码）：验证能用，读出卡号。"""
        access = await self._access_for(refresh)
        username, aime, games = parse_me(await self._get_json("/api/user/me", access))
        return {"username": username, "secret": refresh, "aime": aime, "games": games}

    async def _access_for(self, refresh: str) -> str:
        hit = self._access.get(refresh)
        if hit and hit[1] and time.time() - hit[0] < ACCESS_TTL:
            return hit[1]
        status, js = await self.hub.request("POST", self.base + "/api/auth/refresh", json={"refreshToken": refresh})
        code, _ = _status(js)
        token = ((js or {}).get("data") or {}).get("accessToken") if isinstance(js, dict) else None
        if code != OK or not token:
            self._access.pop(refresh, None)
            if status >= 500:
                raise PrivError(f"{NAME} 暂时连不上（HTTP {status}）")
            raise RinLoginExpired()
        self._access[refresh] = (time.time(), token)
        return token

    # ---------- 请求 ----------
    async def _get_json(self, path: str, access: str) -> Any:
        status, js = await self.hub.request("GET", self.base + path, headers={"Authorization": f"Bearer {access}"})
        if status == 401:
            raise RinLoginExpired()
        if status == 404:
            return None
        if status != 200:
            raise PrivError(f"{NAME} 暂时连不上（HTTP {status}），稍后再试")
        return js

    async def _game(self, cred: dict, game: str, what: str, extra: str = "") -> Any:
        access = await self._access_for(cred["secret"])
        return await self._get_json(f"/api/game/{GAME_PATH[game]}/{what}?aimeId={cred['aime']}{extra}", access)

    async def profile(self, cred: dict, game: str) -> tuple[PrivProfile, int]:
        return parse_profile(await self._game(cred, game, "profile"), game, cred.get("username", "")), 0

    # ---------- 中二 ----------
    async def chu_best(self, cred: dict) -> tuple[PrivProfile, ChuBest]:
        prof, _ = await self.profile(cred, "chusan")
        if _rom_tuple(prof.rom_version) >= (2, 30):
            return prof, parse_chu_verse(await self._game(cred, "chusan", "verse-rating"))
        best = await self._game(cred, "chusan", "rating")
        recent = await self._game(cred, "chusan", "rating/recent")
        return prof, parse_chu_old_rating(best, recent)

    async def chu_recent(self, cred: dict) -> tuple[PrivProfile, list[ChuPlay]]:
        prof, _ = await self.profile(cred, "chusan")
        return prof, parse_chu_recent(await self._game(cred, "chusan", "recent", "&page=0"))

    # ---------- 舞萌（按前端代码写，未用真号核对） ----------
    async def mai_best(self, cred: dict) -> tuple[PrivProfile, MaiBest]:
        prof, _ = await self.profile(cred, "mai2")
        old = parse_mai_rating_string(await self._game(cred, "mai2", "rating"))
        new = parse_mai_rating_string(await self._game(cred, "mai2", "new_rating"))
        return prof, MaiBest(old=old, new=new)

    async def mai_recent(self, cred: dict) -> tuple[PrivProfile, list[MaiPlay]]:
        prof, _ = await self.profile(cred, "mai2")
        return prof, parse_mai_recent(await self._game(cred, "mai2", "recent", "&page=0"))
