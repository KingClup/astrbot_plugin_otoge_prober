"""传分本：曲库加载 / 每日刷新、外号合并，以及聊天里的传分指令。

  /传分、/sdvx 传分、/geki 传分      → 传分网站的个人登录链接
  /sdvx 传 <歌> <难度> <分数> [灯]    → 聊天里直接传一条（灯：puc / uc / mxv / exc / comp / 没过）
  /geki 传 <歌> <难度> <技术分> [fc|ab] [fb] [★5 | p<白金分>]
  /sdvx b50（vf）                      → 手动成绩的 VF 50 图
  /sdvx 成绩 <歌>、/geki 成绩 <歌>     → 自己这首歌各难度的成绩
  /sdvx 批量传 + 换行一行一首          → 一次传很多首（格式：曲名 | 难度 | 分数 | 灯，也认聊天那种空格写法）
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from pathlib import Path

from . import calc as K
from . import catalog as C
from .store import AliasBook, ScoreError, ScoreStore, WebSessions

try:
    from ..mai.bot.commands import Ctx, Reply
    from ..mai.data.fuzzy import decide, fold
except ImportError:  # tests import packages top-level
    from mai.bot.commands import Ctx, Reply
    from mai.data.fuzzy import decide, fold

log = logging.getLogger("astrbot")

BUNDLED = os.path.join(os.path.dirname(__file__), "data")
REFRESH_SECS = 86400
LOGIN_WORDS = ("传分", "传分网站", "传分页", "网页传分", "录分", "录分网站", "录分页", "网页录分", "成绩本",
               "scorebook", "login")
RECORD_WORDS = ("传", "上传", "录", "记", "记分", "录入", "add")
BATCH_WORDS = ("批量传", "批量传分", "批量上传", "批量录", "批量", "批量录分", "多录", "batch", "import", "导入")
GAME_WORDS = {"sdvx": "sdvx", "sv": "sdvx", "ボルテ": "sdvx", "geki": "geki", "音击": "geki", "ongeki": "geki",
              "オンゲキ": "geki"}
BATCH_MAX = 300
CSV_MAX = 8000                     # 官网 CSV 一次能有两三千行
EAM_DIFF = {"NOVICE": "NOV", "ADVANCED": "ADV", "EXHAUST": "EXH", "MAXIMUM": "MXM", "INFINITE": "INF",
            "GRAVITY": "GRV", "HEAVENLY": "HVN", "VIVID": "VVD", "EXCEED": "XCD", "NABLA": "NBL", "ULTIMATE": "ULT"}
EAM_LAMP = {"PLAYED": "PLAY", "COMPLETE": "COMP", "EXCESSIVE COMPLETE": "EXC", "MAXXIVE COMPLETE": "MXV",
            "ULTIMATE CHAIN": "UC", "PERFECT": "PUC", "PERFECT ULTIMATE CHAIN": "PUC"}
BATCH_TIP = "（一次传好几首：/{g} 批量传 然后换行一行一首；或者网页上的「批量传分」，还能让别的 AI 看截图帮你写好格式）"
MINE_WORDS = ("成绩", "我的成绩", "查成绩", "pb", "score")
BEST_WORDS = ("b50", "vf", "volforce", "best", "best50", "ra", "rating", "我", "me", "资料")
SDVX_DIFF_WORDS = {
    "nov": "NOV", "novice": "NOV", "绿": "NOV", "adv": "ADV", "advanced": "ADV", "黄": "ADV",
    "exh": "EXH", "exhaust": "EXH", "红": "EXH", "mxm": "MXM", "maximum": "MXM", "白": "MXM",
    "inf": "INF", "infinite": "INF", "grv": "GRV", "gravity": "GRV", "hvn": "HVN", "heavenly": "HVN",
    "vvd": "VVD", "vivid": "VVD", "xcd": "XCD", "exceed": "XCD", "nbl": "NBL", "nabla": "NBL",
    "ult": "ULT", "ultimate": "ULT", "4th": "4TH", "紫": "4TH",
}
GEKI_DIFF_WORDS = {"bas": "BAS", "basic": "BAS", "绿": "BAS", "adv": "ADV", "advanced": "ADV", "黄": "ADV",
                   "exp": "EXP", "expert": "EXP", "红": "EXP", "mas": "MAS", "master": "MAS", "mst": "MAS",
                   "紫": "MAS", "lun": "LUN", "lunatic": "LUN", "remas": "LUN", "re:master": "LUN", "白": "LUN",
                   "bsc": "BAS", "mst": "MAS"}
SCORE_RE = re.compile(r"^\d{1,2}(?:,\d{3}){2}$|^\d{1,3}(?:,\d{3}){1,2}$|^\d{3,8}$")


def _make_thumb(src: str, dst: str, size: int) -> None:
    from PIL import Image
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.LANCZOS)
        tmp = dst + ".tmp"
        im.save(tmp, "JPEG", quality=82, optimize=True, progressive=True)
    os.replace(tmp, dst)


def _int_or_none(s: str) -> int | None:
    s = (s or "").replace(",", "").strip()
    return int(s) if s.isdigit() else None


def parse_score(tok: str) -> int | None:
    t = tok.replace("，", ",")
    if not SCORE_RE.match(t):
        return None
    return int(t.replace(",", ""))


def _field_word(game: str, f: dict, lw: str, allow_late: bool) -> bool:
    """认一个不是分数的词（难度 / 灯 / FB / 星 / 白金分），认出来就填进 f。"""
    dw = SDVX_DIFF_WORDS if game == "sdvx" else GEKI_DIFF_WORDS
    if f["diff"] is None and lw in dw:
        f["diff"] = dw[lw]
    elif f["diff"] is None and game == "sdvx" and lw.upper() in C.SDVX_DIFFS:
        f["diff"] = lw.upper()
    elif not allow_late:
        return False
    elif game == "sdvx" and f["ex"] is None and re.fullmatch(r"ex[:=：]?\d{2,5}", lw):
        f["ex"] = int(re.sub(r"\D", "", lw))
    elif game == "sdvx" and f["lamp"] is None and K.norm_lamp(lw):
        f["lamp"] = K.norm_lamp(lw)
    elif game == "geki" and f["lamp"] is None and lw in K.GEKI_LAMP_WORDS:
        f["lamp"] = K.GEKI_LAMP_WORDS[lw]
    elif game == "geki" and not f["fb"] and lw in ("fb", "fullbell", "满铃"):
        f["fb"] = True
    elif game == "geki" and f["stars"] is None and re.fullmatch(r"(★|☆|\*|星)[0-6]|[0-6](★|☆|星)|★{1,6}", lw):
        f["stars"] = len(lw) if set(lw) == {"★"} else int(re.sub(r"\D", "", lw))
    elif game == "geki" and f["plat"] is None and re.fullmatch(r"p\d{2,5}", lw):
        f["plat"] = int(lw[1:])
    else:
        return False
    return True


def _new_fields() -> dict:
    return {"score": None, "diff": None, "lamp": None, "fb": False, "stars": None, "plat": None, "ex": None}


def parse_tail(game: str, words: list[str]) -> tuple[list[str], dict]:
    """聊天写法：从右往左吃掉 分数 / 难度 / 灯 / FB / 星 / 白金分，剩下的是歌名。
    灯、FB、星只认写在分数右边的（歌名里常有 ex、p 这种词）。"""
    f = _new_fields()
    q = list(words)
    while q:
        w = q[-1]
        lw = w.lower()
        if f["score"] is None and parse_score(w) is not None and len(q) > 1:
            f["score"] = parse_score(w)
        elif f["diff"] is None and len(q) > 1 and _field_word(game, f, lw, False):
            pass
        elif f["score"] is None and _field_word(game, f, lw, True):
            pass
        else:
            break
        q.pop()
    return q, f


def parse_fields(game: str, tokens: list[str]) -> tuple[list[str], dict]:
    """批量的「曲名 | 难度 | 分数 | 灯 | …」写法：曲名以外的栏从左往右认。
    第一个像分数的是分数，之后再出现的小数字（< 2 万）当白金分；等级、占位符（- / 无）忽略。"""
    f = _new_fields()
    left: list[str] = []
    for w in tokens:
        lw = w.lower().strip(".,;")
        if not lw:
            continue
        if f["score"] is None and parse_score(w) is not None and not re.fullmatch(r"\d{1,2}", lw):
            v = parse_score(w)
            if v is not None and v >= 1000:
                f["score"] = v
                continue
        if game == "geki" and f["score"] is not None and f["plat"] is None \
                and re.fullmatch(r"\d{1,2},?\d{3}", lw) and int(lw.replace(",", "")) < 20000:
            f["plat"] = int(lw.replace(",", ""))
        elif game == "sdvx" and f["score"] is not None and f["ex"] is None \
                and re.fullmatch(r"\d{1,2},?\d{3}", lw) and int(lw.replace(",", "")) < 100000:
            f["ex"] = int(lw.replace(",", ""))       # SDVX 分数后面的小数字 = EX SCORE
        elif _field_word(game, f, lw, True):
            pass
        elif re.fullmatch(r"(lv\.?)?\d{1,2}(\.\d)?\+?|-+|—+|none|null|n/a|无|空|没有|没|no", lw):
            pass
        else:
            left.append(w)
    return left, f


def pick_diff(game: str, song, diff: str | None) -> str:
    """没写难度 → MXM / MAS；写了 4TH → 这首的第 4 难度。"""
    if diff is None:
        diff = "MXM" if game == "sdvx" else "MAS"
        if diff not in song.charts:
            diff = "4TH" if game == "sdvx" else ("LUN" if "LUN" in song.charts else diff)
    if game == "sdvx" and (diff == "4TH" or (diff in C.SDVX_DIFFS and diff not in song.charts
                                             and diff not in ("NOV", "ADV", "EXH", "MXM"))):
        fourth = [d for d in song.charts if d not in ("NOV", "ADV", "EXH", "MXM")]
        if fourth:                       # 第 4 难度名字写错了（INF / GRV / HVN…）就按这首实际的
            diff = fourth[-1]
        elif diff == "4TH":
            diff = "MXM"
    return diff


class ScoreBook:
    def __init__(self, root: str, proxy: str | None = None, geki_db=None):
        self.root = os.path.join(root, "scorebook")
        os.makedirs(self.root, exist_ok=True)
        self.proxy = proxy
        self.geki_db = geki_db                    # 插件的音击定数表（OngekiMusicDB）
        self.store = ScoreStore(self.root)
        self.sessions = WebSessions(self.root)
        self.aliases = AliasBook(self.root)
        self.cats: dict[str, C.Catalog] = {}
        self.sdvxin = None                        # chart.sdvxin.SdvxIn：外号互通、SDVX 曲绘
        self.prefs = None                         # core.prefs.Prefs：显示 EX / DX / 白金分的开关（和出图共用）
        self.last_refresh: dict[str, float] = {}
        self.last_error: dict[str, str] = {}
        self._map_cache: dict[str, tuple] = {}
        self._last_game: dict[str, str] = {}
        self._jk_miss: dict[str, float] = {}
        self._jk_busy: dict[str, asyncio.Future] = {}
        self._jk_sem: asyncio.Semaphore | None = None
        for g in C.GAMES:
            self._load(g)

    # ---------- 曲库 ----------
    def _cache_path(self, game: str) -> str:
        return os.path.join(self.root, f"catalog_{game}.json")

    def _load(self, game: str) -> None:
        cat = C.load(self._cache_path(game))
        bundled = C.load(os.path.join(BUNDLED, f"{game}.json"))
        if cat is None or (bundled is not None and bundled.built > cat.built):
            cat = bundled                          # 新版插件自带的比磁盘缓存新
        if cat is not None:
            self.cats[game] = cat
            self._merge_aliases(game)

    def cat(self, game: str) -> C.Catalog | None:
        return self.cats.get(game)

    async def refresh(self, game: str, force: bool = False) -> int:
        """从 Tachi（SDVX）/ otoge-db（音击）重新拉曲库；失败就继续用旧的。返回歌曲数。"""
        if not force and time.time() - self.last_refresh.get(game, 0) < REFRESH_SECS:
            return len(self.cats.get(game) or [])
        import httpx
        kw = {"timeout": 60, "follow_redirects": True}
        if self.proxy:
            kw["proxy"] = self.proxy
        try:
            async with httpx.AsyncClient(**kw) as c:
                if game == "sdvx":
                    r1, r2 = await asyncio.gather(c.get(C.SDVX_URLS[0]), c.get(C.SDVX_URLS[1]))
                    r1.raise_for_status()
                    r2.raise_for_status()
                    data = await asyncio.to_thread(C.build_sdvx, r1.json(), r2.json())
                else:
                    r = await c.get(C.GEKI_URL)
                    r.raise_for_status()
                    data = await asyncio.to_thread(C.build_geki, r.json(), self.geki_db)
        except Exception as e:  # noqa: BLE001
            self.last_error[game] = f"{type(e).__name__}: {e}"[:200]
            self.last_refresh[game] = time.time() - REFRESH_SECS + 3600       # 一小时后再试
            raise
        old = self.cats.get(game)
        if old is not None and len(data["songs"]) < len(old) * 0.9:
            self.last_error[game] = f"新曲库只有 {len(data['songs'])} 首（原来 {len(old)}），没换"
            self.last_refresh[game] = time.time()
            return len(old)
        await asyncio.to_thread(C.save, data, self._cache_path(game))
        self.cats[game] = C.Catalog(data)
        self._merge_aliases(game)
        self.last_refresh[game] = time.time()
        self.last_error.pop(game, None)
        return len(self.cats[game])

    def _sdvxin_map(self, game: str) -> dict[str, str]:
        """fold(标题) → sdvx.in 曲目编号（按 sdvx.in 曲目表缓存，曲目表换了才重算）。"""
        src = self.sdvxin
        ents = (getattr(src, "entries", None) or {}).get(game) or {} if src is not None else {}
        stamp = (id(ents), len(ents))
        hit = self._map_cache.get(game)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        out = self._build_sdvxin_map(ents)
        self._map_cache[game] = (stamp, out)
        return out

    @staticmethod
    def _build_sdvxin_map(ents) -> dict[str, str]:
        out: dict[str, str] = {}
        for sid, e in ents.items():
            if getattr(e, "removed", False) and fold(e.title) in out:
                continue
            out.setdefault(fold(e.title), sid)
        return out

    def _merge_aliases(self, game: str) -> None:
        """传分网站的外号 + sdvx.in 那份（/sdvx 加别名、猜谱面投票）合在一起给搜索用。"""
        cat = self.cats.get(game)
        if cat is None:
            return
        merged: dict[str, list[str]] = {k: list(v) for k, v in self.aliases.get(game).items()}
        src = self.sdvxin
        table = ((getattr(src, "aliases", None) or {}).get(game) or {}) if src is not None else {}
        if table:
            m = self._sdvxin_map(game)
            for k, s in cat.songs.items():
                sid = m.get(fold(s.title))
                for a in table.get(sid, []) if sid else []:
                    lst = merged.setdefault(k, [])
                    if a not in lst:
                        lst.append(a)
        cat.set_aliases(merged)

    def sync_aliases(self) -> None:
        for g in self.cats:
            self._merge_aliases(g)

    def add_alias(self, game: str, song_key: str, alias: str) -> str:
        cat = self.cats.get(game)
        alias = re.sub(r"\s+", " ", alias or "").strip()
        if cat is None or song_key not in cat.songs:
            raise ScoreError("没有这首歌")
        if not alias or len(alias) > 30 or any(ch in alias for ch in "<>\n\r\t"):
            raise ScoreError("外号 1～30 个字，不能有 < > 和换行")
        song = cat.songs[song_key]
        if fold(alias) == fold(song.title):
            raise ScoreError("这就是原名")
        added = self.aliases.add(game, song_key, alias)
        src = self.sdvxin
        if src is not None:                         # 也写进 sdvx.in 那份：/sdvx 谱面、猜谱面都能用
            sid = self._sdvxin_map(game).get(fold(song.title))
            if sid:
                try:
                    src.add_alias(game, alias, sid)
                except Exception as e:  # noqa: BLE001
                    log.warning(f"[otoge] scorebook alias → sdvx.in failed: {e}")
        self._merge_aliases(game)
        return f"加好了：「{alias}」→ {song.title}" if added else f"「{alias}」已经是 {song.title} 的外号了"

    # ---------- 搜歌 ----------
    def find(self, game: str, query: str):
        """→ (Song | None, 候选列表文字)"""
        cat = self.cats.get(game)
        if cat is None:
            return None, "曲库还没加载好，过一会儿再试"
        d = decide(cat.search(query, 12), query)
        if d.item is not None:
            return d.item, d.note
        if d.choices:
            lines = [f"{i + 1}. {m.item.title}" + (f"（{m.name}）" if m.by_alias else "")
                     for i, m in enumerate(d.choices[:6])]
            return None, "有好几首像的，说得更完整一点：\n" + "\n".join(lines)
        return None, f"没找到「{query}」。可以在传分网站上按等级 / 版本找，找到后顺手加个外号"

    def deep_link(self, game: str, rest: str) -> dict:
        """「/sdvx 传分 VICTIM mxm」→ 网页直达参数 {g, k|q, d}。认出唯一一首就给 k（直接打开传分面板），
        认不准就给 q（网页上搜这个词）。"""
        out: dict = {"g": game} if game in ("sdvx", "geki") else {}
        words = rest.split()
        if not words or game not in ("sdvx", "geki"):
            return out
        dw = SDVX_DIFF_WORDS if game == "sdvx" else GEKI_DIFF_WORDS
        if len(words) > 1 and words[-1].lower() in dw:
            out["d"] = dw[words.pop().lower()]
        query = " ".join(words)
        song, _ = self.find(game, query)
        if song is not None:
            out["k"] = song.key
        else:
            out["q"] = query
        return out

    # ---------- 网页曲绘（缩略图） ----------
    JK_SIZE = 160
    JK_MISS_TTL = 6 * 3600

    def jacket_thumb_path(self, game: str, song_key: str) -> str:
        return os.path.join(self.root, "jk", f"{game}_{song_key}.jpg")

    def jacket_ready(self, game: str) -> bool:
        """sdvx.in 曲目表加载好了没有（插件刚重载时还没有，这时拿不到不能算「没有图」）。"""
        return bool((getattr(self.sdvxin, "entries", None) or {}).get(game))

    async def jacket_thumb(self, game: str, song_key: str) -> str | None:
        """传分网站用的曲绘缩略图（160px JPEG，存在 scorebook/jk/）。原图从 sdvx.in 拿（和出图共用缓存），
        同一首同时只拉一次；确实拉不到的 6 小时内不再试（曲目表还没加载好时不记）。"""
        p = self.jacket_thumb_path(game, song_key)
        if os.path.exists(p):
            return p
        cat = self.cats.get(game)
        song = cat.songs.get(song_key) if cat else None
        miss = f"{game}:{song_key}"
        if song is None or not self.jacket_ready(game) \
                or time.time() - self._jk_miss.get(miss, 0) < self.JK_MISS_TTL:
            return None
        fut = self._jk_busy.get(miss)
        if fut is not None:
            return await asyncio.shield(fut)
        fut = asyncio.get_running_loop().create_future()
        self._jk_busy[miss] = fut
        out = None
        try:
            if self._jk_sem is None:
                self._jk_sem = asyncio.Semaphore(3)
            async with self._jk_sem:
                src = await self._jacket_source(game, song)
            if src:
                await asyncio.to_thread(_make_thumb, src, p, self.JK_SIZE)
                out = p if os.path.exists(p) else None
            if out is None:
                self._jk_miss[miss] = time.time()
        except Exception as e:  # noqa: BLE001
            log.debug(f"[otoge] scorebook jacket {miss}: {type(e).__name__}: {e}")
        finally:
            self._jk_busy.pop(miss, None)
            if not fut.done():
                fut.set_result(out)
        return out

    async def _jacket_source(self, game: str, song) -> str | None:
        src = self.sdvxin
        if game == "sdvx":
            sid = self._sdvxin_map("sdvx").get(fold(song.title))
            e = (src.entries.get("sdvx") or {}).get(sid) if sid else None
            if e is None:
                return None
            return await src.song_jacket(e, budget=15)
        got = await src.geki_jackets([song.title], budget=15)
        return got.get(song.title)

    # ---------- 聊天指令 ----------
    def last_game(self, uid: str) -> str:
        """/传、/批量传 没写游戏时用哪个：这次运行里上次传的那个；没有就看谁的成绩多；都没有 SDVX。"""
        g = self._last_game.get(uid)
        if g:
            return g
        n = {x: len(self.store.scores(uid, x)) for x in ("sdvx", "geki")}
        return "geki" if n["geki"] > n["sdvx"] else "sdvx"

    async def handle(self, ctx: Ctx, game: str, sub: str, rest: str) -> Reply | None:
        """sub 是第一个词（已小写）；不是传分本的指令就返回 None。"""
        if sub in RECORD_WORDS or sub in BATCH_WORDS:
            self._last_game[ctx.uid] = game
        if sub in RECORD_WORDS:
            return self._record(ctx, game, rest)
        if sub in BATCH_WORDS:
            return self._batch_chat(ctx, game, rest)
        if sub in MINE_WORDS and rest.strip():
            return self._mine(ctx, game, rest.strip())
        return None

    def _record(self, ctx: Ctx, game: str, rest: str) -> Reply:
        words = rest.split()
        usage = ("用法：/sdvx 传 <歌名/外号> <难度> <分数> [灯] [ex<EX SCORE>]\n例：/sdvx 传 魔理沙 mxm 9,912,345 uc ex4321\n"
                 "难度 nov/adv/exh/mxm（第 4 难度写 4th 或名字，如 inf / vvd / xcd / nbl）；灯 puc / uc / mxv / exc / comp / 没过，不写算 comp"
                 if game == "sdvx" else
                 "用法：/geki 传 <歌名/外号> <难度> <技术分> [fc|ab] [fb] [★5 或 p<白金分>]\n"
                 "例：/geki 传 アイシング mas 1,007,321 ab fb ★4\n难度 bas/adv/exp/mas/lun")
        q, f = parse_tail(game, words)
        score, diff, lamp, fb, stars, plat, ex = f["score"], f["diff"], f["lamp"], f["fb"], f["stars"], f["plat"], f["ex"]
        if not q or score is None:
            return Reply().say(usage)
        song, note = self.find(game, " ".join(q))
        if song is None:
            return Reply().say(note)
        diff = pick_diff(game, song, diff)
        ch = song.charts.get(diff)
        if ch is None:
            return Reply().say(f"{song.title} 没有 {diff}（有：{' / '.join(song.charts)}）")
        try:
            if game == "sdvx":
                res = self.store.put_sdvx(ctx.uid, ch.key, score, lamp, ex=ex)
            else:
                res = self.store.put_geki(ctx.uid, ch.key, score, lamp or "", fb, plat, stars)
        except ScoreError as e:
            return Reply().say(str(e))
        self.store.set_name(ctx.uid, ctx.name)
        text = self._saved_text(game, ctx.uid, ch, res, note)
        if self._recent_records(ctx.uid, game) >= 2:      # 连着传第二首起，提示能批量
            text += "\n" + BATCH_TIP.format(g=game)
        return Reply().say(text)

    def _recent_records(self, uid: str, game: str, window: int = 1800) -> int:
        now = time.time()
        return sum(1 for r in self.store.scores(uid, game).values() if now - float(r.get("t") or 0) < window)

    # ---------- 批量传分 ----------
    def resolve(self, game: str, title: str, diff: str | None):
        """批量用的找歌：先按曲名原文（折叠后）精确找，再模糊找。→ (Song | None, 候选 [Song], 说明)"""
        cat = self.cats.get(game)
        if cat is None:
            return None, [], "曲库还没加载好"
        ft = fold(title)
        exact = [s for s in cat.songs.values() if fold(s.title) == ft] if ft else []
        if diff and len(exact) > 1:
            exact = [s for s in exact if pick_diff(game, s, diff) in s.charts] or exact
        if len(exact) > 1:          # 同名：优先还在现行机台的
            cur = [s for s in exact if any(c.current == 1 for c in s.charts.values())]
            exact = cur if len(cur) == 1 else exact
        if len(exact) == 1:
            return exact[0], [], ""
        if exact:
            return None, exact[:6], "同名的歌有好几首"
        d = decide(cat.search(title, 12), title)
        if d.item is not None:
            return d.item, [], d.note
        if d.choices:
            return None, [m.item for m in d.choices[:6]], "有好几首像的"
        return None, [], f"没找到「{title}」"

    @staticmethod
    def is_eam_csv(text: str) -> bool:
        head = (text or "").lstrip("\ufeff \t\r\n")[:300]
        return "楽曲名" in head and "難易度" in head and "," in head

    def parse_eam_csv(self, text: str) -> list[dict]:
        """SDVX 官网（e-amusement，要会员）导出的成绩 CSV：
        楽曲名,難易度,楽曲レベル,クリアランク,スコアグレード,ハイスコア,EXスコア,プレー回数,クリア回数,ULTIMATE CHAIN,PERFECT
        （列的含义参考了 Tachi 的导入器；曲名里的空格是不换行空格。）"""
        import csv
        import io
        rd = csv.reader(io.StringIO(text.lstrip("\ufeff").strip()))
        header = next(rd, None) or []
        col = {h.strip(): i for i, h in enumerate(header)}
        need = ("楽曲名", "難易度", "クリアランク", "ハイスコア")
        if not all(k in col for k in need):
            return [{"line": 1, "raw": ",".join(header)[:200], "ok": False, "choices": [],
                     "err": "CSV 表头不认识（要官网导出的原文件）"}]
        rows: list[dict] = []
        for n, cells in enumerate(rd, 2):
            if not cells or not "".join(cells).strip():
                continue
            if len(rows) >= CSV_MAX:
                break
            get = lambda k: (cells[col[k]] if col[k] < len(cells) else "").strip()   # noqa: E731
            title = re.sub(r"\s", " ", get("楽曲名").replace("\u00a0", " ")).strip()
            diff = EAM_DIFF.get(get("難易度").upper())
            lamp = EAM_LAMP.get(get("クリアランク").upper())
            r = {"line": n, "raw": ",".join(cells)[:200], "ok": False, "err": "", "choices": [],
                 "score": _int_or_none(get("ハイスコア")), "lamp": lamp, "fb": False, "stars": None, "plat": None,
                 "ex": _int_or_none(get("EXスコア")) or None,
                 "title_in": title, "diff_in": diff or ""}
            if r["score"] is None or r["score"] <= 0:
                continue                                    # 没打过 / 0 分的行不要
            if diff is None:
                r["err"] = f"难度不认识：{get('難易度')}"
            elif lamp is None:
                r["err"] = f"灯不认识：{get('クリアランク')}"
            if r["err"]:
                rows.append(r)
                continue
            song, cands, note = self.resolve("sdvx", title, diff)
            if song is None:
                r["err"] = note
                r["choices"] = [{"k": s.key, "t": s.title, "a": s.artist} for s in cands]
            else:
                self._fill_row("sdvx", r, song, diff, note)
            rows.append(r)
        return rows

    def parse_batch(self, game: str, text: str) -> list[dict]:
        """一段文字 → 每行一条预览。认这些写法（别的 AI 照截图写的也行）：
            VICTIM | MXM | 9,912,345 | UC            （| / 制表符 / 全角｜ 分隔，推荐）
            VICTIM mxm 9912345 uc                    （聊天那种，空格分隔，从右往左认）
            1. VICTIM | MXM | 9912345 | UC           （前面带序号也行）
        空行、# 开头、``` 、表头行（曲名 | 难度 …）跳过。
        SDVX 官网导出的 CSV（第一行是 楽曲名,難易度,…）整份贴进来也认。"""
        if game == "sdvx" and self.is_eam_csv(text):
            return self.parse_eam_csv(text)
        rows: list[dict] = []
        for n, raw in enumerate((text or "").splitlines()[:BATCH_MAX * 2], 1):
            line = raw.strip().strip("`").strip()
            if not line or line.startswith(("#", "//")) or re.fullmatch(r"[-|:\s=]+", line):
                continue
            line = re.sub(r"^(?:\d{1,3}[.)、:：]\s*|[-*•・]\s+)", "", line)
            parts = [p.strip() for p in re.split(r"\s*[|｜\t]\s*", line) if p.strip()] if re.search(r"[|｜\t]", line) else None
            if parts and fold(parts[0]) in ("曲名", "歌名", "title", "song", "曲目"):
                continue
            r = {"line": n, "raw": raw.strip()[:200], "ok": False, "err": "", "choices": []}
            if parts:
                title = parts[0]
                tail = " ".join(parts[1:]).replace("?", " ").replace("？", " ").split()
                rest, f = parse_fields(game, tail)
                if rest:
                    r["warn"] = "没认出：" + " ".join(rest)[:40]
            else:
                q, f = parse_tail(game, line.split())
                title = " ".join(q)
            r.update({k: f[k] for k in ("score", "lamp", "fb", "stars", "plat", "ex")})
            if not title:
                r["err"] = "没有曲名"
            elif f["score"] is None:
                r["err"] = "没有分数"
            if r["err"]:
                rows.append(r)
                if len(rows) >= BATCH_MAX:
                    break
                continue
            song, cands, note = self.resolve(game, title, f["diff"])
            r["title_in"], r["diff_in"] = title, f["diff"] or ""
            if song is None:
                r["err"] = note
                r["choices"] = [{"k": s.key, "t": s.title, "a": s.artist} for s in cands]
            else:
                self._fill_row(game, r, song, f["diff"], note)
            rows.append(r)
            if len(rows) >= BATCH_MAX:
                break
        return rows

    def _fill_row(self, game: str, r: dict, song, diff: str | None, note: str = "") -> None:
        d = pick_diff(game, song, diff)
        ch = song.charts.get(d)
        r.update({"k": song.key, "t": song.title, "d": d})
        if ch is None:
            r["err"] = f"没有 {d}（有：{' / '.join(song.charts)}）"
            return
        r["key"], r["lv"] = ch.key, ch.level
        if note:
            r["note"] = note
        if diff is None:
            r["note"] = (r.get("note", "") + " 没写难度，按 " + d).strip()
        mx = K.SDVX_MAX if game == "sdvx" else K.GEKI_MAX
        if not 0 <= int(r["score"]) <= mx:
            r["err"] = f"分数超出范围（最多 {mx:,}）"
            return
        if game == "sdvx" and r.get("lamp") == "PUC" and int(r["score"]) != K.SDVX_MAX:
            r["err"] = f"写了 PUC 但分数不是 10,000,000（{int(r['score']):,}，是不是 UC？）"
            return
        if game == "sdvx" and int(r["score"]) == K.SDVX_MAX:
            r["lamp"] = "PUC"
        r["ok"] = True

    def apply_batch(self, uid: str, name: str, game: str, rows: list[dict], overwrite: bool = False,
                    limit: int = CSV_MAX) -> dict:
        """rows: [{key, score, lamp, fb, stars, plat}] → 逐条传（规则和单条一样：只升不降，除非 overwrite）。"""
        cat = self.cats[game]
        before = self.total(uid, game)
        done, same, kept, errs = 0, 0, 0, []
        for r in rows[:limit]:
            ch = cat.charts.get(str(r.get("key") or ""))
            if ch is None:
                errs.append(f"{r.get('key')}：没有这张谱面")
                continue
            try:
                score = int(str(r.get("score")).replace(",", ""))
                if game == "sdvx":
                    lamp = K.norm_lamp(str(r.get("lamp") or "")) or None
                    ex = r.get("ex")
                    res = self.store.put_sdvx(uid, ch.key, score, lamp, overwrite,
                                              int(ex) if ex not in (None, "") else None)
                else:
                    lamp = str(r.get("lamp") or "").upper()
                    lamp = K.GEKI_LAMP_WORDS.get(lamp.lower(), lamp) if lamp else ""
                    plat, stars = r.get("plat"), r.get("stars")
                    res = self.store.put_geki(uid, ch.key, score, lamp, bool(r.get("fb")),
                                              int(plat) if plat not in (None, "") else None,
                                              int(stars) if stars not in (None, "") else None, overwrite)
            except (ScoreError, ValueError, TypeError) as e:
                errs.append(f"{ch.song.title} {ch.diff}：{e if isinstance(e, ScoreError) else '分数不对'}")
                continue
            done += 1
            same += 0 if res.get("changed") else 1
            kept += 1 if res.get("kept_higher") else 0
        if name:
            self.store.set_name(uid, name)
        after = self.total(uid, game)
        return {"done": done, "unchanged": same, "kept_higher": kept, "errors": errs[:30],
                "before": before, "after": after, "delta": after - before}

    def total(self, uid: str, game: str) -> int:
        if game == "sdvx":
            return K.sdvx_total(K.sdvx_rows(self.cats["sdvx"], self.store.scores(uid, "sdvx")))
        return K.geki_best(self.cats["geki"], self.store.scores(uid, "geki")).calc or 0

    def fmt_total(self, game: str, v: int) -> str:
        return K.fmt_k(v) if game == "sdvx" else K.GR.fmt(v)

    def _batch_chat(self, ctx: Ctx, game: str, text: str) -> Reply:
        fmt = ("曲名 | 难度 | 分数 | 灯 | EX SCORE（可不写）" if game == "sdvx" else "曲名 | 难度 | 技术分 | 灯 | FB | 白金分")
        ex = ("VICTIM | MXM | 9,912,345 | UC\n魔理沙 | EXH | 9,700,000 | EXC" if game == "sdvx" else
              "Demonia | MAS | 1,007,321 | AB | FB | p4100\nアイシング | EXP | 1,001,000 | FC")
        if not text.strip():
            return Reply().say(f"批量传：/{game} 批量传 后面换行，一行一首：\n{fmt}\n例：\n/{game} 批量传\n{ex}\n"
                               "也认空格写法（VICTIM mxm 9912345 uc）。分数只升不降。\n"
                               "截图让别的 AI 认：网页「批量传分」里有现成的提示词，复制给它，它写好的直接贴过来。")
        rows = self.parse_batch(game, text)
        good = [r for r in rows if r["ok"]]
        bad = [r for r in rows if not r["ok"]]
        if not good:
            lines = ["一行都没认出来。格式：" + fmt]
            lines += [f"第 {r['line']} 行：{r['err']}" + (("（" + " / ".join(c["t"] for c in r["choices"][:3]) + "）") if r["choices"] else "")
                      for r in bad[:8]]
            return Reply().say("\n".join(lines))
        res = self.apply_batch(ctx.uid, ctx.name, game, good)
        word = "VF" if game == "sdvx" else "rating"
        dl = res["delta"]
        lines = [f"传了 {res['done']} 张" + (f"（{res['unchanged']} 张和之前一样）" if res["unchanged"] else "")
                 + (f"，{res['kept_higher']} 张之前更高、保留了高的" if res["kept_higher"] else ""),
                 f"{word} {self.fmt_total(game, res['before'])} → {self.fmt_total(game, res['after'])}"
                 + (f"（{'+' if dl > 0 else ''}{self.fmt_total(game, dl) if dl >= 0 else '-' + self.fmt_total(game, -dl)}）" if dl else "")]
        notes = [f"· {r['t']} → 按 {r['d']}" for r in good if r.get("diff_in") == ""][:5]
        if notes:
            lines.append("没写难度的：\n" + "\n".join(notes))
        if bad or res["errors"]:
            lines.append("没传上的：")
            for r in bad[:10]:
                tip = ("（是不是：" + " / ".join(c["t"] for c in r["choices"][:3]) + "？写完整一点）") if r["choices"] else ""
                lines.append(f"第 {r['line']} 行 {r.get('title_in') or r['raw'][:20]}：{r['err']}{tip}")
            lines += res["errors"][:5]
        lines.append(f"看全部发 /{game} b50")
        return Reply().say("\n".join(lines))

    def _saved_text(self, game: str, uid: str, ch, res: dict, note: str = "") -> str:
        rec = res["new"]
        head = f"{ch.song.title} [{ch.diff} {ch.level}]"
        if game == "sdvx":
            vf = K.sdvx_vf(ch.num, rec["s"], rec["l"])
            line = f"{head}\n{rec['s']:,}  {K.grade(rec['s'])[0]}  {rec['l']}" + (f"  EX {rec['x']:,}" if rec.get('x') else "") + f"  →  单曲 {K.fmt_song(vf)}"
            rows = K.sdvx_rows(self.cats["sdvx"], self.store.scores(uid, "sdvx"))
            rank = next((i for i, r in enumerate(rows) if r.key == ch.key), 99)
            total = K.sdvx_total(rows)
            line += f"\n{'进了 VF 50（第 ' + str(rank + 1) + ' 名）' if rank < 50 else '没进 VF 50'}，现在总 VF {K.fmt_k(total)}"
        else:
            v = K.geki_chart_value(ch, rec)
            lamp = ("AB+" if rec.get("l") == "AB" and rec["s"] >= K.GEKI_MAX else rec.get("l") or "")
            extra = " ".join(x for x in (lamp, "FB" if rec.get("fb") else "",
                                         f"★{rec['st']}" if rec.get("st") else "") if x)
            line = f"{head}\n{rec['s']:,} {extra}".rstrip()
            if v["rate"] is not None:
                line += f"  →  单曲 {K.GR.fmt(v['rate'])}"
            best = K.geki_best(self.cats["geki"], self.store.scores(uid, "geki"))
            if best.calc is not None:
                line += f"\n现在 rating（只算你传过的）{K.GR.fmt(best.calc)}"
        if res.get("kept_higher"):
            old = res["old"]
            line += f"\n（之前传过更高的 {int(old.get('s') or 0):,}，保留高的；传错了去网页上改）"
        elif not res.get("changed"):
            line += "\n（和之前一样，没变）"
        return (note + "\n" if note else "") + line

    def _mine(self, ctx: Ctx, game: str, query: str) -> Reply:
        song, note = self.find(game, query)
        if song is None:
            return Reply().say(note)
        book = self.store.scores(ctx.uid, game)
        lines = [song.title + (f"（{note}）" if note else "")]
        for d, ch in song.charts.items():
            r = book.get(ch.key)
            if not r:
                lines.append(f"{d} {ch.level}：—")
            elif game == "sdvx":
                lines.append(f"{d} {ch.level}：{r['s']:,} {K.grade(r['s'])[0]} {r['l']}"
                             + (f" EX {r['x']:,}" if r.get("x") else "")
                             + f"  {K.fmt_song(K.sdvx_vf(ch.num, r['s'], r['l']))}")
            else:
                v = K.geki_chart_value(ch, r)
                lines.append(f"{d} {ch.level}：{r['s']:,} {r.get('l') or ''}{' FB' if r.get('fb') else ''}"
                             + (f" P {r['p']:,}" if r.get("p") else "")
                             + (f"  {K.GR.fmt(v['rate'])}" if v["rate"] is not None else ""))
        if not any(book.get(ch.key) for ch in song.charts.values()):
            lines.append("还没传过。发「/" + game + " 传分」打开传分网站，或者 /" + game + " 传 <歌> <难度> <分数>")
        return Reply().say("\n".join(lines))

    # ---------- B50 ----------
    def sdvx_text(self, uid: str, full: bool = False) -> str:
        rows = K.sdvx_rows(self.cats["sdvx"], self.store.scores(uid, "sdvx"))
        if not rows:
            return "你还没传过 SDVX 成绩。发「/sdvx 传分」打开传分网站，或者 /sdvx 传 <歌> <难度> <分数> [灯]"
        total = K.sdvx_total(rows)
        out = [f"VOLFORCE {K.fmt_k(total)}（{K.vf_class(total)}）· 手动传分 {len(rows)} 张",
               "（每首后面是单曲 VF ×50，50 张平均 = 总 VF）"]
        for i, r in enumerate(rows[:50 if full else 20]):
            ex = f" EX {r.ex:,}" if r.ex and (self.prefs is None or self.prefs.show(uid, "sdvx_ex")) else ""
            out.append(f"#{i + 1} {r.title} [{r.diff} {r.level}] {r.score:,} {r.lamp}{ex}  {K.fmt_song(r.vf)}")
        if not full and len(rows) > 20:
            out.append("（列全部 50 张发「/sdvx b50 文字 全」）")
        return "\n".join(out)

    async def sdvx_image(self, uid: str, name: str, bot_name: str, font_path=None,
                         tz: str = "Australia/Sydney") -> bytes | None:
        rows = K.sdvx_rows(self.cats["sdvx"], self.store.scores(uid, "sdvx"))
        if not rows:
            return None
        from .sdvx_img import render
        top = rows[:50]
        jackets = await self._sdvx_jackets([r.title for r in top])
        all_rows = rows
        out = Path(tempfile.gettempdir()) / f"otoge_sdvx_{time.time_ns()}.jpg"
        await asyncio.to_thread(render, top, out, player=name, jackets=jackets, font_path=font_path, tz=tz,
                                footer_left=f"Generated by {bot_name}", count=len(rows), all_rows=all_rows,
                                show_ex=self.prefs.show(uid, "sdvx_ex") if self.prefs is not None else True)
        try:
            return out.read_bytes()
        finally:
            try:
                out.unlink()
            except OSError:
                pass

    async def _sdvx_jackets(self, titles: list[str], budget: float = 25) -> dict[str, str]:
        src = self.sdvxin
        if src is None or not (getattr(src, "entries", None) or {}).get("sdvx"):
            return {}
        m = self._sdvxin_map("sdvx")
        out: dict[str, str] = {}
        todo = []
        for t in dict.fromkeys(titles):
            sid = m.get(fold(t))
            e = src.entries["sdvx"].get(sid) if sid else None
            if e is None:
                continue
            p = src.song_jacket_path(e)
            if os.path.exists(p):
                out[t] = p
            else:
                todo.append((t, e))
        if todo:
            sem = asyncio.Semaphore(2)

            async def one(t, e):
                async with sem:
                    p = await src.song_jacket(e, budget=15)
                    if p:
                        out[t] = p
            try:
                await asyncio.wait_for(asyncio.gather(*(one(t, e) for t, e in todo)), budget)
            except asyncio.TimeoutError:
                pass
        return out
