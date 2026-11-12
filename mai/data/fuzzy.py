"""Ranked fuzzy song search shared by maimai and CHUNITHM.

Every song contributes its title and all its aliases (community nicknames) as search keys. A query is
normalised the same way (NFKC, lower case, katakana → hiragana, no spaces / punctuation / decorative
symbols) and scored against every key:

  100  exact title            95  exact alias
   85  title starts with q    80  alias starts with q
   70  q inside title         65  q inside alias        (longer keys score a little lower)
   40–68  typo-tolerant similarity (difflib, whole key or best window), only for queries of 3+ chars

A song keeps its best score. ``decide`` turns a ranked list into one answer, an "which one?" list, or
nothing, so every command answers ambiguous names the same way.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Generic, Hashable, Iterable, TypeVar

try:
    from ...core.kanji import fold_kanji
except ImportError:  # tests / top-level import
    from core.kanji import fold_kanji

T = TypeVar("T")

_PUNCT = re.compile(r"[\s\-_~〜～・･.,，。、'\"`!！?？:：;；/／\\()（）\[\]【】「」『』<>《》〈〉♪♫☆★○●◇◆□■△▽♡♥❤†‡※#＃*＊+＋=＝|｜…‥·•]+")


def fold(s: str) -> str:
    """Search key: width/case/kana-insensitive, punctuation and decoration removed."""
    raw = unicodedata.normalize("NFKC", s or "").lower().strip()
    s = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in raw)   # katakana → hiragana
    s = fold_kanji(s)                         # 日文新字体 / 繁体 → 简体：「回归」能搜到「回帰」
    s = s.replace("&", "and")
    s = _PUNCT.sub("", s)
    return s or re.sub(r"\s+", "", raw)      # titles made only of symbols keep their symbols


@dataclass
class Match(Generic[T]):
    score: float
    item: T
    name: str          # the title / alias that matched
    by_alias: bool


class FuzzyIndex(Generic[T]):
    def __init__(self) -> None:
        self._keys: list[tuple[str, Hashable, str, bool]] = []   # (key, item id, display name, is_alias)
        self._items: dict[Hashable, T] = {}
        self._exact: dict[str, set[Hashable]] = {}

    def add(self, item_id: Hashable, item: T, title: str, aliases: Iterable[str] = ()) -> None:
        self._items[item_id] = item
        seen = set()
        for name, is_alias in [(title, False), *((a, True) for a in aliases)]:
            k = fold(name)
            if not k or (k, is_alias) in seen:
                continue
            seen.add((k, is_alias))
            self._keys.append((k, item_id, name, is_alias))
            self._exact.setdefault(k, set()).add(item_id)

    def __len__(self) -> int:
        return len(self._items)

    def search(self, query: str, limit: int = 10) -> list[Match[T]]:
        q = fold(query)
        if not q:
            return []
        best: dict[Hashable, Match[T]] = {}

        def offer(item_id, score, name, is_alias):
            m = best.get(item_id)
            if m is None or score > m.score:
                best[item_id] = Match(score, self._items[item_id], name, is_alias)

        fuzzy_ok = len(q) >= 3
        for k, item_id, name, is_alias in self._keys:
            if k == q:
                offer(item_id, 95 if is_alias else 100, name, is_alias)
            elif k.startswith(q):
                offer(item_id, (80 if is_alias else 85) - min(8, (len(k) - len(q)) / 4), name, is_alias)
            elif q in k:
                offer(item_id, (65 if is_alias else 70) - min(8, (len(k) - len(q)) / 4), name, is_alias)
            elif fuzzy_ok:
                cur = best.get(item_id)
                if cur is not None and cur.score >= 68:
                    continue
                r = _similarity(q, k)
                if r >= 0.72:
                    offer(item_id, 40 + 28 * (r - 0.72) / 0.28, name, is_alias)
        out = sorted(best.values(), key=lambda m: (-m.score, len(fold(m.name))))
        return out[:limit]


def _similarity(q: str, k: str) -> float:
    sm = difflib.SequenceMatcher(None, q, k, autojunk=False)
    if sm.real_quick_ratio() < 0.5 and len(k) <= len(q) * 2:
        return 0.0
    r = sm.ratio() if sm.quick_ratio() >= 0.72 else 0.0
    if len(k) > len(q) + 2:      # typo inside a longer title: compare with the best window
        n = len(q)
        for i in range(0, len(k) - n + 1):
            w = k[i:i + n]
            if w[0] != q[0] and w[-1] != q[-1]:
                continue
            sm2 = difflib.SequenceMatcher(None, q, w, autojunk=False)
            if sm2.quick_ratio() >= 0.8:
                r = max(r, sm2.ratio() * 0.95)
    return r


@dataclass
class Decision(Generic[T]):
    item: T | None = None          # one clear answer
    choices: list[Match[T]] | None = None   # ask the user which one
    note: str = ""                 # e.g. 「按别名『救护车』找到」


def decide(matches: list[Match[T]], query: str) -> Decision[T]:
    if not matches:
        return Decision()
    top = matches[0]
    exact = [m for m in matches if m.score >= 95]
    if len(exact) == 1 or (exact and exact[0].score == 100 and (len(exact) == 1 or exact[1].score < 100)):
        return Decision(item=exact[0].item)
    if len(exact) > 1:
        return Decision(choices=exact[:8])
    second = matches[1].score if len(matches) > 1 else 0
    if len(fold(query)) <= 1:        # one character is too little to guess from part of a name
        return Decision(choices=matches[:6])
    if top.score >= 55 and top.score - second >= 8:
        return Decision(item=top.item, note=f"按「{top.name}」找到的" if top.score < 80 else "")
    return Decision(choices=matches[:6])


def hardness(item) -> float:
    """最难谱面的定数（没有定数就按等级估），舞萌 Song / 中二 SongInfo 都能用。"""
    charts = getattr(item, "charts", None)
    vals = charts.values() if isinstance(charts, dict) else (charts or [])
    best = 0.0
    for c in vals:
        v = getattr(c, "ds", None)
        if v is None:
            v = getattr(c, "const", None)
        if v is None:
            m = re.match(r"(\d+)(\+)?", str(getattr(c, "level", "") or ""))
            v = (int(m.group(1)) + (0.7 if m.group(2) else 0.0)) if m else 0.0
        try:
            best = max(best, float(v or 0))
        except (TypeError, ValueError):
            pass
    return best


def alias_pick(choices: list[Match[T]], skip=None) -> tuple[T, list[T]] | None:
    """一个外号对应好几首（全是按外号精确命中的）→ (最难的那首, 其余)。模糊命中的不算，那种要让用户自己挑。"""
    exact = [m for m in (choices or []) if m.score >= 95]
    if len(exact) < 2 or not all(m.by_alias for m in exact):
        return None
    items = [m.item for m in exact if not (skip and skip(m.item))] or [m.item for m in exact]
    seen, uniq = set(), []
    for it in items:                       # dataclass songs aren't hashable: dedupe by identity
        if id(it) not in seen:
            seen.add(id(it))
            uniq.append(it)
    items = sorted(uniq, key=hardness, reverse=True)
    return items[0], items[1:]


# ---------- sub-command helpers (both games) ----------
def split_glued(word: str, commands: Iterable[str]) -> tuple[str, str] | None:
    """'查歌救护车' → ('查歌', '救护车'); 'b50文字' → ('b50', '文字'); longest command wins."""
    w = word.lower()
    for c in sorted(commands, key=len, reverse=True):
        if (len(c) >= 2 or c == "查") and w.startswith(c) and len(w) > len(c):
            return c, word[len(c):]
    return None


COMMON_SLIPS = {"b40": "b50", "best40": "b50", "b30": "b50", "查曲": "查歌", "查谱": "查歌", "查谱面": "查歌",
                "谱面": "查歌", "歌曲": "查歌", "分数": "成绩", "我的成绩": "成绩", "单曲成绩": "成绩",
                "定数查询": "定数", "查定数": "定数", "定数查歌": "定数", "外号": "别名", "添加别名": "加别名",
                "设置别名": "加别名", "删除别名": "删别名", "信息": "我", "个人信息": "我", "rating": "我",
                "ra": "我", "最近成绩": "最近", "绑": "绑定", "登录": "绑定", "教程": "绑定教程", "?": "帮助"}


def suggest(word: str, commands: Iterable[str], n: int = 2) -> list[str]:
    cmds = list(dict.fromkeys(commands))
    w = word.lower()
    out = [COMMON_SLIPS[w]] if COMMON_SLIPS.get(w) in cmds else []
    for c in difflib.get_close_matches(w, cmds, n=n + 2, cutoff=0.5):
        if c not in out:
            out.append(c)
    return out[:n]
