"""猜歌里收集别名 + 群投票（v2.1.0）。"""
import importlib
import os
import random
import sys
import time
import types

import pytest

from games import aliasvote as AV
from games import core as G
from games.commands import GameCommands
from mai.bot.commands import Ctx as MCtx
from tests.test_games import Ctx, FakeData, run

SONG = G.Song("mai", "8", "SUPER AMBULANCE", ["救车"], [])


def test_by_title():
    assert G.by_title("super ambulance", SONG) and G.by_title("SUPER AMBULANC", SONG)
    assert not G.by_title("救车", SONG) and not G.by_title("abc", SONG)


def test_candidates_filters_and_ranks():
    now = time.time()
    lines = ["救护车", "草", "猜 救护车", "/mai b50", "哈哈哈", "SUPER AMBULANCE", "安布兰斯", "https://x.y", "？？",
             "这首歌我以前打过好多次但是记不住名字了", "是这个吗", "sa", "别的歌"]
    log = [AV.LogLine(now - 60 + i, "u%d" % i, "x", t) for i, t in enumerate(lines)]
    log.append(AV.LogLine(now - 200, "9", "x", "开局前的消息"))
    got = AV.candidates(log, now - 100, now, SONG, set(), catalog_keys={G.norm("别的歌")})
    assert got[0] == "sa"                           # 首字母缩写排第一
    assert "救护车" in got and "安布兰斯" in got and len(got) <= AV.TOP_K
    assert "是这个吗" not in got and "别的歌" not in got
    assert AV.candidates(log, now - 100, now, SONG, {G.norm("sa"), G.norm("救护车"), G.norm("安布兰斯")},
                         catalog_keys={G.norm("别的歌")}) == []


def test_candidates_solver_bonus():
    now = time.time()
    song = G.Song("chu", "1", "Garakuta Doll Play", [], [])
    log = [AV.LogLine(now - 30, "solver", "a", "破烂人偶"), AV.LogLine(now - 25, "x", "b", "那个啥")]
    assert AV.candidates(log, now - 100, now, song, set(), solver="solver") == ["破烂人偶"]


def test_parse_reply():
    items = [("舞萌", SONG, ["救护车", "安布兰斯"]), ("中二", G.Song("chu", "2", "Aleph-0", [], []), ["阿列夫"])]
    got = AV.parse_reply('[{"i":1,"a":"救护车","c":0.9,"r":"意译"},{"i":2,"a":null,"c":0.9}]', items)
    assert got == {0: ("救护车", "意译")}
    assert AV.parse_reply('好的：[{"i":2,"a":"阿列夫","c":0.95}]', items) == {1: ("阿列夫", "")}
    assert AV.parse_reply('[{"i":1,"a":"救护车","c":0.5}]', items) == {}
    assert AV.parse_reply('[{"i":1,"a":"别的","c":0.99}]', items) == {}
    assert AV.parse_reply('{"alias":"救护车","confidence":0.9}', items) == {0: ("救护车", "")}   # 旧格式也认
    assert AV.parse_reply("不是 json", items) == {}
    assert "1. 舞萌《SUPER AMBULANCE》 已有外号：救车" in AV.prompt(items) and "候选：救护车 | 安布兰斯" in AV.prompt(items)


def _vote(alias="救护车", origin="g"):
    return AV.Vote(origin, "mai", "letters", "8", "SUPER AMBULANCE", alias, "意译")


def test_vote_pass_reject_queue_and_history(tmp_path):
    av = AV.AliasVotes(str(tmp_path), yes=3, no=2, minutes=10)
    intro = av.propose(_vote())
    assert "「救护车」= 《SUPER AMBULANCE》" in intro and "3 票 y" in intro
    assert av.propose(_vote("安布兰斯")) is None                       # 排队
    assert av.propose(_vote()) is None                                 # 同一个不重复开
    assert av.on_message("g", "1", "今天吃啥") is None
    assert av.on_message("g", "1", "y")[0] == "counted"
    assert av.on_message("g", "1", "Y")[0] == "counted"                # 同一个人只算一票
    assert av.on_message("g", "2", "n")[0] == "counted"
    assert av.on_message("g", "2", "y")[0] == "counted"                # 改票
    what, v = av.on_message("g", "3", "y")
    assert what == "pass" and len(v.yes) == 3
    assert "安布兰斯" in av.next_intro("g")
    av.on_message("g", "1", "n")
    assert av.on_message("g", "2", "no")[0] == "reject"
    assert av.next_intro("g") is None and av.on_message("g", "4", "y") is None
    # 历史：两个都不会再提
    av2 = AV.AliasVotes(str(tmp_path))
    assert av2.known_keys("mai", "letters", "8") == {G.norm("救护车"), G.norm("安布兰斯")}


