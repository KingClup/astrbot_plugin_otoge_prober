"""sdvx.in chart views for CHUNITHM / SOUND VOLTEX / プロセカ (PJSK).

Song lists (refreshed daily, cached on disk; an old list keeps working when sdvx.in is unreachable):
  CHUNITHM  /chunithm/_/json/songs01…20.json, songs_del.json           id "01189", levels {bsc,adv,exp,mst,ult}
  WE        /chunithm/_/json/songs_we.json (+ wecourse / weuso / wedel)  id "312",   levels "狂4" (one chart each)
  SDVX      /sdvx/_/json/songs01…NN.json, removed.json                  id "07112", levels {nov,adv,exh,mxm}
  PJSK      /prsk/_/json/songs0001.json, songs_removed.json             id "0737",  levels {esy,…,exp,mst,apd}
  ONGEKI    no JSON list: the genre pages /ongeki/sort/{pops,…,lunatic}.htm name one script per song,
            /ongeki/{dir}/js/{id}sort.js (BASIC…MASTER) or /ongeki/luna/js/{id}luna.js (LUNATIC); each script
            is read once and kept (songs_geki_parts.json), so a daily refresh only fetches the 8 pages + new songs.
            id "01053", levels {bsc,adv,exp,mst,lun}
A level written with a leading "_" (e.g. "_9+") has no chart view on sdvx.in.

Chart images (what the sdvx.in viewers stack on top of each other):
  CHUNITHM  /chunithm/{id[:2]}/bg/{id}bg.webp + /chunithm/{id[:2]}/obj/data{id}{diff}.webp + …/bg/{id}bar.webp
  WE        /chunithm/end/bg/{id}bg.webp + /chunithm/end/obj/data{id}end.webp + /chunithm/end/bg/{id}bar.webp
  PJSK      /prsk/bg/{id}bg.webp + /prsk/obj/data{id}{diff}.webp + /prsk/bg/{id}bar.webp
  ONGEKI    /ongeki/{id[:2]}/bg/{id}bg.png + /ongeki/{id[:2]}/obj/data{id}{diff}.png + …/bg/{id}bar.png
            LUNATIC: notes layer /ongeki/luna/obj/data{id}luna.png (same bg / bar)
  SDVX      newer charts: /sdvx/{id[:2]}/{id}{d}.json drawn by chart/sdvx_draw.py;
            older charts: /{id[:2]}/bg/{id}bg.png + /{id[:2]}/obj/data{id}{d}.png + /{id[:2]}/bg/{id}bar.png
            (d = n / a / e / m; the 4th chart of every song is "m" whatever its name: MXM / INF / GRV / HVN / VVD / XCD)

Charts are drawn by sdvx.in; the plugin only fetches them for the person who asked (with a sdvx.in referer,
one request at a time) and caches the composed picture so the same chart is never fetched twice in a week.
"""
from __future__ import annotations

import asyncio
import html
import io
import json
import os
import re
import time
from dataclasses import dataclass, field

import httpx
from PIL import Image

BASE = "https://sdvx.in"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; astrbot_plugin_otoge_prober; +chart lookup)",
           "Referer": "https://sdvx.in/"}

GAMES = ("chu", "chuwe", "sdvx", "pjsk", "geki")     # chuwe = CHUNITHM WORLD'S END (its own list on sdvx.in)
GAME_LABEL = {"chu": "CHUNITHM", "chuwe": "CHUNITHM", "sdvx": "SOUND VOLTEX", "pjsk": "プロセカ",
              "geki": "オンゲキ"}

# per game: (json key, label) in display order; only these can have chart views
DIFFS = {
    "chu": [("bsc", "BASIC"), ("adv", "ADVANCED"), ("exp", "EXPERT"), ("mst", "MASTER"), ("ult", "ULTIMA")],
    "chuwe": [("we", "WORLD'S END")],
    "sdvx": [("nov", "NOVICE"), ("adv", "ADVANCED"), ("exh", "EXHAUST"), ("mxm", "MAXIMUM")],
    "pjsk": [("esy", "EASY"), ("nml", "NORMAL"), ("hrd", "HARD"), ("exp", "EXPERT"), ("mst", "MASTER"),
             ("apd", "APPEND")],
    "geki": [("bsc", "BASIC"), ("adv", "ADVANCED"), ("exp", "EXPERT"), ("mst", "MASTER"), ("lun", "LUNATIC")],
}
SDVX_4TH = {"i": "INFINITE", "g": "GRAVITY", "h": "HEAVENLY", "v": "VIVID", "x": "EXCEED", "n": "NABLA",
            "u": "ULTIMATE", "m": "MAXIMUM"}
