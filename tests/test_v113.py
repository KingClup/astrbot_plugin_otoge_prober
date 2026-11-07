"""v1.13.0：版本号（小版本号）、版本进度图、帮助图「现在的版本」、绑定说明图加私服、私服 B50 标客户端版本号。"""
from __future__ import annotations

import io

from PIL import Image

from core import bindguide, help as H
from core import progress_img as PG
from core.progress import CHU_VERSION_NUMBERS, ProgressTracker, mai_code_ver


def _png_size(b: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(b)).size


# ---------------------------------------------------------------- 版本号
def test_mai_code_ver():
    assert mai_code_ver("27004") == "1.70" and mai_code_ver(25506) == "1.55" and mai_code_ver("26502") == "1.65"
    assert mai_code_ver("") == "" and mai_code_ver("abc") == ""


def test_mai_code_picks_newest_batch_of_current_version(tmp_path):
    t = ProgressTracker(str(tmp_path))
    t.official[("mai", "jp")] = (
        [{"title": f"m{i}", "version": "27000", "catcode": "maimai"} for i in range(6)]
        + [{"title": f"n{i}", "version": "27004", "catcode": "maimai"} for i in range(5)]
        + [{"title": "宴", "version": "27509", "catcode": "宴会場"}]           # 宴不算
        + [{"title": "old", "version": "26502", "catcode": "maimai"}])
    t.official[("mai", "intl")] = [{"title": f"c{i}", "version": "26502", "catcode": "maimai"} for i in range(6)]
    import asyncio
    st = asyncio.run(t.refresh(download=False))
    assert st.get("mai", "jp").current == "MAGiCAL" and st.get("mai", "jp").code == "27004"
    assert st.get("mai", "intl").code == "26502"
    assert st.get("chu", "jp").code == ""                                  # 中二没有官方版本码


def test_chu_version_numbers_only_confirmed():
    assert CHU_VERSION_NUMBERS["Mate"] == "2.50"
    assert "X-VERSE" not in CHU_VERSION_NUMBERS and "X-VERSE-X" not in CHU_VERSION_NUMBERS


# ---------------------------------------------------------------- 进度：文字 + 图
def _view():
    R = PG.ProgressRow
    v = PG.ProgressView(when="11-07 01:50", hour=12, changes=["舞萌日服：CiRCLE PLUS → MAGiCAL"])
    v.games = [("舞萌 DX", [R("日服", "MAGiCAL", "27004", "官方曲目表 31 首 MAGiCAL"),
                           R("国服", "PRiSM PLUS", "25506", "DXRating 曲库 · 落雪曲目表")]),
               ("中二节奏", [R("日服", "Mate", "2.50", "官方曲目表 73 首 Mate · 曲库 X-VERSE-X", "曲库还停在 X-VERSE-X")])]
    v.sections = [("定数", ["· 中二日服：8320 张"])]
    v.sources = ["官方曲目表 mai/jp ok 1607 首"]
    return v


def test_progress_text_has_numbers():
    t = PG.text(_view())
    assert "日服：MAGiCAL · 27004（官方曲目表 31 首 MAGiCAL）" in t
    assert "国服：PRiSM PLUS · 25506" in t and "Mate · 2.50" in t and "⚠ 曲库还停在 X-VERSE-X" in t
    assert "最近变化：舞萌日服：CiRCLE PLUS → MAGiCAL" in t


def test_progress_image_renders():
    w, h = _png_size(PG.render(_view(), "Bot"))
    assert w == 1080 and h > 1000