def test_vote_expires(tmp_path):
    av = AV.AliasVotes(str(tmp_path), minutes=1)
    av.propose(_vote())
    av.active["g"].started -= 120
    assert av.on_message("g", "1", "y") is None
    assert av.history[_vote().key]["result"] == "expired"


def test_game_hooks_log_and_title_solve():
    gc = GameCommands(FakeData(), rnd=random.Random(7))
    logged, solved = [], []
    gc.on_message_log = lambda o, c, t: logged.append(t)
    gc.on_title_solve = lambda o, s, i, c, t: solved.append((i, t))
    run(gc.handle("g1", Ctx(), "/猜歌 舞萌 13以上", command=True))
    s = gc.sessions["g1"]
    run(gc.handle("g1", Ctx(), "瞎猜一个", command=False))
    run(gc.handle("g1", Ctx(), s.picks[1].song.aliases[0], command=False))       # 靠外号猜中：不触发
    run(gc.handle("g1", Ctx(), s.picks[0].song.title, command=False))            # 原名：触发
    assert logged[0] == "瞎猜一个" and solved == [(0, s.picks[0].song.title)]


def _main():
    pytest.importorskip("astrbot")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.dirname(root) not in sys.path:
        sys.path.insert(0, os.path.dirname(root))
    return importlib.import_module(os.path.basename(root) + ".main")


async def test_plugin_flow(tmp_path):
    M = _main()
    p = M.OtogeScore.__new__(M.OtogeScore)
    p.config = {}
    p.alias_votes = AV.AliasVotes(str(tmp_path), yes=2, no=2)
    p._alias_checks, p._tasks = {}, []
    sent, added = [], []
    p.charts = types.SimpleNamespace(src=types.SimpleNamespace(add_alias=lambda g, a, sid: added.append((g, a, sid))))
    p.games = types.SimpleNamespace(data=types.SimpleNamespace(_cache={"x": 1}, songs=lambda g: [], chart_songs=lambda g: []))

    async def notify(umo, text, at=""):
        sent.append(text)
    p._notify_private = notify

    calls = []

    async def llm():
        async def call(system, text):
            calls.append(text)
            assert "安布兰斯" in text
            return '[{"i": 1, "a": "安布兰斯", "c": 0.9, "r": "音译"}]'
        return call
    p._alias_llm_call = llm
    p._alias_live = {}
    p.ALIAS_BATCH_SECONDS = 0
    song = G.Song("sdvx", "s1", "SUPER AMBULANCE", [], [])
    s = types.SimpleNamespace(picks=[G.Pick(song)], started=time.time() - 60, kind="jacket")
    p.alias_votes.log("g", "1", "a", "安布兰斯")
    p.alias_votes.log("g", "5", "b", "sa")
    p._alias_solved("g", s, 0, MCtx(uid="1", private=False, admin=False), "SUPER AMBULANCE")
    await p._tasks[0]
    assert sent and "「安布兰斯」" in sent[0] and len(calls) == 1
    assert G.norm("sa") in p.alias_votes.known_keys("sdvx", "jacket", "s1")        # 模型说不是的：不再问
    c = lambda u: MCtx(uid=u, private=False, admin=False)  # noqa: E731
    assert "收到" in p._alias_vote("g", c("1"), "y").texts[0]
    r = p._alias_vote("g", c("2"), "y")
    assert "投票通过" in r.texts[0] and added == [("sdvx", "安布兰斯", "s1")] and p.games.data._cache == {}
    assert p._alias_vote("g", c("3"), "y") is None
    assert p._alias_vote("g", MCtx(uid="3", private=True, admin=False), "y") is None


