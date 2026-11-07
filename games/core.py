"""Guess-the-song games: pure logic (no network, no AstrBot) so it can be tested offline.

Three games share one session object per chat:
  * letters  — 开字母: 10 masked titles, players open characters and shout titles
  * jacket   — 猜曲绘: the jacket pixelated to 4×4 colour blocks, sharper on every hint
  * chart    — 猜谱面: one measure of an sdvx.in chart, one more measure on every hint

Every game picks from a pool filtered by an optional constant range ("14以上", "14.7", "14-14.5", "14+").
"""
from __future__ import annotations

import difflib
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field

from PIL import Image

try:
    from ..core.kanji import fold_kanji, kata_to_hira
except ImportError:  # tests / top-level import
    from core.kanji import fold_kanji, kata_to_hira

# ---------------------------------------------------------------- questions

@dataclass
class Chart:
    diff: str                    # "MASTER" / "LUNATIC" / "MXM" …
    level: str                   # what the game prints: "14+", "13", "18"
    const: float | None          # internal constant if known (sdvx / pjsk: the level number)
    ref: object = None           # source-specific handle (sdvx.in Entry + key …)


@dataclass
class Song:
    game: str                    # mai / chu / geki / sdvx / pjsk
    sid: str
    title: str
    aliases: list[str] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    ref: object = None           # source-specific handle (for jackets)

    def answers(self) -> set[str]:
        keys = {norm(self.title), *(norm(a) for a in self.aliases), *(norm(p) for p in title_parts(self.title))}
        return {k for k in keys if k}


@dataclass
class Pick:
    song: Song
    chart: Chart | None = None


# ---------------------------------------------------------------- text helpers

_PUNCT = re.compile(r"[\s\-_~〜～・･.,，。'\"!！?？:：;；/／\\()（）\[\]【】「」『』<>《》〈〉&＆+＋*＊#＃@＠%％=＝|｜^`´’‘“”…·]+")


def norm(s: str) -> str:
    """Answer key: NFKC, case-folded, katakana → hiragana, Japanese / traditional kanji → simplified
    (「回归」=「回帰」), without spaces and punctuation."""
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return _PUNCT.sub("", fold_kanji(kata_to_hira(s)))


_SUB_SPLIT = re.compile(r"\s+[~〜～\-–—]|[~〜～]|\s*[(（\[【]|\s+-\s+")
_QUOTED = re.compile(r"^[『「【]([^』」】]{2,})[』」】]")


def title_parts(title: str) -> list[str]:
    """标题里能单独当答案的部分（2026-11-07 群里：『回帰』 ~Scherzo ~フォルトゥーナの悪戯~ 大家只猜「回归」）：
      · 开头书名号里的那段：『回帰』 → 回帰
      · 第一个副标题分隔（~ 〜 （ [ 【 或 空格-空格）前面那段：Garakuta Doll Play (Unlimited) → Garakuta Doll Play
    太短（规范化后不到 2 个字）的不要，免得「a」「1」这种也算猜中。"""
    t = unicodedata.normalize("NFKC", title or "").strip()
    out = []
    m = _QUOTED.match(t)
    if m:
        out.append(m.group(1))
    head = _SUB_SPLIT.split(t, maxsplit=1)[0].strip()
    if head and head != t:
        out.append(head)
    return [p for p in out if len(norm(p)) >= 2 and norm(p) != norm(t)]


def is_answer(guess: str, song: Song) -> bool:
    g = norm(guess)
    if not g:
        return False
    keys = song.answers()
    if g in keys:
        return True
    # a near miss on a long title still counts (typos, a missing symbol the regex keeps …)
    if len(g) >= 5:
        t = norm(song.title)
        if difflib.SequenceMatcher(None, g, t).ratio() >= 0.88:
            return True
    return False


# ---------------------------------------------------------------- constant range

@dataclass
class Range:
    lo: float = 0.0
    hi: float = 99.0
    label: str | None = None      # 只给没有定数的游戏用：按游戏里写的等级匹配
    text: str = ""
    level: tuple | None = None    # 「15」「15+」：(15, 是否带 +)，等知道是哪个游戏再换成定数区间（resolve）

    def resolve(self, game: str) -> "Range":
        """「15」「15+」按各游戏自己的分界换成定数区间（2026-11-07 群里：回帰 15.2 被「15+」抽到）：
          中二  15 = 15.0～15.4　15+ = 15.5～15.9
          舞萌  14 = 14.0～14.5　14+ = 14.6～14.9
          音击  14 = 14.0～14.6　14+ = 14.7～14.9
          SDVX / PJSK 没有定数：「18」= 18.x，「18+」按游戏里写的等级。"""
        if self.level is None:
            return self
        n, plus = self.level
        cut = PLUS_FROM.get(game)
        if cut is None:
            if plus:
                return Range(label=f"{n}+", text=self.text)
            return Range(n, n + 0.9, text=self.text)
        if plus:
            return Range(n + cut, n + 0.9, text=self.text)
        return Range(n, n + cut - 0.1, text=self.text)

    @property
    def any(self) -> bool:
        return self.label is None and self.lo <= 0 and self.hi >= 99

    def ok(self, c: Chart) -> bool:
        if self.label is not None:
            return c.level.replace("＋", "+") == self.label
        if c.const is None:
            return False
        return self.lo - 1e-9 <= c.const <= self.hi + 1e-9


