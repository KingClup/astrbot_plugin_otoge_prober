"""Chat side of the guessing games: start commands, in-game messages, replies."""
from __future__ import annotations

import asyncio
import io
import logging
import random
import time
import re
import unicodedata

from PIL import Image

from . import core as G
from .core import Range, Session

try:
    from ..mai.bot.commands import Reply
except ImportError:  # tests import packages top-level
    from mai.bot.commands import Reply

log = logging.getLogger("astrbot")

START = {
    "猜歌": "letters", "开字母": "letters", "猜歌名": "letters", "开字母猜歌": "letters",
    "猜曲绘": "jacket", "猜封面": "jacket", "曲绘猜歌": "jacket",
    "猜谱面": "chart", "猜谱": "chart", "谱面猜歌": "chart", "猜铺面": "chart", "猜普面": "chart",
}
GAME_WORDS = {
    "mai": "mai", "舞萌": "mai", "maimai": "mai", "乌蒙": "mai", "舞萌dx": "mai",
    "chu": "chu", "中二": "chu", "chuni": "chu", "chunithm": "chu",
    "geki": "geki", "音击": "geki", "ongeki": "geki", "オンゲキ": "geki",
    "sdvx": "sdvx", "pjsk": "pjsk", "prsk": "pjsk", "烧烤": "pjsk", "啤酒烧烤": "pjsk",
}
REGION_WORDS = {"国服": "cn", "日服": "jp", "国际服": "intl"}
SUPPORTED = {"letters": ("mai", "chu", "geki", "sdvx", "pjsk"), "jacket": ("mai", "chu", "geki", "sdvx", "pjsk"),
             "chart": ("chu", "geki", "sdvx", "pjsk")}
HINT_DEBOUNCE = 3          # 秒：这么短时间里重复的「提示」只算一次
END_WORDS = {"结束", "不猜了", "公布", "公布答案", "答案", "揭晓", "不玩了", "结束猜歌", "end", "stop"}
HINT_WORDS = {"提示", "加", "再来", "再加", "加一节", "再加一节", "下一节", "更清楚", "清楚点", "再清楚点", "hint",
              "放大", "多一点", "再多一点"}
LETTER_HINT = re.compile(r"^(?:(\d{1,2})\s*[.．、。:：号]?\s*(?:提示|hint)|(?:提示|hint)\s*(\d{1,2})\s*号?)$", re.I)
STATUS_WORDS = {"状态", "题目", "看题", "进度"}
LETTERS_N = 10
CHART_MAX = 8                   # measures shown at most (stage 0 = 1 measure … stage 7 = 8)
CHART_BUDGET = 50               # 秒：猜谱面开局取图最多等这么久（几首候选一共），超了就说没拿到，不让群里干等
EXPIRED_GRACE = 30 * 60         # 秒：一局放太久自动结束后，这段时间里有人再猜 / 发「结束」，告诉他答案

HELP = """猜歌小游戏（群里、私聊都能玩；一个群同时只开一局）
/猜歌 [游戏] [定数]   开字母：出 10 首歌名，全部打码
  · 发「开 a」「开 の」「开 天」开一个字（所有歌名里的这个字都会亮出来），「开 abc」一次开好几个
  · 发「6 提示」（或「6. 提示」「提示 6」）只提示第 6 首：第一次给版本 + 开一个字，之后每次再开一个字
  · 直接发歌名（或常用外号）就算猜，猜中的那首会写上你的名字
/猜曲绘 [游戏] [定数]  曲绘先糊成 4×4 的色块，发「提示」一次比一次清楚，直接发歌名猜
/猜谱面 [游戏] [区服] [版本] [定数]  从 sdvx.in 的谱面里截一个小节，发「提示」多放一个小节（最多 8 个）
发「结束」公布答案。
游戏：舞萌 / 中二 / 音击 / sdvx / pjsk（猜谱面没有舞萌：sdvx.in 上没有舞萌谱面）
版本：舞萌 / 中二可以写区服（国服 / 国际服 / 日服，不写 = 日服全曲）和哪一代（「xversex」「amazon+」「宙」「祭」），答案会写上是哪一代
定数：不写 = 随机；「14以上」「13.5以下」「14.7」「14-14.5」；「15」「15+」按游戏里的等级：
　　　中二 15 = 15.0～15.4、15+ = 15.5～15.9；舞萌 14 = 14.0～14.5、14+ = 14.6～14.9；音击 14 = 14.0～14.6、14+ = 14.7～14.9
　　　sdvx / pjsk 没有定数，按等级算：「/猜曲绘 sdvx 18以上」「/猜歌 pjsk 30以上」
例：/猜歌 舞萌 14以上　/猜曲绘 中二 14.7　/猜谱面 音击 13-14　/猜歌 中二 国际服 xversex"""


