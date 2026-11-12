"""录分本：VF / 音击 rating、存储规则、聊天录分、录分网站接口、VF 50 图。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from mai.bot.commands import Ctx  # noqa: E402
from scorebook import calc as K  # noqa: E402
from scorebook import catalog as C  # noqa: E402
from scorebook.service import ScoreBook, parse_score  # noqa: E402
from scorebook.store import ScoreError, ScoreStore, WebSessions  # noqa: E402
from scorebook.web import ScoreWeb  # noqa: E402


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------- VF：和 Tachi / rg-stats 的 VF7 测试用例对上 ----------
@pytest.mark.parametrize("level,score,lamp,expect", [
    (20, 10_000_000, "PUC", 0.462), (19, 10_000_000, "PUC", 0.438), (18, 10_000_000, "PUC", 0.415),
    (17, 10_000_000, "PUC", 0.392), (13, 10_000_000, "PUC", 0.3), (9, 10_000_000, "PUC", 0.207),
    (1, 10_000_000, "PUC", 0.023),
    (19, 9_500_000, "EXC", 0.357), (18, 9_923_042, "MXV", 0.39), (19, 9_500_000, "COMP", 0.35),
    (19, 9_500_000, "PLAY", 0.175), (20, 5_000_000, "PLAY", 0.08), (20, 7_000_000, "PLAY", 0.114),
    (20, 8_000_000, "PLAY", 0.136), (20, 8_700_000, "PLAY", 0.153),
    (19.8, 10_000_000, "PUC", 0.457), (18.5, 9_700_000, "UC", 0.38), (19.3, 9_500_000, "MXV", 0.369),
])
def test_vf7_matches_tachi(level, score, lamp, expect):
    assert K.sdvx_vf(level, score, lamp) == round(expect * 1000)


def test_grade_class_and_lamp_words():
    assert K.grade(9_899_999)[0] == "AAA+" and K.grade(9_900_000)[0] == "S" and K.grade(8_699_999)[0] == "B"
    assert K.vf_class(23_100) == "IMPERIAL IV" and K.vf_class(19_999) == "CRIMSON IV" and K.vf_class(0) == "SIENNA I"
    assert K.norm_lamp("uc") == "UC" and K.norm_lamp("PUC") == "PUC" and K.norm_lamp("没过") == "PLAY"
    assert K.norm_lamp("exh") is None
    assert K.fmt_song(403) == "20.15" and K.fmt_song(462) == "23.10" and K.fmt_song(0) == "0.00"
    assert parse_score("9,912,345") == 9912345 and parse_score("9912345") == 9912345
    assert parse_score("1,007,321") == 1007321 and parse_score("12") is None and parse_score("9,91,2345") is None


# ---------- 曲库 ----------
@pytest.fixture(scope="module")
def cats():
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scorebook", "data")
    return {g: C.load(os.path.join(base, f"{g}.json")) for g in C.GAMES}


def test_bundled_catalogs(cats):
    sd, gk = cats["sdvx"], cats["geki"]
    assert len(sd) > 2000 and len(gk) > 1000
    levels = {c.level for c in sd.charts.values()}
    assert {"17.5", "18.5", "19.7", "20.5"} <= levels            # ∇ 小数等级
    assert all(k == f"{c.song.key}:{c.diff}" for k, c in list(sd.charts.items())[:50])
    assert any(c.current == 0 for c in sd.charts.values())       # 已删除的也在，但标出来
    mas = [c for c in gk.charts.values() if c.diff == "MAS" and not c.no_const]
    assert mas and all(10 <= c.num <= 16 for c in mas)
    assert any(c.plat_max for c in gk.charts.values())
    assert any(s.lunatic and s.genre == "LUNATIC" for s in gk.songs.values())
    assert "オンゲキ" in gk.data["genres"]


def test_build_sdvx_small():
    songs = [{"id": "S1", "title": "テスト曲", "artist": "a", "data": {"displayVersion": "nabla"},
              "altTitles": [], "searchTerms": ["tesutokyoku"]}]
    charts = [{"songID": "S1", "difficulty": d, "level": lv, "levelNum": float(lv), "isPrimary": True,
               "data": {"inGameID": 9999}, "versions": vs}
              for d, lv, vs in (("NOV", "5", ["nabla"]), ("MXM", "18.5", ["nabla"]), ("EXH", "16", ["exceed"]))]
    d = C.build_sdvx(songs, charts)
    s = d["songs"][0]
    assert s["k"] == "9999" and [c["d"] for c in s["c"]] == ["NOV", "EXH", "MXM"]
    assert [c.get("x", 0) for c in s["c"]] == [1, 0, 1] and s["s"] == ["tesutokyoku"]
    cat = C.Catalog(d)
    cat.set_aliases({"9999": ["测试"]})
    assert cat.search("测试")[0].item.key == "9999"
    assert cat.client_payload()["songs"][0]["al"] == ["测试"]


# ---------- 存储 ----------
def test_store_rules(tmp_path):
    st = ScoreStore(str(tmp_path))
    r = st.put_sdvx("10001", "1:MXM", 9_800_000, "EXC")
    assert r["changed"] and r["new"]["s"] == 9_800_000
    r = st.put_sdvx("10001", "1:MXM", 9_700_000, "UC")           # 分数低了、灯高了：各取高
    assert r["new"]["s"] == 9_800_000 and r["new"]["l"] == "UC" and r["kept_higher"]
    r = st.put_sdvx("10001", "1:MXM", 9_500_000, "COMP", overwrite=True)
    assert r["new"]["s"] == 9_500_000 and r["new"]["l"] == "COMP"
    r = st.put_sdvx("10001", "1:EXH", 10_000_000, "COMP")         # 1000 万 = PUC
    assert r["new"]["l"] == "PUC"
    with pytest.raises(ScoreError):
        st.put_sdvx("10001", "1:EXH", 9_999_999, "PUC")
    with pytest.raises(ScoreError):
        st.put_sdvx("10001", "1:EXH", 10_000_001, "UC")
    assert len(st.user("10001")["sdvx"]["1:MXM"]["h"]) == 3
    st2 = ScoreStore(str(tmp_path))                                # 落盘了
    assert st2.scores("10001", "sdvx")["1:MXM"]["s"] == 9_500_000
    g = st.put_geki("10001", "x:MAS", 1_005_000, "FC", fb=True, stars=3)
    g = st.put_geki("10001", "x:MAS", 1_001_000, "AB", stars=2)
    assert g["new"]["s"] == 1_005_000 and g["new"]["l"] == "AB" and g["new"]["fb"] == 1 and g["new"]["st"] == 3
    with pytest.raises(ScoreError):
        st.put_geki("10001", "x:MAS", 1_010_001)
    with pytest.raises(ScoreError):
        st.user("../etc")
    assert st.delete("10001", "geki", "x:MAS") and not st.delete("10001", "geki", "x:MAS")


def test_sessions(tmp_path):
    ws = WebSessions(str(tmp_path))
    t = ws.issue_login("10001", "Kc", "sdvx")
    got = ws.redeem(t)
    assert got and got[1]["uid"] == "10001" and got[1]["game"] == "sdvx"
    assert ws.redeem(t) is None                                    # 只能用一次
    sess = got[0]
    assert WebSessions(str(tmp_path)).get(sess)["uid"] == "10001"  # 会话落盘（重载插件不掉登录）
    assert ws.drop_user("10001") == 1 and ws.get(sess) is None
    t2 = ws.issue_login("10001")
    ws.issue_login("10001")                                        # 再要一次：旧的作废
    assert ws.redeem(t2) is None


# ---------- 计算 ----------
def test_rows_and_geki_frames(cats):
    sd = cats["sdvx"]
    keys = [k for k, c in sd.charts.items() if c.current == 1 and c.diff in ("MXM", "EXH")][:60]
    scores = {k: {"s": 9_900_000, "l": "UC"} for k in keys}
    rows = K.sdvx_rows(sd, scores)
    assert len(rows) == 60 and rows[0].vf >= rows[-1].vf
    assert K.sdvx_total(rows) == sum(r.vf for r in rows[:50])

    gk = cats["geki"]
    new = next(c for c in gk.charts.values() if c.diff == "MAS" and not c.no_const and c.song.version_code >= 150
               and not c.song.bonus)
    old = next(c for c in gk.charts.values() if c.diff == "MAS" and not c.no_const and 0 < c.song.version_code < 150
               and not c.song.bonus)
    best = K.geki_best(gk, {new.key: {"s": 1_007_500, "l": "AB", "fb": 1, "st": 5},
                            old.key: {"s": 1_000_000, "l": "FC"}}, "P")
    assert [c.sb_key for c in best.new] == [new.key] and [c.sb_key for c in best.best] == [old.key]
    assert [c.sb_key for c in best.plat] == [new.key]
    exp_new = K.GR.ts_rate(new.num, 1_007_500, fc=True, ab=True, fb=True)
    assert best.new[0].rate == exp_new
    assert best.calc == (exp_new + best.best[0].rate + K.GR.ps_rate(new.num, 5)) // 50


# ---------- 聊天 ----------
def test_chat_record(tmp_path, cats):
    sb = ScoreBook(str(tmp_path))
    ctx = Ctx(uid="10001", private=True, admin=False, name="Kc")
    song = next(s for s in sb.cat("sdvx").songs.values() if "MXM" in s.charts and s.charts["MXM"].current == 1
                and s.title.isascii() and " " not in s.title and len(s.title) > 6)
    r = run(sb.handle(ctx, "sdvx", "录", f"{song.title} mxm 9,912,345 uc"))
    t = r.texts[0]
    assert song.title in t and "9,912,345" in t and "UC" in t and "单曲" in t and "VF" in t
    assert sb.store.scores("10001", "sdvx")[song.charts["MXM"].key]["l"] == "UC"
    r = run(sb.handle(ctx, "sdvx", "录", f"{song.title} 9,000,000"))       # 不写难度 = MXM，低了保留高的
    assert "保留高的" in r.texts[0]
    r = run(sb.handle(ctx, "sdvx", "成绩", song.title))
    assert "9,912,345" in r.texts[0]
    assert run(sb.handle(ctx, "sdvx", "录", "")).texts[0].startswith("用法")
    assert "VOLFORCE" in sb.sdvx_text("10001")
    # 音击
    gs = next(s for s in sb.cat("geki").songs.values() if "MAS" in s.charts and not s.charts["MAS"].no_const
              and not s.bonus and s.title.isascii() and " " not in s.title and len(s.title) > 6)
    r = run(sb.handle(ctx, "geki", "录", f"{gs.title} mas 1,007,321 ab fb ★4"))
    rec = sb.store.scores("10001", "geki")[gs.charts["MAS"].key]
    assert rec == {**rec, "s": 1_007_321, "l": "AB", "fb": 1, "st": 4}
    assert "rating" in r.texts[0]
    assert run(sb.handle(ctx, "sdvx", "b50", "")) is None             # b50 由 main 处理


# ---------- 录分网站 ----------
def test_web_flow(tmp_path):
    sb = ScoreBook(str(tmp_path))
    web = ScoreWeb(sb, bot_name="Bot")
    from aiohttp import web as aw

    async def flow():
        app = aw.Application()
        web.add_routes(app)
        async with TestClient(TestServer(app)) as c:
            assert "传分" in await (await c.get("/scores")).text()
            assert (await c.get("/scores/app.js")).status == 200
            me = await (await c.get("/api/sb/me")).json()
            assert me["login"] is False and me["catalogs"]["sdvx"]["songs"] > 2000
            cat = await (await c.get("/api/sb/catalog?game=sdvx")).json()
            assert len(cat["songs"]) > 2000
            assert (await c.get("/api/sb/scores?game=sdvx")).status == 401
            hits = await (await c.get("/api/sb/search", params={"game": "sdvx", "q": "VICTIM"})).json()
            assert hits["hits"]
            song = sb.cat("sdvx").songs[hits["hits"][0]["k"]]
            key = next(ch.key for ch in song.charts.values() if ch.current)
            H = {"X-SB": "1"}
            # 没登录不能写；没有 X-SB 头的提交（跨站表单）直接拒绝
            assert (await c.post("/api/sb/score", json={"game": "sdvx", "key": key, "score": 1}, headers=H)).status == 401
            tok = sb.sessions.issue_login("10001", "Kc", "sdvx")
            assert (await c.post("/api/sb/login", json={"t": tok})).status == 400
            r = await c.post("/api/sb/login", json={"t": tok}, headers=H)
            assert (await r.json())["ok"] and "sb" in r.cookies
            assert (await c.post("/api/sb/login", json={"t": tok}, headers=H)).status == 401     # 用过了
            me = await (await c.get("/api/sb/me")).json()
            assert me["login"] and me["name"] == "Kc"
            r = await (await c.post("/api/sb/score", json={"game": "sdvx", "key": key, "score": "9,950,000",
                                                           "lamp": "UC"}, headers=H)).json()
            assert r["ok"] and r["record"]["s"] == 9_950_000 and r["delta"] > 0 and r["summary"]["b50"] == [key]
            r = await (await c.post("/api/sb/score", json={"game": "sdvx", "key": key, "score": 99, "lamp": "PUC"},
                                    headers=H)).json()
            assert not r["ok"] and "PUC" in r["message"]
            s = await (await c.get("/api/sb/scores?game=sdvx")).json()
            assert s["scores"][key]["s"] == 9_950_000 and "h" not in s["scores"][key]
            r = await (await c.post("/api/sb/alias", json={"game": "sdvx", "song": song.key, "alias": "受害者测试"},
                                    headers=H)).json()
            assert r["ok"] and "受害者测试" in r["aliases"]
            hits = await (await c.get("/api/sb/search", params={"game": "sdvx", "q": "受害者测试"})).json()
            assert hits["hits"][0]["k"] == song.key and hits["hits"][0]["by"] == "受害者测试"
            cat = await (await c.get("/api/sb/catalog?game=sdvx")).json()
            assert any(x.get("al") == ["受害者测试"] for x in cat["songs"])
            csv_text = await (await c.get("/api/sb/export?game=sdvx")).text()
            assert "9950000" in csv_text and song.title in csv_text
            # 音击
            gk = next(ch for ch in sb.cat("geki").charts.values() if ch.diff == "MAS" and not ch.no_const and ch.plat_max)
            r = await (await c.post("/api/sb/score", json={"game": "geki", "key": gk.key, "score": 1_008_000, "lamp": "AB",
                                                           "fb": True, "plat": gk.plat_max}, headers=H)).json()
            assert r["ok"] and r["record"]["p"] == gk.plat_max and r["summary"]["total"] > 0
            assert r["summary"]["plat"] == [gk.key]
            r = await (await c.post("/api/sb/delete", json={"game": "geki", "key": gk.key}, headers=H)).json()
            assert r["ok"] and r["summary"]["count"] == 0
            assert (await (await c.post("/api/sb/logout", json={}, headers=H)).json())["ok"]
            assert (await (await c.get("/api/sb/me")).json())["login"] is False
    run(flow())


def test_bindweb_mounts_scores(tmp_path):
    from core.bindweb import BindWeb
    sb = ScoreBook(str(tmp_path))
    bw = BindWeb(binder=None, extra=[ScoreWeb(sb)])

    async def flow():
        async with TestClient(TestServer(bw.app())) as c:
            r = await c.get("/scores")
            assert r.status == 200 and "script-src 'self'" in r.headers["Content-Security-Policy"]
    run(flow())


def test_vf50_image(tmp_path, cats):
    from pathlib import Path

    from scorebook.sdvx_img import render
    sd = cats["sdvx"]
    keys = [k for k, c in sd.charts.items() if c.current == 1 and c.num >= 17][:55]
    rows = K.sdvx_rows(sd, {k: {"s": 9_950_000 - i * 1000, "l": "UC" if i % 3 else "PUC" if False else "EXC"}
                            for i, k in enumerate(keys)})
    out = render(rows, Path(tmp_path) / "vf.jpg", player="テスト", count=len(rows))
    from PIL import Image
    with Image.open(out) as im:
        assert im.width == 1872 and im.height > 2000


def test_deep_link(tmp_path):
    sb = ScoreBook(str(tmp_path))
    assert sb.deep_link("sdvx", "") == {"g": "sdvx"}
    a = sb.deep_link("sdvx", "VICTIM mxm")
    assert a["g"] == "sdvx" and a["d"] == "MXM" and (a.get("k") or a.get("q"))
    k = a.get("k")
    if k:
        assert "VICTIM" in sb.cat("sdvx").songs[k].title.upper()
    b = sb.deep_link("geki", "zzqqxx不存在的歌")
    assert b == {"g": "geki", "q": "zzqqxx不存在的歌"}
    assert sb.deep_link("", "VICTIM") == {}


def test_help_mentions_scorebook():
    from core import help as H
    assert "/传分" in H.help_text("more") and "/批量传" in H.help_text("more") and "/传 歌" in H.help_text()
    assert "/传分" not in H.help_text("mai")


# ---------- 批量录分 ----------
def test_batch_parse_formats(tmp_path):
    sb = ScoreBook(str(tmp_path))
    text = "\n".join([
        "```", "曲名 | 难度 | 分数 | 灯", "| --- | --- | --- | --- |",
        "1. VICTIM | MXM | 9,912,345 | UC",
        "VICTIM\tEXH\t10000000\tPERFECT",
        "victim adv 9800000 exc",
        "VICTIM | INF | 9900000 | PUC",            # 这首没有第 4 难度
        "VICTIM | MXM | ? | ?",
        "完全不存在的歌名啊啊 | MXM | 9000000",
        "# 注释", "```"])
    rows = sb.parse_batch("sdvx", text)
    assert [r["ok"] for r in rows] == [True, True, True, False, False, False]
    assert rows[0]["key"].endswith(":MXM") and rows[0]["score"] == 9_912_345 and rows[0]["lamp"] == "UC"
    assert rows[1]["d"] == "EXH" and rows[1]["lamp"] == "PUC"
    assert rows[2]["d"] == "ADV" and rows[2]["lamp"] == "EXC"
    assert "没有 INF" in rows[3]["err"] and "没有分数" in rows[4]["err"] and "没找到" in rows[5]["err"]
    g = sb.parse_batch("geki", "Demonia | MASTER | 1,007,321 | AB | FB | 4100\nDemonia | EXP | 1001000 | FC | - | -")
    assert g[0]["ok"] and (g[0]["lamp"], g[0]["fb"], g[0]["plat"]) == ("AB", True, 4100)
    assert g[1]["ok"] and (g[1]["lamp"], g[1]["fb"], g[1]["plat"]) == ("FC", False, None)
    amb = sb.parse_batch("geki", "アイシング | EXP | 1001000 | FC")[0]
    assert not amb["ok"] and len(amb["choices"]) >= 2 and amb["diff_in"] == "EXP"


def test_batch_apply_and_chat(tmp_path):
    sb = ScoreBook(str(tmp_path))
    ctx = Ctx(uid="10002", private=True, admin=False, name="Kc")
    r = run(sb.handle(ctx, "sdvx", "批量录", "VICTIM | MXM | 9,912,345 | UC\nVICTIM exh 9950000 uc\n不存在的歌啊 mxm 9000000"))
    t = r.texts[0]
    assert "传了 2 张" in t and "VF" in t and "没传上" in t and "第 3 行" in t
    assert len(sb.store.scores("10002", "sdvx")) == 2
    assert "一行一首" in run(sb.handle(ctx, "sdvx", "批量录", "")).texts[0]
    # 单条连录第二首起提示批量
    t2 = run(sb.handle(ctx, "sdvx", "传", "VICTIM adv 9000000")).texts[0]   # 新词「传」；旧的「录」也认
    assert "批量传" in t2
    assert "VICTIM" in run(sb.handle(ctx, "sdvx", "录", "VICTIM nov 9000000")).texts[0]
    assert "传了 1 张" in run(sb.handle(ctx, "sdvx", "批量传", "VICTIM | EXH | 9,000,000")).texts[0]
    res = sb.apply_batch("10002", "Kc", "sdvx", [{"key": next(iter(sb.store.scores("10002", "sdvx"))), "score": 1}])
    assert res["kept_higher"] == 1 and res["delta"] == 0


def test_web_batch_and_jacket(tmp_path):
    from PIL import Image
    sb = ScoreBook(str(tmp_path))
    web = ScoreWeb(sb, bot_name="Bot")
    src_png = tmp_path / "src.png"
    Image.new("RGB", (300, 300), (200, 30, 90)).save(src_png)
    victim = next(s for s in sb.cat("sdvx").songs.values() if s.title == "VICTIM")
    other_key = next(k for k, s in sb.cat("sdvx").songs.items() if s.title != "VICTIM")

    class FakeSrc:                       # 假的 sdvx.in：只有 VICTIM 有图
        entries = {"sdvx": {"9999": type("E", (), {"title": "VICTIM", "removed": False})()}, "geki": {}}
        calls = 0

        async def song_jacket(self, e, budget=15):
            FakeSrc.calls += 1
            return str(src_png)
    sb.sdvxin = FakeSrc()
    from aiohttp import web as aw

    async def flow():
        app = aw.Application()
        web.add_routes(app)
        async with TestClient(TestServer(app)) as c:
            H = {"X-SB": "1"}
            r = await c.get(f"/api/sb/jk/sdvx/{victim.key}.jpg")
            assert r.status == 200 and r.headers["Content-Type"] == "image/jpeg" and "immutable" in r.headers["Cache-Control"]
            assert (await c.get(f"/api/sb/jk/sdvx/{victim.key}.jpg")).status == 200 and FakeSrc.calls == 1   # 走缓存
            assert (await c.get("/api/sb/jk/sdvx/..%2Fx.jpg")).status == 404
            keep = FakeSrc.entries
            FakeSrc.entries = {"sdvx": {}, "geki": {}}       # 刚重载、曲目表还没加载好
            nr = await c.get(f"/api/sb/jk/sdvx/{other_key}.jpg")
            assert nr.status == 404 and nr.headers["Cache-Control"] == "no-store"
            FakeSrc.entries = keep
            assert f"sdvx:{other_key}" not in sb._jk_miss
            other = next(k for k, s in sb.cat("sdvx").songs.items() if s.title != "VICTIM")
            assert (await c.get(f"/api/sb/jk/sdvx/{other}.jpg")).status == 404
            p = await (await c.post("/api/sb/batch", json={"game": "sdvx", "text": "VICTIM | MXM | 9912345 | UC"},
                                    headers=H)).json()
            assert p["ok"] and p["rows"][0]["ok"]
            assert (await c.post("/api/sb/batch_apply", json={"game": "sdvx", "rows": []}, headers=H)).status == 401
            tok = sb.sessions.issue_login("10003", "Kc", "sdvx")
            await c.post("/api/sb/login", json={"t": tok}, headers=H)
            row = p["rows"][0]
            a = await (await c.post("/api/sb/batch_apply", json={"game": "sdvx", "rows": [
                {"key": row["key"], "score": row["score"], "lamp": row["lamp"]}, {"key": "nope:MXM", "score": 1}]},
                headers=H)).json()
            assert a["ok"] and a["done"] == 1 and a["delta"] > 0 and a["errors"] and row["key"] in a["scores"]
            p2 = await (await c.post("/api/sb/batch", json={"game": "sdvx", "text": "VICTIM | MXM | 9000000"},
                                     headers=H)).json()
            assert p2["rows"][0]["old"]["s"] == 9_912_345
    run(flow())



def test_chuan_routes():
    from core.route import route
    assert route("/传分").argline == "传分" and route("/传分 sdvx VICTIM").argline == "传分 sdvx VICTIM"
    assert route("/录分").argline == "传分"                       # 旧的照样认
    r = route("/传 VICTIM mxm 9912345 uc")
    assert (r.game, r.argline) == ("core", "传 VICTIM mxm 9912345 uc")
    r = route("/批量传\nVICTIM | MXM | 9912345 | UC\nfoo")
    assert r.game == "core" and r.argline.startswith("批量传\nVICTIM") and r.argline.count("\n") == 2
    assert route("/批量传 sdvx\nVICTIM | MXM | 9912345").argline.startswith("批量传 sdvx\nVICTIM")
    assert route("/传说") is None or route("/传说").argline != "传 说"


def test_from_bind(tmp_path):
    from core.bindweb import BindWeb
    sb = ScoreBook(str(tmp_path))
    bw = BindWeb(binder=None, extra=[ScoreWeb(sb)])

    async def flow():
        async with TestClient(TestServer(bw.app())) as c:
            assert (await c.post("/api/sb/from_bind", json={"game": "sdvx"}, headers={"X-Bind-Token": "nope"})).status == 401
            tok = bw.sessions.issue("10009", name="Kc")
            r = await (await c.post("/api/sb/from_bind", json={"game": "geki"}, headers={"X-Bind-Token": tok})).json()
            assert r["ok"] and r["url"].startswith("/scores#t=") and r["url"].endswith("&g=geki")
            t2 = r["url"].split("t=")[1].split("&")[0]
            lg = await (await c.post("/api/sb/login", json={"t": t2}, headers={"X-SB": "1"})).json()
            assert lg["ok"] and lg["game"] == "geki"
            assert (await (await c.get("/api/sb/me")).json())["name"] == "Kc"
    run(flow())


def test_sdvx_account_words():
    from chart.commands import ChartCommands
    cc = ChartCommands.__new__(ChartCommands)
    ctx = Ctx(uid="1", private=True, admin=False, name="Kc")
    assert "不用绑定" in run(cc.handle(ctx, "绑定", "sdvx")).texts[0]
    assert "游戏记录" in run(cc.handle(ctx, "最近", "sdvx")).texts[0] or "游玩记录" in run(cc.handle(ctx, "最近", "sdvx")).texts[0]
    assert "小数等级" in run(cc.handle(ctx, "定数", "sdvx")).texts[0]
    assert "详细定数" in run(cc.handle(ctx, "定数", "geki")).texts[0]
    assert "用法" in run(cc.handle(ctx, "别名", "sdvx")).texts[0]


def test_help_has_account_rows():
    from core import help as H
    for g in ("sdvx", "geki"):
        t = H.help_text(g)
        assert "网页绑定" in t and "/传分 登出" in t and "别名 · 加别名" in t, g
    assert "/mai 曲库" in H.help_text("mai") and "删别名" in H.help_text("chu")


def test_core_webui_scorebook(tmp_path):
    from core.webui import CoreWebUI, ROUTES
    sb = ScoreBook(str(tmp_path))
    ctx = Ctx(uid="12345678", private=True, admin=False, name="Kc")
    run(sb.handle(ctx, "sdvx", "传", "VICTIM mxm 9912345 uc"))
    tok = sb.sessions.issue_login("12345678", "Kc")
    sb.sessions.redeem(tok)

    class P:
        scorebook = sb
        bindweb = None
        def bindweb_url(self): return "https://bind.example.com"
        def _cfg(self, k, d=None): return d
    w = CoreWebUI(P())
    r = run(w.scorebook({}))
    assert r["web"]["scores_url"] == "https://bind.example.com/scores" and r["web"]["running"] is False
    assert r["catalogs"]["sdvx"]["songs"] > 2000 and r["users"][0]["sdvx"] == 1 and r["users"][0]["sessions"] == 1
    assert r["users"][0]["vf"] and r["users"][0]["qq"] != "12345678"
    assert run(w.scorebook_logout({"uid": "12345678"}))["dropped"] == 1
    assert {"scorebook", "scorebook/refresh", "scorebook/logout"} <= set(ROUTES)


EAM_CSV = ("﻿楽曲名,難易度,楽曲レベル,クリアランク,スコアグレード,ハイスコア,EXスコア,プレー回数,クリア回数,ULTIMATE CHAIN,PERFECT\n"
           "VICTIM,MAXIMUM,18.3,ULTIMATE CHAIN,S,9912345,0,3,3,1,0\n"
           "VICTIM,EXHAUST,16,PERFECT,S,10000000,0,1,1,1,1\n"
           "VICTIM,ADVANCED,13,PLAYED,D,0,0,1,0,0,0\n"
           "Victim of Nights,EXHAUST,15,EXCESSIVE COMPLETE,AA+,9512345,0,1,1,0,0\n"
           "完全に存在しない曲,MAXIMUM,18,COMPLETE,A,9000000,0,1,1,0,0\n"
           "VICTIM,WHATEVER,18,COMPLETE,A,9000000,0,1,1,0,0\n")


def test_eam_csv(tmp_path):
    sb = ScoreBook(str(tmp_path))
    assert sb.is_eam_csv(EAM_CSV) and not sb.is_eam_csv("VICTIM | MXM | 9912345")
    rows = sb.parse_batch("sdvx", EAM_CSV)
    ok = [r for r in rows if r["ok"]]
    assert [(r["t"], r["d"], r["score"], r["lamp"]) for r in ok] == [
        ("VICTIM", "MXM", 9_912_345, "UC"), ("VICTIM", "EXH", 10_000_000, "PUC"),
        ("Victim of Nights", "EXH", 9_512_345, "EXC")]
    bad = [r for r in rows if not r["ok"]]
    assert len(bad) == 2 and any("难度不认识" in r["err"] for r in bad)        # 0 分那行直接跳过
    res = sb.apply_batch("200", "Kc", "sdvx", [{"key": r["key"], "score": r["score"], "lamp": r["lamp"]} for r in ok])
    assert res["done"] == 3 and res["delta"] > 0


def test_eam_csv_big_through_bindweb(tmp_path):
    from core.bindweb import BindWeb
    sb = ScoreBook(str(tmp_path))
    bw = BindWeb(binder=None, extra=[ScoreWeb(sb)])
    lines = EAM_CSV.splitlines()
    big = "\n".join([lines[0]] + [lines[1]] * 2500)                 # ~120 KB，比整个服务 16 KB 的上限大
    assert len(big.encode()) > 100_000

    async def flow():
        async with TestClient(TestServer(bw.app())) as c:
            r = await c.post("/api/sb/batch", json={"game": "sdvx", "text": big}, headers={"X-SB": "1"})
            assert r.status == 200
            d = await r.json()
            assert d["csv"] and len(d["rows"]) == 2500 and all(x["ok"] for x in d["rows"])
    run(flow())


# ---------- 群里发的传分链接：要本人回确认码 ----------
def test_group_link_needs_confirm(tmp_path):
    ws = WebSessions(str(tmp_path))
    t = ws.issue_login("10001", "Kc", "sdvx", confirm=True)
    sess, info = ws.redeem(t)
    assert sess == "" and len(info["code"]) == 4 and info["pid"]
    assert ws.redeem(t) is None                                   # 链接还是只能点一次
    assert ws.poll(info["pid"]) == "wait"
    assert ws.confirm("20002", info["code"]) == "none"            # 别人发确认没用
    wrong = "0000" if info["code"] != "0000" else "1111"
    assert ws.confirm("10001", wrong) == "wrong"
    assert ws.poll(info["pid"]) == "wait"
    assert ws.confirm("10001", info["code"]) == "ok"
    sess, v = ws.poll(info["pid"])
    assert sess and ws.get(sess)["uid"] == "10001"
    assert ws.poll(info["pid"]) is None                           # 只发一次会话
    # 输错 5 次作废
    t = ws.issue_login("10001", "Kc", "", confirm=True)
    _, info = ws.redeem(t)
    wrong = "0000" if info["code"] != "0000" else "1111"
    for _ in range(5):
        assert ws.confirm("10001", wrong) == "wrong"
    assert ws.confirm("10001", info["code"]) == "locked"
    assert ws.poll(info["pid"]) is None
    # 私聊发的照旧直接登录
    s2, _ = ws.redeem(ws.issue_login("10001", "Kc"))
    assert s2 and ws.get(s2)


def test_group_link_web_flow(tmp_path):
    sb = ScoreBook(str(tmp_path))
    web = ScoreWeb(sb, bot_name="Bot")
    from aiohttp import web as aw

    async def flow():
        app = aw.Application()
        web.add_routes(app)
        H = {"X-SB": "1"}
        async with TestClient(TestServer(app)) as c:
            tok = sb.sessions.issue_login("10001", "Kc", "sdvx", confirm=True)
            d = await (await c.post("/api/sb/login", json={"t": tok}, headers=H)).json()
            assert d["pending"] and not d["ok"] and len(d["code"]) == 4
            assert not (await (await c.get("/api/sb/me")).json())["login"]
            r = await (await c.post("/api/sb/pending", json={"p": d["pid"]}, headers=H)).json()
            assert r["wait"]
            assert (await c.post("/api/sb/pending", json={"p": d["pid"]})).status == 400   # 没 X-SB
            assert sb.sessions.confirm("10001", d["code"]) == "ok"
            r = await c.post("/api/sb/pending", json={"p": d["pid"]}, headers=H)
            assert (await r.json())["ok"] and "sb" in r.cookies
            assert (await (await c.get("/api/sb/me")).json())["login"]
            assert (await c.post("/api/sb/pending", json={"p": d["pid"]}, headers=H)).status == 401
            assert (await c.post("/api/sb/pending", json={"p": "nope"}, headers=H)).status == 401
    run(flow())


# ---------- v2.3.4：EX SCORE / 显示开关 ----------
def test_sdvx_ex_score(tmp_path):
    from scorebook.service import parse_fields, parse_tail
    st = ScoreStore(str(tmp_path))
    st.put_sdvx("1", "k", 9_900_000, "UC", ex=4000)
    r = st.put_sdvx("1", "k", 9_800_000, "EXC", ex=3900)
    assert r["new"]["s"] == 9_900_000 and r["new"]["x"] == 4000           # 只升不降
    r = st.put_sdvx("1", "k", 9_800_000, "EXC", ex=4100)
    assert r["new"]["x"] == 4100 and r["changed"]
    r = st.put_sdvx("1", "k", 9_800_000, "EXC", overwrite=True)
    assert "x" not in r["new"]
    with pytest.raises(ScoreError):
        st.put_sdvx("1", "k", 9_800_000, "EXC", ex=123456)
    _, f = parse_fields("sdvx", "MXM | 9,912,345 | UC | 4,321".replace("|", " ").split())
    assert f["score"] == 9_912_345 and f["ex"] == 4321 and f["lamp"] == "UC"
    q, f = parse_tail("sdvx", "VICTIM mxm 9912345 uc ex4321".split())
    assert q == ["VICTIM"] and f["ex"] == 4321 and f["lamp"] == "UC"
    sb = ScoreBook(str(tmp_path / "b"))
    ok = [r for r in sb.parse_batch("sdvx", EAM_CSV.replace("9912345,0,3", "9912345,4567,3")) if r["ok"]]
    assert ok[0]["ex"] == 4567 and ok[1]["ex"] is None                    # 0 = 没有
    rows = sb.parse_batch("sdvx", "VICTIM | MXM | 9,912,345 | UC | 4321")
    assert rows[0]["ok"] and rows[0]["ex"] == 4321
    sb.apply_batch("9", "Kc", "sdvx", [{"key": rows[0]["key"], "score": rows[0]["score"], "lamp": "UC", "ex": 4321}])
    assert sb.store.scores("9", "sdvx")[rows[0]["key"]]["x"] == 4321
    assert K.sdvx_rows(sb.cat("sdvx"), sb.store.scores("9", "sdvx"))[0].ex == 4321
    assert "EX 4,321" in sb.sdvx_text("9")


def test_show_prefs_and_api(tmp_path):
    from core.prefs import Prefs
    pf = Prefs(str(tmp_path))
    assert pf.shows("1") == {"sdvx_ex": True, "mai_dx": True, "geki_plat": True}
    pf.set_show("1", "sdvx_ex", False)
    assert not Prefs(str(tmp_path)).show("1", "sdvx_ex")                 # 存盘了
    sb = ScoreBook(str(tmp_path))
    sb.prefs = pf
    web = ScoreWeb(sb, bot_name="Bot")
    from aiohttp import web as aw

    async def flow():
        app = aw.Application()
        web.add_routes(app)
        H = {"X-SB": "1"}
        async with TestClient(TestServer(app)) as c:
            assert (await c.post("/api/sb/show", json={"k": "geki_plat", "on": False}, headers=H)).status == 401
            tok = sb.sessions.issue_login("1", "Kc")
            await c.post("/api/sb/login", json={"t": tok}, headers=H)
            me = await (await c.get("/api/sb/me")).json()
            assert me["show"]["sdvx_ex"] is False
            d = await (await c.post("/api/sb/show", json={"k": "geki_plat", "on": False}, headers=H)).json()
            assert d["ok"] and d["show"]["geki_plat"] is False and not pf.show("1", "geki_plat")
            assert (await c.post("/api/sb/show", json={"k": "nope", "on": False}, headers=H)).status == 400
            hits = await (await c.get("/api/sb/search", params={"game": "sdvx", "q": "VICTIM"})).json()
            song = sb.cat("sdvx").songs[hits["hits"][0]["k"]]
            key = next(ch.key for ch in song.charts.values() if ch.current)
            r = await (await c.post("/api/sb/score", json={"game": "sdvx", "key": key, "score": 9_900_000, "lamp": "UC",
                                                           "ex": "4,321"}, headers=H)).json()
            assert r["ok"] and r["record"]["x"] == 4321
    run(flow())


def test_images_extra_scores(tmp_path):
    from pathlib import Path
    from scorebook import sdvx_img
    sb = ScoreBook(str(tmp_path))
    rows = sb.parse_batch("sdvx", "VICTIM | MXM | 9,912,345 | UC | 4321")
    sb.store.put_sdvx("1", rows[0]["key"], 9_912_345, "UC", ex=4321)
    rs = K.sdvx_rows(sb.cat("sdvx"), sb.store.scores("1", "sdvx"))
    for on in (True, False):
        out = sdvx_img.render(rs, Path(tmp_path) / f"s{on}.jpg", player="Kc", show_ex=on)
        assert out.exists()
    sb.store.put_geki("1", next(iter(sb.cat("geki").charts)), 1_007_000, "AB", platinum=4100, stars=4)
    best = K.geki_best(sb.cat("geki"), sb.store.scores("1", "geki"), "Kc")
    from ongeki.b50img import render as gr
    for on in (True, False):
        best.show_plat = on
        assert gr(best, Path(tmp_path) / f"g{on}.jpg").exists()


def test_mai_dx_max_filled():
    import gzip
    import json
    from mai.calc.rating import Best50
    from mai.data.songdb import SongDB
    from mai.models import Score
    from mai.render.b50img import fill_dx_max
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mai", "data")
    db = SongDB(json.load(gzip.open(os.path.join(base, "dxrating_snapshot.json.gz"))))
    ch = next(c for s in db.songs for c in s.charts if (c.notes or {}).get("total") and c.type in ("dx", "std"))
    s = Score(title=ch.song.title, type=ch.type, diff=ch.diff, level=ch.level, ach=1_000_000, dx=100)
    b = Best50(region="jp", old=[s])
    b.show_dx = False
    fill_dx_max(b, db)
    assert s.dx_max == ch.notes["total"] * 3 and s._show_dx is False


def test_active_sessions_count(tmp_path):
    ws = WebSessions(str(tmp_path))
    assert ws.active("1") == 0
    ws.redeem(ws.issue_login("1", "Kc"))
    ws.redeem(ws.issue_login("1", "Kc"))
    ws.redeem(ws.issue_login("2", "X"))
    assert ws.active("1") == 2 and ws.active("2") == 1
    ws.drop_user("1")
    assert ws.active("1") == 0
