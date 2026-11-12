"""v2.0.1：没给凭据的「绑定」和查分时的「还没绑定」都引到网页绑定。"""
from __future__ import annotations

import importlib
import os
import sys

import pytest

from mai.bot.commands import Ctx, Reply


def _main():
    pytest.importorskip("astrbot")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.dirname(root) not in sys.path:
        sys.path.insert(0, os.path.dirname(root))
    return importlib.import_module(os.path.basename(root) + ".main")


@pytest.mark.parametrize("game,rest,web", [
    ("mai", "", True), ("mai", "国服", True), ("mai", "落雪", True), ("mai", "日服", True),
    ("mai", "国服 someone", False), ("mai", "落雪 abcdefg", False), ("mai", "aqua", True), ("mai", "aqua kc", False),
    ("chu", "国服", True), ("chu", "国际服", True), ("chu", "国服 someone", False), ("chu", "水鱼", True),
    ("geki", "", True), ("geki", "aqua", True), ("geki", "aqua kc", False),
])
def test_bind_without_creds(game, rest, web):
    assert _main().bind_without_creds(game, rest) is web


def _plugin(M, ready=True, group_link=True):
    p = M.OtogeScore.__new__(M.OtogeScore)
    p.bindweb_ready = lambda: ready

    async def web(event, ctx, game=""):
        return Reply(at=None if ctx.private else ctx.uid).say(
            "你的绑定链接（10 分钟内有效）：\nhttps://bind.example/#t=x" if group_link else "私聊我发「/网页绑定」拿链接～")
    p._web_bind_reply = web
    return p


async def test_unbound_reply_becomes_web_link():
    M = _main()
    p = _plugin(M)
    ctx = Ctx(uid="1", private=False, admin=False)
    r = Reply().say("按 QQ 在落雪没找到你（404）。\n你还没绑定中二国服：发「/网页绑定」，或「/chu 绑定 国服 <水鱼用户名>」")
    w = await p._unbound_to_web(None, ctx, "chu", r)
    text = "\n".join(w.texts)
    assert "按 QQ 在落雪没找到你" in text and "你还没绑定中二国服，点链接在网页上绑定" in text
    assert "https://bind.example/#t=x" in text and w.at == "1"
    assert "/chu 绑定 国服" not in text


async def test_unbound_reply_untouched_when_not_ready_or_other():
    M = _main()
    ctx = Ctx(uid="1", private=True, admin=False)
    r = Reply().say("你还没绑定舞萌国服，发「/mai 绑定 国服 <水鱼用户名>」")
    assert await _plugin(M, ready=False)._unbound_to_web(None, ctx, "mai", r) is r
    assert await _plugin(M, group_link=False)._unbound_to_web(None, ctx, "mai", r) is r
    ok = Reply().say("B50 ……")
    assert await _plugin(M)._unbound_to_web(None, ctx, "mai", ok) is ok
