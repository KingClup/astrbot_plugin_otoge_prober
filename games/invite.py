"""群里热闹的时候，轻轻问一句要不要玩小游戏（不花 token、不 @ 人、不刷屏）。

判断全在本地：
- 热闹：window_min 分钟内 ≥ min_msgs 条消息、≥ min_people 个人在说话；
- 不打扰：这个群正在玩 / 正在投别名票、刚结束一局（after_game_min 分钟内）、夜里（quiet 时段）都不发；
- 不尴尬：同一个群两次至少隔 cooldown_min 分钟、每天最多 daily_max 次；
  发了以后 answer_min 分钟内没人开局 → 下次间隔翻倍（最多 ×8），有人开了就恢复。
- 群里刚好在聊哪个音游就推荐哪个（舞萌 / 中二 / 音击 / SDVX / PJSK），没聊就随便挑舞萌或中二。
"""
from __future__ import annotations

import random
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

DEFAULTS = {
    "window_min": 5,        # 看最近几分钟
    "min_msgs": 15,         # 至少几条
    "min_people": 3,        # 至少几个人
    "cooldown_min": 120,    # 同一个群两次至少隔多久
    "daily_max": 3,         # 每个群每天最多几次
    "answer_min": 5,        # 发了以后多久内有人开局算「接了」
    "after_game_min": 30,   # 刚结束一局多久内不问
    "quiet_start": 3,       # 几点开始不发（本地时间，整点）
    "quiet_end": 10,        # 几点恢复
}
LIMITS = {"window_min": (1, 60), "min_msgs": (3, 200), "min_people": (2, 30), "cooldown_min": (10, 1440),
          "daily_max": (1, 20), "answer_min": (1, 30), "after_game_min": (0, 240), "quiet_start": (0, 23),
          "quiet_end": (0, 23)}
MAX_BACKOFF = 8

GAME_WORDS = [
    ("mai", "舞萌", re.compile(r"舞萌|maimai|乌蒙|打乌|\bmai\b", re.I)),
    ("chu", "中二", re.compile(r"中二|chuni|chunithm|\bchu\b", re.I)),
    ("geki", "音击", re.compile(r"音击|ongeki|オンゲキ|\bgeki\b", re.I)),
    ("sdvx", "sdvx", re.compile(r"sdvx|ボルテ|sound ?voltex|volforce", re.I)),
    ("pjsk", "pjsk", re.compile(r"pjsk|プロセカ|啤酒烧烤|世界计划", re.I)),
]
NAMES = {"mai": "舞萌", "chu": "中二", "geki": "音击", "sdvx": "SDVX", "pjsk": "PJSK"}
MODES = {"mai": ["猜歌", "猜曲绘"], "chu": ["猜歌", "猜曲绘", "猜谱面"], "geki": ["猜歌", "猜曲绘", "猜谱面"],
         "sdvx": ["猜歌", "猜曲绘", "猜谱面"], "pjsk": ["猜歌", "猜曲绘"]}
MODE_NAME = {"猜歌": "开字母", "猜曲绘": "猜曲绘", "猜谱面": "猜谱面"}
LINES_TOPIC = [
    "聊{name}聊得这么起劲 要不要来一局{mode}？发 {cmd} 就开",
    "{name}人好齐 来把{mode}不？{cmd}",
]
LINES_PLAIN = [
    "群里好热闹 要不要来一局{mode}？发 {cmd} 就开",
    "人挺多的 来玩{mode}吗？{cmd}",
    "趁人多来一局{mode}？发 {cmd}",
]


def clamp_settings(raw: dict | None) -> dict:
    out = dict(DEFAULTS)
    for k, (lo, hi) in LIMITS.items():
        try:
            v = int((raw or {}).get(k, out[k]))
        except (TypeError, ValueError):
            continue
        out[k] = max(lo, min(hi, v))
    return out


@dataclass
class GroupState:
    msgs: deque = field(default_factory=lambda: deque(maxlen=400))   # (时间, 发言人, 文字)
    last_sent: float = 0.0
    day: str = ""
    sent_today: int = 0
    backoff: int = 1
    pending: float = 0.0          # 上次邀请的时间（等人开局中）；0 = 没在等
    playing: bool = False
    last_game_end: float = 0.0
    last_text: str = ""


