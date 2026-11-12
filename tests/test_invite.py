"""v2.3.6：群里热闹时邀请小游戏（本地判断，不花 token）。"""
import os
import random
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.prefs import Prefs  # noqa: E402
from games.invite import InviteWatcher, clamp_settings, detect_game  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


EVENING = datetime(2026, 11, 12, 21, 0)
NIGHT = datetime(2026, 11, 12, 4, 0)


def chat(w, clock, n, people=4, text="哈哈哈", gid="1", when=EVENING, **kw):
    out = []
    for i in range(n):
        clock.t += 5
        r = w.on_message(gid, str(i % people), text, when, CFG, **kw)
        if r:
            out.append(r)
    return out


CFG = clamp_settings({})


def test_invites_once_when_lively_then_cooldown():
    c = Clock()
    w = InviteWatcher(clock=c, rng=random.Random(1))
    assert chat(w, c, 14) == []                      # 还不够 15 条
    got = chat(w, c, 1)
    assert len(got) == 1 and "/" in got[0]
    assert chat(w, c, 40) == []                      # 冷却中 / 等人开局中


def test_not_enough_people_or_playing_or_quiet():
    c = Clock()
    w = InviteWatcher(clock=c)
    assert chat(w, c, 30, people=2) == []            # 只有两个人在聊
    assert chat(w, c, 30, gid="2", playing=True) == []
    assert chat(w, c, 30, gid="3", busy=True) == []
    assert chat(w, c, 30, gid="4", when=NIGHT) == []  # 03–10 点不发


def test_backoff_when_ignored_and_reset_when_taken():
    c = Clock()
    w = InviteWatcher(clock=c)
    assert len(chat(w, c, 15)) == 1
    c.t += 6 * 60                                    # 5 分钟没人开局
    chat(w, c, 1)
    assert w.state("1").backoff == 2
    c.t += 121 * 60                                  # 过了 2 小时，但间隔已翻倍 → 还不发
    assert chat(w, c, 20) == []
    c.t += 120 * 60
    assert len(chat(w, c, 20)) == 1
    w.observe("1", True)                             # 这次有人开了
    assert w.state("1").backoff == 1
    w.observe("1", False)                            # 结束了：30 分钟内不问
    c.t += 300 * 60
    st = w.state("1")
    st.last_sent = 0
    st.last_game_end = c.t
    assert chat(w, c, 20) == []


def test_daily_cap_and_topic():
    c = Clock()
    w = InviteWatcher(clock=c, rng=random.Random(3))
    got = []
    for _ in range(6):
        got += chat(w, c, 20, text="今天打乌蒙了 舞萌好难")
        c.t += 130 * 60
        w.observe("1", True)                         # 每次都有人接，不翻倍
        w.observe("1", False)
        w.state("1").last_game_end = 0
    assert len(got) == 3                             # 每天最多 3 次
    assert all("舞萌" in g for g in got)
    assert detect_game(["sdvx 好难", "ボルテ 打不过"]) == "sdvx"
    assert detect_game(["吃饭了吗"]) is None and detect_game(["中二"]) is None   # 只提一次不算


def test_settings_clamped_and_prefs(tmp_path):
    s = clamp_settings({"min_msgs": 1, "daily_max": 999, "quiet_start": "x"})
    assert s["min_msgs"] == 3 and s["daily_max"] == 20 and s["quiet_start"] == 3
    p = Prefs(str(tmp_path))
    assert not p.invite_enabled("123") and p.games_enabled() is None
    p.add_group("123")
    p.set_invite("123", True)
    p.set_games_enabled(False)
    p.set_group_names({"123": "音游群"})
    q = Prefs(str(tmp_path))
    assert q.invite_enabled("123") and not q.llm_enabled("123") and q.games_enabled() is False
    assert q.group_switches()["123"] == {"llm": False, "invite": True} and q.group_names()["123"] == "音游群"
    q.remove_group("123")
    assert "123" not in Prefs(str(tmp_path)).group_switches()