SDVX_FILE = {"nov": "n", "adv": "a", "exh": "e", "mxm": "m"}

# what people type → json key
DIFF_WORDS = {
    "chu": {"bsc": "bsc", "basic": "bsc", "绿": "bsc", "绿谱": "bsc", "adv": "adv", "advanced": "adv", "黄": "adv",
            "黄谱": "adv", "exp": "exp", "expert": "exp", "红": "exp", "红谱": "exp", "mst": "mst", "mas": "mst",
            "master": "mst", "紫": "mst", "紫谱": "mst", "ult": "ult", "ultima": "ult", "黑": "ult", "黑谱": "ult",
            "究极": "ult", "we": "we", "worldsend": "we", "world'send": "we", "end": "we", "世界尽头": "we",
            "世末": "we"},
    "sdvx": {"nov": "nov", "novice": "nov", "nvc": "nov", "adv": "adv", "advanced": "adv", "exh": "exh",
             "exhaust": "exh", "mxm": "mxm", "maximum": "mxm", "inf": "mxm", "infinite": "mxm", "grv": "mxm",
             "gravity": "mxm", "hvn": "mxm", "heavenly": "mxm", "vvd": "mxm", "vivid": "mxm", "xcd": "mxm",
             "exceed": "mxm", "4th": "mxm", "四难": "mxm", "紫": "exh", "红": "exh"},
    "pjsk": {"exp": "exp", "expert": "exp", "ex": "exp", "红": "exp", "红谱": "exp", "mst": "mst", "mas": "mst",
             "master": "mst", "ma": "mst", "紫": "mst", "紫谱": "mst", "apd": "apd", "append": "apd", "ap": "apd",
             "白": "apd", "白谱": "apd", "esy": "esy", "easy": "esy", "nml": "nml", "normal": "nml",
             "hrd": "hrd", "hard": "hrd"},
    "geki": {"bsc": "bsc", "basic": "bsc", "绿": "bsc", "绿谱": "bsc", "adv": "adv", "advanced": "adv", "黄": "adv",
             "黄谱": "adv", "exp": "exp", "expert": "exp", "红": "exp", "红谱": "exp", "mst": "mst", "mas": "mst",
             "master": "mst", "紫": "mst", "紫谱": "mst", "lun": "lun", "luna": "lun", "lunatic": "lun",
             "白": "lun", "白谱": "lun", "re:master": "lun", "remaster": "lun", "rem": "lun"},
}
GEKI_PAGES = ("pops", "niconico", "toho", "variety", "chumai", "ongeki", "remaster", "lunatic")
GEKI_CODE = {"B": "bsc", "A": "adv", "E": "exp", "M": "mst", "L": "lun"}
GEKI_REFS = re.compile(r'src="/ongeki/(\w+)/js/(\d{5})(sort|luna)\.js"')
GEKI_PART_DAYS = 30           # re-read a song's script after this long (levels / videos get updated)
GEKI_STALE_PER_RUN = 60       # … but at most this many old ones per refresh


@dataclass
class Entry:
    game: str
    id: str
    title: str
    artist: str
    raw: dict = field(repr=False)
    removed: bool = False

    def level(self, key: str) -> str:
        lv = self.raw.get("levels")
        if isinstance(lv, str):                     # WORLD'S END: "狂4" / "_嘘3"
            return lv
        return str((lv or {}).get(key) or "")

    def has_view(self, key: str) -> bool:
        lv = self.level(key)
        return bool(lv) and lv not in ("_", "0", "-") and not lv.startswith("_")

    def exists(self, key: str) -> bool:
        lv = self.level(key)
        return bool(lv) and lv not in ("_", "0", "-")

    def diff_label(self, key: str) -> str:
        if self.game == "sdvx" and key == "mxm":
            m = re.match(r"_?([a-zA-Z])", self.level(key))
            return SDVX_4TH.get(m.group(1).lower(), "MAXIMUM") if m else "MAXIMUM"
        return dict(DIFFS[self.game]).get(key, key.upper())

    def level_text(self, key: str) -> str:
        lv = self.level(key).lstrip("_")
        if self.game == "chuwe":
            m = re.match(r"(\D*)(\d+)", lv)
            return f"{m.group(1)}{'☆' * int(m.group(2))}" if m else lv
        if self.game == "sdvx":
            digits = re.sub(r"\D", "", lv)
            return f"{digits[:2]}.{digits[2:]}" if len(digits) == 3 else digits.lstrip("0") or digits
        return lv

    def viewer_url(self, key: str) -> str:
        if self.game in ("chu", "chuwe"):
            return f"{BASE}/chunithm/_/viewer.php?id={self.id}&diff={key}"
        if self.game == "pjsk":
            return f"{BASE}/prsk/_/viewer.php?id={self.id}&diff={key}"
        if self.game == "geki":
            if key == "lun":
                return f"{BASE}/ongeki/luna/{self.id}luna.htm"
            return f"{BASE}/ongeki/{self.id[:2]}/{self.id}{key}.htm"
        return f"{BASE}/sdvx/_/viewer/?id={self.id}{SDVX_FILE.get(key, 'm')}"

    def youtube(self, key: str) -> list[str]:
        yt = self.raw.get("youtube") or {}
        if not isinstance(yt, dict):
            return [str(yt)] if yt else []
        ids = [yt.get(f"{key}1"), yt.get(f"{key}2"), yt.get(key)]
        out = []
        for v in ids:
            v = str(v or "").strip()
            if v and v != "_" and v not in out:
                out.append(v)
        return [f"https://youtu.be/{v}" for v in out]