# 「+」从小数点后几开始（等级 = 整数部分，+ = 小数 ≥ 这个值）
PLUS_FROM = {"chu": 0.5, "mai": 0.6, "geki": 0.7}

_NUM = r"(\d{1,2}(?:\.\d)?)"
_RANGE_PATTERNS = [
    (re.compile(rf"^{_NUM}\s*(?:以上|及以上|↑|起|\+以上)$"), lambda a: (float(a), 99.0)),
    (re.compile(rf"^(?:>=|≥|大于等于){_NUM}$"), lambda a: (float(a), 99.0)),
    (re.compile(rf"^{_NUM}\s*(?:以下|及以下|↓)$"), lambda a: (0.0, float(a) + (0.9 if "." not in a else 0))),
    (re.compile(rf"^(?:<=|≤|小于等于){_NUM}$"), lambda a: (0.0, float(a))),
]
_SPAN = re.compile(rf"^{_NUM}\s*(?:-|~|～|〜|到|至)\s*{_NUM}$")


def parse_range(tok: str) -> Range | None:
    t = unicodedata.normalize("NFKC", tok or "").strip().replace("＋", "+")
    if not t:
        return None
    for pat, f in _RANGE_PATTERNS:
        m = pat.match(t)
        if m:
            lo, hi = f(m.group(1))
            return Range(lo, hi, text=t)
    m = _SPAN.match(t)
    if m:
        a, b = sorted((float(m.group(1)), float(m.group(2))))
        if "." not in m.group(2) and b == float(m.group(2)):
            b += 0.9                       # 「13-14」 means up to 14.9
        return Range(a, b, text=t)
    m = re.match(r"^(\d{1,2})\+$", t)
    if m:
        n = int(m.group(1))
        return Range(n + 0.5, n + 0.9, text=t, level=(n, True))      # resolve(game) 换成该游戏的分界
    m = re.match(r"^(\d{1,2})\.(\d)$", t)
    if m:
        v = float(t)
        return Range(v, v, text=t)
    m = re.match(r"^(\d{1,2})$", t)
    if m:
        n = int(t)
        return Range(n, n + 0.4, text=t, level=(n, False))          # 「15」= 15 不含 15+；resolve(game) 定分界
    return None


# ---------------------------------------------------------------- picking

def pick(songs: list[Song], rng_: Range, n: int, *, rnd: random.Random | None = None,
         need=None, prefer=None) -> list[Pick]:
    """n distinct songs whose charts match the range. `need(song, chart)` filters further (e.g. sdvx.in has a
    chart picture); `prefer(charts)` picks among matching charts (default: the hardest)."""
    rnd = rnd or random
    pool = []
    for s in songs:
        ok = [c for c in s.charts if rng_.ok(c) and (need is None or need(s, c))] if not rng_.any else \
             [c for c in s.charts if need is None or need(s, c)]
        if ok:
            pool.append((s, ok))
    rnd.shuffle(pool)
    out, seen = [], set()
    for s, charts in pool:
        key = norm(s.title)
        if key in seen:
            continue
        seen.add(key)
        if prefer is not None:
            c = prefer(charts)
        elif rng_.any:
            c = max(charts, key=lambda c: (c.const or 0))
        else:
            c = rnd.choice(charts)
        out.append(Pick(s, c))
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- 开字母

def _maskable(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "N")


def char_key(ch: str) -> str:
    return unicodedata.normalize("NFKC", ch).casefold()


def mask(title: str, opened: set[str]) -> str:
    out = []
    for ch in title:
        if _maskable(ch) and char_key(ch) not in opened:
            out.append("＊" if ord(ch) > 0x2E80 else "*")
        else:
            out.append(ch)
    return "".join(out)


def fully_open(title: str, opened: set[str]) -> bool:
    return all(not _maskable(ch) or char_key(ch) in opened for ch in title)


# ---------------------------------------------------------------- 猜曲绘

JACKET_STEPS = (4, 6, 8, 12, 16, 24, 32)


