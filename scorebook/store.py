"""手动成绩、网页登录、录分网站自己收的外号。都存在插件数据目录 scorebook/ 下。

  users/<QQ>.json   {"sdvx": {谱面键: 记录}, "geki": {...}, "name": "昵称"}
       SDVX 记录 {"s": 分数, "l": 灯, "t": 时间, "h": [[时间, 分数, 灯], …最近 5 次]}
       音击记录 {"s": 技术分, "l": ""/FC/AB, "fb": 1, "p": 白金分, "st": 星数, "t": 时间, "h": …}
  sessions.json     {令牌哈希: {"uid", "exp", "name"}}   网页登录（30 天），只存哈希
  aliases.json      {"sdvx": {歌曲键: [外号…]}, "geki": {...}}
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time

try:
    from . import calc as K
except ImportError:  # tests import packages top-level
    from scorebook import calc as K

HISTORY = 5
SESSION_TTL = 30 * 86400
LOGIN_TTL = 15 * 60
PENDING_TTL = 5 * 60
UID_RE = re.compile(r"^[0-9A-Za-z_\-]{1,40}$")


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _read(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


class ScoreError(ValueError):
    pass


class ScoreStore:
    def __init__(self, root: str):
        self.dir = os.path.join(root, "users")
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _path(self, uid: str) -> str:
        if not UID_RE.fullmatch(str(uid)):
            raise ScoreError("bad uid")
        return os.path.join(self.dir, f"{uid}.json")

    def user(self, uid: str) -> dict:
        uid = str(uid)
        d = self._cache.get(uid)
        if d is None:
            d = _read(self._path(uid), {})
            d.setdefault("sdvx", {})
            d.setdefault("geki", {})
            self._cache[uid] = d
        return d

    def scores(self, uid: str, game: str) -> dict:
        return self.user(uid).get(game, {})

    def has_any(self, uid: str, game: str) -> bool:
        try:
            return bool(self.scores(uid, game))
        except ScoreError:
            return False

    def _save(self, uid: str) -> None:
        _write(self._path(uid), self._cache[str(uid)])

    # ---------- 写 ----------
    def put_sdvx(self, uid: str, key: str, score: int, lamp: str | None, overwrite: bool = False,
                 ex: int | None = None) -> dict:
        """返回 {"old": 旧记录, "new": 新记录, "changed": bool, "kept_higher": bool}。
        平时只升不降（分数、灯各自取高，和游戏一样）；overwrite=True 就照填的改（录错了改低用）。"""
        score = int(score)
        if not 0 <= score <= K.SDVX_MAX:
            raise ScoreError("分数要在 0～10,000,000 之间")
        if lamp is not None and lamp not in K.LAMPS:
            raise ScoreError("灯不对")
        if score == K.SDVX_MAX:
            lamp = "PUC"
        if lamp == "PUC" and score != K.SDVX_MAX:
            raise ScoreError("PUC 的分数一定是 10,000,000")
        lamp = lamp or "COMP"
        if ex is not None and not 0 <= int(ex) <= 99_999:
            raise ScoreError("EX SCORE 不对（0～99,999）")
        ex = int(ex) if ex else 0
        with self._lock:
            book = self.user(uid)["sdvx"]
            old = dict(book.get(key) or {})
            if old and not overwrite:
                new_s = max(score, int(old.get("s") or 0))
                new_l = lamp if K.lamp_rank(lamp) >= K.lamp_rank(old.get("l", "PLAY")) else old["l"]
                new_x = max(ex, int(old.get("x") or 0))
            else:
                new_s, new_l, new_x = score, lamp, ex
            new = {"s": new_s, "l": new_l}
            if new_x:
                new["x"] = new_x                       # EX SCORE（只升不降，和分数分开取高）
            rec = self._stamp(old, new, [score, lamp] + ([ex] if ex else []))
            changed = (old.get("s"), old.get("l"), old.get("x")) != (new_s, new_l, rec.get("x"))
            book[key] = rec
            self._save(uid)
        return {"old": old, "new": rec, "changed": changed,
                "kept_higher": bool(old) and not overwrite and (new_s > score or new_l != lamp)}

    def put_geki(self, uid: str, key: str, score: int, lamp: str = "", fb: bool = False,
                 platinum: int | None = None, stars: int | None = None, overwrite: bool = False) -> dict:
        score = int(score)
        if not 0 <= score <= K.GEKI_MAX:
            raise ScoreError("技术分要在 0～1,010,000 之间")
        if lamp not in K.GEKI_LAMPS:
            raise ScoreError("灯不对（不填 / FC / AB）")
        if platinum is not None and not 0 <= int(platinum) <= 99_999:
            raise ScoreError("白金分不对")
        if stars is not None and not 0 <= int(stars) <= 6:
            raise ScoreError("星数是 0～6（6 = 彩星）")
        with self._lock:
            book = self.user(uid)["geki"]
            old = dict(book.get(key) or {})
            new = {"s": score, "l": lamp}
            if fb:
                new["fb"] = 1
            if platinum:
                new["p"] = int(platinum)
            if stars:
                new["st"] = int(stars)
            if old and not overwrite:
                new["s"] = max(score, int(old.get("s") or 0))
                new["l"] = max(lamp, old.get("l", ""), key=K.GEKI_LAMPS.index)
                if old.get("fb"):
                    new["fb"] = 1
                if int(old.get("p") or 0) > int(new.get("p") or 0):
                    new["p"] = old["p"]
                if int(old.get("st") or 0) > int(new.get("st") or 0):
                    new["st"] = old["st"]
            rec = self._stamp(old, new, [score, lamp])
            changed = any(old.get(k) != rec.get(k) for k in ("s", "l", "fb", "p", "st"))
            book[key] = rec
            self._save(uid)
        return {"old": old, "new": rec, "changed": changed,
                "kept_higher": bool(old) and not overwrite and new["s"] > score}

    @staticmethod
    def _stamp(old: dict, new: dict, entry: list) -> dict:
        now = int(time.time())
        hist = list(old.get("h") or [])
        hist.append([now, *entry])
        new["t"] = now
        new["h"] = hist[-HISTORY:]
        return new

    def delete(self, uid: str, game: str, key: str) -> bool:
        with self._lock:
            book = self.user(uid)[game]
            if key not in book:
                return False
            del book[key]
            self._save(uid)
        return True

    def set_name(self, uid: str, name: str) -> None:
        if name and self.user(uid).get("name") != name:
            with self._lock:
                self.user(uid)["name"] = name[:40]
                self._save(uid)

    def uids(self) -> list[str]:
        try:
            names = os.listdir(self.dir)
        except OSError:
            return []
        return [n[:-5] for n in names if n.endswith(".json") and UID_RE.fullmatch(n[:-5])]

    def count_users(self) -> dict:
        out = {"sdvx": 0, "geki": 0}
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for n in names:
            if n.endswith(".json"):
                d = self.user(n[:-5]) if UID_RE.fullmatch(n[:-5]) else {}
                for g in out:
                    out[g] += bool(d.get(g))
        return out


class WebSessions:
    """录分网站登录：QQ 里拿一次性登录链接（15 分钟）→ 打开后换成 30 天的会话 cookie。只存哈希。"""

    def __init__(self, root: str):
        self.path = os.path.join(root, "sessions.json")
        self._s: dict[str, dict] = _read(self.path, {})
        self._login: dict[str, dict] = {}            # 一次性登录令牌只放内存
        self._pend: dict[str, dict] = {}             # 群里发的链接：点开后等发命令的人回确认码
        self._miss: dict[str, list[float]] = {}      # 确认码输错的时间（防猜）
        self._lock = threading.Lock()
        self._gc()

    def _gc(self) -> None:
        now = time.time()
        self._s = {k: v for k, v in self._s.items() if v.get("exp", 0) > now}
        self._login = {k: v for k, v in self._login.items() if v.get("exp", 0) > now}
        self._pend = {k: v for k, v in self._pend.items() if v.get("exp", 0) > now}

    def issue_login(self, uid: str, name: str = "", game: str = "", confirm: bool = False) -> str:
        """confirm=True（群里发的）：点开后不直接登录，网页上出 4 位码，要发命令的人自己在 QQ 回「/传分 确认 码」。"""
        self._gc()
        for k in [k for k, v in self._login.items() if v["uid"] == str(uid)]:
            del self._login[k]
        tok = secrets.token_urlsafe(24)
        self._login[_h(tok)] = {"uid": str(uid), "name": name, "game": game, "exp": time.time() + LOGIN_TTL,
                                "confirm": bool(confirm)}
        return tok

    def redeem(self, login_token: str) -> tuple[str, dict] | None:
        """一次性登录令牌 → (会话令牌, 信息)；用过就作废。
        要确认的令牌返回 ("", 信息 + pid / code)：网页拿 pid 轮询，等本人在 QQ 回确认码。"""
        if not login_token or len(login_token) > 100:
            return None
        info = self._login.pop(_h(login_token), None)
        if info is None or info["exp"] < time.time():
            return None
        if info.get("confirm"):
            self._gc()
            for k in [k for k, v in self._pend.items() if v["uid"] == info["uid"]]:
                del self._pend[k]                     # 一个人同时只留一个待确认
            pid = secrets.token_urlsafe(24)
            code = f"{secrets.randbelow(10000):04d}"
            self._pend[_h(pid)] = {"uid": info["uid"], "name": info.get("name", ""), "game": info.get("game", ""),
                                   "code": code, "ok": False, "exp": time.time() + PENDING_TTL}
            return "", {**info, "pid": pid, "code": code}
        return self._new_session(info), info

    def confirm(self, uid: str, code: str) -> str:
        """QQ 里「/传分 确认 1234」→ "ok" / "none"（没有待确认的）/ "wrong" / "locked"（输错太多次）。"""
        self._gc()
        uid, now = str(uid), time.time()
        mine = [v for v in self._pend.values() if v["uid"] == uid and not v["ok"]]
        if not mine:
            return "none"
        miss = [t for t in self._miss.get(uid, []) if now - t < PENDING_TTL]
        if len(miss) >= 5:
            for k in [k for k, v in self._pend.items() if v["uid"] == uid]:
                del self._pend[k]
            self._miss[uid] = []
            return "locked"
        code = "".join(ch for ch in str(code) if ch.isdigit())
        for v in mine:
            if secrets.compare_digest(v["code"], code):
                v["ok"] = True
                self._miss.pop(uid, None)
                return "ok"
        self._miss[uid] = miss + [now]
        return "wrong"

    def poll(self, pid: str) -> tuple[str, dict] | str | None:
        """网页轮询：None = 过期 / 没有；"wait" = 还没确认；确认了就发会话 (会话令牌, 信息)，只发一次。"""
        if not pid or len(pid) > 100:
            return None
        self._gc()
        v = self._pend.get(_h(pid))
        if v is None:
            return None
        if not v["ok"]:
            return "wait"
        del self._pend[_h(pid)]
        return self._new_session(v), v

    def _new_session(self, info: dict) -> str:
        sess = secrets.token_urlsafe(32)
        with self._lock:
            self._gc()
            self._s[_h(sess)] = {"uid": info["uid"], "name": info.get("name", ""), "exp": time.time() + SESSION_TTL}
            _write(self.path, self._s)
        return sess

    def get(self, sess: str) -> dict | None:
        if not sess or len(sess) > 100:
            return None
        v = self._s.get(_h(sess))
        if v is None or v["exp"] < time.time():
            return None
        return v

    def drop(self, sess: str) -> None:
        with self._lock:
            if self._s.pop(_h(sess), None) is not None:
                _write(self.path, self._s)

    def active(self, uid: str) -> int:
        """这个 QQ 现在有几个没过期的网站登录（有的话 /传分 只发网址，不发登录链接）。"""
        now = time.time()
        return sum(1 for v in self._s.values() if v.get("uid") == str(uid) and v.get("exp", 0) > now)

    def per_user(self) -> dict[str, int]:
        """每个 QQ 现在有几个没过期的登录（WebUI 看）。"""
        now = time.time()
        out: dict[str, int] = {}
        for v in self._s.values():
            if v.get("exp", 0) > now:
                out[v["uid"]] = out.get(v["uid"], 0) + 1
        return out

    def drop_user(self, uid: str) -> int:
        with self._lock:
            ks = [k for k, v in self._s.items() if v.get("uid") == str(uid)]
            for k in ks:
                del self._s[k]
            self._login = {k: v for k, v in self._login.items() if v["uid"] != str(uid)}
            self._pend = {k: v for k, v in self._pend.items() if v["uid"] != str(uid)}
            _write(self.path, self._s)
        return len(ks)


class AliasBook:
    """录分网站上加的外号（按歌曲键）。SDVX / 音击 还会同时写进 sdvx.in 那份，/sdvx 谱面 也能用。"""

    def __init__(self, root: str):
        self.path = os.path.join(root, "aliases.json")
        self.d: dict[str, dict[str, list[str]]] = _read(self.path, {})

    def get(self, game: str) -> dict[str, list[str]]:
        return self.d.get(game) or {}

    def add(self, game: str, song_key: str, alias: str) -> bool:
        lst = self.d.setdefault(game, {}).setdefault(song_key, [])
        if alias in lst:
            return False
        lst.append(alias)
        _write(self.path, self.d)
        return True