def test_apply_mai_and_chu(tmp_path):
    M = _main()
    p = M.OtogeScore.__new__(M.OtogeScore)
    log = []

    class Store:
        def __init__(self, tag):
            self.tag = tag

        def add_local(self, a, sid):
            log.append((self.tag, a, sid))

        def merged(self):
            return {}
    p.cmd, p.chu = types.SimpleNamespace(aliases=Store("mai")), types.SimpleNamespace(aliases=Store("chu"))
    p.service = types.SimpleNamespace(catalog=types.SimpleNamespace(set_aliases=lambda d: log.append("mai set")))
    p.chu_svc = types.SimpleNamespace(songdb=types.SimpleNamespace(apply_aliases=lambda d: log.append("chu set")))
    p.games = types.SimpleNamespace(data=types.SimpleNamespace(_cache={}))
    ref = types.SimpleNamespace(music_ids=lambda: {10832, 832})
    assert p._alias_apply(AV.Vote("g", "mai", "letters", "832", "T", "救 车", ref=ref)) == ""
    assert p._alias_apply(AV.Vote("g", "chu", "jacket", "2338", "T", "阿列夫")) == ""
    assert log == [("mai", "救车", 832), "mai set", ("chu", "阿列夫", 2338), "chu set"]


def test_alias_library_export(tmp_path):
    import json as _json
    from core import aliaslib as AL
    av = AV.AliasVotes(str(tmp_path))
    v = AV.Vote("g", "chu", "jacket", "2338", "Aleph-0", "阿列夫")
    v.yes = {"1", "2", "3"}
    av._remember(v, "pass")
    mai_song = types.SimpleNamespace(title="SUPER AMBULANCE")
    chu_song = types.SimpleNamespace(title="Aleph-0")
    p = types.SimpleNamespace(
        alias_votes=av,
        cmd=types.SimpleNamespace(db=types.SimpleNamespace(song_by_any_id=lambda n: mai_song if n == 832 else None),
                                  aliases=types.SimpleNamespace(local=lambda: {"救车": 832, "孤儿": 9999})),
        chu_svc=types.SimpleNamespace(songdb=types.SimpleNamespace(get=lambda n: chu_song if n == 2338 else None)),
        chu=types.SimpleNamespace(aliases=types.SimpleNamespace(local=lambda: {"阿列夫": 2338})),
        charts=types.SimpleNamespace(src=types.SimpleNamespace(
            aliases={"chu": {"00123": ["阿列夫", "a0"]}, "sdvx": {"05": ["炸弹"]}},
            entries={"chu": {"00123": types.SimpleNamespace(title="Aleph-0")}, "sdvx": {}})))
    counts = AL.write(AL.collect(p), str(tmp_path / "lib"))
    assert counts == {"mai": 2, "chu": 2, "geki": 0, "sdvx": 1, "pjsk": 0}
    chu = _json.load(open(tmp_path / "lib" / "chu.json", encoding="utf-8"))
    assert chu["schema"] == "otoge-community-aliases" and chu["license"] == "CC0-1.0"
    song = chu["songs"][0]
    assert song["ids"] == {"chu": 2338, "sdvxin": "00123"}
    a = {x["alias"]: x for x in song["aliases"]}
    assert a["阿列夫"]["source"] == "vote" and a["阿列夫"]["votes"] == {"yes": 3, "no": 0} and a["a0"]["source"] == "manual"
    raw = (tmp_path / "lib" / "chu.json").read_text(encoding="utf-8")
    assert '"g"' not in raw and "README" not in raw and (tmp_path / "lib" / "README.md").exists()


