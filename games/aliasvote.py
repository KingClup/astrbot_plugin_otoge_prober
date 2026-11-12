"""猜歌里收集别名：有人用原名猜中 → 往回看这一局里没猜中的短消息 → 大模型判断哪条像这首歌的外号 →
在群里发起投票（默认 3 票 y 通过、2 票 n 否决、10 分钟），通过了就加进本机别名库。

这里只管「挑候选、问模型、记票」，不碰网络和 AstrBot：模型调用和写别名库由插件主体传进来。
"""
from __future__ import annotations

import json
import os
import unicodedata
import re
import time
from collections import deque
from dataclasses import dataclass, field

from .core import norm, title_parts

YES = {"y", "yes", "同意", "赞成", "+1"}
NO = {"n", "no", "反对", "不同意", "-1"}
LOG_SIZE = 60
MAX_CANDIDATES = 8
REMEMBER_DAYS = 60                 # 被否决 / 过期的同一个外号这么久之内不再提
_SKIP = re.compile(r"^(?:[/／!！#＃]|https?://|\[CQ:|开\s|\d{1,2}\s*[.．、。:：号]?\s*提示$|提示\s*\d)", re.I)
_ONLY_SYMBOLS = re.compile(r"^[\W_]+$", re.U)
CHAT_WORDS = {"不对", "不是", "啊", "啊啊", "哈哈", "哈哈哈", "草", "好难", "难", "什么", "啥", "？", "?", "。", "不知道",
              "不会", "放弃", "不猜了", "猜不出", "下一个", "这是啥", "这是什么", "好熟", "眼熟", "6", "666", "笑死",
              "我知道", "知道了", "想起来了", "好像是", "是不是", "提示", "加", "开", "结束", "答案"}

SYSTEM = ("判断音游群聊里的短消息是不是某首歌的外号（简称、缩写、谐音、译名、梗称都算；聊天、提问、猜别的歌、乱猜都不算，拿不准就当不是）。"
          "只输出 JSON 数组，每首歌一项：[{\"i\":歌序号,\"a\":原样复制的候选或null,\"c\":0~1把握,\"r\":\"≤10字理由\"}]")
TOP_K = 3                 # 每首歌最多给模型看几条
MIN_SCORE = 1.5           # 本地打分低于这个就不问模型（省 token）
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_CHATTY = re.compile(r"[吗呢吧啊呀哦嘛么哈嘿]$|^(?:我|你|他|这|那|是不是|有没有|好像|感觉|应该)|[?？!！]$")

@dataclass
class LogLine:
    ts: float
    uid: str
    name: str
    text: str


@dataclass
class Vote:
    origin: str
    game: str
    kind: str                       # 猜歌种类：chart 的 sid 是 sdvx.in 的 ID
    sid: str
    title: str
    alias: str
    reason: str = ""
    started: float = 0.0
    yes: set[str] = field(default_factory=set)
    no: set[str] = field(default_factory=set)
    ref: object = field(default=None, repr=False)     # 曲库里的那首（舞萌要拿曲目 ID）

    @property
    def key(self) -> str:
        return f"{self.game}|{self.kind == 'chart'}|{self.sid}|{norm(self.alias)}"


