"""国服 scores through 落雪查分器 (LXNS, maimai.lxns.net) with the player's own 个人 API 密钥.

The player creates the key on the LXNS website (账号详情 → 个人 API 密钥) and sends it to the bot in a
private chat. It is a secret: stored Fernet-encrypted, never logged, never sent to a group or the model.

Personal API (header ``X-User-Token: <key>``; an OAuth JWT would go as ``Authorization: Bearer``):
  GET /api/v0/user/{game}/player          → Player
  GET /api/v0/user/{game}/player/scores   → Score[] (every chart the player has played)
Public API (no key):
  GET /api/v0/{game}/song/list            → {songs, genres, versions}; difficulties carry level_value (国服定数)
                                            and the version a chart first appeared in
Responses are wrapped as {"success": bool, "code": int, "message": str, "data": ...}.

game = "maimai" | "chunithm". 国服 B50 split (old / new) is done by chart version against the newest version
in the 国服 song list, the same rule maimai.py uses.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

import httpx

BASE = "https://maimai.lxns.net/api/v0"
UA = {"User-Agent": "astrbot_plugin_otoge_prober"}
_JWT = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
# A personal key is a long opaque string; accept the usual base64 / url-safe alphabets.
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9+/=_.-])[A-Za-z0-9+/=_.-]{20,512}(?![A-Za-z0-9+/=_.-])")
KEYWORDS = ("落雪", "lxns", "luoxue")


class LxnsError(Exception):
    pass


def find_token(args: list[str]) -> str:
    for a in args:
        a = a.strip().strip("\"'“”‘’「」")
        if a.lower() in KEYWORDS:
            continue
        if TOKEN_RE.fullmatch(a):
            return a
    return ""


def mentions_lxns(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in KEYWORDS)


def looks_like_lxns_secret(text: str) -> bool:
    """「绑定 落雪 <key>」-shaped message: the key must never stay in a group or reach the model."""
    if not mentions_lxns(text):
        return False
    return bool(find_token(re.split(r"\s+", text or "")))


def _headers(token: str) -> dict:
    token = (token or "").strip()
    if not token:
        raise LxnsError("没有落雪个人 API 密钥")
    if _JWT.match(token):
        return {**UA, "Authorization": f"Bearer {token}"}
    return {**UA, "X-User-Token": token}


def _unwrap(r: httpx.Response):
    try:
        body = r.json()
    except ValueError as e:
        if r.status_code in (401, 403):
            raise LxnsError("密钥不对或已经失效，去落雪网站「账号详情」重新生成一个再绑定") from e
        raise LxnsError(f"落雪返回 {r.status_code}，不是 JSON") from e
    if isinstance(body, dict) and "success" in body:
        if not body.get("success"):
            code = body.get("code") or r.status_code
            msg = str(body.get("message") or "")
            if code == 401 or r.status_code == 401:
                raise LxnsError("密钥不对或已经失效，去落雪网站「账号详情」重新生成一个再绑定")
            if code == 403 or r.status_code == 403:
                raise LxnsError("落雪拒绝了这次查询（隐私设置或权限不够）" + (f"：{msg}" if msg else ""))
            if code == 404 or r.status_code == 404:
                raise LxnsError("落雪上没有这个游戏的数据，先在落雪同步一次成绩" + (f"（{msg}）" if msg else ""))
            raise LxnsError(msg or f"落雪返回 {code}")
        return body.get("data")
    if r.status_code != 200:
        raise LxnsError(f"落雪返回 {r.status_code}")
    return body


async def _get(path: str, token: str | None = None, *, params: dict | None = None, timeout: float = 20,
               transport=None, proxy: str | None = None):
    kw = {"proxy": proxy} if proxy else {}
    headers = _headers(token) if token is not None else UA
    async with httpx.AsyncClient(timeout=timeout, headers=headers, transport=transport, **kw) as c:
        try:
            r = await c.get(BASE + path, params=params)
        except httpx.HTTPError as e:
            raise LxnsError(f"连不上落雪（{type(e).__name__}）") from e
    return _unwrap(r)


async def player(game: str, token: str, transport=None, proxy: str | None = None) -> dict:
    return await _get(f"/user/{game}/player", token, transport=transport, proxy=proxy) or {}


async def scores(game: str, token: str, transport=None, proxy: str | None = None) -> list[dict]:
    return await _get(f"/user/{game}/player/scores", token, transport=transport, proxy=proxy) or []


async def recents(game: str, token: str, transport=None, proxy: str | None = None) -> list[dict]:
    """Not in the public docs for the personal API; callers treat any error as 'not available'."""
    return await _get(f"/user/{game}/player/recents", token, transport=transport, proxy=proxy) or []


# ---------------- developer API（开发者令牌，按 QQ 查，不用玩家自己的密钥） ----------------
# header ``Authorization: <开发者令牌>``（不带 Bearer）。实测 2026-11-08：
#   GET /{game}/player/qq/{qq}        → Player（含 friend_code、upload_time）
#   GET /{game}/player/{fc}/bests     → maimai {standard_total, dx_total, standard[35], dx[15], *_selections}
#                                       chunithm {bests[30], new_bests[20], selections}
#   GET /{game}/player/{fc}/scores    → 只有 id/level/rate 等，没有达成率 → 本插件不用
#   recents 只有增量爬取的数据才有（多数人 404）
# 玩家要在落雪「隐私设置」里允许第三方查询；没在落雪绑 QQ 的查不到。

def dev_token_from(config_value: str = "", data_dir: str = "") -> str:
    """配置里的 lx_dev_token；空的话读数据目录下 lx_dev_token.txt（安装脚本可以放这里，避免出现在 WebUI 里）。"""
    v = (config_value or "").strip()
    if v:
        return v
    if data_dir:
        try:
            with open(os.path.join(data_dir, "lx_dev_token.txt"), encoding="utf-8-sig") as f:
                return f.read().strip()
        except OSError:
            pass
    return ""


def _dev_unwrap(r: httpx.Response, what: str):
    try:
        body = r.json()
    except ValueError as e:
        raise LxnsError(f"落雪返回 {r.status_code}，不是 JSON") from e
    if isinstance(body, dict) and "success" in body:
        if body.get("success"):
            return body.get("data")
        code = body.get("code") or r.status_code
        msg = str(body.get("message") or "")
        if code == 401:
            raise LxnsError("开发者令牌无效（找 bot 主人）")
        if code == 403:
            raise LxnsError("落雪不让第三方查你的" + what + "：去落雪「账号详情 → 隐私设置」打开允许第三方查询")
        if code == 404:
            raise NotFoundOnLxns(msg or "落雪上没有这条数据")
        raise LxnsError(msg or f"落雪返回 {code}")
    if r.status_code != 200:
        raise LxnsError(f"落雪返回 {r.status_code}")
    return body


class NotFoundOnLxns(LxnsError):
    pass


async def _dev_get(path: str, dev: str, what: str, *, timeout: float = 20, transport=None, proxy: str | None = None):
    if not dev:
        raise LxnsError("没有配置落雪开发者令牌")
    kw = {"proxy": proxy} if proxy else {}
    async with httpx.AsyncClient(timeout=timeout, headers={**UA, "Authorization": dev}, transport=transport, **kw) as c:
        try:
            r = await c.get(BASE + path)
        except httpx.HTTPError as e:
            raise LxnsError(f"连不上落雪（{type(e).__name__}）") from e
    return _dev_unwrap(r, what)


async def player_by_qq(game: str, qq: str, dev: str, transport=None, proxy: str | None = None) -> dict:
    if not str(qq).isdigit():
        raise LxnsError("只能用 QQ 号查")
    try:
        return await _dev_get(f"/{game}/player/qq/{qq}", dev, "资料", transport=transport, proxy=proxy) or {}
    except NotFoundOnLxns as e:
        raise NotFoundOnLxns("落雪上没有绑定这个 QQ 的账号（去 maimai.lxns.net 登录并绑定 QQ，再同步一次成绩）") from e


async def dev_player(game: str, fc, dev: str, transport=None, proxy: str | None = None) -> dict:
    return await _dev_get(f"/{game}/player/{fc}", dev, "资料", transport=transport, proxy=proxy) or {}


async def dev_bests(game: str, fc, dev: str, transport=None, proxy: str | None = None) -> dict:
    try:
        return await _dev_get(f"/{game}/player/{fc}/bests", dev, "成绩", transport=transport, proxy=proxy) or {}
    except NotFoundOnLxns as e:
        raise NotFoundOnLxns("落雪上还没有你的成绩，先在落雪同步一次") from e


# ---------------- song list (public, cached on disk) ----------------
class SongIndex:
    """Charts of the 国服 song list: (song_id % 10000 or chuni id, type, level_index) → (level_value, version).

    type: maimai "standard" / "dx"; chunithm always "".
    """

    def __init__(self, game: str, cache_dir: str, refresh_hours: float = 24, proxy: str | None = None,
                 transport=None):
        self.game = game
        self.path = os.path.join(cache_dir, f"lxns-{game}-songs.json")
        self.refresh_hours = refresh_hours
        self.proxy = proxy
        self.transport = transport
        self.charts: dict[tuple[int, str, int], tuple[float | None, int]] = {}
        self.titles: dict[int, str] = {}
        self.versions: list[dict] = []
        self.current: int = 0
        self.newest: int = 0
        self.loaded_at = 0.0
        self._lock = asyncio.Lock()

    def load(self, doc: dict) -> None:
        charts: dict[tuple[int, str, int], tuple[float | None, int]] = {}
        titles: dict[int, str] = {}
        newest = 0
        for s in doc.get("songs") or []:
            try:
                sid = int(s.get("id"))
            except (TypeError, ValueError):
                continue
            if sid >= 100000:          # 宴 charts are not rated
                continue
            key_id = sid % 10000 if self.game == "maimai" else sid
            titles.setdefault(key_id, s.get("title") or "")
            diffs = s.get("difficulties") or {}
            groups = diffs.items() if isinstance(diffs, dict) else (("", diffs),)
            for typ, lst in groups:
                if typ == "utage":
                    continue
                for d in lst or []:
                    try:
                        li = int(d.get("difficulty"))
                    except (TypeError, ValueError):
                        continue
                    ver = int(d.get("version") or s.get("version") or 0)
                    lv = d.get("level_value")
                    charts[(key_id, typ if self.game == "maimai" else "", li)] = (
                        float(lv) if lv is not None else None, ver)
                    newest = max(newest, ver)
        self.charts, self.titles = charts, titles
        self.newest = newest            # 曲目表里最新一张谱面的版本码（国服小版本号，如 25506）
        self.versions = list(doc.get("versions") or [])
        vers = [int(v.get("version") or 0) for v in self.versions if v.get("version")]
        # newest version that 国服 actually has charts for (the list may also name future versions)
        cands = [v for v in vers if v <= newest]
        self.current = max(cands) if cands else newest
        self.loaded_at = time.time()

    def version_title(self, v: int | None = None) -> str:
        v = self.current if v is None else v
        best = None
        for x in self.versions:
            xv = int(x.get("version") or 0)
            if xv <= v and (best is None or xv > int(best.get("version") or 0)):
                best = x
        return str((best or {}).get("title") or "")

    def get(self, sid: int, typ: str, li: int) -> tuple[float | None, int] | None:
        key_id = sid % 10000 if self.game == "maimai" else sid
        return self.charts.get((key_id, typ if self.game == "maimai" else "", li))

    def is_new(self, sid: int, typ: str, li: int) -> bool | None:
        hit = self.get(sid, typ, li)
        if hit is None or not self.current:
            return None
        return hit[1] >= self.current

    def load_cached(self) -> bool:
        try:
            with open(self.path, encoding="utf-8") as f:
                self.load(json.load(f))
            return True
        except (OSError, ValueError):
            return False

    async def ensure(self, force: bool = False, budget: float = 30) -> bool:
        """Have a song list: memory → disk (fresh enough) → download. Never raises."""
        async with self._lock:
            fresh = os.path.exists(self.path) and time.time() - os.path.getmtime(self.path) < self.refresh_hours * 3600
            if self.charts and fresh and not force:
                return True
            if fresh and not force and self.load_cached():
                return True
            try:
                doc = await asyncio.wait_for(_get(f"/{self.game}/song/list", None, params={"notes": "false"},
                                                  timeout=budget, transport=self.transport, proxy=self.proxy),
                                             budget + 5)
                if not isinstance(doc, dict) or not doc.get("songs"):
                    raise LxnsError("song list empty")
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(doc, f, ensure_ascii=False)
                os.replace(tmp, self.path)
                self.load(doc)
                return True
            except Exception:  # noqa: BLE001 — an old list (or none) is still usable
                return bool(self.charts) or self.load_cached()