def test_chart_shows_local_aliases():
    from chart.commands import ChartCommands
    from chart.sdvxin import Entry
    c = ChartCommands.__new__(ChartCommands)
    c.src = types.SimpleNamespace(aliases={"chu": {"00123": ["a0"]}})
    song = types.SimpleNamespace(id=2338, title="Aleph-0")
    c.chu = types.SimpleNamespace(aliases=types.SimpleNamespace(local=lambda: {"阿列夫": 2338, "别的": 1}),
                                  svc=types.SimpleNamespace(songdb=types.SimpleNamespace(songs={2338: song})))
    e = Entry("chu", "00123", "Aleph-0", "", {})
    assert c.local_aliases(e) == ["a0", "阿列夫"]
    c.chu = None
    assert c.local_aliases(Entry("sdvx", "1", "x", "", {})) == []


async def test_webui_alias_settings_and_votes(tmp_path):
    M = _main()
    from core.webui import CoreWebUI
    p = M.OtogeScore.__new__(M.OtogeScore)
    p.config, p.root = {"alias_vote_yes": 3}, str(tmp_path)
    p._alias_live = {}
    p.alias_votes = AV.AliasVotes(str(tmp_path))
    p.context = types.SimpleNamespace(get_all_providers=lambda: [types.SimpleNamespace(
        meta=lambda: types.SimpleNamespace(id="ds_flash", model="deepseek-flash"))])
    added, sent = [], []
    p.charts = types.SimpleNamespace(src=types.SimpleNamespace(
        aliases={"sdvx": {"s1": ["炸弹"]}}, entries={"sdvx": {}},
        add_alias=lambda g, a, sid: added.append(a),
        remove_alias=lambda g, a, sid: a == "炸弹"))
    p.games = types.SimpleNamespace(data=types.SimpleNamespace(_cache={}))
    p.cmd = types.SimpleNamespace(aliases=None, db=None)
    p.chu = types.SimpleNamespace(aliases=None)

    async def notify(umo, text, at=""):
        sent.append(text)
    p._notify_private = notify
    w = CoreWebUI(p)
    r = await w.alias_settings({"alias_vote_yes": 5, "alias_checks_per_hour": 0, "bogus": 1})
    assert r["settings"]["alias_vote_yes"] == 5 and p.alias_votes.need_yes == 5
    assert M.OtogeScore._alias_live_load(str(tmp_path))["alias_vote_yes"] == 5          # 存盘了，重载后还在
    with pytest.raises(ValueError):
        await w.alias_settings({"alias_vote_no": 0})
    p.alias_votes.propose(AV.Vote("g1", "sdvx", "jacket", "s2", "T", "新外号"))
    p.alias_votes.propose(AV.Vote("g1", "sdvx", "jacket", "s3", "T3", "第二个"))
    d = await w.aliases({})
    assert d["auto_provider"] == "ds_flash" and d["votes"][0]["alias"] == "新外号" and d["votes"][0]["queued"] == 1
    assert d["counts"]["sdvx"] == 1
    await w.alias_vote_end({"origin": "g1", "result": "pass"})
    assert added == ["新外号"] and "第二个" in sent[0]
    await w.alias_vote_end({"origin": "g1", "result": "cancel"})
    assert p.alias_votes.known_keys("sdvx", "jacket", "s3") == set()                    # 取消的以后还能再提
    assert (await w.alias_delete({"game": "sdvx", "ids": {"sdvxin": "s1"}, "alias": "炸弹"}))["ok"]
    with pytest.raises(ValueError):
        await w.alias_delete({"game": "sdvx", "ids": {"sdvxin": "s1"}, "alias": "没有"})


def test_hint_debounce():
    from tests.test_games import FakeData
    gc = GameCommands(FakeData(), rnd=random.Random(3))
    run(gc.handle("h1", Ctx(), "/猜曲绘 舞萌", command=True))
    s = gc.sessions["h1"]
    r1 = run(gc.handle("h1", Ctx(uid="1"), "提示", command=False))
    assert r1 is not None and s.stage == 1
    r2 = run(gc.handle("h1", Ctx(uid="2"), "提示", command=False))
    assert r2 is not None and not r2.texts and r2.image is None and s.stage == 1    # 3 秒内：不再加，也不回话
    s.data["last_hint"] -= 5
    assert run(gc.handle("h1", Ctx(uid="3"), "提示", command=False)) is not None and s.stage == 2