# ---------------------------------------------------------------- 帮助图
def test_help_overview_is_one_screen_and_topics_split():
    vers = [("mai", "日服", "MAGiCAL", "27004"), ("chu", "日服", "Mate", "2.50")]
    w0, h0 = _png_size(H.render_help("Bot"))
    _w, h1 = _png_size(H.render_help("Bot", None, vers))
    assert w0 == 1600 and h0 < 1800 and h1 > h0           # 总览一屏，版本行只是多一点
    for key in H.TOPIC_ORDER:
        w, h = _png_size(H.render_topic(key, "Bot"))
        assert w == 1600 and h < 2400, key
    assert _png_size(H.render_full("Bot"))[1] > 6000
    # 文字版：总览 / 主题 / 全部
    ov = H.help_text()
    assert "/mai 帮助" in ov and "/猜歌 帮助" in ov and "/sdvx 帮助" in ov and "/pjsk 帮助" in ov and "/谱面 帮助" in ov
    assert "分数线" in H.help_text("mai") and "分数线" not in H.help_text("chu")
    full = H.help_text("all")
    assert "版本号" in full and "Ver.x.xx" in full and "MuNET" in full and "开字母" in full
    assert H.topic_key("舞萌") == "mai" and H.topic_key("sdvx") == "sdvx" and H.topic_key("烧烤") == "pjsk"
    assert H.topic_key("谱面") == "chart" and H.topic_key("全") == "all"
    assert "sdvx.in" in H.TOPICS["chart"].intro and "没有查分" in H.TOPICS["sdvx"].intro
    assert H.topic_key("xx") is None


def test_help_wrap_keeps_words():
    lines = H._wrap("私服 AquaDX / MuNET：填网站个人主页 /u/ 后面的用户名，群里也能绑；舞萌中二绑一次两边都能查",
                    "regular", 23, 300, 9)
    assert all(not ln.startswith(("uNET", "quaDX", "，", "；")) for ln in lines)


# ---------------------------------------------------------------- 绑定说明图
def test_bind_guide_lists_private_servers():
    names = [s[0] for s in bindguide.SERVERS]
    assert names == ["国际服", "日服", "国服", "私服"]
    priv = dict(bindguide.SERVERS[3][2])
    assert set(priv) == {"AquaDX", "RinNET", "MuNET"} and "暂时用不了" in priv["MuNET"]
    assert "私服" in bindguide.STEPS[1][2]
    w, _h = _png_size(bindguide.render_bind_guide("Bot"))
    assert w == 1080


def test_bind_guide_wrap_no_lone_punctuation():
    from core.bindguide import _wrap
    for width in range(200, 900, 37):
        assert all(not ln.startswith(("。", "，", "）")) for ln in _wrap("MuNET 目前不允许第三方查分工具读数据。", "regular", 25, width))


# ---------------------------------------------------------------- 私服 B50 标客户端版本号
def test_mai_text_shows_client_version():
    from mai.calc.rating import Best50
    from mai.render.b50img import rom_short
    from mai.render.text import best50_text

    class DB:
        current_version = {"jp": "MAGiCAL"}

        def new_versions(self, r):
            return []

        def version_index(self, v):
            return 0
    b = Best50(region="aqua", version="PRiSM PLUS", rom="1.55.00")
    assert rom_short(b.rom) == "1.55"
    assert "PRiSM PLUS（客户端 Ver.1.55）" in best50_text(b, None, DB())


def test_chu_text_shows_client_version():
    from chuni.rating import B50
    from chuni.render import b50_text
    t = b50_text("X", B50(best=[], new=[], displayed_rating=16.9, version="Mate", rom="2.50.00"), "AquaDX")
    assert t.splitlines()[0] == "X 的 B50 · Mate（客户端 Ver.2.50）"


def test_webui_help_preview_topics():
    import asyncio
    from types import SimpleNamespace
    from core.webui import CoreWebUI
    ui = CoreWebUI(SimpleNamespace(bot_name="Bot", _help_versions=lambda: ()))
    for topic in ("", "mai", "games", "all"):
        r = asyncio.run(ui.help_preview({"topic": topic}))
        assert r["image"].startswith("data:image/jpeg") and r["topic"] == topic
        assert [t["key"] for t in r["topics"]] == list(H.TOPIC_ORDER)


def test_palette_games_distinct():
    from core import palette as P
    games = [P.MAI, P.CHU, P.GEKI, P.SDVX, P.PJSK]
    others = [P.CORE, P.CHART, P.MINIGAME, P.REQ, P.OPT, *P.REGION.values()]
    far = lambda a, b: sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 > 60  # noqa: E731
    assert all(far(a, b) for i, a in enumerate(games) for b in games[i + 1:])
    assert all(far(g, o) for g in games for o in others)
    assert P.MAI[2] > P.MAI[0] and P.CHU[0] > P.CHU[2] and P.SDVX[2] > P.SDVX[1]   # 蓝 / 金黄 / 紫
