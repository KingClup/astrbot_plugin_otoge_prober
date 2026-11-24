"""v3.1.0：成绩图底下的站点条（带二维码和 QQ 号）、主人看的使用统计、公开名片。"""
import io
import os
import re

import pytest
from PIL import Image

from core import brand, qr
from core.cards import Cards
from core.route import route
from core.stats import Stats, norm_sub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- 二维码 ----------
def test_qr_shape_and_finders():
    m = qr.matrix("https://bind.example.com")
    n = len(m)
    assert n in (21, 25, 29, 33, 37) and all(len(r) == n for r in m)
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):            # 三个定位角：外圈黑、里圈白、中心 3×3 黑
        assert all(m[r0][c0 + i] and m[r0 + 6][c0 + i] and m[r0 + i][c0] and m[r0 + i][c0 + 6] for i in range(7))
        assert not any(m[r0 + 1][c0 + i] for i in range(1, 6)) and all(m[r0 + 3][c0 + i] for i in range(2, 5))
    assert m[n - 8][8] == 1                                     # 固定的那个黑点
    with pytest.raises(ValueError):
        qr.matrix("x" * 200)


def test_qr_decodes_back():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    for text in ("https://bind.example.com", "https://bind.example.com/u/abcdefgh23", "http://127.0.0.1:8088"):
        img = qr.image(text, scale=8, border=4, dark=(0, 0, 0))
        got, _, _ = cv2.QRCodeDetector().detectAndDecode(np.array(img.convert("L")))
        assert got == text


# ---------- 站点条 ----------
def _pic(w=1200, h=900, fmt="JPEG"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (240, 244, 250)).save(buf, fmt)
    return buf.getvalue()


def test_stamp_adds_strip_and_keeps_format():
    for fmt in ("JPEG", "PNG"):
        src = _pic(fmt=fmt)
        out = brand.stamp(src, "https://bind.example.com", "10000001", "Bot")
        a, b = Image.open(io.BytesIO(src)), Image.open(io.BytesIO(out))
        assert b.format == fmt and b.width == a.width and 90 <= b.height - a.height <= 140


def _edge(img, y0):
    return img.convert("RGB").crop((0, y0, 6, img.height)).resize((1, 1)).getpixel((0, 0))


def test_strip_continues_the_picture_it_sits_under():
    """页脚的底色是从原图最下面接下来的，不是固定的一种颜色。"""
    for color in ((250, 214, 236), (12, 20, 18), (255, 255, 255), (90, 86, 70)):
        buf = io.BytesIO()
        Image.new("RGB", (1200, 600), color).save(buf, "PNG")
        out = Image.open(io.BytesIO(brand.stamp(buf.getvalue(), "https://bind.example.com", "10000001")))
        got = _edge(out, 600 + 60)
        assert all(abs(g - c) <= 6 for g, c in zip(got, color)), (color, got)


def test_strip_themes_and_fallback():
    dark = Image.new("RGB", (1400, 300), (10, 20, 16))
    light = Image.new("RGB", (1400, 300), (252, 246, 250))
    outs = {}
    for name in ("mai", "chu", "geki", "sdvx", "help", "", "没见过的"):
        for tag, base in (("d", dark), ("l", light)):
            s = brand.strip(1400, "https://bind.example.com", "10000001", "Bot", name, base)
            assert s is not None and s.size == (1400, 118)
            outs[name, tag] = s.tobytes()
    assert len(set(outs.values())) >= 8                      # 各游戏各一个样
    assert brand._pick("chu", (250, 250, 250)) is brand.THEMES["light"]      # 白字主题碰上浅底：自动换深色字
    assert brand._pick("geki", (8, 8, 8)) is brand.THEMES["dark"]
    assert brand._pick("chuni", (60, 60, 60)) is brand.THEMES["chu"] and brand._pick("mai", (0, 0, 0)) is brand.THEMES["mai"]