def _initials(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", unicodedata.normalize("NFKC", title))
    return "".join(w[0] for w in words).lower() if len(words) >= 2 else ""


def _subseq(a: str, b: str) -> bool:
    it = iter(b)
    return all(ch in it for ch in a)


def score(text: str, k: str, ln: "LogLine", song, solver: str, until: float, repeats: int) -> float:
    """本地给一条候选打分（不花 token）：越像这首歌的外号越高。"""
    t = norm(song.title)
    sc = 0.0
    if ln.uid == solver:                               # 猜中的人自己先试过这个叫法，再打了原名
        sc += 2.5
    if repeats >= 2:                                   # 不止一个人这么叫
        sc += 1.5
    ini = _initials(song.title)
    if ini and k == ini:                               # Abstract Art → aa
        sc += 3
    elif len(k) >= 2 and k in t:                       # 标题里的一段
        sc += 2
    elif len(k) >= 2 and _subseq(k, t):                # 按顺序取标题里的字（缩写）
        sc += 1.5
    else:
        common = len(set(k) & set(t))
        if common and common / len(set(k)) >= 0.5:
            sc += 1
    if _CJK.search(text) and 2 <= len(k) <= 6:          # 中文 / 日文短词：可能是译名 / 梗，交给模型
        sc += 0.8
    if len(k) == 1:
        sc -= 1.5
    if _CHATTY.search(text.strip()):
        sc -= 2
    sc += max(0.0, 1 - (until - ln.ts) / 300)           # 离猜中越近越像
    return sc


def candidates(log: list[LogLine], since: float, until: float, song, known_keys: set[str],
               other_songs: list = (), *, solver: str = "", catalog_keys: set[str] = frozenset(),
               top: int = TOP_K, min_score: float = MIN_SCORE) -> list[str]:
    """这一局里、猜中之前、没猜中的短消息，按本地打分挑前几条（分太低的不要，省得白问模型）。"""
    title_keys = {norm(song.title), *(norm(p) for p in title_parts(song.title))}
    taken = set(song.answers()) | set(catalog_keys)     # 已经是某首歌的名字 / 外号：不是这首的新外号
    for s in other_songs:
        taken |= s.answers()
    seen: dict[str, tuple[str, LogLine]] = {}
    who: dict[str, set[str]] = {}
    for ln in log:
        if not (since <= ln.ts <= until):
            continue
        t = ln.text.strip()
        m = re.match(r"^猜\s*(.+)$", t)
        if m:
            t = m.group(1).strip()
        k = norm(t)
        if (not k or len(t) > 20 or len(k) > 16 or _SKIP.match(t) or _ONLY_SYMBOLS.match(t)
                or t.lower() in CHAT_WORDS or k in title_keys or k in taken or k in known_keys
                or (" " in t and len(t.split()) > 3)):
            continue
        seen[k] = (t, ln)
        who.setdefault(k, set()).add(ln.uid)
    ranked = sorted(((score(t, k, ln, song, solver, until, len(who[k])), t) for k, (t, ln) in seen.items()),
                    reverse=True)
    return [t for sc, t in ranked if sc >= min_score][:top]


def prompt(items: list[tuple[str, object, list[str]]]) -> str:
    """items = [(游戏名, 歌, 候选)]，几首一起问（开字母一局能连中好几首，攒一下一次问完）。"""
    out = []
    for n, (game_name, song, cands) in enumerate(items, 1):
        known = "、".join(song.aliases[:5])
        out.append(f"{n}. {game_name}《{song.title}》" + (f" 已有外号：{known}" if known else "")
                   + "\n候选：" + " | ".join(cands))
    return "\n".join(out)


def parse_reply(text: str, items: list[tuple[str, object, list[str]]], threshold: float = 0.75) -> dict[int, tuple[str, str]]:
    """模型回复 → {歌序号(0 起): (候选原文, 理由)}；没把握 / 解析不了的不在里面。"""
    m = re.search(r"\[.*\]", text or "", re.S) or re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {}
    if isinstance(data, dict):
        data = [data]
    out: dict[int, tuple[str, str]] = {}
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        try:
            i = int(d.get("i", 1)) - 1
            conf = float(d.get("c", d.get("confidence", 0)) or 0)
        except (TypeError, ValueError):
            continue
        a = d.get("a", d.get("alias"))
        if not (0 <= i < len(items)) or not isinstance(a, str) or conf < threshold:
            continue
        pick = next((c for c in items[i][2] if norm(c) == norm(a)), None)
        if pick is not None:
            out[i] = (pick, str(d.get("r", d.get("reason", "")) or "")[:20])
    return out


ASK_SECONDS = 180          # 「要加外号吗」发出去后多久内回「别名 xxx」算数
ASK_MAX_SONGS = 3
ASK_MAX_PROPOSALS = 3      # 一次提问最多收几个提议（再多就刷屏了）
_ASK_RE = re.compile(r"^(?:别名|外号)\s*[:：]?\s*(.+)$", re.S)


@dataclass
class Ask:
    origin: str
    started: float
    items: list                      # [(kind, song)]
    taken: int = 0                   # 已经收了几个提议


def parse_ask_reply(text: str, n_items: int) -> tuple[int, str] | None:
    """「别名 xxx」/「外号：xxx」/「别名 2 xxx」→ (第几首(0 起), 外号)；不是这个格式 → None。
    只认开头是「别名 / 外号」的消息，别的聊天一律不碰（不会把闲聊当成外号）。"""
    m = _ASK_RE.match((text or "").strip())
    if not m:
        return None
    rest = m.group(1).strip()
    idx = 0
    n = re.match(r"^(\d)\s+(.+)$", rest)
    if n and 1 <= int(n.group(1)) <= max(n_items, 1) and (n_items > 1 or n.group(1) == "1"):
        idx, rest = int(n.group(1)) - 1, n.group(2).strip()
    elif n_items > 1:
        return (-1, rest)            # 好几首又没写序号：让对方补
    return idx, rest


def which_song_hint(items, alias: str = "") -> str:
    """好几首在问、对方没写序号：把这几首连序号列出来，照着抄就行。"""
    t = (alias or "").strip()
    shown = t if t and len(t) <= 20 and "\n" not in t else "外号"
    rows = "\n".join(f"{n}. 《{song.title}》" for n, (_, song) in enumerate(items, 1))
    head = f"「{t}」要加给哪首？" if shown != "外号" else "要加给哪首？"
    return f"{head}\n{rows}\n回「别名 序号 {shown}」，比如「别名 1 {shown}」"


def check_alias(alias: str, song, blocked: set[str], catalog_keys: set[str]) -> str:
    """群友提的外号能不能拿去投票：能 → ""；不能 → 原因（直接回给群里）。"""
    t = alias.strip()
    k = norm(t)
    if not k or _ONLY_SYMBOLS.match(t) or _SKIP.match(t) or ("[" in t and "CQ:" in t):
        return "这个看不出是外号"
    if len(t) > 20 or len(k) > 16 or "\n" in t:
        return "太长了，外号一般就几个字"
    if t.lower() in CHAT_WORDS:
        return "这个像聊天，不像外号"
    if k in set(song.answers()):
        return f"「{t}」已经能直接猜中《{song.title}》了，不用加"
    if k in catalog_keys:
        return f"「{t}」已经是别的歌的名字或外号了，加了会撞"
    if k in blocked:
        return f"「{t}」最近投过票了"
    return ""


class AliasVotes:
    """每个群（origin）同时只开一个投票，其余排队。"""

    def __init__(self, root: str, *, yes: int = 3, no: int = 2, minutes: float = 10):
        self.path = os.path.join(root, "alias_votes.json")
        self.need_yes, self.need_no, self.minutes = max(1, int(yes)), max(1, int(no)), float(minutes)
        self.active: dict[str, Vote] = {}
        self.queue: dict[str, list[Vote]] = {}
        self.logs: dict[str, deque] = {}
        self.asks: dict[str, Ask] = {}
        self.last_ask: dict[str, float] = {}
        self.history = self._load()

    # ---- 聊天记录（只在猜歌局里记，局外的消息不进来） ----
    def log(self, origin: str, uid: str, name: str, text: str, ts: float | None = None) -> None:
        self.logs.setdefault(origin, deque(maxlen=LOG_SIZE)).append(
            LogLine(ts or time.time(), str(uid), name, text))

    def lines(self, origin: str) -> list[LogLine]:
        return list(self.logs.get(origin) or [])

    # ---- 历史：通过 / 否决 / 过期的不再提 ----
    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        cut = time.time() - REMEMBER_DAYS * 86400
        cut_no = time.time() - 30 * 86400
        self.history = {k: v for k, v in self.history.items()
                        if v.get("result") == "pass"
                        or float(v.get("ts") or 0) >= (cut_no if v.get("result") == "llm_no" else cut)}
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def known_keys(self, game: str, kind: str, sid: str) -> set[str]:
        """这首歌已经投过 / 正在投 / 排队的外号（标准化后）。"""
        pre = f"{game}|{kind == 'chart'}|{sid}|"
        keys = {k[len(pre):] for k in self.history if k.startswith(pre)}
        for v in [*self.active.values(), *(x for q in self.queue.values() for x in q)]:
            if v.key.startswith(pre):
                keys.add(norm(v.alias))
        return keys

    def voted_keys(self, game: str, kind: str, sid: str) -> set[str]:
        """真投过票（通过 / 否决 / 过期）或正在投、排队的；「模型说不是」的不算，群友亲自提还是可以投。"""
        pre = f"{game}|{kind == 'chart'}|{sid}|"
        keys = {k[len(pre):] for k, h in self.history.items() if k.startswith(pre) and h.get("result") != "llm_no"}
        for v in [*self.active.values(), *(x for q in self.queue.values() for x in q)]:
            if v.key.startswith(pre):
                keys.add(norm(v.alias))
        return keys

    # ---- 模型没找到外号时，问群友「要加外号吗」 ----
    def busy(self, origin: str) -> bool:
        return (self.ask_current(origin) is not None or self._current(origin) is not None
                or bool(self.queue.get(origin)))

    def can_ask(self, origin: str, cooldown_min: float, now: float | None = None) -> bool:
        """猜歌一般连着猜：默认不冷却（cooldown 0），在问的、在投的都不挡；设了冷却才按分钟算。"""
        now = now or time.time()
        return cooldown_min <= 0 or now - self.last_ask.get(origin, 0) >= cooldown_min * 60

    def ask_current(self, origin: str) -> Ask | None:
        a = self.asks.get(origin)
        if a is not None and (time.time() - a.started > ASK_SECONDS
                              or a.taken >= ASK_MAX_PROPOSALS * max(1, len(a.items))):
            self.asks.pop(origin, None)
            return None
        return a

    def open_ask(self, origin: str, items: list, game_names: dict | None = None) -> str | None:
        """items = [(kind, song)]。返回要发到群里的话；都已经在问了 → None。
        上一次问的还没过期就接着编号（4、5…），旧序号不变，免得有人回「别名 1 xx」加错歌。"""
        now = time.time()
        cur = self.ask_current(origin)
        if cur is not None:
            have = {(sg.game, k == "chart", sg.sid) for k, sg in cur.items}
            items = [(k, sg) for k, sg in items if (sg.game, k == "chart", sg.sid) not in have]
            if not items:
                return None
            if len(cur.items) + len(items) > 9:                  # 序号只认一位数：太多了就重新开一轮
                cur = None
        items = items[-ASK_MAX_SONGS:]
        if cur is None:
            cur = Ask(origin, now, [])
            self.asks[origin] = cur
        start = len(cur.items)
        cur.items.extend(items)
        cur.started = now
        self.last_ask[origin] = now
        gn = game_names or {}
        mins = ASK_SECONDS // 60

        def line(song) -> str:
            known = "、".join(song.aliases[:3])
            return f"《{song.title}》（{gn.get(song.game, song.game)}）" + (f" 已有：{known}" if known else "")
        if len(cur.items) == 1:
            ask = "这首还有别的叫法吗？" if items[0][1].aliases else "这首大家平时叫它什么？"
            return (f"🤔 {line(items[0][1])}\n{ask}有外号的话 {mins} 分钟内回「别名 外号」，"
                    f"我拿去投票（没有就不用理）")
        rows = "\n".join(f"{n}. {line(sg)}" for n, (_, sg) in enumerate(items, start + 1))
        head = "刚猜中的这几首还有别的外号吗？" if start == 0 else "还有这几首："
        if start == 0 and len(items) == 1:
            head = "这首还有别的外号吗？"
        return (f"🤔 {head}\n{rows}\n回「别名 序号 外号」（比如「别名 {start + 1} xxx」），"
                f"{mins} 分钟内有效，我拿去投票（没有就不用理）")

    def remember_no(self, game: str, kind: str, sid: str, title: str, alias: str) -> None:
        """模型判断「不是外号」的也记下（不再拿去问，省 token；30 天后忘掉）。"""
        v = Vote("", game, kind, sid, title, alias)
        self.history[v.key] = {"result": "llm_no", "ts": time.time(), "alias": alias, "title": title, "yes": 0, "no": 0}

    def flush(self) -> None:
        self._save()

    def _remember(self, v: Vote, result: str) -> None:
        self.history[v.key] = {"result": result, "ts": time.time(), "alias": v.alias, "title": v.title,
                               "yes": len(v.yes), "no": len(v.no)}
        self._save()

    # ---- 投票 ----
    def intro(self, v: Vote) -> str:
        why = f"（{v.reason}）" if v.reason else ""
        return (f"🗳 别名投票：「{v.alias}」= 《{v.title}》？{why}\n"
                f"同意回 y，反对回 n：{self.need_yes} 票 y 通过，{self.need_no} 票 n 否决，{int(self.minutes)} 分钟内有效")

    def propose(self, v: Vote) -> str | None:
        """开始投票就返回要发的话；前面还有在投的就排队（返回 None，轮到时再发）。"""
        if any(x.key == v.key for x in [self.active.get(v.origin), *self.queue.get(v.origin, [])] if x):
            return None
        cur = self._current(v.origin)
        if cur is not None:
            self.queue.setdefault(v.origin, []).append(v)
            return None
        v.started = time.time()
        self.active[v.origin] = v
        return self.intro(v)

    def _current(self, origin: str) -> Vote | None:
        v = self.active.get(origin)
        if v is not None and time.time() - v.started > self.minutes * 60:
            self._remember(v, "expired")
            self.active.pop(origin, None)
            return None
        return v

    def next_intro(self, origin: str) -> str | None:
        """当前的结束 / 过期后，把排队的下一个拿出来。"""
        if self._current(origin) is not None:
            return None
        q = self.queue.get(origin) or []
        while q:
            v = q.pop(0)
            if v.key in self.history:
                continue
            v.started = time.time()
            self.active[origin] = v
            return self.intro(v)
        return None

    def on_message(self, origin: str, uid: str, text: str) -> tuple[str, Vote] | None:
        """群里的 y / n → ("counted" | "pass" | "reject", vote)；不是投票消息 / 没有在投的 → None。"""
        w = (text or "").strip().lower()
        if w not in YES and w not in NO:
            return None
        v = self._current(origin)
        if v is None:
            return None
        uid = str(uid)
        (v.yes if w in YES else v.no).add(uid)
        (v.no if w in YES else v.yes).discard(uid)
        if len(v.yes) >= self.need_yes:
            self.active.pop(origin, None)
            self._remember(v, "pass")
            return "pass", v
        if len(v.no) >= self.need_no:
            self.active.pop(origin, None)
            self._remember(v, "reject")
            return "reject", v
        return "counted", v

    def status(self, v: Vote) -> str:
        return f"y {len(v.yes)}/{self.need_yes} · n {len(v.no)}/{self.need_no}"