def mosaic(img: Image.Image, blocks: int, size: int = 480) -> Image.Image:
    """Average the picture down to blocks×blocks colour cells, then blow it back up with hard edges."""
    im = img.convert("RGB")
    side = min(im.size)
    left, top = (im.width - side) // 2, (im.height - side) // 2
    im = im.crop((left, top, left + side, top + side))
    small = im.resize((blocks, blocks), Image.BOX)
    return small.resize((size, size), Image.NEAREST)


# ---------------------------------------------------------------- 猜谱面

def stack_measures(img: Image.Image, rects: list[tuple[int, int, int, int]], *, scale: float = 2.0,
                   max_h: int = 2400, min_w: int = 300, cols: int = 1, gap: int = 0,
                   min_ratio: float = 0.4, pad_color=(16, 16, 22)) -> Image.Image:
    """rects are in reading order (first = earliest measure). Default: one continuous strip,
    earlier measures at the bottom (stitched like the real chart, so notes that cross a measure
    line still connect). A tall strip is padded left/right up to width = min_ratio × height,
    otherwise QQ shrinks it to a sliver. cols > 1 lays columns side by side instead."""
    crops = [img.crop(r) for r in rects]
    n = len(crops)
    per_col = max(1, -(-n // max(1, cols)))
    columns = [crops[i:i + per_col] for i in range(0, n, per_col)]
    cw = max(c.width for c in crops)
    h = max(sum(c.height for c in col) for col in columns)
    w = len(columns) * cw + (len(columns) - 1) * gap
    out = Image.new("RGB", (w, h), (0, 0, 0))
    for i, col in enumerate(columns):
        x0 = i * (cw + gap)
        y = h
        for c in col:
            y -= c.height
            out.paste(c, (x0 + (cw - c.width) // 2, y))
    k = max(scale, min_w / max(1, out.width))
    k = min(k, max_h / max(1, out.height))
    if abs(k - 1) > 1e-3:
        out = out.resize((max(1, int(out.width * k)), max(1, int(out.height * k))), Image.NEAREST)
    want_w = int(out.height * min_ratio)
    if min_ratio and out.width < want_w:
        padded = Image.new("RGB", (want_w, out.height), pad_color)
        padded.paste(out, ((want_w - out.width) // 2, 0))
        out = padded
    return out


def choose_window(n_measures: int, max_show: int, rnd: random.Random | None = None) -> int:
    """Start index of the revealed run: away from the silent intro and the outro when possible."""
    rnd = rnd or random
    if n_measures <= max_show:
        return 0
    lo = min(n_measures - max_show, max(0, n_measures // 8))
    hi = max(lo, n_measures - max_show - max(0, n_measures // 10))
    return rnd.randint(lo, hi)


# ---------------------------------------------------------------- sessions

GAME_LABEL = {"mai": "舞萌", "chu": "中二", "geki": "音击", "sdvx": "SDVX", "pjsk": "PJSK"}
KIND_LABEL = {"letters": "开字母", "jacket": "猜曲绘", "chart": "猜谱面"}
IDLE_TIMEOUT = {"letters": 20 * 60, "jacket": 8 * 60, "chart": 8 * 60}


@dataclass
class Session:
    kind: str
    game: str
    picks: list[Pick]
    range_text: str = ""
    started: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)
    opened: set[str] = field(default_factory=set)          # letters
    solved: dict[int, str] = field(default_factory=dict)   # index → who (name), "" = opened out
    stage: int = 0                                         # jacket / chart
    data: dict = field(default_factory=dict)               # per-kind cached stuff (image, rects, start …)

    @property
    def expired(self) -> bool:
        return time.time() - self.touched > IDLE_TIMEOUT.get(self.kind, 600)

    @property
    def done(self) -> bool:
        return len(self.solved) >= len(self.picks)

    def touch(self) -> None:
        self.touched = time.time()

    def title_line(self, i: int) -> str:
        p = self.picks[i]
        return p.song.title

    def letters_board(self) -> str:
        lines = []
        for i, p in enumerate(self.picks):
            if i in self.solved:
                who = self.solved[i]
                tag = f"✓ {who}" if who else "✓ 开出来了"
                lines.append(f"{i + 1:>2}. {p.song.title}  （{tag}）")
            else:
                lines.append(f"{i + 1:>2}. {mask(p.song.title, self.opened)}")
        opened = "".join(sorted(self.opened)) or "无"
        return "\n".join(lines) + f"\n已开：{opened}"

    def scoreboard(self) -> str:
        counts: dict[str, int] = {}
        for who in self.solved.values():
            if who:
                counts[who] = counts.get(who, 0) + 1
        if not counts:
            return ""
        return "猜中：" + "、".join(f"{k} ×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))


def chart_answer(p: Pick) -> str:
    c = p.chart
    if c is None:
        return p.song.title
    const = f" {c.const:.1f}" if c.const is not None and p.song.game in ("mai", "chu", "geki") else ""
    return f"{p.song.title}  [{c.diff} {c.level}{const}]"
