"""v2.5.7：根路径是主页，绑定页在 /bind；老的「/#t=令牌」链接由主页脚本转到 /bind。"""
import os
import re

import pytest

pytest.importorskip("aiohttp")
from aiohttp import web as aioweb
from aiohttp.test_utils import TestClient, TestServer

from core.bindweb import HOME_DIR, BindWeb, Binder
from tests.test_bindweb import FakePlugin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _FakeScores:
    def add_routes(self, app):
        async def page(request):
            return aioweb.Response(text="scores")
        app.router.add_get("/scores", page)


async def _client(web):
    c = TestClient(TestServer(web.app()))
    await c.start_server()
    return c


async def test_root_is_home_and_bind_moved():
    c = await _client(BindWeb(Binder(FakePlugin()), bot_name="Bot<x>", extra=[_FakeScores()]))
    try:
        r = await c.get("/")
        html = await r.text()
        assert r.status == 200 and "Bot&lt;x&gt;" in html and "{{" not in html
        assert 'href="/bind"' in html and 'href="/scores"' in html and 'class=""' in html
        assert 'id="intro"' not in html                      # 不是绑定页
        assert "script-src 'self'" in r.headers["Content-Security-Policy"] and r.headers["Cache-Control"] == "no-store"
        for path in re.findall(r'(?:src|href)="(/home/[^"?]+)', html):
            assert (await c.get(path)).status == 200, path
        for path in ("/bind", "/bind/"):
            r = await c.get(path)
            page = await r.text()
            assert r.status == 200 and 'id="intro"' in page and '<script src="/app.js?v=300">' in page
        assert (await c.get("/app.js")).status == 200 and (await c.get("/app.css")).status == 200
        assert (await c.get("/home/main.py")).status == 404 and (await c.get("/home/..%2Fapp.js")).status == 404
    finally:
        await c.close()


async def test_home_hides_scores_card_when_there_is_no_score_site():
    c = await _client(BindWeb(Binder(FakePlugin())))
    try:
        html = await (await c.get("/")).text()
        assert 'class="no-scores"' in html
    finally:
        await c.close()
    css = open(os.path.join(HOME_DIR, "app.css"), encoding="utf-8").read()
    assert ".no-scores .pass-scores" in css


def test_home_files_follow_site_rules():
    html = open(os.path.join(HOME_DIR, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(HOME_DIR, "app.js"), encoding="utf-8").read()
    css = open(os.path.join(HOME_DIR, "app.css"), encoding="utf-8").read()
    assert "style=" not in html and "<style" not in html and "<script>" not in html
    assert ".innerHTML" not in js and "http" not in css
    # 外链只有开源仓库一个；别的都是本站路径
    outside = [u for u in re.findall(r'(?:src|href)="([^"]+)"', html) if not u.startswith(("/", "#n-"))]      # #n-*：开场里引用本页的音符剪影
    assert outside == ["https://github.com/KingClup/astrbot_plugin_otoge_prober"], outside
    assert "app.css?v=300" in html and "app.js?v=300" in html and "/yume.js?v=300" in html
    # 老链接：带令牌打开根路径 → 原样转到 /bind
    assert 'location.replace("/bind" + location.hash)' in js
    # 看板娘图没有也不留破图
    assert "naturalWidth" in js and ".window.no-girl .girl" in css


def test_bind_link_points_at_bind_path():
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert 'f"{url}/bind#t={token}"' in src and 'f"{url}/#t={token}"' not in src
