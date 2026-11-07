"""Chat side of the guessing games: start commands, in-game messages, replies."""
from __future__ import annotations

import asyncio
import io
import logging
import random
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
    "猜谱面": "chart", "猜谱": "chart", "谱面猜歌": "chart",
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
END_WORDS = {"结束", "不猜了", "公布", "公布答案", "答案", "揭晓", "不玩了", "结束猜歌", "end", "stop"}
HINT_WORDS = {"提示", "加", "再来", "再加", "加一节", "再加一节", "下一节", "更清楚", "清楚点", "再清楚点", "hint",
              "放大", "多一点", "再多一点"}
STATUS_WORDS = {"状态", "题目", "看题", "进度"}
LETTERS_N = 10
CHART_MAX = 8                   # measures shown at most (stage 0 = 1 measure … stage 7 = 8)

HELP = """猜歌小游戏（群里、私聊都能玩；一个群同时只开一局）
/猜歌 [游戏] [定数]   开字母：出 10 首歌名，全部打码
  · 发「开 a」「开 の」「开 天」开一个字（所有歌名里的这个字都会亮出来），「开 abc」一次开好几个
  · 直接发歌名（或常用外号）就算猜，猜中的那首会写上你的名字
/猜曲绘 [游戏] [定数]  曲绘先糊成 4×4 的色块，发「提示」一次比一次清楚，直接发歌名猜
/猜谱面 [游戏] [定数]  从 sdvx.in 的谱面里截一个小节，发「提示」多放一个小节（最多 8 个）
发「结束」公布答案。
游戏：舞萌 / 中二 / 音击 / sdvx / pjsk（猜谱面没有舞萌：sdvx.in 上没有舞萌谱面）
定数：不写 = 随机；「14以上」「13.5以下」「14.7」「14-14.5」；「15」「15+」按游戏里的等级：
　　　中二 15 = 15.0～15.4、15+ = 15.5～15.9；舞萌 14 = 14.0～14.5、14+ = 14.6～14.9；音击 14 = 14.0～14.6、14+ = 14.7～14.9
　　　sdvx / pjsk 没有定数，按等级算：「/猜曲绘 sdvx 18以上」「/猜歌 pjsk 30以上」
例：/猜歌 舞萌 14以上　/猜曲绘 中二 14.7　/猜谱面 音击 13-14"""


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

    # ---------------------------------------------------------------- entry points
    def is_start(self, text: str) -> str | None:
        t = _clean(text)
        head = t.split(" ", 1)[0].lower()
        return START.get(head)

    def active(self, origin: str) -> Session | None:
        s = self.sessions.get(origin)
        if s is not None and s.expired:
            self.sessions.pop(origin, None)
            return None
        return s

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
            return None
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
        game, region, rng, unknown = self._parse(kind, words, ctx.uid)
        if unknown:
            return Reply().say(f"没看懂「{' '.join(unknown)}」。\n{HELP}")
        if game not in SUPPORTED[kind]:
            if kind == "chart" and game == "mai":
                return Reply().say("sdvx.in 没有舞萌的谱面，猜谱面可以选：中二 / 音击 / sdvx / pjsk")
            names = " / ".join(G.GAME_LABEL[g] for g in SUPPORTED[kind])
            return Reply().say(f"{G.KIND_LABEL[kind]}现在支持：{names}")
        try:
            if kind == "letters":
                if game in ("sdvx", "pjsk"):
                    await self.data.ensure_charts(game)
                return self._start_letters(origin, game, region, rng)
            if kind == "jacket":
                if game in ("sdvx", "pjsk"):
                    await self.data.ensure_charts(game)
                return await self._start_jacket(origin, game, region, rng)
            return await self._start_chart(origin, game, rng)
        except Exception as e:  # noqa: BLE001
            log.warning(f"[otoge] game start failed: {type(e).__name__}: {e}", exc_info=True)
            self.sessions.pop(origin, None)
            return Reply().say("开局失败了（曲库或图片没拿到），等会儿再试试")

    def _range_note(self, rng: Range, game: str = "") -> str:
        if rng.any:
            return "随机"
        return f"{'等级' if game in ('sdvx', 'pjsk') else '定数'} {rng.text}"

    def _start_letters(self, origin: str, game: str, region: str, rng: Range) -> Reply:
        songs = [s for s in self.data.songs(game, region) if any(G._maskable(c) for c in s.title)]
        picks = G.pick(songs, rng, LETTERS_N, rnd=self.rnd)
        if not picks:
            return Reply().say(f"{G.GAME_LABEL[game]}里没有符合「{rng.text}」的歌")
        s = Session("letters", game, picks, range_text=self._range_note(rng, game))
        self.sessions[origin] = s
        head = f"开字母 · {G.GAME_LABEL[game]} · {s.range_text} · {len(picks)} 首"
        tail = "发「开 a」开字，直接发歌名猜，发「结束」公布答案"
        return Reply().say(f"{head}\n{s.letters_board()}\n{tail}")

    async def _start_jacket(self, origin: str, game: str, region: str, rng: Range) -> Reply:
        songs = self.data.songs(game, region)
        cands = G.pick(songs, rng, 6, rnd=self.rnd)
        if not cands:
            return Reply().say(f"{G.GAME_LABEL[game]}里没有符合「{rng.text}」的歌")
        for p in cands:
            try:
                img = await asyncio.wait_for(self.data.jacket(p.song), 25)
            except Exception:  # noqa: BLE001
                img = None
            if img is None:
                continue
            s = Session("jacket", game, [p], range_text=self._range_note(rng, game), data={"img": img})
            self.sessions[origin] = s
            pic = G.mosaic(img, G.JACKET_STEPS[0])
            return Reply(image=_png(pic)).say(
                f"猜曲绘 · {G.GAME_LABEL[game]} · {s.range_text}\n直接发歌名猜；发「提示」变清楚一点"
                f"（还能提示 {len(G.JACKET_STEPS) - 1} 次），发「结束」公布答案")
        return Reply().say("这几首的曲绘都没拿到，等会儿再试试")

    async def _start_chart(self, origin: str, game: str, rng: Range) -> Reply:
        await self.data.ensure_charts(game)
        songs = self.data.chart_songs(game)
        cands = G.pick(songs, rng, 4, rnd=self.rnd)
        if not cands:
            return Reply().say(f"sdvx.in 上 {G.GAME_LABEL[game]} 没有符合「{rng.text}」的谱面")
        for p in cands:
            try:
                got = await asyncio.wait_for(self.data.chart_picture(p.chart), 60)
            except Exception as e:  # noqa: BLE001
                log.info(f"[otoge] chart picture failed: {type(e).__name__}: {e}")
                got = None
            if not got or len(got[1]) < 2:
                continue
            img, rects = got
            start = G.choose_window(len(rects), CHART_MAX, self.rnd)
            s = Session("chart", game, [p], range_text=self._range_note(rng, game),
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
        if low in END_WORDS or low in {"猜歌 结束", "猜歌结束"}:
            return self.finish(origin, s)
        if low in STATUS_WORDS:
            s.touch()
            return self._status(s)
        if s.kind == "letters":
            m = re.match(r"^开\s*(.+)$", t)
            if m and len(m.group(1).replace(" ", "")) <= 6:
                return self._open(origin, s, m.group(1))
        elif low in HINT_WORDS:
            return self._hint(s)
        explicit = False
        m = re.match(r"^猜\s*(.+)$", t)
        if m:
            t, explicit = m.group(1).strip(), True
        return self._guess(origin, s, who, t, explicit)

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
            if i not in s.solved and G.fully_open(p.song.title, s.opened):
                s.solved[i] = ""
            if any(G.char_key(ch) in fresh for ch in p.song.title):
                hit += 1
        note = f"开「{''.join(fresh)}」：{hit} 首里有" if hit else f"开「{''.join(fresh)}」：都没有"
        if s.done:
            return self.finish(origin, s, prefix=note)
        return Reply().say(f"{note}\n{s.letters_board()}")

    def _hint(self, s: Session) -> Reply:
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

    def _guess(self, origin: str, s: Session, who: str, t: str, explicit: bool) -> Reply | None:
        if not t or len(t) > 80:
            return None
        hits = [i for i, p in enumerate(s.picks) if i not in s.solved and G.is_answer(t, p.song)]
        if not hits:
            return Reply().say("不对哦") if explicit else None
        s.touch()
        for i in hits:
            s.solved[i] = who
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
                lines.append(f"{i + 1:>2}. {p.song.title}{mark}")
            sb = s.scoreboard()
            if sb:
                lines.append(sb)
            return Reply().say("\n".join(lines))
        p = s.picks[0]
        lines.append(f"答案：{G.chart_answer(p)}" if s.kind == "chart" else f"答案：{p.song.title}")
        if s.kind == "jacket":
            return Reply(image=self._jacket_pic(s, full=True)).say("\n".join(lines))
        return Reply().say("\n".join(lines))
