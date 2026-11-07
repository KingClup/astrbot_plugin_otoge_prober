"""sdvx.in ONGEKI chart lookup: song list from the genre pages + per-song scripts (no JSON list on sdvx.in)."""
from __future__ import annotations

import io
import json
import os

import httpx
from PIL import Image

from chart.commands import ChartCommands, hardest
from chart.sdvxin import SdvxIn, merge_geki, parse_geki_js
from mai.bot.commands import Ctx

CTX = Ctx(uid="1", private=True, admin=False)

WHAT_COLOR = (
    'var TITLE01053="<div class=f1>What color...</div>";\r\n'
    'var ARTIST01053="<div class=b2>　/ 曲：NAOKI／歌：早乙女 彩華(CV：中島 唯)</div>";\r\n'
    'var BPM01053="<table><tr><td class=b2>BPM<td width=2><td class=f1>158</table>";\r\n'
    'var CR01053M="<table><tr><td class=ef>NOTES DESIGNER / 譜面-100号</table>";\r\n'
    'var LV01053B="<table><tr><td><href=/ongeki/01/01053bsc.htm><img src=/ongeki/files/lv/bsc_2.png></a></table>";\r\n'
    'var LV01053E="<table><tr><td><href=/ongeki/01/01053exp.htm><img src=/ongeki/files/lv/exp_8+.png></a></table>";\r\n'
    'var LV01053M="<table><tr><td><a href=/ongeki/01/01053mst.htm><img src=/ongeki/files/lv/mst12+.png></a></table>";\r\n'
    'var CH01053M="<table><tr><td class=b2>CHAIN<td width=2><td class=mst1>904</table>";\r\n'
    'var BL01053M="<table><tr><td class=y2>BELL<td width=2><td class=y1>87</table>";\r\n'
    'var MV01053M="<table><tr><td class=c><div class=f2>譜面確認</div><br><a href=https://www.youtube.com/watch?v=kOGuVsn-FQ0 target=_blank></a></table>";\r\n'
)
WHAT_COLOR_LUNA = (
    'var TITLE01053="<div class=f1>What color...</div>";\r\n'
    'var LV01053L="<table><tr><td><a href=/ongeki/luna/01053luna.htm><img src=/ongeki/files/lv/luna14+.png></a></table>";\r\n'
)
HYPERNAID = (
    'var TITLE05106="<div class=f1>Hypernaid &amp; D&#201;</div>";\r\n'
    'var ARTIST05106="<div class=b2>　/ KATOMORI</div>";\r\n'
    'var LV05106L="<table><tr><td><a href=/ongeki/luna/05106luna.htm><img src=/ongeki/files/lv/luna0.png></a></table>";\r\n'
)


def _img(color, size=(300, 200)):
    b = io.BytesIO()
    Image.new("RGBA", size, color).save(b, "PNG")
    return b.getvalue()


def transport(calls):
    files = {
        "/ongeki/sort/pops.htm": b'<script src="/ongeki/01/js/01053sort.js"></script><script>SORT01053();</script>',
        "/ongeki/sort/lunatic.htm": b'<script src="/ongeki/luna/js/01053luna.js"></script>'
                                    b'<script src="/ongeki/luna/js/05106luna.js"></script>',
        "/ongeki/01/js/01053sort.js": WHAT_COLOR.encode(),
        "/ongeki/luna/js/01053luna.js": WHAT_COLOR_LUNA.encode(),
        "/ongeki/luna/js/05106luna.js": HYPERNAID.encode(),
        "/ongeki/01/bg/01053bg.png": _img((0, 0, 50, 255)),
        "/ongeki/01/obj/data01053mst.png": _img((255, 0, 255, 200)),
        "/ongeki/01/bg/01053bar.png": _img((0, 0, 0, 0)),
        "/ongeki/01/jacket/01053.png": _img((9, 9, 9, 255), (100, 100)),
        "/ongeki/05/bg/05106bg.png": _img((0, 0, 0, 255)),
        "/ongeki/luna/obj/data05106luna.png": _img((255, 255, 255, 255)),
    }

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        body = files.get(req.url.path)
        if body is None:
            return httpx.Response(302, headers={"location": "https://sdvx.in/"})
        return httpx.Response(200, content=body)
    return httpx.MockTransport(handler)


