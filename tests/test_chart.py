"""sdvx.in chart lookup (CHUNITHM / SDVX / PJSK) with a mock sdvx.in built from real (trimmed) responses."""
from __future__ import annotations

import io
import json
import os

import httpx
import pytest
from PIL import Image

from chart.commands import ChartCommands, split_diff
from chart.sdvxin import SdvxIn, compose
from chart.sdvx_draw import render
from mai.bot.commands import Ctx

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f)


def _img(color, fmt="WEBP", size=(400, 200)):
    im = Image.new("RGBA", size, color)
    b = io.BytesIO()
    im.save(b, fmt)
    return b.getvalue()


def sdvxin_transport(calls: list):
    files = {
        "/chunithm/_/json/songs01.json": json.dumps(_load("sdvxin_chu_songs01.json")).encode(),
        "/sdvx/_/json/songs01.json": json.dumps(_load("sdvxin_sdvx_songs.json")).encode(),
        "/prsk/_/json/songs0001.json": json.dumps(_load("sdvxin_prsk_songs.json")).encode(),
        "/sdvx/07/07112m.json": json.dumps(_load("sdvxin_07112m.json")).encode(),
        "/chunithm/01/bg/01189bg.webp": _img((0, 0, 60, 255)),
        "/chunithm/01/obj/data01189mst.webp": _img((255, 0, 0, 128)),
        "/chunithm/01/bg/01189bar.webp": _img((0, 0, 0, 0)),
        "/prsk/bg/0737bg.webp": _img((10, 10, 10, 255)),
        "/prsk/obj/data0737mst.webp": _img((0, 255, 0, 200)),
        "/01/bg/01165bg.png": _img((0, 0, 0, 255), "PNG"),
        "/01/obj/data01165m.png": _img((255, 255, 255, 255), "PNG"),
        "/chunithm/_/json/songs_we.json": json.dumps(_load("sdvxin_chu_we.json")).encode(),
        "/chunithm/end/bg/311bg.webp": _img((0, 0, 0, 255)),
        "/chunithm/end/obj/data311end.webp": _img((200, 0, 200, 255)),
        "/chunithm/end/obj/data304end.webp": _img((0, 200, 200, 255)),
        "/chunithm/end/obj/data118end.webp": _img((200, 200, 0, 255)),
    }

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        assert req.headers.get("referer") == "https://sdvx.in/"
        body = files.get(req.url.path)
        if body is None:
            return httpx.Response(302, headers={"location": "https://sdvx.in/sdvx.php"})
        ct = "application/json" if req.url.path.endswith(".json") else "image/webp"
        return httpx.Response(200, content=body, headers={"content-type": ct})
    return httpx.MockTransport(handler)


@pytest.fixture()
def cmd(tmp_path):
    calls: list = []
    src = SdvxIn(str(tmp_path / "sdvxin"), transport=sdvxin_transport(calls))
    return ChartCommands(src), calls


CTX = Ctx(uid="1", private=True, admin=False)


def test_split_diff():
    assert split_diff("chu", ["a0", "紫"]) == ("mst", ["a0"])
    assert split_diff("pjsk", ["tell", "your", "world", "apd"]) == ("apd", ["tell", "your", "world"])
    assert split_diff("pjsk", ["master"]) == (None, ["master"])          # a lone word stays the song name
    assert split_diff("sdvx", ["VICTIM", "hvn"]) == ("mxm", ["VICTIM"])


async def test_chunithm_chart_image_and_info(cmd):
    c, calls = cmd
    r = await c.handle(CTX, "Contrapasso", "chu")
    assert r.image and Image.open(io.BytesIO(r.image)).size == (400, 200)
    t = "\n".join(r.texts)
    assert "MASTER 15" in t and "BPM 243" in t and "FLICK 156" in t and "譜面ボーイズ" in t
    assert "https://youtu.be/hWgq3N6okKA" in t and "https://youtu.be/u4oGmteWapU" in t
    assert "viewer.php?id=01189&diff=mst" in t
    # second time comes from the picture cache: no new image requests
    n = len([p for p in calls if "/obj/" in p])
    await c.handle(CTX, "Contrapasso", "chu")
    assert len([p for p in calls if "/obj/" in p]) == n


async def test_chunithm_diff_without_view(cmd):
    c, _ = cmd
    r = await c.handle(CTX, "Contrapasso 绿", "chu")
    t = "\n".join(r.texts)
    assert r.image is None and "没有这个难度的谱面图" in t and "MASTER" in t


async def test_sdvx_json_chart_is_drawn(cmd):
    c, calls = cmd
    r = await c.handle(CTX, "谱面 VICTIM", "sdvx")
    assert r.image
    im = Image.open(io.BytesIO(r.image))
    assert im.width > 1000                                   # many columns
    t = "\n".join(r.texts)
    assert "MAXIMUM 18.3" in t and "CHIP" in t and "viewer/?id=07112m" in t
    assert "/sdvx/07/07112m.json" in calls


