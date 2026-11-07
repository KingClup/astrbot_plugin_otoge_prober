"""落雪 OAuth：玩家在网页上点「授权」，bot 拿到这个玩家自己的读取权限（scope read_player），
效果等于个人 API 密钥（全部成绩、最近游玩），但玩家不用复制密钥。

落雪的规则（docs/oauth-guide，2026-11 查）：
  授权   GET  https://maimai.lxns.net/oauth/authorize?response_type=code&client_id&redirect_uri&scope&state
              &code_challenge&code_challenge_method=S256
  换令牌 POST https://maimai.lxns.net/api/v0/oauth/token   grant_type=authorization_code|refresh_token
  access_token 是 JWT，15 分钟；refresh_token 30 天，每次刷新都换新的、旧的立刻作废。
  个人 API 用 Authorization: Bearer <access_token>（core.lxns._headers 认 JWT 就走 Bearer）。

所以：refresh_token 用 Fernet 加密存盘（lx_oauth_tokens.json），access_token 只放内存；
后台每几小时把超过 20 天没刷新的续一次，玩家一直不用也不会掉。已经解绑（舞萌中二都不用了）的会被清掉。
client_id / client_secret 来自配置或数据目录 lx_oauth.json；都不进日志。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

try:
    from .lxns import BASE, UA, LxnsError
except ImportError:  # tests import flat
    from core.lxns import BASE, UA, LxnsError

AUTHORIZE = "https://maimai.lxns.net/oauth/authorize"
TOKEN_URL = BASE + "/oauth/token"
SCOPE = "read_player"
STATE_TTL = 900               # 授权页最多停 15 分钟
REFRESH_AFTER = 20 * 86400    # 超过 20 天没刷新就续（refresh_token 30 天过期）


class OAuthExpired(LxnsError):
    pass


def load_client(config_id: str = "", config_secret: str = "", data_dir: str = "") -> tuple[str, str]:
    cid, sec = (config_id or "").strip(), (config_secret or "").strip()
    if cid:
        return cid, sec
    if data_dir:
        try:
            with open(os.path.join(data_dir, "lx_oauth.json"), encoding="utf-8-sig") as f:
                d = json.load(f)
            return str(d.get("client_id") or "").strip(), str(d.get("client_secret") or "").strip()
        except (OSError, ValueError):
            pass
    return "", ""


def save_client(data_dir: str, client_id: str, client_secret: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "lx_oauth.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"client_id": client_id, "client_secret": client_secret}, f)
    os.replace(tmp, path)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class LxOAuth:
    def __init__(self, data_dir: str, fernet, client_id: str = "", client_secret: str = "",
                 transport=None, proxy: str | None = None):
        self.path = os.path.join(data_dir, "lx_oauth_tokens.json")
        self.fernet = fernet
        self.client_id = client_id
        self.client_secret = client_secret
        self.transport = transport
        self.proxy = proxy
        self._pending: dict[str, dict] = {}            # state → {uid, verifier, redirect, exp, extra}
        self._access: dict[str, tuple[str, float]] = {}  # uid → (access_token, expires_at)
        self._locks: dict[str, asyncio.Lock] = {}
        self.d: dict[str, dict] = self._load()

    # ---------- 存储 ----------
    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.d, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    @property
    def configured(self) -> bool:
        return bool(self.client_id)

    def has(self, uid: str) -> bool:
        return str(uid) in self.d

    def users(self) -> list[str]:
        return list(self.d)

    def forget(self, uid: str) -> None:
        uid = str(uid)
        self._access.pop(uid, None)
        if self.d.pop(uid, None) is not None:
            self._save()

    def _refresh_token(self, uid: str) -> str:
        rec = self.d.get(str(uid)) or {}
        try:
            return self.fernet.decrypt(str(rec.get("rt_enc") or "").encode()).decode()
        except Exception:  # noqa: BLE001
            return ""

    def _store(self, uid: str, tok: dict) -> str:
        uid = str(uid)
        access = str(tok.get("access_token") or "")
        refresh = str(tok.get("refresh_token") or "")
        if not access:
            raise LxnsError("落雪没有给出访问令牌")
        exp = time.time() + max(60, int(tok.get("expires_in") or 900)) - 60
        self._access[uid] = (access, exp)
        if refresh:
            self.d[uid] = {"rt_enc": self.fernet.encrypt(refresh.encode()).decode(), "rt_at": int(time.time()),
                           "scope": str(tok.get("scope") or SCOPE)}
            self._save()
        return access

    # ---------- 授权 ----------
    def begin(self, uid: str, redirect_uri: str, extra: dict | None = None) -> str:
        """→ 落雪授权页地址。state 一次性、15 分钟内有效。"""
        if not self.configured:
            raise LxnsError("bot 主人还没配置落雪 OAuth 应用")
        now = time.time()
        for k in [k for k, v in self._pending.items() if v["exp"] < now]:
            self._pending.pop(k, None)
        state = secrets.token_urlsafe(24)
        verifier, challenge = _pkce()
        self._pending[state] = {"uid": str(uid), "verifier": verifier, "redirect": redirect_uri,
                                "exp": now + STATE_TTL, "extra": extra or {}}
        q = {"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect_uri, "scope": SCOPE,
             "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        return AUTHORIZE + "?" + urlencode(q)

    def pending(self, state: str) -> dict | None:
        p = self._pending.get(state or "")
        return p if p and p["exp"] >= time.time() else None

    async def finish(self, state: str, code: str) -> tuple[str, dict]:
        """回调：state → 玩家 QQ；用 code 换令牌并保存。→ (uid, 开始授权时带的 extra)"""
        p = self._pending.pop(state or "", None)
        if not p or p["exp"] < time.time():
            raise LxnsError("授权链接过期了，回 QQ 重新发「/网页绑定」")
        body = {"grant_type": "authorization_code", "code": code, "redirect_uri": p["redirect"],
                "client_id": self.client_id, "code_verifier": p["verifier"]}
        if self.client_secret:
            body["client_secret"] = self.client_secret
        tok = await self._token(body)
        self._store(p["uid"], tok)
        return p["uid"], p["extra"]

    async def _token(self, body: dict) -> dict:
        kw = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(timeout=20, headers=UA, transport=self.transport, **kw) as c:
            try:
                r = await c.post(TOKEN_URL, json=body)
            except httpx.HTTPError as e:
                raise LxnsError(f"连不上落雪（{type(e).__name__}）") from e
        try:
            j = r.json()
        except ValueError as e:
            raise LxnsError(f"落雪返回 {r.status_code}，不是 JSON") from e
        if isinstance(j, dict) and isinstance(j.get("data"), dict) and "access_token" in j["data"]:
            j = j["data"]
        if r.status_code != 200 or not isinstance(j, dict) or "access_token" not in j:
            err = str((j or {}).get("error") or (j or {}).get("message") or r.status_code) if isinstance(j, dict) else r.status_code
            if err in ("invalid_grant",):
                raise OAuthExpired("落雪授权已失效（可能在落雪那边取消了授权）")
            if err in ("invalid_client", "unauthorized_client"):
                raise LxnsError("OAuth 应用的 client_id / 密钥不对（找 bot 主人）")
            raise LxnsError(f"落雪授权失败：{err}")
        return j

    # ---------- 使用 ----------
    async def access(self, uid: str) -> str:
        """有效的 access_token（过期就用 refresh_token 换）。授权失效 → OAuthExpired。"""
        uid = str(uid)
        hit = self._access.get(uid)
        if hit and hit[1] > time.time():
            return hit[0]
        lock = self._locks.setdefault(uid, asyncio.Lock())
        async with lock:
            hit = self._access.get(uid)
            if hit and hit[1] > time.time():
                return hit[0]
            return await self._refresh(uid)

    async def _refresh(self, uid: str) -> str:
        rt = self._refresh_token(uid)
        if not rt:
            raise OAuthExpired("还没在网页上授权落雪，或者授权记录丢了")
        body = {"grant_type": "refresh_token", "refresh_token": rt, "client_id": self.client_id}
        if self.client_secret:
            body["client_secret"] = self.client_secret
        try:
            tok = await self._token(body)
        except OAuthExpired:
            self.forget(uid)
            raise
        return self._store(uid, tok)

    async def keepalive(self, in_use=None) -> dict:
        """续期快过期的；in_use(uid) → False 的（舞萌中二都解绑了）直接删掉。→ 统计"""
        out = {"refreshed": 0, "dropped": 0, "failed": 0}
        now = time.time()
        for uid in list(self.d):
            if in_use is not None and not in_use(uid):
                self.forget(uid)
                out["dropped"] += 1
                continue
            if now - float((self.d.get(uid) or {}).get("rt_at") or 0) < REFRESH_AFTER:
                continue
            lock = self._locks.setdefault(uid, asyncio.Lock())
            try:
                async with lock:
                    await self._refresh(uid)
                out["refreshed"] += 1
            except OAuthExpired:
                out["dropped"] += 1
            except Exception:  # noqa: BLE001 — 网络问题下次再试
                out["failed"] += 1
        return out