def test_strip_on_busy_bottom_does_not_streak():
    """原图底边正好切在内容上：不把那一行原样拉成竖条。"""
    base = Image.new("RGB", (1200, 400), (240, 240, 240))
    px = base.load()
    for x in range(1200):
        if (x // 37) % 2:
            for y in range(380, 400):
                px[x, y] = (20, 30, 160)
    s = brand.strip(1200, "https://bind.example.com", "1234567", "Bot", "", base).convert("L")
    row = list(s.crop((0, 4, 1200, 5)).tobytes())
    assert max(abs(a - b) for a, b in zip(row[450:650], row[451:651])) < 12


def test_stamp_leaves_small_or_broken_images_alone():
    small = _pic(w=500, h=300)
    assert brand.stamp(small, "https://bind.example.com", "1") == small
    assert brand.stamp(b"not an image", "https://bind.example.com", "1") == b"not an image"
    assert brand.stamp(_pic(), "", "") == _pic()                  # 网站和 QQ 号都没有：不加


def test_strip_without_site_still_shows_qq_and_host_of():
    assert brand.host_of("https://bind.example.com/") == "bind.example.com"
    assert brand.host_of("http://1.2.3.4:8088") == "1.2.3.4:8088"
    s = brand.strip(1400, "", "10000001", "Bot")
    assert s is not None and s.width == 1400
    assert brand.strip(1400, "", "", "Bot") is None


# ---------- 统计 ----------
def test_stats_counts_people_not_names(tmp_path):
    p = str(tmp_path / "stats.json")
    s = Stats(p)
    s.hit("10001", "mai", "b50", private=True)
    s.hit("10001", "mai", "b50", private=False, group="555")
    s.hit("10002", "chu", "我随便打的一句话", private=False, group="555", official=True)
    s.bump("funnel", "bind_issued", 4)
    s.bump("funnel", "bind_done", 1)
    s.bump("web", "home", 3)
    s.bump("ref", "github.com")
    s.save()
    raw = open(p, encoding="utf-8").read()
    assert "10001" not in raw and "555" not in raw and "随便" not in raw       # 不存 QQ 号、群号、原话
    t = Stats(p).report(7)
    assert "用过的人：2 个" in t and "指令：3 次" in t and "有人用的群：1 个" in t
    assert "发出 4" in t and "25%" in t and "主页 3" in t and "github.com 1" in t and "官方机器人 1 次" in t
    assert norm_sub("B50") == "b50" and norm_sub("这是一句话") == "其他"


def test_stats_empty_report(tmp_path):
    assert "还没有记到" in Stats(str(tmp_path / "s.json")).report(7)


# ---------- 名片 ----------
def test_cards_lifecycle(tmp_path):
    c = Cards(str(tmp_path))
    assert c.get("1") is None and c.update("1", "mai", _pic()) is False        # 没开的人不存
    u = c.enable("1", "小明")
    slug = u["slug"]
    assert re.fullmatch(r"[a-z0-9]{10}", slug) and c.public(slug)["games"] == []
    assert c.update("1", "mai", _pic(), 15234, "国服") and c.update("1", "sdvx", _pic(fmt="PNG"), 17.123)
    assert c.update("1", "nope", _pic()) is False
    pub = Cards(str(tmp_path)).public(slug)                                   # 重开一次还在
    assert pub["name"] == "小明" and [g["game"] for g in pub["games"]] == ["mai", "sdvx"]
    g = pub["games"][0]
    assert g["rating"] == 15234 and g["label"] == "国服" and g["img"].startswith(f"/u/{slug}/mai.jpg?t=")
    assert "1" not in str(pub.get("uid", "")) and "uid" not in pub and "qq" not in pub
    assert c.image_path(slug, "mai.jpg") and c.image_path(slug, "sdvx.png")
    assert c.image_path(slug, "../cards.json") is None and c.image_path(slug, "mai.png") is None
    new = c.relink("1")["slug"]
    assert new != slug and c.public(slug) is None and c.public(new)["games"]
    assert c.disable("1") and c.public(new) is None and not os.path.isdir(tmp_path / "cards" / new)
    assert c.disable("1") is False


def test_card_route():
    r = route("/名片 开")
    assert r is not None and r.game == "core" and r.argline == "名片 开"
    assert route("/名片").argline == "名片" and route("/我的名片 关").argline == "名片 关"
    assert route("名片 开") is None                      # 不带斜杠的闲聊不接


aiohttp = pytest.importorskip("aiohttp")


async def test_card_page_and_api(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    from core.bindweb import BindWeb, Binder
    from tests.test_bindweb import FakePlugin
    web = BindWeb(Binder(FakePlugin()), bot_name="Bot")
    web.cards = Cards(str(tmp_path))
    web.stats = Stats(str(tmp_path / "stats.json"))
    web.brand_qq = "10000001"
    slug = web.cards.enable("42", "K")["slug"]
    web.cards.update("42", "chu", _pic(), 16.82, "国际服")
    c = TestClient(TestServer(web.app()))
    await c.start_server()
    try:
        r = await c.get(f"/u/{slug}")
        html = await r.text()
        assert r.status == 200 and "{{" not in html and 'data-qq="10000001"' in html
        assert r.headers["X-Robots-Tag"] == "noindex" and "script-src 'self'" in r.headers["Content-Security-Policy"]
        assert "style=" not in html and "<script>" not in html and "onclick" not in html
        for path in re.findall(r'(?:src|href)="(/card/[^"?]+)', html):
            assert (await c.get(path)).status == 200, path
        j = await (await c.get(f"/api/card/{slug}")).json()
        assert j["name"] == "K" and j["qq"] == "10000001" and j["games"][0]["rating"] == 16.82 and "42" not in str(j)
        img = await c.get(j["games"][0]["img"])
        assert img.status == 200 and img.headers["Content-Type"] == "image/jpeg"
        assert (await c.get("/u/zzzzzzzzzz")).status == 404 and (await c.get("/api/card/zzzzzzzzzz")).status == 404
        assert (await c.get(f"/u/{slug}/..%2F..%2Fcards.json")).status == 404
        web.cards.disable("42")
        assert (await c.get(f"/u/{slug}")).status == 404 and (await c.get(j["games"][0]["img"])).status == 404
        s = web.stats.summary(1)
        assert s["funnel"].get("card_view") == 1 and s["web"].get("card", 0) >= 1
    finally:
        await c.close()


def test_card_files_follow_site_rules():
    js = open(os.path.join(ROOT, "web", "card", "app.js"), encoding="utf-8").read()
    assert "innerHTML" not in js and "eval(" not in js and "document.write" not in js
    css = open(os.path.join(ROOT, "web", "card", "app.css"), encoding="utf-8").read()
    assert "@import" not in css and "http" not in css
