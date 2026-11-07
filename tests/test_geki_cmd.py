"""/geki commands on the shared private-server hub (AquaDX via a fake network)."""
from __future__ import annotations

import json

import httpx

from core import privsrv as P
from core.route import route
from mai.bot.commands import Ctx
from ongeki.commands import GekiCommands
from test_ongeki_core import D, _all_music, _lamp_rows

SUMMARY = json.loads((D / "aqua_ongeki_summary.json").read_text(encoding="utf-8"))
CTX = Ctx(uid="42", private=False, admin=False)


def hub(tmp_path, calls=None):
    def handler(req: httpx.Request):
        if calls is not None:
            calls.append((req.method, str(req.url)))
        p = req.url.path
        user = req.url.params.get("username")
        if p.endswith("/card/user-games"):
            return httpx.Response(200 if user == "playera" else 404, json={})
        if p.endswith("/ongeki/user-summary"):
            return httpx.Response(200, json=SUMMARY) if user == "playera" else httpx.Response(404)
        if p.endswith("/ongeki/user-music-from-list"):
            return httpx.Response(200, json=_lamp_rows())
        if p == "/d/ongeki/00/all-music.json":
            return httpx.Response(200, json=_all_music())
        return httpx.Response(404)
    return P.Hub(str(tmp_path), transport=httpx.MockTransport(handler))


async def test_geki_bind_and_b50(tmp_path):
    calls: list = []
    g = GekiCommands(hub(tmp_path, calls))
    r = await g.handle(CTX, "b50")
    assert "还没绑定私服" in r.texts[0]
    r = await g.handle(CTX, "绑定 aqua nobody")
    assert "找不到用户" in r.texts[0]
    r = await g.handle(CTX, "绑定 playera")                    # no server word = AquaDX
    assert "AquaDX 绑定成功：playera" in r.texts[0]
    r = await g.handle(CTX, "b50")
    assert r.image and r.image[:2] == b"\xff\xd8" and not r.texts          # picture; calc == shown → no note
    r = await g.handle(CTX, "b50 文字")
    t = r.texts[0]
    assert t.startswith("音击 · AquaDX · Re:Fresh") and "Rating 21.202" in t and "/geki b50 文字 全" in t
    r = await g.handle(CTX, "b50 文字 全")
    assert len(r.texts[0].splitlines()) > len(t.splitlines()) + 30
    assert (await g.handle(CTX, "全")).texts                                  # 「/geki 全」= full text
    assert sum(1 for m, u in calls if u.endswith("all-music.json")) == 1      # cached for a day


async def test_geki_other_servers(tmp_path):
    h = hub(tmp_path)
    g = GekiCommands(h)
    h.bindings.set("42", "munet", "someone")
    assert "HTTP 418" in (await g.handle(CTX, "b50")).texts[0]
    r = await g.handle(CTX, "绑定 rin x y")
    assert "RinNET 的音击还查不了" in r.texts[0]
    assert "/geki b50" in (await g.handle(CTX, "")).texts[0]


def test_route_geki_words():
    assert route("/音击 b50").game == "geki"
    assert route("/ongeki 谱面 Demonia").argline == "谱面 Demonia"
    assert route("/gekib50").game == "geki"
    assert route("音击 b50").how == "plain"
