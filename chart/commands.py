"""谱面 commands: /chu 谱面 <歌> [难度] · /geki 谱面 <歌> [难度] · /sdvx 谱面 <歌> [难度] · /pjsk 谱面 <歌> [难度] · /谱面 <歌>.

Answer = the sdvx.in chart picture + title / difficulty / level (CHUNITHM: 定数 of every server), BPM, note
counts, charter, the chart-confirmation YouTube videos and the sdvx.in viewer link.
"""
from __future__ import annotations

import asyncio
import re
import logging

from .sdvxin import DIFF_WORDS, DIFFS, GAME_LABEL, Entry, SdvxIn

try:
    from ..mai.bot.commands import Ctx, Reply
    from ..mai.data.fuzzy import decide
except ImportError:  # tests import packages top-level
    from mai.bot.commands import Ctx, Reply
    from mai.data.fuzzy import decide

log = logging.getLogger("astrbot")

CMD = {"chu": "/chu 谱面", "sdvx": "/sdvx 谱面", "pjsk": "/pjsk 谱面", "geki": "/geki 谱面"}
SUB_CHART = ("谱面", "谱", "谱面确认", "chart", "查谱", "谱面图")
SUB_SEARCH = ("查", "查歌", "song", "查曲")
DEFAULT_DIFF = {"chuwe": ("we",), "chu": ("mst", "exp", "ult"), "sdvx": ("mxm", "exh", "adv"), "pjsk": ("mst", "apd", "exp"),
                "geki": ("mst", "exp", "lun")}
# every difficulty, easiest slot first (used to pick "the hardest chart" when no difficulty was asked for)
ALL_DIFF = {"chu": ("bsc", "adv", "exp", "mst", "ult"), "sdvx": ("nov", "adv", "exh", "mxm"),
            "pjsk": ("esy", "nml", "hrd", "exp", "mst", "apd"), "geki": ("bsc", "adv", "exp", "mst")}
# ONGEKI: LUNATIC is its own thing too, so "the hardest" stops at MASTER (LUNATIC-only songs → LUNATIC)
PREFERRED = {"pjsk": "mst"}      # PJSK: MASTER first (APPEND is its own thing); only without MASTER take the hardest
CHU_DIFF_INDEX = {"bsc": 0, "adv": 1, "exp": 2, "mst": 3, "ult": 4}
SERVER_LABEL = {"intl": "国际服", "jp": "日服", "cn": "国服"}

HELP = """谱面查询（数据和谱面图来自 sdvx.in）
/chu 谱面 <歌名/外号> [紫|红|黑|exp|mst|ult|we]（WORLD'S END 写 we，同名有几张时再加字，如 we 狂）
/sdvx 谱面 <歌名> [nov|adv|exh|mxm]（第 4 难度 INF/GRV/HVN/VVD/XCD 都写 mxm 或直接写名字）
/pjsk 谱面 <歌名> [exp|mst|apd]
/geki 谱面 <歌名> [红|紫|lun]（音击；LUNATIC / Re:MASTER 写 lun 或 白）
/谱面 <歌名>：四个游戏一起找
不写难度 = 这首歌最难的那张（中二不算 WE、音击不算 LUNATIC；PJSK 出 MASTER）
回：谱面图 + 定数 / BPM / 物量 / 谱师 + 谱面确认视频 + sdvx.in 链接
/sdvx 加别名 <外号> <歌名>、/pjsk 加别名 …、/geki 加别名 …：教我外号（中二用 /chu 加别名）"""


def level_num(e: Entry, key: str) -> float:
    """14+ → 14.5, sdvx "h184" → 18.4, pjsk "32" → 32; unknown → -1."""
    lv = e.level(key).lstrip("_")
    m = re.search(r"(\d+)(\.\d+)?(\+)?", lv)          # sdvx 4th: "h184"
    if not m:
        return -1.0
    digits = m.group(1)
    if e.game == "sdvx" and len(digits) == 3 and not m.group(2):
        return int(digits) / 10
    return float(digits + (m.group(2) or "")) + (0.5 if m.group(3) else 0)


def hardest(e: Entry, game: str) -> str:
    """The hardest chart of a song (CHUNITHM: never WORLD'S END) — highest level, later slot on ties.
    Charts that sdvx.in can show win over ones it can't."""
    keys = ALL_DIFF.get(game, DEFAULT_DIFF.get(game, ()))
    pref = PREFERRED.get(game)
    if pref and (e.has_view(pref) or e.exists(pref)):
        return pref
    for ok in (e.has_view, e.exists):
        have = [(level_num(e, k), i, k) for i, k in enumerate(keys) if ok(k)]
        if have:
            return max(have)[2]
    return next((k for k in DEFAULT_DIFF[game] if e.exists(k)), DEFAULT_DIFF[game][0])