def _js_var(text: str, name: str) -> str | None:
    m = re.search(r'var ' + re.escape(name) + r'="((?:[^"\\]|\\.)*)";', text)
    return m.group(1) if m else None


def _plain(h: str | None) -> str:
    t = html.unescape(re.sub(r"<[^>]*>", "", h or ""))
    return re.sub(r"^[\s\u3000]*/\s*", "", t).strip()


def parse_geki_js(text: str, sid: str) -> dict:
    """One sdvx.in ONGEKI song script (…sort.js / …luna.js) → {id,title,artist,bpm,levels,youtube,designer,chain,bell}.
    A level is written "_9+" when sdvx.in has no chart page for it (the level picture is not a link)."""
    out = {"id": sid, "title": _plain(_js_var(text, f"TITLE{sid}")), "artist": _plain(_js_var(text, f"ARTIST{sid}")),
           "levels": {}, "youtube": {}, "designer": {}, "chain": {}, "bell": {}}
    bpm = _plain(_js_var(text, f"BPM{sid}"))
    if bpm:
        out["bpm"] = bpm.replace("BPM", "").strip()
    for c, k in GEKI_CODE.items():
        lv = _js_var(text, f"LV{sid}{c}")
        if not lv:
            continue
        m = re.search(r"lv/(?:bsc|adv|exp|mst|luna)(_?)([\d+]+)\.png", lv)
        if not m:
            continue
        level = m.group(2)
        if k == "lun" and level == "0":
            level = "?"                               # a few LUNATIC charts carry no level on sdvx.in
        out["levels"][k] = ("" if "<a href" in lv and not m.group(1) else "_") + level
        mv = _js_var(text, f"MV{sid}{c}") or ""
        y = re.search(r"watch\?v=([\w-]{6,})", mv)
        if y:
            out["youtube"][k] = y.group(1)
        cr = _plain(_js_var(text, f"CR{sid}{c}"))
        if cr:
            out["designer"][k] = re.sub(r"^NOTES DESIGNER\s*/\s*", "", cr)
        for var, dst in (("CH", "chain"), ("BL", "bell")):
            n = re.sub(r"\D", "", _plain(_js_var(text, f"{var}{sid}{c}")))
            if n:
                out[dst][k] = n
    return out


def merge_geki(parts: list[dict]) -> list[dict]:
    """The normal script and the LUNATIC script of one song → one entry."""
    by: dict[str, dict] = {}
    for p in parts:
        sid = p.get("id")
        if not sid or not p.get("title"):
            continue
        cur = by.get(sid)
        if cur is None:
            by[sid] = {**p, **{k: dict(p.get(k) or {}) for k in ("levels", "youtube", "designer", "chain", "bell")}}
            continue
        for k in ("levels", "youtube", "designer", "chain", "bell"):
            cur[k].update(p.get(k) or {})
        if not cur.get("bpm") and p.get("bpm"):
            cur["bpm"] = p["bpm"]
    return list(by.values())