def test_match_version_and_filter():
    mai = [("UNiVERSE", ["UNiVERSE (宙)"]), ("UNiVERSE PLUS", ["UNiVERSE+ (星)"]), ("maimaiでらっくす", ["でらっくす (熊)"]),
           ("maimai", ["maimai (真)"])]
    chu = [("CHUNITHM AMAZON", []), ("CHUNITHM AMAZON PLUS", []), ("X-VERSE-X", []), ("X-VERSE", [])]
    assert G.match_version("universe", mai) == "UNiVERSE" and G.match_version("宙", mai) == "UNiVERSE"
    assert G.match_version("universe+", mai) == "UNiVERSE PLUS" and G.match_version("星", mai) == "UNiVERSE PLUS"
    assert G.match_version("dx", mai) == "maimaiでらっくす" and G.match_version("maimai", mai) == "maimai"
    assert G.match_version("amazon", chu) == "CHUNITHM AMAZON" and G.match_version("Amazon Plus", chu) == "CHUNITHM AMAZON PLUS"
    assert G.match_version("amazon+", chu) == "CHUNITHM AMAZON PLUS"
    assert G.match_version("xversex", chu) == "X-VERSE-X" and G.match_version("x-verse", chu) == "X-VERSE"
    assert G.match_version("好难", chu) is None

    class D(FakeData):
        def versions(self, game):
            return [("AMAZON", []), ("X-VERSE-X", [])]
    d = D()
    for i, s in enumerate(d.mai):
        s.version = "X-VERSE-X" if i % 2 else "AMAZON"
    gc = GameCommands(d, rnd=random.Random(5))
    r = run(gc.handle("v1", Ctx(), "/猜歌 舞萌 国际服 xversex", command=True))
    assert "开字母 · 舞萌 · 国际服 · X-VERSE-X · 随机" in r.texts[0]
    assert all(p.song.version == "X-VERSE-X" for p in gc.sessions["v1"].picks)
    r = run(gc.handle("v1", Ctx(), "结束", command=False))
    assert "（X-VERSE-X）" in r.texts[0]
    r = run(gc.handle("v2", Ctx(), "/猜歌 舞萌 什么鬼", command=True))
    assert "没看懂「什么鬼」" in r.texts[0] and "X-VERSE-X" in r.texts[0]


def test_parse_ask_reply_and_check():
    assert AV.parse_ask_reply("别名 救护车", 1) == (0, "救护车")
    assert AV.parse_ask_reply("外号：救护车", 1) == (0, "救护车")
    assert AV.parse_ask_reply("别名 1 救护车", 1) == (0, "救护车")
    assert AV.parse_ask_reply("别名 2hu", 1) == (0, "2hu")
    assert AV.parse_ask_reply("别名 2 阿列夫", 3) == (1, "阿列夫")
    assert AV.parse_ask_reply("别名 阿列夫", 3) == (-1, "阿列夫")                 # 几首又没写序号
    assert AV.parse_ask_reply("别名 5 阿列夫", 3) == (-1, "5 阿列夫")
    for t in ("救护车", "我觉得叫救护车", "y", "这个别名不错", "/查分 别名 xx"):
        assert AV.parse_ask_reply(t, 1) is None                                   # 不是「别名」开头一律不碰
    other = {G.norm("别的歌")}
    assert AV.check_alias("救护车", SONG, set(), other) == ""
    assert "直接猜中" in AV.check_alias("救车", SONG, set(), other)
    assert "别的歌" in AV.check_alias("别的歌", SONG, set(), other)
    assert "投过" in AV.check_alias("救护车", SONG, {G.norm("救护车")}, other)
    assert "聊天" in AV.check_alias("哈哈哈", SONG, set(), other)
    assert "太长" in AV.check_alias("这首歌我以前打过好多次但是记不住名字了啊啊啊", SONG, set(), other)
    assert AV.check_alias("？？", SONG, set(), other)