def _png(img: Image.Image, fmt: str = "PNG", quality: int = 88) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    else:
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _clean(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").strip()
    return t.lstrip("/").strip()


class GameCommands:
    def __init__(self, data, *, last_game=None, rnd: random.Random | None = None, help=None):
        self.data = data                              # games.sources.GameData
        self.last_game = last_game or (lambda uid: None)
        self.help = help                              # async () -> Reply：图片版帮助；没有就发文字
        self.rnd = rnd or random.Random()
        self.sessions: dict[str, Session] = {}
        self.starting: dict[str, float] = {}          # origin → 开局开始的时间（取图期间别再开一局把它顶掉）
        self.expired: dict[str, tuple[Session, float]] = {}   # origin → (放太久自动结束的那局, 结束时间)
        self.on_message_log = None    # (origin, ctx, text) → None：局里的每条消息（别名收集用）
        self.on_title_solve = None    # (origin, session, index, ctx, guess) → None：有人用原名猜中
        self.on_alias_solve = None    # 同上：有人用已有外号猜中（外号少的歌也问一句「还有别的叫法吗」）

    # ---------------------------------------------------------------- entry points
    def is_start(self, text: str) -> str | None:
        t = _clean(text)
        head = t.split(" ", 1)[0].lower()
        return START.get(head)

    def active(self, origin: str) -> Session | None:
        s = self.sessions.get(origin)
        if s is not None and s.expired:
            self.sessions.pop(origin, None)
            self.expired[origin] = (s, time.time())
            log.info(f"[otoge] game expired (idle): {origin.rsplit(':', 1)[-1]} {s.kind} {s.game}")
            return None
        return s

    def _after_expired(self, origin: str, t: str, command: bool) -> Reply | None:
        """一局因为太久没人动自动结束了：之后有人发「结束 / 提示 / 状态」、「猜 xxx」或者正好猜对，别装没听见。"""
        got = self.expired.get(origin)
        if got is None:
            return None
        s, when = got
        if time.time() - when > EXPIRED_GRACE:
            self.expired.pop(origin, None)
            return None
        low = t.lower()
        m = re.match(r"^猜\s*(.+)$", t)
        asked = low in END_WORDS or low in HINT_WORDS or low in STATUS_WORDS or bool(m) or bool(LETTER_HINT.match(t))
        guess = m.group(1).strip() if m else t
        hit = s.kind != "letters" and 0 < len(guess) <= 80 and G.is_answer(guess, s.picks[0].song)
        if not (asked or hit):
            return None
        self.expired.pop(origin, None)
        mins = max(1, int(G.IDLE_TIMEOUT.get(s.kind, 600) // 60))
        head = (f"✓ 猜对了！不过这局{G.KIND_LABEL[s.kind]}之前 {mins} 分钟没动静，已经自动结束了" if hit
                else f"这局{G.KIND_LABEL[s.kind]}之前 {mins} 分钟没动静，已经自动结束了")
        r = self.finish(origin, s, prefix=head)
        r.say("想再来一局发「/" + {"letters": "猜歌", "jacket": "猜曲绘", "chart": "猜谱面"}[s.kind] + "」")
        return r

    async def handle(self, origin: str, ctx, text: str, *, command: bool) -> Reply | None:
        """command = the message is addressed to us (slash / @ / private chat). Returns None when the
        message is not ours (normal chat during a game, a wrong guess without 「猜」…)."""
        t = _clean(text)
        kind = self.is_start(t) if command else None
        if kind is not None:
            rest = t.split(" ", 1)[1] if " " in t else ""
            return await self.start(origin, ctx, kind, rest)
        s = self.active(origin)
        if s is None:
            if origin in self.starting and (t.lower() in END_WORDS or t.lower() in HINT_WORDS):
                return Reply().say("正在开局（在拿图），稍等一下")
            return self._after_expired(origin, t, command)
        return await self.on_message(origin, s, ctx, t)

    # ---------------------------------------------------------------- start
    def _parse(self, kind: str, words: list[str], uid: str):
        game, region, rng, unknown = None, "jp", Range(), []
        i = 0
        while i < len(words):
            w = words[i]
            lw = w.lower()
            if lw in GAME_WORDS and game is None:
                game = GAME_WORDS[lw]
            elif w in REGION_WORDS:
                region = REGION_WORDS[w]
            else:
                r = G.parse_range(w)
                if r is None and i + 1 < len(words):          # 「14 以上」 written apart
                    r = G.parse_range(w + words[i + 1])
                    if r is not None:
                        i += 1
                if r is not None:
                    rng = r
                else:
                    unknown.append(w)
            i += 1
        if game is None:
            last = self.last_game(uid)
            game = last if last in SUPPORTED[kind] else SUPPORTED[kind][0]
        return game, region, rng.resolve(game), unknown

    async def start(self, origin: str, ctx, kind: str, rest: str) -> Reply:
        words = [w for w in re.split(r"\s+", rest.strip()) if w]
        if words and words[0] in ("帮助", "help", "说明", "怎么玩"):
            return await self.help() if self.help else Reply().say(HELP)
        if words and words[0] in END_WORDS:
            s = self.active(origin)
            return self.finish(origin, s) if s else Reply().say("现在没有在猜的歌")
        cur = self.active(origin)
        if cur is not None:
            return Reply().say(f"这里还有一局{G.KIND_LABEL[cur.kind]}没结束（{G.GAME_LABEL[cur.game]}）。"
                               "接着猜，或者发「结束」公布答案")
        if time.time() - self.starting.get(origin, 0) < CHART_BUDGET + 30:
            return Reply().say("刚才那局正在开（在拿图），稍等一下，别再开一局")
        game, region, rng, unknown = self._parse(kind, words, ctx.uid)
        ver = ""
        if unknown:
            vers = self.data.versions(game) if hasattr(self.data, "versions") else []
            ver = G.match_version(" ".join(unknown), vers) or ""
            if not ver and len(unknown) > 1:                    # 「中二 AMAZON PLUS 14以上」之外还夹了别的词
                ver = next((v for w in unknown if (v := G.match_version(w, vers))), "")
                unknown = [w for w in unknown if not G.match_version(w, vers)] if ver else unknown
            else:
                unknown = [] if ver else unknown
            if unknown:
                more = ("；版本可以写：" + "、".join(v for v, _ in vers[-8:]) + " …") if vers else ""
                return Reply().say(f"没看懂「{' '.join(unknown)}」{more}\n{HELP}")
        if game not in SUPPORTED[kind]:
            if kind == "chart" and game == "mai":
                return Reply().say("sdvx.in 没有舞萌的谱面，猜谱面可以选：中二 / 音击 / sdvx / pjsk")
            names = " / ".join(G.GAME_LABEL[g] for g in SUPPORTED[kind])
            return Reply().say(f"{G.KIND_LABEL[kind]}现在支持：{names}")
        self.expired.pop(origin, None)
        self.starting[origin] = time.time()
        try:
            if kind == "letters":
                if game in ("sdvx", "pjsk"):
                    await self.data.ensure_charts(game)
                return self._start_letters(origin, game, region, rng, ver)
            if kind == "jacket":
                if game in ("sdvx", "pjsk"):
                    await self.data.ensure_charts(game)
                return await self._start_jacket(origin, game, region, rng, ver)
            return await self._start_chart(origin, game, rng, ver, region)
        except Exception as e:  # noqa: BLE001
            log.warning(f"[otoge] game start failed: {type(e).__name__}: {e}", exc_info=True)
            self.sessions.pop(origin, None)
            return Reply().say("开局失败了（曲库或图片没拿到），等会儿再试试")
        finally:
            self.starting.pop(origin, None)

    def _range_note(self, rng: Range, game: str = "", ver: str = "", region: str = "jp") -> str:
        bits = []
        if region != "jp" and game in ("mai", "chu"):
            bits.append({"cn": "国服", "intl": "国际服"}.get(region, region))
        if ver:
            bits.append(ver)
        bits.append("随机" if rng.any else f"{'等级' if game in ('sdvx', 'pjsk') else '定数'} {rng.text}")
        return " · ".join(bits)

    @staticmethod
    def _by_ver(songs, ver: str):
        return [s for s in songs if s.version == ver] if ver else songs

    def _start_letters(self, origin: str, game: str, region: str, rng: Range, ver: str = "") -> Reply:
        songs = [s for s in self._by_ver(self.data.songs(game, region), ver) if any(G._maskable(c) for c in s.title)]
        picks = G.pick(songs, rng, LETTERS_N, rnd=self.rnd)
        if not picks:
            return Reply().say(f"{G.GAME_LABEL[game]}里没有符合「{self._range_note(rng, game, ver, region)}」的歌")
        s = Session("letters", game, picks, range_text=self._range_note(rng, game, ver, region))
        self.sessions[origin] = s
        head = f"开字母 · {G.GAME_LABEL[game]} · {s.range_text} · {len(picks)} 首"
        tail = "发「开 a」开字，直接发歌名猜，发「结束」公布答案"
        return Reply().say(f"{head}\n{s.letters_board()}\n{tail}")

    async def _start_jacket(self, origin: str, game: str, region: str, rng: Range, ver: str = "") -> Reply:
        songs = self._by_ver(self.data.songs(game, region), ver)
        cands = G.pick(songs, rng, 6, rnd=self.rnd)
        if not cands:
            return Reply().say(f"{G.GAME_LABEL[game]}里没有符合「{self._range_note(rng, game, ver, region)}」的歌")
        for p in cands:
            try:
                img = await asyncio.wait_for(self.data.jacket(p.song), 25)
            except Exception:  # noqa: BLE001
                img = None
            if img is None:
                continue
            s = Session("jacket", game, [p], range_text=self._range_note(rng, game, ver, region), data={"img": img})
            self.sessions[origin] = s
            pic = G.mosaic(img, G.JACKET_STEPS[0])
            return Reply(image=_png(pic)).say(
                f"猜曲绘 · {G.GAME_LABEL[game]} · {s.range_text}\n直接发歌名猜；发「提示」变清楚一点"
                f"（还能提示 {len(G.JACKET_STEPS) - 1} 次），发「结束」公布答案")
        return Reply().say("这几首的曲绘都没拿到，等会儿再试试")

    async def _start_chart(self, origin: str, game: str, rng: Range, ver: str = "", region: str = "jp") -> Reply:
        await self.data.ensure_charts(game)
        region = region if game == "chu" else "jp"
        songs = self._by_ver(self.data.chart_songs(game, region) if region != "jp" else self.data.chart_songs(game), ver)
        cands = G.pick(songs, rng, 4, rnd=self.rnd)
        if not cands:
            return Reply().say(f"sdvx.in 上 {G.GAME_LABEL[game]} 没有符合「{self._range_note(rng, game, ver, region)}」的谱面")
        deadline = time.monotonic() + CHART_BUDGET
        for p in cands:
            left = deadline - time.monotonic()
            if left < 3:
                log.info(f"[otoge] chart picture: gave up after {CHART_BUDGET}s ({game})")
                break
            try:
                got = await asyncio.wait_for(self.data.chart_picture(p.chart), left)
            except Exception as e:  # noqa: BLE001
                log.info(f"[otoge] chart picture failed: {type(e).__name__}: {e}")
                got = None
            if not got or len(got[1]) < 2:
                e, key = p.chart.ref if isinstance(getattr(p.chart, "ref", None), tuple) else (None, "")
                log.info(f"[otoge] chart picture missing: {game} {getattr(e, 'id', '?')} {key} "
                         f"{getattr(getattr(self.data, '_sx', None), 'last_error', '')}")
                continue
            img, rects = got
            start = G.choose_window(len(rects), CHART_MAX, self.rnd)
            s = Session("chart", game, [p], range_text=self._range_note(rng, game, ver, region),
                        data={"img": img, "rects": rects, "start": start})
            self.sessions[origin] = s
            return Reply(image=self._chart_pic(s)).say(
                f"猜谱面 · {G.GAME_LABEL[game]} · {s.range_text}\n这是其中 1 个小节。直接发歌名猜；"
                f"发「提示」再放一个小节（最多 {CHART_MAX} 个），发「结束」公布答案")
        return Reply().say("sdvx.in 的谱面图这次没拿到，等会儿再试试")

    # ---------------------------------------------------------------- pictures
    def _chart_pic(self, s: Session) -> bytes:
        rects = s.data["rects"][s.data["start"]: s.data["start"] + s.stage + 1]
        return _png(G.stack_measures(s.data["img"], rects), "JPEG")

    def _jacket_pic(self, s: Session, full: bool = False) -> bytes:
        img = s.data["img"]
        if full:
            im = img.convert("RGB")
            side = min(im.size)
            im = im.crop(((im.width - side) // 2, (im.height - side) // 2,
                          (im.width + side) // 2, (im.height + side) // 2)).resize((480, 480), Image.LANCZOS)
            return _png(im, "JPEG")
        return _png(G.mosaic(img, G.JACKET_STEPS[min(s.stage, len(G.JACKET_STEPS) - 1)]))

    # ---------------------------------------------------------------- in game
    async def on_message(self, origin: str, s: Session, ctx, t: str) -> Reply | None:
        low = t.lower()
        who = (getattr(ctx, "name", "") or "").strip() or str(getattr(ctx, "uid", "") or "有人")
        if self.on_message_log is not None:
            try:
                self.on_message_log(origin, ctx, t)
            except Exception:  # noqa: BLE001
                pass
        if low in END_WORDS or low in {"猜歌 结束", "猜歌结束"}:
            return self.finish(origin, s)
        if low in STATUS_WORDS:
            s.touch()
            return self._status(s)
        if s.kind == "letters":
            m = re.match(r"^开\s*(.+)$", t)
            if m and len(m.group(1).replace(" ", "")) <= 6:
                return self._open(origin, s, m.group(1))
            m = LETTER_HINT.match(t.strip())
            if m:
                return self._letter_hint(origin, s, int(m.group(1) or m.group(2)))
            if low in ("提示", "hint"):
                return Reply().say("开字母要说提示第几首：发「6 提示」（或「6. 提示」「提示 6」），"
                                   "第一次给版本 + 开一个字，之后每次再开一个字")
        elif low in HINT_WORDS:
            return self._hint(s)
        explicit = False
        m = re.match(r"^猜\s*(.+)$", t)
        if m:
            t, explicit = m.group(1).strip(), True
        return self._guess(origin, s, who, t, explicit, ctx)

    def _status(self, s: Session) -> Reply:
        if s.kind == "letters":
            return Reply().say(s.letters_board())
        if s.kind == "jacket":
            return Reply(image=self._jacket_pic(s)).say("还在猜这张")
        return Reply(image=self._chart_pic(s)).say("还在猜这张谱")

    def _open(self, origin: str, s: Session, chars: str) -> Reply:
        s.touch()
        new = [G.char_key(c) for c in chars if not c.isspace()]
        fresh = [c for c in dict.fromkeys(new) if c not in s.opened]
        if not fresh:
            return Reply().say(f"「{chars.strip()}」已经开过了")
        s.opened.update(fresh)
        hit = 0
        for i, p in enumerate(s.picks):
            if i not in s.solved and G.fully_open(p.song.title, s.opened, s.shown(i)):
                s.solved[i] = ""
            if any(G.char_key(ch) in fresh for ch in p.song.title):
                hit += 1
        note = f"开「{''.join(fresh)}」：{hit} 首里有" if hit else f"开「{''.join(fresh)}」：都没有"
        if s.done:
            return self.finish(origin, s, prefix=note)
        return Reply().say(f"{note}\n{s.letters_board()}")

    def _letter_hint(self, origin: str, s: Session, n: int) -> Reply:
        """开字母「6 提示」：第一次给版本 + 只在这首里开一个字，之后每次再开一个字（最后一个字不给）。"""
        i = n - 1
        if not 0 <= i < len(s.picks):
            return Reply().say(f"这局只有 {len(s.picks)} 首，发「1 提示」到「{len(s.picks)} 提示」")
        if i in s.solved:
            return Reply().say(f"第 {n} 首已经出来了")
        now = time.time()
        last = s.data.setdefault("last_hint_i", {})
        if now - last.get(i, 0) < HINT_DEBOUNCE:                  # 几个人同时喊「6 提示」：只算一次
            return Reply()
        last[i] = now
        s.touch()
        song = s.picks[i].song
        first = i not in s.hinted
        shown = s.hinted.setdefault(i, set())
        hidden = G.hidden_positions(song.title, s.opened, shown)
        bits = []
        if first and song.version:
            bits.append(f"版本：{song.version}")
        if len(hidden) <= 1:
            bits.append("只剩最后一个字了，自己猜吧" if hidden else "字都开完了")
        else:
            pos = self.rnd.choice(hidden)
            shown.add(pos)
            bits.append(f"开了一个「{song.title[pos]}」")
        line = f"{n:>2}. {G.mask(song.title, s.opened, shown)}" + (f"  （{song.version}）" if song.version else "")
        return Reply().say(f"第 {n} 首提示：" + "，".join(bits) + f"\n{line}")

    def _hint(self, s: Session) -> Reply:
        now = time.time()
        if now - s.data.get("last_hint", 0) < HINT_DEBOUNCE:      # 几个人同时喊「提示」：只算一次，别的不回
            return Reply()                                         # 空回复：吞掉这条，也不交给聊天模型
        s.data["last_hint"] = now
        s.touch()
        if s.kind == "jacket":
            if s.stage + 1 >= len(G.JACKET_STEPS):
                return Reply().say("已经最清楚了（再清楚就是原图了），发「结束」看答案")
            s.stage += 1
            left = len(G.JACKET_STEPS) - 1 - s.stage
            return Reply(image=self._jacket_pic(s)).say(
                f"{G.JACKET_STEPS[s.stage]}×{G.JACKET_STEPS[s.stage]}" + (f"（还能提示 {left} 次）" if left else "（最后一次提示）"))
        total = len(s.data["rects"]) - s.data["start"]
        if s.stage + 1 >= min(CHART_MAX, total):
            return Reply().say("已经放到最多了，发「结束」看答案")
        s.stage += 1
        return Reply(image=self._chart_pic(s)).say(f"{s.stage + 1} 个小节")

    def _guess(self, origin: str, s: Session, who: str, t: str, explicit: bool, ctx=None) -> Reply | None:
        if not t or len(t) > 80:
            return None
        hits = [i for i, p in enumerate(s.picks) if i not in s.solved and G.is_answer(t, p.song)]
        if not hits:
            if explicit or len(t) <= 30:
                s.touch()                        # 有人在猜（猜错也算）：别让这局因为「没人动」过期
            return Reply().say("不对哦") if explicit else None
        s.touch()
        for i in hits:
            s.solved[i] = who
            hook = self.on_title_solve if G.by_title(t, s.picks[i].song) else self.on_alias_solve
            if hook is not None:
                try:
                    hook(origin, s, i, ctx, t)
                except Exception:  # noqa: BLE001
                    pass
        if s.kind == "letters":
            got = "、".join(f"{i + 1}. {s.picks[i].song.title}" for i in hits)
            if s.done:
                return self.finish(origin, s, prefix=f"✓ {who} 猜中 {got}")
            return Reply().say(f"✓ {who} 猜中 {got}\n{s.letters_board()}")
        return self.finish(origin, s, prefix=f"✓ {who} 猜中了！")

    def finish(self, origin: str, s: Session | None, prefix: str = "") -> Reply:
        self.sessions.pop(origin, None)
        if s is None:
            return Reply().say("现在没有在猜的歌")
        lines = [prefix] if prefix else []
        if s.kind == "letters":
            lines.append("答案：" if not prefix else "全部答案：")
            for i, p in enumerate(s.picks):
                who = s.solved.get(i)
                mark = f"（{who}）" if who else "（开出来了）" if who == "" else ""
                lines.append(f"{i + 1:>2}. {p.song.title}{G.ver_tag(p.song)}{mark}")
            sb = s.scoreboard()
            if sb:
                lines.append(sb)
            return Reply().say("\n".join(lines))
        p = s.picks[0]
        lines.append(f"答案：{G.chart_answer(p)}" if s.kind == "chart" else f"答案：{p.song.title}{G.ver_tag(p.song)}")
        if s.kind == "jacket":
            return Reply(image=self._jacket_pic(s, full=True)).say("\n".join(lines))
        return Reply().say("\n".join(lines))
