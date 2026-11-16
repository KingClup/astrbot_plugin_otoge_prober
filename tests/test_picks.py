"""「可能是这几首」→ 回序号：PickBox + 谱面 / 舞萌 / 中二的候选都带上可以直接跑的那一项。"""
from __future__ import annotations

import copy

from chart.commands import ChartCommands
from chart.sdvxin import Entry, SdvxIn
from core.picks import PickBox
from mai.bot.commands import Ctx
from test_chart import sdvxin_transport

CTX = Ctx(uid="1", private=True, admin=False)


def test_pickbox_ttl_and_matching():
    t = [100.0]
    box = PickBox(ttl=15, clock=lambda: t[0])
    k = ("grp", "42")
    assert box.arm(k, []) == ""
    hint = box.arm(k, ["a", "b", "c"])
    assert "15 秒内" in hint and "1～3" in hint
    assert box.take(("grp", "43"), "1") is None          # 别人回的不算
    assert box.take(k, "好的") is None                     # 普通聊天不吃
    assert box.take(k, "4") is None                        # 超出范围
    assert box.take(k, " 第2个 ") == "b"
    assert box.take(k, "1") is None                        # 用过就没了
    box.arm(k, ["x", "y"])
    t[0] += 15.5
    assert box.take(k, "1") is None                        # 过了 15 秒


async def test_sdvx_ambiguous_then_pick(tmp_path):
    src = SdvxIn(str(tmp_path / "sdvxin"), transport=sdvxin_transport([]))
    c = ChartCommands(src)
    await src.ensure("sdvx")
    v = src.entries["sdvx"]["07112"]
    raw = copy.deepcopy(v.raw)
    raw.update(id="07998", title="VICTIMA", artist="Someone Else", title_search_abc="VICTIMA", title_search_hira="")
    src.entries["sdvx"]["07998"] = Entry("sdvx", "07998", "VICTIMA", "Someone Else", raw)
    src._search.pop("sdvx", None)
    r = await c.handle(CTX, "谱面 victi", "sdvx")
    assert len(r.picks) == 2                     # 两首分不清 → 列出来，可以回序号
    if True:
        assert "可能是这几首" in r.texts[0] and "换个更完整的名字" not in r.texts[0]
        titles = [ln.split(". ", 1)[1] for ln in r.texts[0].splitlines()[1:]]
        i = next(n for n, t in enumerate(titles) if t.startswith("VICTIMA"))
        r2 = await r.picks[i]()
        assert any("VICTIMA" in t for t in r2.texts)
    # 照着列表抄回来「歌名（曲师）」也能查
    r3 = await c.handle(CTX, "谱面 VICTIMA（Someone Else）", "sdvx")
    assert any("VICTIMA / Someone Else" in t for t in r3.texts)
    r4 = await c.handle(CTX, "谱面 VICTIM（U-ske feat. 駄々子）", "sdvx")
    assert any(t.startswith("VICTIM /") for t in r4.texts)


def test_fold_curly_apostrophe():
    from mai.data.fuzzy import fold
    assert fold("Bl∞min’") == fold("Bl∞min'")