def _lists(game: str) -> list[tuple[str, bool]]:
    if game == "chu":
        return [(f"/chunithm/_/json/songs{i:02d}.json", False) for i in range(1, 21)] + \
            [("/chunithm/_/json/songs_del.json", True)]
    if game == "chuwe":
        return [("/chunithm/_/json/songs_we.json", False), ("/chunithm/_/json/songs_wecourse.json", False),
                ("/chunithm/_/json/songs_weuso.json", False), ("/chunithm/_/json/songs_wedel.json", True)]
    if game == "sdvx":
        return [(f"/sdvx/_/json/songs{i:02d}.json", False) for i in range(1, 16)] + [("/sdvx/_/json/removed.json", True)]
    return [("/prsk/_/json/songs0001.json", False), ("/prsk/_/json/songs_removed.json", True)]


class SdvxIn:
    def __init__(self, cache_dir: str, proxy: str | None = None, transport=None, refresh_hours: float = 24):
        self.dir = cache_dir
        os.makedirs(os.path.join(cache_dir, "img"), exist_ok=True)
        self.proxy = proxy
        self.transport = transport
        self.refresh_hours = refresh_hours
        self.entries: dict[str, dict[str, Entry]] = {g: {} for g in GAMES}
        self.loaded_at: dict[str, float] = {}
        self.last_error = ""
        self._locks = {g: asyncio.Lock() for g in GAMES}
        self._net = asyncio.Semaphore(2)
        self._search: dict[str, object] = {}
        self.aliases: dict[str, dict[str, list[str]]] = self._load_aliases()
        self._last_fail: dict[str, float] = {}       # list refresh failed → don't hammer sdvx.in on every query
        self._miss: dict[str, float] = {}            # chart / jacket known to be absent (negative cache)

    RETRY_AFTER = 30 * 60          # seconds between list-refresh attempts after a failure
    MISS_TTL = 12 * 3600           # how long a 「没有这张图」 answer is remembered
    IMG_DAYS = 30                  # composed chart pictures never change; keep them a month

    def _missed(self, key: str) -> bool:
        t = self._miss.get(key)
        if t is None:
            return False
        if time.time() - t > self.MISS_TTL:
            self._miss.pop(key, None)
            return False
        return True

    def _note_miss(self, key: str) -> None:
        if len(self._miss) > 4000:
            now = time.time()
            self._miss = {k: v for k, v in self._miss.items() if now - v < self.MISS_TTL}
        self._miss[key] = time.time()

    # ---------- http ----------
    def _client(self, timeout: float = 25) -> httpx.AsyncClient:
        kw = {"proxy": self.proxy} if self.proxy else {}
        return httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=False,
                                 transport=self.transport, **kw)

    async def _get(self, c: httpx.AsyncClient, path: str) -> bytes | None:
        async with self._net:
            try:
                r = await c.get(BASE + path)
            except httpx.HTTPError as e:
                self.last_error = f"{path}: {type(e).__name__}"
                return None
        if r.status_code != 200:          # sdvx.in answers a missing file with a 302 to its top page
            return None
        return r.content

    # ---------- song lists ----------
    def _cache_path(self, game: str) -> str:
        return os.path.join(self.dir, f"songs_{game}.json")

    def _load_entries(self, game: str, items: list[dict]) -> None:
        out: dict[str, Entry] = {}
        for raw in items:
            sid = str(raw.get("id") or "").strip()
            title = str(raw.get("title") or "").strip()
            if not sid or not title:
                continue
            removed = bool(raw.get("_removed"))
            if sid in out and not out[sid].removed:
                continue                       # the live entry wins over the removed copy
            out[sid] = Entry(game, sid, title, str(raw.get("artist") or ""), raw, removed)
        self.entries[game] = out
        self._search.pop(game, None)

    def load_cached(self, game: str) -> int:
        """只读本地缓存的曲目表（不联网）；给 WebUI 总览这种只想看个数的地方用。"""
        p = self._cache_path(game)
        if not self.entries.get(game) and os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    self._load_entries(game, json.load(f))
                self.loaded_at[game] = os.path.getmtime(p)
            except (OSError, ValueError):
                pass
        return len(self.entries.get(game) or {})

    async def ensure(self, game: str, force: bool = False) -> int:
        async with self._locks[game]:
            p = self._cache_path(game)
            fresh = os.path.exists(p) and time.time() - os.path.getmtime(p) < self.refresh_hours * 3600
            if self.entries[game] and fresh and not force:
                return len(self.entries[game])
            if not self.entries[game] and os.path.exists(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        self._load_entries(game, json.load(f))
                    self.loaded_at[game] = os.path.getmtime(p)
                except (OSError, ValueError):
                    pass
                if fresh and not force:
                    return len(self.entries[game])
            if (not force and self.entries[game]
                    and time.time() - self._last_fail.get(game, 0) < self.RETRY_AFTER):
                return len(self.entries[game])       # refresh failed a moment ago: keep the old list for now
            if game == "geki":
                items = await self._geki_items(force)
                ok = 1 if items else 0
            else:
                items, ok = await self._json_items(game)
            if not (ok and items):
                self._last_fail[game] = time.time()
            else:
                self._last_fail.pop(game, None)
            if ok and items:
                tmp = p + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(items, f, ensure_ascii=False)
                os.replace(tmp, p)
                self._load_entries(game, items)
                self.loaded_at[game] = time.time()
            return len(self.entries[game])

    async def _json_items(self, game: str) -> tuple[list[dict], int]:
        items: list[dict] = []
        ok = 0
        async with self._client() as c:
            for path, removed in _lists(game):
                data = await self._get(c, path)
                if data is None:
                    continue
                try:
                    arr = json.loads(data)
                except ValueError:
                    continue
                if isinstance(arr, list):
                    ok += 1
                    for it in arr:
                        if isinstance(it, dict):
                            if removed:
                                it = {**it, "_removed": True}
                            items.append(it)
        return items, ok

    async def _geki_items(self, force: bool = False) -> list[dict]:
        """ONGEKI: genre pages → song scripts. Scripts already read are kept (sdvx.in ids never change)."""
        pp = os.path.join(self.dir, "songs_geki_parts.json")
        try:
            with open(pp, encoding="utf-8") as f:
                parts: dict = json.load(f)
        except (OSError, ValueError):
            parts = {}
        refs: dict[str, tuple[str, str, str]] = {}
        async with self._client() as c:
            for page in GEKI_PAGES:
                data = await self._get(c, f"/ongeki/sort/{page}.htm")
                if data is None:
                    continue
                for d, sid, kind in GEKI_REFS.findall(data.decode("utf-8", "replace")):
                    refs[f"{d}/{sid}{kind}"] = (d, sid, kind)
            if not refs:
                return merge_geki([v["d"] for v in parts.values() if isinstance(v, dict) and v.get("d")])
            now = time.time()
            todo = [k for k in refs if k not in parts]
            stale = sorted((k for k in refs if k in parts and now - parts[k].get("t", 0) > GEKI_PART_DAYS * 86400),
                           key=lambda k: parts[k].get("t", 0))
            todo += stale if force else stale[:GEKI_STALE_PER_RUN]

            async def one(k: str) -> None:
                d, sid, kind = refs[k]
                data = await self._get(c, f"/ongeki/{d}/js/{sid}{kind}.js")
                if data is None:
                    return
                info = parse_geki_js(data.decode("utf-8", "replace"), sid)
                if info["title"]:
                    parts[k] = {"t": time.time(), "d": info}

            for i in range(0, len(todo), 20):            # _get allows 2 requests at a time
                await asyncio.gather(*(one(k) for k in todo[i:i + 20]))
                if todo[i + 20:]:
                    tmp = pp + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(parts, f, ensure_ascii=False)
                    os.replace(tmp, pp)
        tmp = pp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(parts, f, ensure_ascii=False)
        os.replace(tmp, pp)
        return merge_geki([parts[k]["d"] for k in refs if k in parts])

    # ---------- search ----------
    def _alias_path(self) -> str:
        return os.path.join(self.dir, "aliases.json")

    def _load_aliases(self) -> dict[str, dict[str, list[str]]]:
        try:
            with open(self._alias_path(), encoding="utf-8") as f:
                d = json.load(f)
            return {g: dict(d.get(g) or {}) for g in GAMES}
        except (OSError, ValueError):
            return {g: {} for g in GAMES}

    def add_alias(self, game: str, alias: str, sid: str) -> None:
        lst = self.aliases.setdefault(game, {}).setdefault(sid, [])
        if alias not in lst:
            lst.append(alias)
        tmp = self._alias_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.aliases, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._alias_path())
        self._search.pop(game, None)

    def index(self, game: str):
        try:
            from ..mai.data.fuzzy import FuzzyIndex
        except ImportError:   # tests import packages top-level
            from mai.data.fuzzy import FuzzyIndex
        idx = self._search.get(game)
        if idx is None:
            idx = FuzzyIndex()
            local = self.aliases.get(game) or {}
            for sid, e in self.entries[game].items():
                names = [e.raw.get("title_search_hira") or "", e.raw.get("title_search_abc") or "", sid,
                         *local.get(sid, [])]
                idx.add(sid, e, e.title, [n for n in names if n])
            self._search[game] = idx
        return idx

    def by_title(self, game: str, title: str) -> Entry | None:
        try:
            from ..mai.data.fuzzy import fold
        except ImportError:
            from mai.data.fuzzy import fold
        k = fold(title)
        cands = [e for e in self.entries[game].values() if fold(e.title) == k]
        if not cands:
            k2 = fold(CHU_TITLE_FIX.get(title, title))
            cands = [e for e in self.entries[game].values() if fold(CHU_TITLE_FIX.get(e.title, e.title)) == k2]
        cands.sort(key=lambda e: e.removed)
        return cands[0] if cands else None

    # ---------- ONGEKI jackets (for the /geki B50 picture) ----------
    def geki_jacket_path(self, sid: str) -> str:
        return os.path.join(self.dir, "img", f"geki_jk_{sid}.png")

    async def geki_jackets(self, titles: list[str], budget: float = 30) -> dict[str, str]:
        """title → local jacket file. Only songs already in the cached list; missing ones are fetched
        (2 at a time) until the time budget runs out, the rest just get no picture this time."""
        out: dict[str, str] = {}
        todo: list[tuple[str, str]] = []
        for t in dict.fromkeys(titles):
            e = self.by_title("geki", t) if self.entries.get("geki") else None
            if e is None:
                continue
            p = self.geki_jacket_path(e.id)
            if os.path.exists(p):
                out[t] = p
            elif not self._missed(f"geki_jk_{e.id}"):
                todo.append((t, e.id))
        if not todo:
            return out

        async def one(c, t: str, sid: str) -> None:
            data = await self._get(c, f"/ongeki/{sid[:2]}/jacket/{sid}.png")
            if data and data[:4] == b"\x89PNG":
                p = self.geki_jacket_path(sid)
                tmp = p + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, p)
                out[t] = p
            elif data is not None or not self.last_error:
                self._note_miss(f"geki_jk_{sid}")      # sdvx.in answered「没有」(not a network failure)
        try:
            async with self._client(20) as c:
                await asyncio.wait_for(asyncio.gather(*(one(c, t, sid) for t, sid in todo)), budget)
        except (asyncio.TimeoutError, httpx.HTTPError):
            pass
        return out

    # ---------- SDVX / PJSK jackets (for 猜曲绘) ----------
    def jacket_candidates(self, e: Entry) -> list[str]:
        """Same order sdvx.in's own viewer.js tries (2026-11 实测)：
        SDVX  /{folder}/jacket/{id}{diff}.png → /sdvx/{folder}/jacket/{id}{diff}.png → /{folder}/jacket/{id}.png
        PJSK  /prsk/jacket/{id}.png"""
        if e.game == "pjsk":
            return [f"/prsk/jacket/{e.id}.png"]
        if e.game != "sdvx":
            return []
        i2 = e.id[:2]
        codes = []
        for k in ("mxm", "exh", "adv", "nov"):
            c = SDVX_FILE[k]
            if e.exists(k) and c not in codes:
                codes.append(c)
        out = []
        for c in codes[:2]:                          # 最难的两个难度，够了
            out += [f"/{i2}/jacket/{e.id}{c}.png", f"/sdvx/{i2}/jacket/{e.id}{c}.png"]
        out.append(f"/{i2}/jacket/{e.id}.png")
        return out

    def song_jacket_path(self, e: Entry) -> str:
        return os.path.join(self.dir, "img", f"{e.game}_jk_{e.id}.png")

    async def song_jacket(self, e: Entry, budget: float = 20) -> str | None:
        p = self.song_jacket_path(e)
        if os.path.exists(p):
            return p
        miss = f"{e.game}_jk_{e.id}"
        if self._missed(miss) or not self.jacket_candidates(e):
            return None

        async def run() -> str | None:
            answered = True
            async with self._client(20) as c:
                for path in self.jacket_candidates(e):
                    data = await self._get(c, path)
                    if data and data[:4] == b"\x89PNG":
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        tmp = p + ".tmp"
                        with open(tmp, "wb") as f:
                            f.write(data)
                        os.replace(tmp, p)
                        return p
                    if data is None and self.last_error and path in self.last_error:
                        answered = False           # 网络故障，不记「没有」
            if answered:
                self._note_miss(miss)
            return None
        try:
            return await asyncio.wait_for(run(), budget)
        except (asyncio.TimeoutError, httpx.HTTPError):
            return None

    # ---------- images ----------
    def _img_path(self, e: Entry, key: str) -> str:
        return os.path.join(self.dir, "img", f"{e.game}_{e.id}_{key}.jpg")

    async def chart_image(self, e: Entry, key: str, max_kb: int = 2500) -> bytes | None:
        p = self._img_path(e, key)
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < self.IMG_DAYS * 86400:
            with open(p, "rb") as f:
                return f.read()
        miss_key = f"chart_{e.game}_{e.id}_{key}"
        if self._missed(miss_key):
            return None
        self.last_error = ""
        img = await self._fetch(e, key)
        if img is None:
            if not self.last_error:                  # a clean「没有这张谱面图」, not a connection problem
                self._note_miss(miss_key)
            return None
        data = await asyncio.to_thread(_encode, img, max_kb)
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        return data

    async def _fetch(self, e: Entry, key: str) -> Image.Image | None:
        got = await self._fetch_raw(e, key)
        if got is None:
            return None
        kind, payload = got
        if kind == "sdvxjson":
            from .sdvx_draw import render
            return await asyncio.to_thread(render, payload)
        return await asyncio.to_thread(compose, *payload)

    async def _fetch_raw(self, e: Entry, key: str):
        """("layers", (bg, notes, bar) bytes) or ("sdvxjson", chart dict) or None (no chart)."""
        i2 = e.id[:2]
        async with self._client(40) as c:
            if e.game == "chu":
                paths = (f"/chunithm/{i2}/bg/{e.id}bg.webp", f"/chunithm/{i2}/obj/data{e.id}{key}.webp",
                         f"/chunithm/{i2}/bg/{e.id}bar.webp")
                return await self._layer_blobs(c, paths, alt_ext=".png")
            if e.game == "chuwe":
                paths = (f"/chunithm/end/bg/{e.id}bg.webp", f"/chunithm/end/obj/data{e.id}end.webp",
                         f"/chunithm/end/bg/{e.id}bar.webp")
                return await self._layer_blobs(c, paths, alt_ext=".png")
            if e.game == "geki":
                notes = (f"/ongeki/luna/obj/data{e.id}luna.png" if key == "lun"
                         else f"/ongeki/{i2}/obj/data{e.id}{key}.png")
                paths = (f"/ongeki/{i2}/bg/{e.id}bg.png", notes, f"/ongeki/{i2}/bg/{e.id}bar.png")
                return await self._layer_blobs(c, paths)
            if e.game == "pjsk":
                paths = (f"/prsk/bg/{e.id}bg.webp", f"/prsk/obj/data{e.id}{key}.webp", f"/prsk/bg/{e.id}bar.webp")
                return await self._layer_blobs(c, paths)
            d = SDVX_FILE.get(key, "m")
            js = await self._get(c, f"/sdvx/{i2}/{e.id}{d}.json")
            if js:
                try:
                    chart = json.loads(js)
                    if chart.get("lasers") is not None:
                        return "sdvxjson", chart
                except ValueError:
                    pass
            paths = (f"/{i2}/bg/{e.id}bg.png", f"/{i2}/obj/data{e.id}{d}.png", f"/{i2}/bg/{e.id}bar.png")
            return await self._layer_blobs(c, paths)

    async def _layer_blobs(self, c, paths, alt_ext: str | None = None):
        blobs = []
        for p in paths:
            b = await self._get(c, p)
            if b is None and alt_ext:
                b = await self._get(c, p.rsplit(".", 1)[0] + alt_ext)
            blobs.append(b)
        if blobs[1] is None:                       # no notes layer = no chart
            return None
        return "layers", tuple(blobs)

    def _measures_path(self, e: Entry, key: str) -> str:
        return self._img_path(e, key)[:-4] + ".measures.json"

    async def chart_measures(self, e: Entry, key: str, max_kb: int = 2500):
        """(chart picture, measure boxes in play order) for the 猜谱面 game, or None. Shares the picture cache
        with chart_image(); the boxes are cached next to it (stored relative to the picture size)."""
        p, mp = self._img_path(e, key), self._measures_path(e, key)
        fresh = lambda f: os.path.exists(f) and time.time() - os.path.getmtime(f) < self.IMG_DAYS * 86400  # noqa: E731
        if fresh(p) and fresh(mp):
            try:
                with open(mp, encoding="utf-8") as f:
                    meta = json.load(f)
                img = await asyncio.to_thread(lambda: Image.open(p).convert("RGB"))
                kx, ky = img.width / meta["w"], img.height / meta["h"]
                rects = [(int(a * kx), int(b * ky), int(c * kx), int(d * ky)) for a, b, c, d in meta["rects"]]
                if rects:
                    return img, rects
            except Exception:  # noqa: BLE001
                pass
        miss_key = f"chart_{e.game}_{e.id}_{key}"
        if self._missed(miss_key):
            return None
        self.last_error = ""
        got = await self._fetch_raw(e, key)
        if got is None:
            if not self.last_error:
                self._note_miss(miss_key)
            return None
        kind, payload = got

        def build():
            if kind == "sdvxjson":
                from .sdvx_draw import measure_rects, render
                img = render(payload)
                return img.convert("RGB"), measure_rects(payload)
            img = compose(*payload)
            try:
                from ..games.chartcut import fallback_measures, measures
            except ImportError:
                from games.chartcut import fallback_measures, measures
            rects = []
            if payload[0]:
                pad = 4 if e.game == "sdvx" else 0          # lasers stick out a little; numbers start ~6 px out
                rects = measures(Image.open(io.BytesIO(payload[0])), pad=pad)
            return img, rects or fallback_measures(img)

        img, rects = await asyncio.to_thread(build)
        data = await asyncio.to_thread(_encode, img, max_kb)
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        with open(mp + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"w": img.width, "h": img.height, "rects": rects}, f)
        os.replace(mp + ".tmp", mp)
        return img, rects

    async def _layers(self, c, paths, alt_ext: str | None = None) -> Image.Image | None:
        blobs = []
        for p in paths:
            b = await self._get(c, p)
            if b is None and alt_ext:
                b = await self._get(c, p.rsplit(".", 1)[0] + alt_ext)
            blobs.append(b)
        if blobs[1] is None:                       # no notes layer = no chart
            return None
        return await asyncio.to_thread(compose, *blobs)


