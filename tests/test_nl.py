"""自然语言意图：规则路径（不调大模型）的各种问法。"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import nl as NL  # noqa: E402

CASES = [
    ("我有抑郁症什么歌", "song", "我有抑郁症", False), ("我有抑郁症是什么歌", "song", "我有抑郁症", False),
    ("抑郁症是什么歌", "song", "抑郁症", True), ("反叛是什么歌", "song", "反叛", True),
    ("6A景区是啥歌", "song", "6A景区", True), ("潘是哪首", "song", "潘", True), ("什么是潘", "song", "潘", True),
    ("救护车什么歌", "song", "救护车", True), ("我在听什么歌", "song", None, False),
    ("你唱的是什么歌", "song", None, False), ("大家都在打什么歌", "song", None, False),
    ("最近推荐什么歌", "song", None, False),
    ("帮我看下舞萌b50", "b50", None, None), ("中二b30日服", "b50", None, None), ("舞萌b50", "b50", None, None),
    ("中二日服b50文字版", "b50_text", None, None),
    ("我b50好低啊", "none", None, None), ("这歌好难", "none", None, None), ("今天吃什么", "none", None, None),
    ("你好", "none", None, None), ("我想打中二", "none", None, None), ("arc什么歌最难", "none", None, None),
    ("我绑定好了", "none", None, None), ("绑定了吗", "none", None, None),
    ("查一下中二 Aleph-0 的成绩", "song", "Aleph-0", None), ("舞萌14.9有哪些歌", "ds", None, None),
    ("中二最近打了啥", "recent", None, None), ("舞萌怎么绑定", "bind", None, None),
    ("查下我的舞萌rating", "profile", None, None),
]


@pytest.mark.parametrize("text,action,query,explicit", CASES)
def test_rules(text, action, query, explicit):
    it = asyncio.new_event_loop().run_until_complete(NL.classify(text, None))
    assert it.action == action
    if query is not None:
        assert it.query == query
    if explicit is not None:
        assert it.explicit == explicit


def test_server_detected():
    it = asyncio.new_event_loop().run_until_complete(NL.classify("中二b30日服", None))
    assert it.game == "chu" and it.server == "jp"


@pytest.mark.parametrize("text,game,server", [
    ("国服中二理论ra", "chu", "cn"), ("舞萌理论值多少", "mai", ""), ("理论rating是多少", "unknown", ""),
])
def test_theory_rules(text, game, server):
    it = asyncio.new_event_loop().run_until_complete(NL.classify(text, None))
    assert (it.action, it.game, it.server) == ("theory", game, server)
    assert NL.to_command(it) == ("理论 " + {"cn": "国服"}.get(server, "")).strip()


def test_addressed_llm_not_vetoed():
    async def llm(system, text):
        return '{"game":"chu","action":"theory","query":"","server":"cn"}'
    run = asyncio.new_event_loop().run_until_complete
    # 「中二国服满分ra能有几」：没有请求词表里的词，但 @ 了机器人、大模型判成理论值 → 照办
    assert run(NL.classify("中二国服满分ra能有几", llm, addressed=True)).action == "theory"
    assert run(NL.classify("中二国服满分ra能有几", llm, addressed=False)).action == "none"

    async def chat(system, text):
        return '{"game":"mai","action":"none","query":"","server":""}'
    assert run(NL.classify("我b50好低啊", chat, addressed=True)).action == "none"


def test_rules_first_skips_llm():
    calls = []

    async def llm(system, text):
        calls.append(text)
        return '{"game":"chu","action":"theory","query":"","server":"cn"}'
    run = asyncio.new_event_loop().run_until_complete
    NL._LLM_CACHE.clear()
    # 规则拿得准：不问模型
    assert run(NL.classify("舞萌b50", llm, addressed=True)).action == "b50"
    assert run(NL.classify("反叛是什么歌", llm, addressed=True)).action == "song"
    assert run(NL.classify("帮我查一下 sdvx 成绩", llm, addressed=True)).action == "none"
    # 既没请求词也不像提问：当闲聊，不问模型
    assert run(NL.classify("今天去打中二了好累", llm, addressed=True)).action == "none"
    assert calls == []
    # 规则拿不准但像在问 → 问一次，第二次走缓存
    assert run(NL.classify("中二国服满分ra能有几", llm, addressed=True)).action == "theory"
    assert run(NL.classify("中二国服满分ra能有几", llm, addressed=True)).action == "theory"
    assert calls == ["中二国服满分ra能有几"]
    # 关掉 rules_first 时行为和以前一样：先问模型
    run(NL.classify("舞萌b50", llm, addressed=True, rules_first=False))
    assert calls[-1] == "舞萌b50"