def detect_game(texts: list[str]) -> str | None:
    hits: dict[str, int] = {}
    for t in texts:
        for key, _, rx in GAME_WORDS:
            if rx.search(t):
                hits[key] = hits.get(key, 0) + 1
    if not hits:
        return None
    best = max(hits.values())
    if best < 2:                   # 只提了一次不算在聊
        return None
    return max(hits, key=lambda k: hits[k])


def make_line(game: str | None, rng: random.Random) -> str:
    g = game or rng.choice(["mai", "chu"])
    mode = rng.choice(MODES[g])
    cmd = f"/{mode} {NAMES[g] if g in ('mai', 'chu', 'geki') else g}"
    tpl = rng.choice(LINES_TOPIC if game else LINES_PLAIN)
    return tpl.format(name=NAMES[g], mode=MODE_NAME[mode], cmd=cmd)


class InviteWatcher:
    def __init__(self, clock=time.time, rng: random.Random | None = None):
        self.clock = clock
        self.rng = rng or random.Random()
        self.groups: dict[str, GroupState] = {}

    def state(self, gid: str) -> GroupState:
        st = self.groups.get(gid)
        if st is None:
            st = self.groups[gid] = GroupState()
        return st

    def observe(self, gid: str, playing: bool) -> None:
        """每条群消息前先告诉它这个群现在有没有在玩（用来记「刚结束」「有人接了邀请」）。"""
        st, now = self.state(gid), self.clock()
        if playing and not st.playing:
            if st.pending and now - st.pending <= 3600:
                st.backoff = 1                       # 邀请后有人开了：恢复正常间隔
            st.pending = 0.0
        if st.playing and not playing:
            st.last_game_end = now
        st.playing = playing

    def on_message(self, gid: str, uid: str, text: str, local: datetime, cfg: dict,
                   playing: bool = False, busy: bool = False) -> str | None:
        """记一条群消息；该邀请了就返回要发的那句话（并记账），否则 None。"""
        self.observe(gid, playing)
        st, now = self.state(gid), self.clock()
        st.msgs.append((now, str(uid), (text or "")[:200]))
        day = local.strftime("%Y-%m-%d")
        if st.day != day:
            st.day, st.sent_today = day, 0
        # 邀请过了、answer_min 内没人开 → 间隔翻倍
        if st.pending and now - st.pending > cfg["answer_min"] * 60:
            st.backoff = min(MAX_BACKOFF, st.backoff * 2)
            st.pending = 0.0
        if playing or busy or st.pending:
            return None
        if self._quiet(local.hour, cfg):
            return None
        if st.sent_today >= cfg["daily_max"]:
            return None
        if st.last_sent and now - st.last_sent < cfg["cooldown_min"] * 60 * st.backoff:
            return None
        if st.last_game_end and now - st.last_game_end < cfg["after_game_min"] * 60:
            return None
        recent = [m for m in st.msgs if now - m[0] <= cfg["window_min"] * 60]
        if len(recent) < cfg["min_msgs"] or len({m[1] for m in recent}) < cfg["min_people"]:
            return None
        line = make_line(detect_game([m[2] for m in recent]), self.rng)
        st.last_sent, st.pending, st.last_text = now, now, line
        st.sent_today += 1
        return line

    @staticmethod
    def _quiet(hour: int, cfg: dict) -> bool:
        a, b = cfg["quiet_start"], cfg["quiet_end"]
        if a == b:
            return False
        return a <= hour < b if a < b else (hour >= a or hour < b)

    def snapshot(self, gid: str, cfg: dict) -> dict:
        st = self.groups.get(gid)
        if st is None:
            return {"sent_today": 0, "last": "", "backoff": 1, "recent": 0, "people": 0}
        now = self.clock()
        recent = [m for m in st.msgs if now - m[0] <= cfg["window_min"] * 60]
        return {"sent_today": st.sent_today, "last_ago_min": int((now - st.last_sent) / 60) if st.last_sent else None,
                "last": st.last_text, "backoff": st.backoff, "recent": len(recent),
                "people": len({m[1] for m in recent}), "waiting": bool(st.pending)}