def test_parse_script():
    d = parse_geki_js(WHAT_COLOR, "01053")
    assert d["title"] == "What color..."
    assert d["artist"].startswith("曲：NAOKI")
    assert d["levels"] == {"bsc": "_2", "exp": "_8+", "mst": "12+"}       # only MASTER has a chart page
    assert d["youtube"] == {"mst": "kOGuVsn-FQ0"}
    assert d["designer"] == {"mst": "譜面-100号"} and d["chain"] == {"mst": "904"} and d["bell"] == {"mst": "87"}
    assert d["bpm"] == "158"
    h = parse_geki_js(HYPERNAID, "05106")
    assert h["title"] == "Hypernaid & DÉ" and h["levels"] == {"lun": "?"}
    m = merge_geki([d, parse_geki_js(WHAT_COLOR_LUNA, "01053")])
    assert len(m) == 1 and m[0]["levels"]["lun"] == "14+" and m[0]["levels"]["mst"] == "12+"


async def test_geki_list_chart_and_cache(tmp_path):
    calls: list = []
    src = SdvxIn(str(tmp_path / "s"), transport=transport(calls))
    cmd = ChartCommands(src)
    assert await src.ensure("geki") == 2
    e = src.entries["geki"]["01053"]
    assert hardest(e, "geki") == "mst"                       # LUNATIC is not "the hardest" by default
    assert hardest(src.entries["geki"]["05106"], "geki") == "lun"   # … unless it is the only chart
    r = await cmd.handle(CTX, "谱面 what color", "geki")
    assert r.image and "[オンゲキ MASTER 12+]" in r.texts[0] and "CHAIN 904 / BELL 87" in r.texts[0]
    assert "https://sdvx.in/ongeki/01/01053mst.htm" in r.texts[0] and "youtu.be/kOGuVsn-FQ0" in r.texts[0]
    r = await cmd.handle(CTX, "what color lun", "geki")
    assert "LUNATIC 14+" in r.texts[0] and "/ongeki/luna/01053luna.htm" in r.texts[0]
    assert r.image is None and "谱面图没取到" in r.texts[0]      # (no LUNATIC layer in the fake site)
    r = await cmd.handle(CTX, "what color 红", "geki")
    assert "没有这个难度的谱面图" in r.texts[0]
    r = await cmd.handle(CTX, "hypernaid", "geki")
    assert r.image and "LUNATIC ?" in r.texts[0]
    # a second refresh only reads the genre pages (song scripts are kept)
    n = len(calls)
    assert await src.ensure("geki", force=False) == 2 and len(calls) == n          # fresh: nothing fetched
    os.utime(os.path.join(src.dir, "songs_geki.json"), (0, 0))
    src.entries["geki"] = {}
    await src.ensure("geki")
    new = calls[n:]
    assert all(p.startswith("/ongeki/sort/") for p in new) and new
    saved = json.load(open(os.path.join(src.dir, "songs_geki_parts.json"), encoding="utf-8"))
    assert set(saved) == {"01/01053sort", "luna/01053luna", "luna/05106luna"}


async def test_any_game_finds_ongeki(tmp_path):
    src = SdvxIn(str(tmp_path / "s"), transport=transport([]))
    r = await ChartCommands(src).handle(CTX, "hypernaid", "chart")
    assert "按 オンゲキ 找到的" in r.texts[0]


async def test_geki_jackets(tmp_path):
    calls: list = []
    src = SdvxIn(str(tmp_path / "s"), transport=transport(calls))
    assert await src.geki_jackets(["What color..."]) == {}          # list not loaded yet: no network
    await src.ensure("geki")
    got = await src.geki_jackets(["What color...", "Hypernaid & DÉ", "nope"])
    assert list(got) == ["What color..."] and os.path.exists(got["What color..."])
    n = len(calls)
    assert list(await src.geki_jackets(["What color..."])) == ["What color..."] and len(calls) == n   # cached
