"""v2.3.7：绑定网站改版（开场页 + 看板娘图片）。只测服务端：图片路由、页面结构、CSP 不放松。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.bindweb import Binder, BindWeb, WEB_DIR  # noqa: E402
from tests.test_bindweb import FakePlugin, _client, run  # noqa: E402


HAS_GIRL = os.path.isfile(os.path.join(WEB_DIR, "img", "yume-hello.webp"))     # 看板娘图只在自用版里


def test_images_route():
    if not HAS_GIRL:
        import pytest
        pytest.skip("公开版没有看板娘图片")
    web = BindWeb(Binder(FakePlugin()), bot_name="Bot")

    async def go():
        c = await _client(web)
        try:
            for name in ("yume-hello", "yume-ok", "yume-gone", "yume-pass", "yume-wave", "yume-shh", "yume-peace", "yume-think"):
                r = await c.get(f"/img/{name}.webp")
                body = await r.read()
                assert r.status == 200 and r.content_type == "image/webp" and body[:4] == b"RIFF"
                assert r.headers["Cache-Control"] == "public, max-age=86400"
                assert r.headers["X-Content-Type-Options"] == "nosniff"
            for bad in ("/img/nope.webp", "/img/..%2Fapp.js", "/img/%2e%2e%2f%2e%2e%2fmain.py", "/img/yume-ok.png",
                        "/img/YUME-OK.webp", "/img/"):
                assert (await c.get(bad)).status == 404, bad
            # 页面和接口照旧不缓存
            assert (await c.get("/")).headers["Cache-Control"] == "no-store"
        finally:
            await c.close()
    run(go())


def test_page_has_intro_and_keeps_csp_rules():
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(WEB_DIR, "app.js"), encoding="utf-8") as f:
        js = f.read()
    with open(os.path.join(WEB_DIR, "app.css"), encoding="utf-8") as f:
        css = f.read()
    assert 'id="intro"' in html and 'id="enter"' in html and 'id="main" hidden' in html
    # CSP 是 style-src 'self' / script-src 'self'：页面里不能有行内样式、行内脚本、外链资源
    assert " style=" not in html and "<style" not in html and "onclick" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert "innerHTML" not in js and ".style." not in js
    assert not re.search(r"https?://", css) and "@import" not in css
    # 图片都在 /img/ 下，而且文件真的在包里
    for src in re.findall(r'src="(/img/[^"]+)"', html):
        assert src.startswith("/img/yume-") and src.endswith(".webp"), src
        if HAS_GIRL:
            assert os.path.isfile(os.path.join(WEB_DIR, src.lstrip("/"))), src
    # 开场不耽误领链接：/api/session 不在任何点击 / 定时回调里才发
    assert js.index('api("/api/session")') > js.index("function introReady")
    assert "prefers-reduced-motion" in css and "prefers-reduced-motion" in js


def test_scores_theme_bits():
    """v2.3.8：传分网站按游戏分主题、灯按钮带颜色类、顶栏有看板娘。"""
    root = os.path.join(os.path.dirname(WEB_DIR), "scores")
    with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(root, "app.js"), encoding="utf-8") as f:
        js = f.read()
    with open(os.path.join(root, "app.css"), encoding="utf-8") as f:
        css = f.read()
    assert 'src="/img/yume-pass.webp"' in html and " style=" not in html
    assert '"lp L-" + (k || "NONE")' in js and '"lp L-BELL"' in js and ".innerHTML" not in js
    for cls in ("L-PUC", "L-UC", "L-MXV", "L-EXC", "L-COMP", "L-PLAY", "L-AB", "L-FC", "L-NONE", "L-BELL"):
        assert "." + cls + " { --lc:" in css, cls
    assert 'body[data-game="sdvx"]' in css and 'body[data-game="geki"]' in css
    assert not re.search(r"https?://", css) and "@import" not in css


def test_scores_gate_and_motion():
    """v2.3.9：传分网站入口页（两扇门）+ 动效都在，且尊重「减少动态效果」。"""
    root = os.path.join(os.path.dirname(WEB_DIR), "scores")
    with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(root, "app.js"), encoding="utf-8") as f:
        js = f.read()
    with open(os.path.join(root, "app.css"), encoding="utf-8") as f:
        css = f.read()
    assert 'id="gate"' in html and 'data-game="sdvx" disabled' in html and 'data-game="geki" disabled' in html
    assert " style=" not in html and 'src="/img/yume-wave.webp"' in html       # 入口用挥手那张，和绑定站开场不是同一张
    for used in ("yume-shh.webp", "yume-peace.webp", "yume-think.webp"):
        assert used in js, used
    assert "function gateClose" in js and 'sessionStorage.getItem("sb_gate")' in js
    assert 'hp.get("k") || hp.get("q")' in js                       # 直达链接不放入口页
    assert js.index("await applyHash(true);") < js.index("gateReady();\n  }\n  init();")   # 登录 / 选游戏先做完，门才能点
    assert ".songs.fresh .song" in css and ".pill.just" in css and "prefers-reduced-motion" in css
    for p in ("views/a_overview/index.html", "views/mai/index.html", "views/chuni/style.css"):
        with open(os.path.join(os.path.dirname(os.path.dirname(WEB_DIR)), p), encoding="utf-8") as f:
            assert "prefers-reduced-motion" in f.read(), p


def test_private_scores_link_always_has_login_token():
    """v2.3.9：私聊 /传分 不管有没有登录着都带登录链接（只看 main.py 里的条件，不起 AstrBot）。"""
    with open(os.path.join(os.path.dirname(os.path.dirname(WEB_DIR)), "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert "if n_sess and not force and not ctx.private:" in src


def test_confirm_poll_survives_failed_request():
    """v2.3.10：等确认码时一次请求失败不能让轮询停掉；回到前台马上再问。"""
    root = os.path.join(os.path.dirname(WEB_DIR), "scores")
    with open(os.path.join(root, "app.js"), encoding="utf-8") as f:
        js = f.read()
    with open(os.path.join(root, "app.css"), encoding="utf-8") as f:
        css = f.read()
    assert "catch (e) { return { _status: 0, offline: true }; }" in js
    body = js[js.index("function waitConfirm(d) {"):js.index("async function goTo(nav) {")]
    assert '"visibilitychange", "focus", "pageshow", "online"' in body and "removeEventListener(ev, wake)" in body
    assert "!r.offline" in body and "pend-go" in body
    assert ".pend .pend-go" in css and ".pend-rule i" in css


def test_confirm_code_copy_button():
    """v2.3.11：确认命令能一键复制。"""
    root = os.path.join(os.path.dirname(WEB_DIR), "scores")
    with open(os.path.join(root, "app.js"), encoding="utf-8") as f:
        js = f.read()
    body = js[js.index("function waitConfirm(d) {"):js.index("async function goTo(nav) {")]
    assert 'class: "pend-copy"' in body and "await copyText(cmd)" in body and 'const cmd = "/传分 确认 " + d.code;' in body


def test_pending_login_survives_page_reload():
    """v2.3.13：等确认码的状态存在浏览器里，页面被关 / 刷新后接着等。"""
    root = os.path.join(os.path.dirname(WEB_DIR), "scores")
    with open(os.path.join(root, "app.js"), encoding="utf-8") as f:
        js = f.read()
    assert 'store.set("sb_pend", JSON.stringify({ p: d.pid, c: d.code, e: end }));' in js
    assert 'store.del("sb_pend");' in js and "function readPend()" in js
    assert "if (nav.t || (first && readPend())) {" in js
    body = js[js.index("async function login(t) {"):js.index("// 群里发的链接：显示 4 位码")]
    assert "resumed: true" in body and 'me.login === false' in body


def test_login_logs_browser_family_only():
    from scorebook.web import ScoreWeb

    class R:
        def __init__(self, ua):
            self.headers = {"User-Agent": ua}
    assert ScoreWeb._ua(R("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) AppleWebKit/605 Version/18.0 Mobile Safari/604.1")) == "safari/ios"
    assert ScoreWeb._ua(R("Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile Safari/537.36 QQ/9.0.0")) == "qq-app/android"
    assert ScoreWeb._ua(R("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/151.0.0.0 Safari/537.36")) == "chrome/mac"
    assert ScoreWeb._ua(R("")) == "unknown"


# ---------------------------------------------------------------- v2.4.0：B50 图重画
def test_lx_profile_plate_frame_class():
    from mai.service import lx_profile
    p = lx_profile({"name": "x", "rating": 15000, "icon": {"id": 1}, "name_plate": {"id": 250101},
                    "frame": {"id": 558001}, "class_rank": 21, "star": 7})
    assert p.plate_url.endswith("/maimai/plate/250101.png") and p.frame_url.endswith("/maimai/frame/558001.png")
    assert p.class_rank == "icon:class_21"
    q = lx_profile({"name": "x", "rating": 1})
    assert q.plate_url == "" and q.frame_url == "" and q.class_rank == ""
    # 旧快照里没有这两个字段也读得回来
    from mai.models import Profile
    assert Profile.from_dict({"name": "a"}).frame_url == ""


def test_mai_b50_header_with_and_without_frame(tmp_path):
    import gzip
    import hashlib
    import io
    import json
    import os

    from PIL import Image

    from mai.calc.rating import attach_charts, build_best50
    from mai.data.songdb import SongDB
    from mai.models import Profile, Score
    from mai.render import b50img as R
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db = SongDB(json.load(gzip.open(os.path.join(root, "mai", "data", "dxrating_snapshot.json.gz"))))
    chs = [c for so in db.songs for c in so.charts if c.type in ("dx", "std") and c.diff == "master" and c.ds][:20]
    scs = [Score(title=c.song.title, type=c.type, diff=c.diff, level=c.level, ach=1005000, dx=100) for c in chs]
    attach_charts(scs, db, "jp")
    b = build_best50(scs, db, "jp")
    data = str(tmp_path)
    os.makedirs(os.path.join(data, "avatars"))
    for url, size in (("mock://frame", (1080, 452)), ("mock://plate", (720, 116))):
        Image.new("RGBA", size, (200, 120, 220, 255)).save(
            os.path.join(data, "avatars", hashlib.sha1(url.encode()).hexdigest() + ".png"))
    plain = R.B50Renderer(data)(b, Profile(name="P", rating=b.total, region="jp"), db, None)
    framed = R.B50Renderer(data)(b, Profile(name="P", rating=b.total, region="cn", plate_url="mock://plate",
                                            frame_url="mock://frame", class_rank="icon:class_21", stars=3), db, None)
    h0 = Image.open(io.BytesIO(plain)).height
    h1 = Image.open(io.BytesIO(framed)).height
    assert h1 - h0 == R.HEADER_H_FRAME - R.HEADER_H


def test_sdvx_card_fits_and_geki_mascot_optional(tmp_path, monkeypatch):
    from scorebook import sdvx_img as S
    assert S.COLS * S.CARD_W + (S.COLS - 1) * S.GAP_X + 2 * S.MX <= S.W
    assert S.JK + 52 + 16 <= S.CARD_H
    # 包里没有看板娘图（公开版）时头像位退回写名字的第一个字，不报错
    from ongeki import b50img as GB
    monkeypatch.setattr(GB, "_ASSET_DIR", tmp_path)
    GB._sprites.clear()
    assert GB._mascot(64) is None
    from PIL import Image
    im = Image.new("RGBA", (400, 400), (0, 0, 0, 255))
    S._avatar(im, 200, 200, 96, "Kc")
    GB._sprites.clear()


def test_scores_hero_big_and_compact():
    """v2.4.0：成绩那一块放大（没成绩也一样大），往下翻收成一小条。"""
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "scores")
    css = open(os.path.join(root, "app.css"), encoding="utf-8").read()
    js = open(os.path.join(root, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(root, "index.html"), encoding="utf-8").read()
    assert "min-height: 150px" in css and "body.compact .herobox" in css and "body.compact .hero-girl" in css
    assert 'class: "hn none"' in js and '"还没传"' in js
    assert 'classList.toggle("compact"' in js and "ResizeObserver" in js
    assert "app.css?v=2405" in html and "app.js?v=2405" in html


def test_help_image_bind_style_and_poses(tmp_path, monkeypatch):
    """v2.4.0：帮助图和绑定网站一套（藏青 / 宋体标题 / 看板娘），每页姿势不一样；包里没有看板娘图也能画。"""
    from core import help as H
    from mai.render import fonts as F
    assert H.CORE == H.NAVY == (27, 42, 74) and "serif" in F._CANDIDATES
    assert set(H.TOPIC_POSE) == set(H.TOPIC_ORDER) and len(set(H.TOPIC_POSE.values())) >= 7
    assert H.GUIDE[0][1] != H.NAVY                        # 游戏色不动
    monkeypatch.setattr(H, "_GIRL_DIR", tmp_path)
    H._girls.clear()
    assert H.render_topic("pjsk", "Bot")[:4] == b"\x89PNG"
    H._girls.clear()
    import os
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "scores", "app.js"),
              encoding="utf-8").read()
    for pose in ("pass", "think", "ok", "wave"):
        assert f'"{pose}"' in js


def test_sdvx_view_tabs_spread():
    import os
    css = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "scores", "app.css"),
               encoding="utf-8").read()
    assert 'body[data-game="sdvx"] .views button { flex: 1;' in css


def test_webbind_confirm_route_and_guide_style():
    """v2.4.1：/网页绑定 确认 码 能路由到；绑定说明图、进度图用帮助图那一套。"""
    from core import bindguide as B
    from core import help as H
    from core import progress_img as PG
    from core import route as R
    assert R.route("/网页绑定").argline == "网页绑定"
    assert R.route("/网页绑定 确认 1234").argline == "网页绑定 确认 1234"
    assert R.route("/网页绑定确认 12 34").argline == "网页绑定 确认 1234"
    assert B.NAVY == H.NAVY == PG.NAVY and B.render_bind_guide("Bot")[:4] == b"\x89PNG"
    assert any("确认码" in x for x in B.SAFETY)
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "bind")
    html = open(os.path.join(root, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(root, "app.js"), encoding="utf-8").read()
    assert 'id="confirm"' in html and 'id="confirmCopy"' in html and "style=" not in html
    assert "j.pending" in js and "localStorage" in js and ".innerHTML" not in js


def test_pages_cope_without_mascot_images():
    """v2.4.5：公开版包里没有看板娘图 → 网页不留空位，结果页不放图。"""
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
    for site in ("bind", "scores"):
        js = open(os.path.join(root, site, "app.js"), encoding="utf-8").read()
        css = open(os.path.join(root, site, "app.css"), encoding="utf-8").read()
        assert "girl-missing" in js and "naturalWidth" in js and ".girl-missing { display: none !important; }" in css
    assert "no-hero-girl" in open(os.path.join(root, "scores", "app.css"), encoding="utf-8").read()
    src = open(os.path.join(os.path.dirname(root), "core", "bindweb.py"), encoding="utf-8").read()
    assert "公开版包里没有这张图" in src
