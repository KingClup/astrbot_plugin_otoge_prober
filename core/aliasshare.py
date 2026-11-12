"""共享外号库：装了这个插件的 bot 互相分享自己收的外号。

每个 bot（客户端）：
  · 上报：把本机收的外号（「加别名」+ 猜歌投票通过的）发给汇总点。只发 游戏 / 曲目编号 / 歌名 / 外号，
    不带 QQ 号、群号、谁加的。bot 用一个随机生成的编号区分，跟 QQ 无关。
  · 下载：每天从汇总点拉一次「共享库」，合进搜索，排在本机外号后面；不会写进本机别名库，所以不会再被报回去。
汇总点（Hub，跑在某一个 bot 的网页绑定服务上）：
  · 收各个 bot 报上来的外号；同一条有 2 个不同来源（不同 bot、不同 IP）报过才自动进共享库，
    汇总点主人也可以手动「通过」或「删」。汇总点自己这个 bot 的外号直接算通过。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import unicodedata

SCHEMA = "otoge-shared-aliases"
VERSION = 1
DEFAULT_HUB = "https://bind.kcrump.me"       # 默认汇总点（插件作者的 bot）；配置里可以换成自己的
HUB_DEFAULT = False                          # 这个 bot 默认当不当汇总点（公开版是 False）
GAMES = ("mai", "chu", "geki", "sdvx", "pjsk")
SPACES = ("mai", "chu", "sdvxin")
MAX_ALIAS = 24            # 外号最长多少个字
MAX_TITLE = 160
MAX_ITEMS = 4000          # 一次上报最多多少条
MAX_PER_BOT = 6000        # 一个 bot 最多占多少条
MAX_TOTAL = 300_000
MIN_SOURCES = 2           # 几个不同来源报过才自动进共享库

_BAD = re.compile(r"https?:|://|www\.|[@#<>{}\[\]\\|`]|\.(?:com|cn|net|org|top|xyz|cc)\b", re.I)


def fold(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s)).casefold())


def clean_alias(a) -> str | None:
    """外号过一遍：太长、带链接 / @ / 控制字符、纯数字的不要。"""
    if not isinstance(a, str):
        return None
    if any(unicodedata.category(c)[0] == "C" for c in a) or _BAD.search(a):
        return None
    a = " ".join(a.split())
    if not a or len(a) > MAX_ALIAS or a.isdigit():
        return None
    return a


def clean_item(d) -> dict | None:
    """一条上报 / 共享记录 → {g, sp, id, t, a}；不合格返回 None。"""
    if isinstance(d, (list, tuple)) and len(d) == 5:
        d = dict(zip(("g", "sp", "id", "t", "a"), d))
    if not isinstance(d, dict):
        return None
    g, sp = d.get("g"), d.get("sp")
    if g not in GAMES or sp not in SPACES:
        return None
    if sp in ("mai", "chu") and sp != g:
        return None
    sid = d.get("id")
    if sp == "sdvxin":
        sid = str(sid or "")
        if not re.fullmatch(r"[0-9A-Za-z_-]{1,12}", sid):
            return None
    else:
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            return None
        if not 0 < sid < 1_000_000:
            return None
    a = clean_alias(d.get("a"))
    t = d.get("t")
    if a is None or not isinstance(t, str) or not t.strip() or len(t) > MAX_TITLE:
        return None
    if fold(a) == fold(t):
        return None
    return {"g": g, "sp": sp, "id": sid, "t": t.strip(), "a": a}


def key_of(it: dict) -> str:
    return f"{it['g']}|{it['sp']}|{it['id']}|{fold(it['a'])}"


def items_from_lib(lib) -> list[dict]:
    """core.aliaslib.Lib（本机别名库）→ 上报用的条目。舞萌 / 中二用各自的官方编号，其余用 sdvx.in 编号。"""
    out, seen = [], set()
    for game, songs in lib.games.items():
        for s in songs.values():
            ids = s.get("ids") or {}
            sp = game if game in ids else "sdvxin" if "sdvxin" in ids else None
            title = str(s.get("title") or "")
            if sp is None or title.startswith("#") or title.startswith("sdvx.in "):     # 曲库里对不上歌名的不报
                continue
            for a in s.get("aliases") or []:
                it = clean_item({"g": game, "sp": sp, "id": ids[sp], "t": s.get("title", ""), "a": a.get("alias")})
                if it is not None and key_of(it) not in seen:
                    seen.add(key_of(it))
                    out.append(it)
    return out


def split_pack(pack: dict | None) -> tuple[dict[int, list[str]], dict[int, list[str]], dict[str, dict[str, list[str]]]]:
    """共享库 → (舞萌 {编号: [外号]}, 中二 {编号: [外号]}, sdvx.in {游戏: {编号: [外号]}})。"""
    mai: dict[int, list[str]] = {}
    chu: dict[int, list[str]] = {}
    sx: dict[str, dict[str, list[str]]] = {g: {} for g in GAMES}
    for raw in (pack or {}).get("items") or []:
        it = clean_item(raw)
        if it is None:
            continue
        if it["sp"] == "mai":
            lst = mai.setdefault(int(it["id"]), [])
        elif it["sp"] == "chu":
            lst = chu.setdefault(int(it["id"]), [])
        else:
            lst = sx[it["g"]].setdefault(str(it["id"]), [])
        if it["a"] not in lst:
            lst.append(it["a"])
    return mai, chu, sx


# ---------------------------------------------------------------- 客户端

def bot_id(root: str) -> str:
    """这个 bot 的随机编号（第一次用时生成，存在数据目录里；跟 QQ 号无关）。"""
    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, "bot_id")
    try:
        with open(p, encoding="utf-8") as f:
            v = f.read().strip()
        if re.fullmatch(r"[0-9a-f]{32}", v):
            return v
    except OSError:
        pass
    v = secrets.token_hex(16)
    with open(p, "w", encoding="utf-8") as f:
        f.write(v)
    return v


def pack_path(root: str) -> str:
    return os.path.join(root, "shared_pack.json")


def load_pack(root: str) -> dict | None:
    try:
        with open(pack_path(root), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("schema") == SCHEMA else None
    except (OSError, ValueError):
        return None


def save_pack(root: str, pack: dict) -> None:
    os.makedirs(root, exist_ok=True)
    tmp = pack_path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, pack_path(root))


def _client(proxy: str | None = None):
    import httpx
    kw = {"proxy": proxy} if proxy else {}
    return httpx.AsyncClient(timeout=30, follow_redirects=True,
                             headers={"user-agent": "astrbot_plugin_otoge_prober alias-share"}, **kw)


async def upload(hub: str, bid: str, items: list[dict], proxy: str | None = None, version: str = "") -> dict:
    body = {"schema": SCHEMA, "version": VERSION, "bot": bid, "plugin": version,
            "items": [[i["g"], i["sp"], i["id"], i["t"], i["a"]] for i in items[:MAX_ITEMS]]}
    async with _client(proxy) as c:
        r = await c.post(hub.rstrip("/") + "/api/aliases/submit", json=body)
        r.raise_for_status()
        return r.json()


async def download(hub: str, proxy: str | None = None) -> dict:
    async with _client(proxy) as c:
        r = await c.get(hub.rstrip("/") + "/api/aliases/pack")
        r.raise_for_status()
        d = r.json()
    if not isinstance(d, dict) or d.get("schema") != SCHEMA or not isinstance(d.get("items"), list):
        raise ValueError("不是共享外号库")
    return d


# ---------------------------------------------------------------- 汇总点

class Hub:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, "hub.json")
        self.items: dict[str, dict] = {}
        self.salt = secrets.token_hex(16)
        self.rev = 0
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.items = dict(d.get("items") or {})
            self.salt = d.get("salt") or self.salt
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"schema": SCHEMA + "-hub", "salt": self.salt, "items": self.items}, f, ensure_ascii=False,
                      separators=(",", ":"))
        os.replace(tmp, self.path)
        self.rev += 1

    def _h(self, s: str) -> str:
        return hashlib.sha256((self.salt + "|" + s).encode()).hexdigest()[:12]

    def submit(self, bot: str, ip: str, items: list, trusted: bool = False) -> dict:
        """收一个 bot 报上来的外号。trusted = 汇总点自己这个 bot（直接算通过）。"""
        bh, ih = self._h("bot:" + bot), self._h("ip:" + ip)
        mine = sum(1 for it in self.items.values() if bh in it.get("b", {}))
        new = seen = bad = 0
        now = int(time.time())
        for raw in list(items)[:MAX_ITEMS]:
            it = clean_item(raw)
            if it is None:
                bad += 1
                continue
            k = key_of(it)
            cur = self.items.get(k)
            if cur is None:
                if mine >= MAX_PER_BOT or len(self.items) >= MAX_TOTAL:
                    bad += 1
                    continue
                cur = self.items[k] = {**it, "b": {}, "st": "", "ts": now}
                new += 1
                mine += 1
            else:
                seen += 1
            if bh not in cur["b"]:
                cur["b"][bh] = ih
            if trusted and cur.get("st") != "block":
                cur["st"] = "ok"
        if new or seen:
            self._save()
        return {"ok": True, "new": new, "known": seen, "skipped": bad, "shared": self.count()}

    @staticmethod
    def accepted(it: dict) -> bool:
        if it.get("st") == "block":
            return False
        if it.get("st") == "ok":
            return True
        b = it.get("b") or {}
        return len(b) >= MIN_SOURCES and len(set(b.values())) >= MIN_SOURCES

    def count(self) -> int:
        return sum(1 for it in self.items.values() if self.accepted(it))

    def pack(self) -> dict:
        rows = [[it["g"], it["sp"], it["id"], it["t"], it["a"]] for it in self.items.values() if self.accepted(it)]
        rows.sort(key=lambda r: (r[0], r[1], str(r[2]), r[4]))
        return {"schema": SCHEMA, "version": VERSION, "generated": int(time.time()), "count": len(rows), "items": rows}

    def pending(self) -> list[tuple[str, dict]]:
        out = [(k, it) for k, it in self.items.items() if not self.accepted(it) and it.get("st") != "block"]
        out.sort(key=lambda x: (-len(x[1].get("b") or {}), x[1].get("ts", 0)))
        return out

    def stats(self) -> dict:
        bots = {b for it in self.items.values() for b in (it.get("b") or {})}
        return {"shared": self.count(), "pending": len(self.pending()),
                "blocked": sum(1 for it in self.items.values() if it.get("st") == "block"), "bots": len(bots)}

    def mark(self, keys, state: str) -> int:
        n = 0
        for k in keys:
            it = self.items.get(k)
            if it is not None and it.get("st") != state:
                it["st"] = state
                n += 1
        if n:
            self._save()
        return n

    def find(self, text: str) -> list[str]:
        """按外号（整条一样）找；找不到再按歌名找。"""
        q = fold(text)
        hit = [k for k, it in self.items.items() if fold(it["a"]) == q]
        return hit or [k for k, it in self.items.items() if fold(it["t"]) == q]


class ShareWeb:
    """汇总点的两个接口，挂在网页绑定那个服务上。没开汇总点时一律 404。"""

    def __init__(self, hub_getter, *, log=None):
        self.hub_getter = hub_getter          # () -> Hub | None
        self.log = log or (lambda s: None)
        self._pack: tuple[int, bytes] | None = None
        self._limits = None

    def add_routes(self, app) -> None:
        app.router.add_post("/api/aliases/submit", self.api_submit)
        app.router.add_get("/api/aliases/pack", self.api_pack)

    def _rl(self):
        if self._limits is None:
            try:
                from .bindweb import RateLimit
            except ImportError:
                from core.bindweb import RateLimit
            self._limits = (RateLimit(12, 3600), RateLimit(60, 3600))
        return self._limits

    @staticmethod
    def _ip(request) -> str:
        try:
            from .bindweb import BindWeb
        except ImportError:
            from core.bindweb import BindWeb
        return BindWeb.client_ip(request)

    @staticmethod
    def _json(data, status: int = 200):
        from aiohttp import web
        return web.json_response(data, status=status, dumps=lambda o: json.dumps(o, ensure_ascii=False))

    async def api_submit(self, request):
        hub = self.hub_getter()
        if hub is None:
            return self._json({"ok": False, "message": "这里没开汇总点"}, 404)
        ip = self._ip(request)
        if not self._rl()[0].allow(ip):
            return self._json({"ok": False, "message": "太频繁了，过一会儿再报"}, 429)
        try:
            if (request.content_length or 0) > 600_000:
                return self._json({"ok": False, "message": "太大了"}, 413)
            raw = b""
            async for chunk in request.content.iter_chunked(65536):
                raw += chunk
                if len(raw) > 600_000:
                    return self._json({"ok": False, "message": "太大了"}, 413)
            b = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json({"ok": False, "message": "格式不对"}, 400)
        bot, items = (b or {}).get("bot"), (b or {}).get("items")
        if not isinstance(b, dict) or b.get("schema") != SCHEMA or not isinstance(items, list) \
                or not isinstance(bot, str) or not re.fullmatch(r"[0-9a-f]{32}", bot):
            return self._json({"ok": False, "message": "格式不对"}, 400)
        out = hub.submit(bot, ip, items)
        self.log(f"[otoge] alias hub: +{out['new']} 新，{out['known']} 已有，{out['skipped']} 不要")
        return self._json(out)

    async def api_pack(self, request):
        from aiohttp import web
        hub = self.hub_getter()
        if hub is None:
            return self._json({"ok": False, "message": "这里没开汇总点"}, 404)
        if not self._rl()[1].allow(self._ip(request)):
            return web.Response(status=429)
        if self._pack is None or self._pack[0] != hub.rev:
            self._pack = (hub.rev, json.dumps(hub.pack(), ensure_ascii=False, separators=(",", ":")).encode())
        resp = web.Response(body=self._pack[1], content_type="application/json", charset="utf-8",
                            headers={"Cache-Control": "public, max-age=600"})
        resp.enable_compression()
        return resp
