"""共享外号库：清洗、汇总点的收录规则、上报 / 下载往返。"""
import asyncio
import json

import pytest

from core import aliasshare as AS
from core import aliaslib as AL


def item(a="救车", g="mai", sp="mai", sid=11475, t="SUPER AMBULANCE"):
    return {"g": g, "sp": sp, "id": sid, "t": t, "a": a}


def test_clean_alias_rejects_junk():
    assert AS.clean_alias("  救  车 ") == "救 车"
    for bad in ("", "1234", "x" * 25, "看 http://a.b", "加群@我", "a\nb", "foo.com", None, 5):
        assert AS.clean_alias(bad) is None


def test_clean_item_spaces_and_ids():
    assert AS.clean_item(item())["id"] == 11475
    assert AS.clean_item(["sdvx", "sdvxin", "07083", "Solitary Poison", "孤毒"])["id"] == "07083"
    assert AS.clean_item(item(g="chu")) is None            # 舞萌编号只能配舞萌
    assert AS.clean_item(item(sid="abc")) is None
    assert AS.clean_item(item(a="SUPER AMBULANCE")) is None  # 外号就是原名
    assert AS.clean_item(item(g="arcaea")) is None
    assert AS.clean_item("x") is None


def test_hub_needs_two_sources(tmp_path):
    hub = AS.Hub(str(tmp_path))
    r = hub.submit("a" * 32, "1.1.1.1", [item()])
    assert r["new"] == 1 and hub.count() == 0 and len(hub.pending()) == 1
    hub.submit("b" * 32, "1.1.1.1", [item()])              # 另一个 bot 但同一个 IP：不算第二个来源
    assert hub.count() == 0
    hub.submit("c" * 32, "2.2.2.2", [item(a="救 车")])      # 空格、大小写不同算同一条
    assert hub.count() == 1 and not hub.pending()
    assert hub.pack()["items"] == [["mai", "mai", 11475, "SUPER AMBULANCE", "救车"]]


def test_hub_trusted_block_and_reload(tmp_path):
    hub = AS.Hub(str(tmp_path))
    hub.submit("a" * 32, "local", [item(), item(a="千夏救护车")], trusted=True)
    assert hub.count() == 2
    assert hub.mark(hub.find("救车"), "block") == 1
    hub.submit("b" * 32, "9.9.9.9", [item()])
    hub.submit("c" * 32, "8.8.8.8", [item()])
    hub.submit("a" * 32, "local", [item()], trusted=True)   # 删掉的再报、主人自己再报都不回来
    assert hub.count() == 1
    again = AS.Hub(str(tmp_path))
    assert again.count() == 1 and again.stats()["blocked"] == 1
    raw = json.loads((tmp_path / "hub.json").read_text("utf-8"))
    assert "1.1.1.1" not in json.dumps(raw) and "a" * 32 not in json.dumps(raw)   # 只存哈希


def test_hub_manual_approve(tmp_path):
    hub = AS.Hub(str(tmp_path))
    hub.submit("a" * 32, "1.1.1.1", [item(), item(a="xx" * 20)])
    keys = [k for k, _ in hub.pending()]
    assert len(keys) == 1 and hub.mark(keys, "ok") == 1 and hub.count() == 1


def test_items_from_lib_and_split():
    lib = AL.Lib()
    lib.add("mai", "SUPER AMBULANCE", "mai", 11475, "救车")
    lib.add("chu", "Aleph-0", "chu", 2338, "a0", "vote", "2026-11-08", {"yes": 3, "no": 0})
    lib.add("sdvx", "VICTIM", "sdvxin", "06001", "维克")
    lib.add("mai", "#404", "mai", 404, "http://x.y")
    items = AS.items_from_lib(lib)
    assert {(i["g"], i["sp"], i["a"]) for i in items} == {("mai", "mai", "救车"), ("chu", "chu", "a0"), ("sdvx", "sdvxin", "维克")}
    mai, chu, sx = AS.split_pack({"items": [[i["g"], i["sp"], i["id"], i["t"], i["a"]] for i in items] + [["bad"]]})
    assert mai == {11475: ["救车"]} and chu == {2338: ["a0"]} and sx["sdvx"] == {"06001": ["维克"]}


def test_bot_id_stable(tmp_path):
    a = AS.bot_id(str(tmp_path))
    assert len(a) == 32 and AS.bot_id(str(tmp_path)) == a


def test_web_roundtrip(tmp_path):
    aiohttp = pytest.importorskip("aiohttp")
    from aiohttp import web

    async def run():
        hub = AS.Hub(str(tmp_path / "hub"))
        on = {"v": True}
        sw = AS.ShareWeb(lambda: hub if on["v"] else None)
        app = web.Application()
        sw.add_routes(app)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        try:
            r = await AS.upload(url, "a" * 32, [item()])
            assert r["ok"] and r["new"] == 1
            assert (await AS.download(url))["count"] == 0
            hub.mark([k for k, _ in hub.pending()], "ok")
            pack = await AS.download(url)
            assert pack["items"] == [["mai", "mai", 11475, "SUPER AMBULANCE", "救车"]]
            AS.save_pack(str(tmp_path / "c"), pack)
            assert AS.load_pack(str(tmp_path / "c"))["count"] == 1
            async with aiohttp.ClientSession() as s:
                async with s.post(url + "/api/aliases/submit", data=b"{}") as resp:
                    assert resp.status == 400
                async with s.post(url + "/api/aliases/submit", data=b"x" * 700_000) as resp:
                    assert resp.status == 413
            on["v"] = False
            with pytest.raises(Exception):
                await AS.download(url)
        finally:
            await runner.cleanup()
    asyncio.run(run())


def test_shared_layer_stays_out_of_local(tmp_path):
    from mai.data.aliases import AliasStore
    st = AliasStore(tmp_path, "mai")
    st.add_local("本机外号", 11475)
    st.shared = {11475: ["共享外号"], 8: ["别的歌"]}
    m = st.merged()
    assert m[11475][:2] == ["本机外号", "共享外号"] and "别的歌" in m[8]
    assert st.local() == {"本机外号": 11475}               # 共享的不进本机库，也就不会再被报回去
