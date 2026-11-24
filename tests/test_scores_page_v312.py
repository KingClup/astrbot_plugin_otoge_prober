"""v3.1.2：传分网站手机上的传分面板、领航员图上传（CSP 只认 data: 图）和框选。"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


def test_images_never_go_through_blob_urls():
    """CSP 是 img-src 'self' data:：blob: 链接给 <img> 会被拦，所有图都会「读不了」（v3.1.1 以前的坏法）。"""
    from core.bindweb import SECURITY_HEADERS
    csp = SECURITY_HEADERS["Content-Security-Policy"]
    assert "blob:" not in csp
    for d in ("scores", "bind", "home", "card"):
        for f in os.listdir(os.path.join(ROOT, "web", d)):
            if f.endswith(".js"):
                assert "createObjectURL" not in _read("web", d, f), f"{d}/{f}"
    js = _read("web", "scores", "app.js")
    assert "createImageBitmap" in js and "readAsDataURL" in js


def test_sheet_can_always_be_closed_on_phones():
    js = _read("web", "scores", "app.js")
    css = _read("web", "scores", "app.css")
    assert 'class: "sheet-x"' in js and 'text: "取消"' in js            # 右上角关闭 + 底下取消
    assert "popstate" in js and "history.pushState({ sheet: 1 }" in js     # 手机的「返回」关面板
    assert "overscroll-behavior: contain" in css and "html.sheet-open body { position: fixed" in css
    m = re.search(r"\.sheet-in \{[^}]*\}", css)
    assert m and "92vh" not in m.group(0) and "dvh" in m.group(0)       # 不再几乎占满整屏


def test_nav_crop_matches_b50_panel():
    """框选的形状 = B50 上领航员那一块（名片条里六维图右边）。"""
    from scorebook import sdvx_img as M
    w = M.W - 2 * M.MX - 40 - 760 - 24
    h = M.PROFILE_H - 18 - 28
    js = _read("web", "scores", "app.js")
    assert f"const NAV_W = {w}, NAV_H = {h};" in js
    assert f"aspect-ratio: {w} / {h};" in _read("web", "scores", "app.css")
