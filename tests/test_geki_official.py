"""音击官服（オンゲキ-NET）：页面解析 + 同步进传分本。页面是照公开描述手写的样本（没有真账号实测）。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ongeki.net import PageChanged, parse_course, parse_error, parse_scores  # noqa: E402
from ongeki.official import GekiOfficial  # noqa: E402
from scorebook.service import ScoreBook  # noqa: E402


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def song_block(title, lv, od, battle, tech, icons=(), plat=None, star=None, idx="1"):
    imgs = "".join(f'<img src="https://ongeki-net.com/ongeki-mobile/img/{i}">' for i in icons)
    p = (f'<div class="platinum_high_score_text_block">{plat}/9999</div>'
         f'<div class="platinum_high_score_star_block"><span class="f_b">{star}</span></div>') if plat else ""
    return (f'<div class="basic_btn master_score_back"><form><input type="hidden" name="idx" value="{idx}"></form>'
            f'<div class="music_label">{title}</div><div class="score_level">{lv}</div>'
            f'<table><tr><td class="score_value">{od}</td><td class="score_value">{battle}</td>'
            f'<td class="score_value">{tech}</td></tr></table>{imgs}{p}</div>')


PAGE = ('<html><body><div class="container3">'
        '<div class="p_5 f_20">オンゲキ</div>'
        + song_block("Demonia", "15", "350%", "1,234,567", "1,007,321",
                     ("music_icon_abplus.png", "music_icon_fb.png"), plat="4,100", star="4", idx="9")
        + song_block("アイシング・ドリーム", "13", "100%", "900,000", "1,001,000", ("music_icon_fc.png",))
        + song_block("没打过的歌", "14", "", "", "")
        + song_block("曲库里没有的新歌 XYZ", "14+", "200%", "1", "990,000")
        + '</div></body></html>')


def test_parse_pages():
    rows = parse_scores(PAGE, 3)
    assert [r.title for r in rows] == ["Demonia", "アイシング・ドリーム", "曲库里没有的新歌 XYZ"]
    d = rows[0]
    assert (d.diff, d.level, d.technical, d.lamp, d.fb, d.platinum, d.stars, d.genre, d.idx) == \
        ("MAS", "15", 1_007_321, "AB", True, 4100, 4, "オンゲキ", "9")
    assert rows[1].lamp == "FC" and not rows[1].fb and rows[1].platinum is None
    try:
        parse_scores("<html><body>nothing</body></html>", 0)
        assert False
    except PageChanged:
        pass
    assert parse_course('<div class="back_course_standard"><span>利用中</span></div>'
                        '<div class="back_course_premium"><span>未加入</span></div>') == (True, False)
    assert parse_course("<html></html>") == (False, False)
    assert parse_error("<p>ERROR CODE：100101</p>")[0] == 100101


class FakeClient:
    std = True

    def __init__(self, sid, pw, aime):
        self.sid, self.pw = sid, pw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def login(self):
        from chuni.client import LoginFailed
        if self.pw != "good":
            raise LoginFailed("オンゲキ-NET 登录失败：SEGA ID 或密码不对")

    async def course(self):
        return FakeClient.std, False

    async def scores(self, code):
        return parse_scores(PAGE, code) if code == 3 else []


def test_bind_and_sync(tmp_path):
    sb = ScoreBook(str(tmp_path))
    off = GekiOfficial(str(tmp_path / "geki_official"), sb, client_factory=FakeClient)
    assert "失败" in run(off.bind("100", "Kc", "sega1", "bad")) and not off.bound("100")
    t = run(off.bind("100", "Kc", "sega1", "good"))
    assert "绑定成功" in t and "同步完成" in t and "曲库里没对上" in t and off.bound("100")
    book = sb.store.scores("100", "geki")
    demo = next(k for k in book if k.endswith(":MAS") and sb.cat("geki").charts[k].song.title == "Demonia")
    assert book[demo]["s"] == 1_007_321 and book[demo]["l"] == "AB" and book[demo]["fb"] and book[demo]["p"] == 4100
    assert "刚同步过" in run(off.sync("100"))                 # 5 分钟内不重复拉
    FakeClient.std = False
    assert "没开" in run(off.sync("100", force=True))
    FakeClient.std = True
    # 凭据加密存：文件里看不到密码
    raw = (tmp_path / "geki_official" / "geki_official.json").read_text("utf-8")
    assert "good" not in raw and "sega1" not in raw
    assert off.unbind("100") and not off.bound("100")


def test_client_flow_mocked():
    import httpx
    from ongeki.net import OngekiNetClient
    seen = []

    def handler(req: httpx.Request):
        p = req.url.path
        seen.append((req.method, p, req.url.query.decode()))
        if p == "/ongeki-mobile/" and req.method == "GET":
            return httpx.Response(200, text='<form><input name="segaId"><input name="password">'
                                              '<input type="hidden" name="token" value="tok123"></form>')
        if p == "/ongeki-mobile/submit/":
            body = req.content.decode()
            assert "segaId=sid" in body and "token=tok123" in body
            if "password=bad" in body:
                return httpx.Response(200, text='<form><input name="segaId"><input name="password"></form>')
            return httpx.Response(200, text="<html>aime list</html>")
        if p.startswith("/ongeki-mobile/aimeList/submit"):
            return httpx.Response(200, text="<html>ok</html>")
        if p == "/ongeki-mobile/home/":
            return httpx.Response(200, text="<html>home</html>")
        if p == "/ongeki-mobile/courseDetail/":
            return httpx.Response(200, text='<div class="back_course_standard"><span>利用中</span></div>')
        if p == "/ongeki-mobile/record/musicGenre/search/":
            return httpx.Response(200, text=PAGE)
        return httpx.Response(404)

    async def go():
        c = OngekiNetClient("sid", "pw", transport=httpx.MockTransport(handler), request_interval=0)
        async with c:
            await c.login()
            assert await c.course() == (True, False)
            rows = await c.scores(10)
        assert rows and rows[0].diff == "LUN"
        assert ("GET", "/ongeki-mobile/record/musicGenre/search/", "genre=99&diff=10") in seen
        from chuni.client import LoginFailed
        bad = OngekiNetClient("sid", "bad", transport=httpx.MockTransport(handler), request_interval=0)
        try:
            async with bad:
                await bad.login()
            assert False
        except LoginFailed:
            pass
    run(go())