async def test_sdvx_old_png_chart_and_4th_name(cmd):
    c, _ = cmd
    r = await c.handle(CTX, "孤独の番人", "sdvx")
    assert r.image
    assert "HEAVENLY 18.4" in "\n".join(r.texts)


async def test_pjsk_by_reading_and_default_master(cmd):
    c, _ = cmd
    r = await c.handle(CTX, "ぷれでたー", "pjsk")
    t = "\n".join(r.texts)
    assert "プレデター" in t and "MASTER 30" in t and "1029 notes" in t
    r = await c.handle(CTX, "ULTIM@TE", "pjsk")
    assert r.image is not None or "谱面图没取到" in "\n".join(r.texts)


async def test_any_game_and_aliases(cmd):
    c, _ = cmd
    r = await c.handle(CTX, "VICTIM", "chart")
    assert "SOUND VOLTEX" in r.texts[0]
    r = await c.handle(CTX, "加别名 受害者 VICTIM", "sdvx")
    assert "VICTIM" in r.texts[0]
    r = await c.handle(CTX, "受害者", "sdvx")
    assert any("VICTIM" in t for t in r.texts)
    r = await c.handle(CTX, "b50", "sdvx")
    assert "只有谱面查询" in r.texts[0]


async def test_offline_list_is_reused(tmp_path):
    calls: list = []
    src = SdvxIn(str(tmp_path / "s"), transport=sdvxin_transport(calls))
    assert await src.ensure("pjsk") == 3
    dead = SdvxIn(str(tmp_path / "s"), transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert await dead.ensure("pjsk", force=True) == 3      # cached list survives a dead sdvx.in


def test_compose_and_render_shapes():
    out = compose(_img((0, 0, 0, 255), "PNG", (50, 40)), _img((255, 0, 0, 255), "PNG", (30, 20)), None)
    assert out.size == (50, 40) and out.getpixel((5, 5)) == (255, 0, 0)
    im = render({"totalPulses": 960 * 8, "wraps": [0, 3840], "notes": [{"type": "BT", "lane": "A", "pulse": 0}],
                 "holds": [{"type": "FX_HOLD", "lane": "L", "pulse": 3000, "pulseEnd": 5000}],
                 "lasers": {"left": [[0, [[0, 0.0], [960, [0.0, 1.0]], [1920, 1.0]], 1]], "right": []},
                 "bpm": [{"y": 0, "v": 180}]})
    assert im.width > 200 and im.height > 500


async def test_chunithm_constants_skip_worlds_end_twin(cmd):
    from types import SimpleNamespace as NS

    from chuni.models import Difficulty
    c, _ = cmd
    normal = NS(id=2338, title="Contrapasso -inferno-", charts={Difficulty.MASTER: 1})
    we = NS(id=8123, title="Contrapasso -inferno-", charts={})

    class DB:
        def search_ranked(self, q, n):
            return [NS(item=we, score=100), NS(item=normal, score=100)]

    def consts_for(song):
        return {Difficulty.MASTER: {"intl": 15.0, "jp": 15.2}} if song is normal else {}
    c.chu = NS(svc=NS(songdb=DB(), consts_for=consts_for))
    await c.src.ensure("chu")
    e = c.src.entries["chu"]["01189"]
    assert c._chu_consts(e, "mst") == {"intl": 15.0, "jp": 15.2}
    assert "国际服 15.0 / 日服 15.2" in "\n".join(c._info(e, "mst"))



async def test_worlds_end(cmd):
    c, calls = cmd
    r = await c.handle(CTX, "Hainuwele we", "chu")
    t = "\n".join(r.texts)
    assert r.image and "WORLD'S END 狂☆☆☆☆" in t and "谱师 Ushumgallu" in t and "diff=we" in t
    assert "/chunithm/end/obj/data311end.webp" in calls
    r = await c.handle(CTX, "並行天涯 we", "chu")          # "_狂5": listed but no chart picture yet
    assert r.image is None and "没有这个难度的谱面图" in "\n".join(r.texts)
    r = await c.handle(CTX, "volcanic we", "chu")          # two WORLD'S END charts share the title
    t = "\n".join(r.texts)
    assert r.image and "有 2 张 WORLD'S END" in t
    r = await c.handle(CTX, "volcanic we 避", "chu")
    assert "避☆☆☆☆" in "\n".join(r.texts) and "有 2 张" not in "\n".join(r.texts)
    r = await c.handle(CTX, "Hainuwele we", "chart")       # /谱面 … we
    assert "狂☆☆☆☆" in "\n".join(r.texts)