async def test_plugin_ask_when_llm_finds_nothing(tmp_path):
    M = _main()
    p = M.OtogeScore.__new__(M.OtogeScore)
    p.config = {}
    p.alias_votes = AV.AliasVotes(str(tmp_path), yes=2, no=2)
    p._alias_checks, p._tasks = {}, []
    sent, added = [], []
    p.charts = types.SimpleNamespace(src=types.SimpleNamespace(add_alias=lambda g, a, sid: added.append((g, a, sid))))
    other = G.Song("sdvx", "s9", "OTHER SONG", ["别的外号"], [])
    p.games = types.SimpleNamespace(data=types.SimpleNamespace(_cache={}, songs=lambda g: [other], chart_songs=lambda g: []))

    async def notify(umo, text, at=""):
        sent.append(text)
    p._notify_private = notify

    async def llm():
        async def call(system, text):
            return '[{"i": 1, "a": null, "c": 0.9}]'
        return call
    p._alias_llm_call = llm
    p._alias_live = {}
    p.ALIAS_BATCH_SECONDS = 0
    song = G.Song("sdvx", "s1", "SUPER AMBULANCE", [], [])
    s = types.SimpleNamespace(picks=[G.Pick(song)], started=time.time() - 60, kind="jacket")
    p.alias_votes.log("g", "1", "a", "安布兰斯")
    c = lambda u, n="": MCtx(uid=u, private=False, admin=False)  # noqa: E731
    p._alias_solved("g", s, 0, c("1"), "SUPER AMBULANCE")
    await p._tasks[0]
    assert len(sent) == 1 and "《SUPER AMBULANCE》" in sent[0] and "别名 外号" in sent[0]
    assert p._alias_vote("g", c("2"), "救护车") is None                         # 闲聊 / 普通猜歌不碰
    assert "直接猜中" in p._alias_vote("g", c("2"), "别名 super ambulance").texts[0]
    assert "别的歌" in p._alias_vote("g", c("2"), "别名 别的外号").texts[0]
    r = p._alias_vote("g", c("2"), "别名 救护车")
    assert "🗳" in r.texts[0] and "「救护车」= 《SUPER AMBULANCE》" in r.texts[0]
    assert "排上了" in p._alias_vote("g", c("3"), "别名 安布兰斯").texts[0]     # 模型说不是，群友提还是能投
    p._alias_vote("g", c("4"), "y")
    assert "投票通过" in p._alias_vote("g", c("5"), "y").texts[0] and added == [("sdvx", "救护车", "s1")]
    # 设了冷却：10 分钟内同一个群不再问（默认不冷却）
    p._alias_live = {"alias_ask_cooldown_minutes": 10}
    p.alias_votes.asks.clear(); p.alias_votes.queue.clear(); p.alias_votes.active.clear()  # noqa: E702
    p._tasks = []
    p._alias_solved("g", s, 0, c("1"), "SUPER AMBULANCE")
    await p._tasks[0]
    assert len(sent) == 1
    p.alias_votes.last_ask["g"] -= 601
    p._tasks = []
    p._alias_solved("g", s, 0, c("1"), "SUPER AMBULANCE")
    await p._tasks[0]
    assert len(sent) == 2
    # 关掉追问
    p._alias_live = {"alias_ask_enabled": False}
    p.alias_votes.asks.clear(); p.alias_votes.last_ask.clear()  # noqa: E702
    p._tasks = []
    p._alias_solved("g2", s, 0, c("1"), "SUPER AMBULANCE")
    for t in p._tasks:
        await t
    assert len(sent) == 2


def test_ask_multi_and_busy(tmp_path):
    av = AV.AliasVotes(str(tmp_path))
    a, b = G.Song("mai", "1", "AAA", ["a1"], []), G.Song("mai", "2", "BBB", [], [])
    text = av.open_ask("g", [("letters", a), ("letters", b)], {"mai": "舞萌"})
    assert "1. 《AAA》（舞萌） 已有：a1" in text and "2. 《BBB》" in text and "别名 序号 外号" in text and "还有别的外号" in text
    assert av.busy("g") and av.can_ask("g", 0) and not av.can_ask("g", 10)       # 默认不冷却
    c = G.Song("mai", "3", "CCC", [], [])
    more = av.open_ask("g", [("letters", b), ("letters", c)], {"mai": "舞萌"})   # 接着编号，BBB 不重复问
    assert more.startswith("🤔 还有这几首") and "3. 《CCC》" in more and "BBB" not in more and "别名 3 xxx" in more
    assert av.open_ask("g", [("letters", c)]) is None
    assert AV.parse_ask_reply("别名 3 西西西", len(av.asks["g"].items)) == (2, "西西西")
    av.asks["g"].started -= AV.ASK_SECONDS + 1
    assert av.ask_current("g") is None and av.can_ask("g", 0)
    one = av.open_ask("g", [("letters", c)])
    assert "别名 外号" in one and "序号" not in one