def compose(bg: bytes | None, data: bytes, bar: bytes | None) -> Image.Image:
    """Stack bg / notes / bar layers on black (what the sdvx.in viewer does in the browser)."""
    layers = [Image.open(io.BytesIO(b)).convert("RGBA") for b in (bg, data, bar) if b]
    size = layers[0].size if bg else Image.open(io.BytesIO(data)).size
    out = Image.new("RGBA", size, (0, 0, 0, 255))
    for im in layers:
        if im.size != size:
            box = Image.new("RGBA", size, (0, 0, 0, 0))
            box.paste(im, (0, 0), im)
            im = box
        out = Image.alpha_composite(out, im)
    return out.convert("RGB")


def _encode(img: Image.Image, max_kb: int) -> bytes:
    img = img.convert("RGB")
    for scale in (1.0, 0.85, 0.7, 0.55):
        im = img if scale == 1.0 else img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        for q in (88, 80, 70):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q, optimize=True)
            if buf.tell() <= max_kb * 1024:
                return buf.getvalue()
    return buf.getvalue()


# sdvx.in spells a few CHUNITHM titles differently from the official song list (from chuni-penguin, 0BSD)
CHU_TITLE_FIX = {
    "AMARA (大未来電脳)": "ÅMARA (大未来電脳)", "AstroNotes.": "AstrøNotes.", "Aventyr": "Äventyr",
    "Chaotic Order": "Chaotic Ørder", "Daydream cafe": "Daydream café", "Defandour": "Dèfandour",
    "GRANDIR": "GRÄNDIR", "GranFatalite": "GranFatalité", "Jorqer": "Jörqer", "L'epilogue": "L'épilogue",
    "MegiddO": "MegiddØ", "Okeanos": "Ωκεανος", "Pump": "Pump!n", "Re：Re": "Ré：Ré", "Solstand": "Solstånd",
    "Tuatha De Danann": "Tuatha Dé Danann", "Walzer fur das Nichts": "Walzer für das Nichts",
    "chronos": "χρόνος", "solips": "sølips", "ム責任集合体": "㋰責任集合体", "Wing No.6223": "Wing:No.6223",
    "ouroboros": "ouroboros -twin stroke of the end-", "Excalibur": "Excalibur ～Revived resolution～",
    "The Metaverse": "The Metaverse -First story of the SeelischTact-", "崩壊歌姫": "崩壊歌姫 -disruptive diva-",
    "多重未来のカルテット": "多重未来のカルテット -Quartet Theme-", "宵の平安京 Stargaze": "宵の平安京 Stargazer",
    "めっちゃ煽ってくる": "めっちゃ煽ってくるタイプの音ゲーボス曲ちゃんなんかに負けないが？？？？？",
    "チルノおかん": "チルノおかんのさいきょう☆バイブスごはん", "Super Lovely": "Super Lovely (Heavenly Remix)",
    "Seyana": "Seyana. ～何でも言うことを聞いてくれるアカネチャン～",
}