def split_diff(game: str, words: list[str]) -> tuple[str | None, list[str]]:
    table = DIFF_WORDS[game]
    key, rest = None, []
    for w in words:
        k = table.get(w.lower())
        if k and key is None and (rest or len(words) > 1):
            key = k
        else:
            rest.append(w)
    return key, rest


class ChartCommands:
    def __init__(self, sdvxin: SdvxIn, chu=None):
        self.src = sdvxin
        self.chu = chu            # chuni.commands.ChuCommands: song DB, aliases, per-server constants

    # ---------- entry points ----------
    async def handle(self, ctx: Ctx, argline: str, game: str) -> Reply:
        words = argline.split()
        if game == "chart":
            if not words or words[0] in ("帮助", "help"):
                return Reply().say(HELP)
            return await self._any(" ".join(words))
        if not words or words[0] in ("帮助", "help", "?"):
            return Reply().say(HELP)
        sub = words[0].lower()
        if game != "chu" and sub in ("b50", "b40", "b30", "绑定", "解绑", "我", "最近", "成绩", "刷新成绩", "定数", "定数表"):
            return Reply().say(f"{GAME_LABEL[game]} 这边只有谱面查询：{CMD[game]} <歌名> [难度]")
        if sub in ("加别名", "添加别名") and game != "chu":
            return await self._alias_add(game, words[1:])
        if sub in ("刷新", "更新"):
            n = await self.src.ensure(game, force=True)
            return Reply().say(f"已刷新 sdvx.in {GAME_LABEL[game]} 曲目列表：{n} 首")
        if sub in SUB_CHART or sub in SUB_SEARCH:
            words = words[1:]
        if not words:
            return Reply().say(f"用法：{CMD[game]} <歌名> [难度]")
        try:
            return await asyncio.wait_for(self._chart(game, words), 120)
        except asyncio.TimeoutError:
            return Reply().say("sdvx.in 响应太慢了，过一会儿再试")

    # ---------- lookup ----------
    async def _find(self, game: str, q: str):
        """→ (entry, error reply, note). CHUNITHM goes through the plugin's song DB first (its aliases are richer)."""
        await self.src.ensure(game)
        chu_err = None
        if game == "chu" and self.chu is not None:
            try:
                await self.chu._ensure_catalog()
                song, chu_err, note = self.chu.find_song(q, "谱面")
            except Exception:  # noqa: BLE001
                song, chu_err, note = None, None, ""
            if song is not None:
                e = self.src.by_title("chu", song.title)
                if e is not None:
                    e.chu_song = song          # the exact song (not its WORLD'S END twin) for 定数
                    return e, None, note
                return None, Reply().say(f"{song.title}：sdvx.in 上还没有这首的谱面确认"), ""
        if not self.src.entries[game]:
            return None, Reply().say(f"连不上 sdvx.in，{GAME_LABEL[game]} 曲目列表还没下载下来（{self.src.last_error or '稍后再试'}）"), ""
        d = decide(self.src.index(game).search(q, 8), q)
        if d.item is not None:
            return d.item, None, d.note
        if chu_err is not None and any("可能是" in t for t in chu_err.texts):
            return None, chu_err, ""
        if d.choices:
            lines = [f"「{q}」可能是这几首，换个更完整的名字再查："]
            for i, m in enumerate(d.choices, 1):
                lines.append(f"{i}. {m.item.title}" + (f"（{m.item.artist}）" if m.item.artist else ""))
            return None, Reply().say("\n".join(lines)), ""
        return None, Reply().say(f"sdvx.in 的 {GAME_LABEL[game]} 里没找到「{q}」"), ""

    async def _chart(self, game: str, words: list[str]) -> Reply:
        key, rest = split_diff(game, words)
        if game == "chu" and key == "we":
            return await self._we(rest)
        q = " ".join(rest)
        e, err, note = await self._find(game, q)
        if err:
            return err
        if key is None:
            key = hardest(e, game)
        return await self._answer(e, key, note)

    async def _we(self, words: list[str]) -> Reply:
        """CHUNITHM WORLD'S END: its own sdvx.in list; one title can have several (狂 / 嘘 / 改 …)."""
        try:
            from ..mai.data.fuzzy import fold
        except ImportError:
            from mai.data.fuzzy import fold
        await self.src.ensure("chuwe")
        if not self.src.entries["chuwe"]:
            return Reply().say(f"连不上 sdvx.in，WORLD'S END 列表还没下载下来（{self.src.last_error or '稍后再试'}）")
        kanji = {e.level("we").lstrip("_")[:1] for e in self.src.entries["chuwe"].values()}
        mark = next((w for w in words if len(w) == 1 and w in kanji), None)
        q = " ".join(w for w in words if w != mark)
        if not q:
            return Reply().say("用法：/chu 谱面 <歌名> we [狂|嘘|…]")
        title = None
        if self.chu is not None:                 # nicknames from the CHUNITHM song DB
            try:
                await self.chu._ensure_catalog()
                d0 = decide(self.chu.svc.songdb.search_ranked(q, 6), q)
                title = d0.item.title if d0.item is not None else None
            except Exception:  # noqa: BLE001
                title = None
        if title is None or not any(fold(e.title) == fold(title) for e in self.src.entries["chuwe"].values()):
            d = decide(self.src.index("chuwe").search(q, 8), q)
            if d.item is None and d.choices and len({fold(m.item.title) for m in d.choices
                                                     if m.score >= 95}) == 1 and d.choices[0].score >= 95:
                d.item = d.choices[0].item          # several WORLD'S END charts of one title: handled below
            if d.item is None:
                if d.choices:
                    names = list(dict.fromkeys(m.item.title for m in d.choices))
                    return Reply().say(f"「{q}」的 WORLD'S END 可能是：" + "、".join(names[:6]))
                return Reply().say(f"sdvx.in 的 WORLD'S END 里没找到「{q}」")
            title = d.item.title
        same = [e for e in self.src.entries["chuwe"].values() if fold(e.title) == fold(title)]
        if mark:
            same = [e for e in same if e.level("we").lstrip("_").startswith(mark)] or same
        same.sort(key=lambda e: (e.removed, not e.has_view("we")))
        if len(same) > 1 and not mark:
            opts = "、".join(f"{e.level_text('we')}" for e in same)
            first = same[0].level("we").lstrip("_")[:1]
            r = await self._answer(same[0], "we", "")
            r.say(f"（{title} 有 {len(same)} 张 WORLD'S END：{opts}；查别的发「/chu 谱面 {q} we {first}」这种格式换字）")
            return r
        return await self._answer(same[0], "we", "")

    async def _any(self, q: str) -> Reply:
        """/谱面 <歌>: look in all three games, take the clearest match."""
        wk, wrest = split_diff("chu", q.split())
        if wk == "we":
            return await self._we(wrest)
        best = None
        for game in ("chu", "geki", "sdvx", "pjsk"):
            try:
                await self.src.ensure(game)
            except Exception:  # noqa: BLE001
                continue
            words = q.split()
            key, rest = split_diff(game, words)
            qq = " ".join(rest) or q
            ms = self.src.index(game).search(qq, 3)
            score = ms[0].score if ms else 0
            if game == "chu" and self.chu is not None:
                try:
                    await self.chu._ensure_catalog()
                    r = self.chu.svc.songdb.search_ranked(qq, 3)
                    if r and r[0].score > score:
                        e = self.src.by_title("chu", r[0].item.title)
                        if e is not None:
                            score, ms = r[0].score, [type("M", (), {"item": e, "score": r[0].score})()]
                except Exception:  # noqa: BLE001
                    pass
            if ms and (best is None or score > best[0]):
                best = (score, game, ms[0].item, key)
        if best is None or best[0] < 55:
            return Reply().say(f"四个游戏（中二 / 音击 / SDVX / PJSK）里都没找到「{q}」。"
                               "指定游戏试试：/chu 谱面、/geki 谱面、/sdvx 谱面、/pjsk 谱面")
        _s, game, e, key = best
        if key is None:
            key = hardest(e, game)
        r = await self._answer(e, key, "")
        others = " / ".join(CMD[g] for g in ("chu", "geki", "sdvx", "pjsk") if g != game)
        r.texts.insert(0, f"（按 {GAME_LABEL[game]} 找到的；别的游戏用 {others}）")
        return r

    # ---------- answer ----------
    def _info(self, e: Entry, key: str) -> list[str]:
        raw = e.raw
        lines = [f"{e.title}" + (f" / {e.artist}" if e.artist else "") + ("（已删除）" if e.removed else "")]
        head = f"[{GAME_LABEL[e.game]} {e.diff_label(key)} {e.level_text(key)}]"
        if e.game == "chu":
            consts = self._chu_consts(e, key)
            if consts:
                vals = list(dict.fromkeys(consts.values()))
                if len(vals) == 1:
                    head += f" 定数 {vals[0]:.1f}"
                else:
                    head += " 定数 " + " / ".join(f"{SERVER_LABEL[s]} {v:.1f}" for s, v in consts.items())
        if raw.get("bpm"):
            head += f"  BPM {raw.get('bpm')}"
        lines.append(head)
        counts = self._counts(e, key)
        if counts:
            lines.append("物量 " + counts)
        who = self._designer(e, key)
        if who:
            lines.append(who)
        yt = e.youtube(key)
        if yt:
            lines.append("谱面确认：" + "  ".join(yt))
        lines.append("sdvx.in：" + e.viewer_url(key))
        return lines

    def _chu_consts(self, e: Entry, key: str) -> dict:
        if self.chu is None or key not in CHU_DIFF_INDEX:
            return {}
        try:
            from ..chuni.models import Difficulty
        except ImportError:
            from chuni.models import Difficulty
        try:
            song = getattr(e, "chu_song", None)
            if song is None:
                try:
                    from ..mai.data.fuzzy import fold
                except ImportError:
                    from mai.data.fuzzy import fold
                same = [m.item for m in self.chu.svc.songdb.search_ranked(e.title, 8)
                        if fold(m.item.title) == fold(e.title)]
                same.sort(key=lambda x: (Difficulty(CHU_DIFF_INDEX[key]) not in x.charts, x.id >= 8000))
                song = same[0] if same else None
            if song is None:
                return {}
            v = self.chu.svc.consts_for(song).get(Difficulty(CHU_DIFF_INDEX[key]), {})
            return {s: float(v[s]) for s in ("intl", "jp", "cn") if v.get(s)}
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _counts(e: Entry, key: str) -> str:
        raw = e.raw
        if e.game in ("chu", "chuwe"):
            n = (raw.get("notes") if e.game == "chuwe" else raw.get(key)) or {}
            parts = [(k.upper(), n.get(k)) for k in ("tap", "hold", "slide", "air", "flick")]
            parts = [(k, v) for k, v in parts if v not in (None, "", "_")]
            total = sum(int(v) for _k, v in parts if str(v).isdigit())
            return " / ".join(f"{k} {v}" for k, v in parts) + (f"（合计 {total}）" if total else "") if parts else ""
        if e.game == "geki":
            parts = [(lab, (raw.get(k) or {}).get(key)) for k, lab in (("chain", "CHAIN"), ("bell", "BELL"))]
            return " / ".join(f"{k} {v}" for k, v in parts if v not in (None, "", "_"))
        if e.game == "sdvx":
            parts = [(k.upper(), (raw.get(k) or {}).get(key)) for k in ("chip", "hold", "laser")]
            parts = [(k, v) for k, v in parts if v not in (None, "", "_")]
            return " / ".join(f"{k} {v}" for k, v in parts)
        v = (raw.get("notes") or {}).get(key)
        return f"{v} notes" if v not in (None, "", "_") else ""

    @staticmethod
    def _designer(e: Entry, key: str) -> str:
        raw = e.raw
        if e.game in ("chu", "chuwe", "geki"):
            d = raw.get("designer")
            who = d if isinstance(d, str) else (d or {}).get(key)
            return f"谱师 {who}" if who else ""
        if e.game == "sdvx":
            ef = (raw.get("effect") or {}).get(key)
            il = (raw.get("illust") or {}).get(key)
            return " · ".join(x for x in ((f"Effected by {ef}" if ef else ""), (f"Illust {il}" if il else "")) if x)
        return ""

    async def _answer(self, e: Entry, key: str, note: str) -> Reply:
        r = Reply()
        if not e.exists(key):
            have = [lab for k, lab in DIFFS[e.game] if e.has_view(k)]
            return r.say(f"{e.title} 没有 {dict(DIFFS[e.game]).get(key, key)} 难度。" +
                         (f"sdvx.in 上有谱面图的：{'、'.join(have)}" if have else ""))
        lines = self._info(e, key)
        if note:
            lines.insert(0, f"（{note}）")
        if not e.has_view(key):
            have = [lab for k, lab in DIFFS[e.game] if e.has_view(k)]
            lines.insert(1 if not note else 2, "sdvx.in 没有这个难度的谱面图" + (f"（有：{'、'.join(have)}）" if have else ""))
            return r.say("\n".join(lines))
        try:
            img = await self.src.chart_image(e, key)
        except Exception as ex:  # noqa: BLE001
            log.warning(f"[otoge] sdvx.in chart {e.game} {e.id}{key} failed: {type(ex).__name__}: {ex}")
            img = None
        if img:
            r.image = img
        else:
            lines.append("（谱面图没取到，点上面的 sdvx.in 链接看）")
        return r.say("\n".join(lines))

    async def _alias_add(self, game: str, words: list[str]) -> Reply:
        if len(words) < 2:
            return Reply().say(f"用法：/{game} 加别名 <外号> <歌名>")
        alias, q = words[0], " ".join(words[1:])
        if len(alias) > 20:
            return Reply().say("外号太长了（最多 20 个字）")
        e, err, _ = await self._find(game, q)
        if err:
            return err
        self.src.add_alias(game, alias, e.id)
        return Reply().say(f"记住了：{alias} → {e.title}")