async def test_ask_skips_songs_with_many_aliases(tmp_path):
    M = _main()
    p = M.OtogeScore.__new__(M.OtogeScore)
    p.config, p._alias_live = {}, {}
    p.alias_votes = AV.AliasVotes(str(tmp_path))
    sent = []

    async def notify(umo, text, at=""):
        sent.append(text)
    p._notify_private = notify
    many = G.Song("mai", "1", "AAA", ["a1", "a2", "a3", "a4", "a5"], [])
    few = G.Song("mai", "2", "BBB", ["b1", "b2", "b3", "b4"], [])
    assert not p._ask_worth(many) and p._ask_worth(few)
    await p._alias_ask("g", [("letters", many)])
    assert sent == []
    await p._alias_ask("g", [("letters", many), ("letters", few)])
    assert len(sent) == 1 and "BBB" in sent[0] and "AAA" not in sent[0]
    p._alias_live = {"alias_ask_max_known": 0}
    assert p._ask_worth(many)


def test_alias_solve_hook():
    gc = GameCommands(FakeData(), rnd=random.Random(7))
    by_title, by_alias = [], []
    gc.on_title_solve = lambda o, s, i, c, t: by_title.append(i)
    gc.on_alias_solve = lambda o, s, i, c, t: by_alias.append((i, t))
    run(gc.handle("g1", Ctx(), "/猜歌 舞萌 13以上", command=True))
    s = gc.sessions["g1"]
    a = s.picks[1].song.aliases[0]
    run(gc.handle("g1", Ctx(), a, command=False))
    assert by_alias == [(1, a)] and by_title == []


async def test_plugin_asks_after_alias_solve(tmp_path):
    M = _main()
    p = M.OtogeScore.__new__(M.OtogeScore)
    p.config, p._alias_live = {}, {}
    p.alias_votes = AV.AliasVotes(str(tmp_path))
    p._alias_checks, p._tasks = {}, []
    p.ALIAS_BATCH_SECONDS = 0
    sent, calls = [], []

    async def notify(umo, text, at=""):
        sent.append(text)
    p._notify_private = notify

    async def llm():
        calls.append(1)
    p._alias_llm_call = llm
    c = MCtx(uid="1", private=False, admin=False)
    few = G.Song("mai", "2", "BBB", ["b1"], [])
    many = G.Song("mai", "3", "CCC", ["c1", "c2", "c3", "c4", "c5"], [])
    s = types.SimpleNamespace(picks=[G.Pick(many), G.Pick(few)], started=time.time() - 60, kind="letters")
    p._alias_solved_by_alias("g", s, 0, c, "c1")
    assert p._tasks == []                                         # 外号够多：不问
    p._alias_solved_by_alias("g", s, 1, c, "b1")
    await p._tasks[0]
    assert len(sent) == 1 and "《BBB》" in sent[0] and "还有别的叫法" in sent[0] and calls == []   # 不问模型
    assert "直接猜中" in p._alias_vote("g", c, "别名 b1").texts[0]          # 报的是已有的：不投


def test_which_song_hint_lists_songs():
    from types import SimpleNamespace as NS
    from games import aliasvote as AV2
    items = [("guess", NS(title="VICTIM")), ("guess", NS(title="Aleph-0")), ("guess", NS(title="Xevel"))]
    t = AV2.which_song_hint(items, "维克")
    assert "1. 《VICTIM》" in t and "3. 《Xevel》" in t and "「维克」要加给哪首" in t and "别名 1 维克" in t
    assert AV2.parse_ask_reply("别名 维克", 3) == (-1, "维克")
    assert "别名 序号 外号" in AV2.which_song_hint(items, "")
