"""猜歌小游戏：区间解析、答案判断、开字母 / 猜曲绘 / 猜谱面完整流程（假数据，离线）。"""
import asyncio
import random
from dataclasses import dataclass

import numpy as np
import pytest
from PIL import Image

from games import core as G
from games.chartcut import measures
from games.commands import GameCommands

run = asyncio.new_event_loop().run_until_complete


@dataclass
class Ctx:
    uid: str = "1"
    name: str = "阿K"
    private: bool = False


# ---------------------------------------------------------------- pure helpers

@pytest.mark.parametrize("tok,lo,hi,label", [
    ("14以上", 14.0, 99.0, None), ("14.5以上", 14.5, 99.0, None), ("13.5以下", 0.0, 13.5, None),
    ("14.7", 14.7, 14.7, None), ("14-14.5", 14.0, 14.5, None), ("13~14", 13.0, 14.9, None),
    ("１４．７", 14.7, 14.7, None),
    # 「15」「15+」按游戏的分界（resolve 之后）；下面这几条是中二
    ("15", 15.0, 15.4, None), ("15+", 15.5, 15.9, None),
])
def test_parse_range(tok, lo, hi, label):
    r = G.parse_range(tok).resolve("chu")
    assert r is not None and r.label == label
    if label is None:
        assert (r.lo, r.hi) == pytest.approx((lo, hi))


def test_parse_range_rejects_words():
    assert G.parse_range("舞萌") is None and G.parse_range("abc") is None


def test_range_ok():
    c = G.Chart("MASTER", "14+", 14.7)
    R = lambda t, g="chu": G.parse_range(t).resolve(g)  # noqa: E731
    assert R("14.7").ok(c) and R("14以上").ok(c) and R("14+").ok(c)
    assert not R("14.6").ok(c) and not R("15").ok(c)
    assert not R("14").ok(G.Chart("MASTER", "14", None))      # unknown constant never matches


def test_level_ranges_per_game():
    """2026-11-07 群里：『回帰』 MASTER 15.2 被「15+」抽到；应该是 15 = 15.0～15.4、15+ = 15.5～15.9。
    哪怕曲库里印的等级是旧的「15+」，也按定数算。"""
    kaiki = G.Chart("MASTER", "15+", 15.2)
    R = lambda t, g: G.parse_range(t).resolve(g)  # noqa: E731
    assert not R("15+", "chu").ok(kaiki) and R("15", "chu").ok(kaiki)
    assert R("15+", "chu").ok(G.Chart("MASTER", "15+", 15.5)) and not R("15", "chu").ok(G.Chart("MASTER", "15", 15.5))
    # 舞萌：14 = 14.0～14.5，14+ = 14.6～14.9
    assert R("14", "mai").ok(G.Chart("MASTER", "14", 14.5)) and R("14+", "mai").ok(G.Chart("MASTER", "14+", 14.6))
    assert not R("14+", "mai").ok(G.Chart("MASTER", "14", 14.5))
    # 音击：14 = 14.0～14.6，14+ = 14.7～14.9
    assert R("14", "geki").ok(G.Chart("MASTER", "14", 14.6)) and R("14+", "geki").ok(G.Chart("MASTER", "14+", 14.7))
    # SDVX / PJSK 没有「+」的定数分界：「18」= 18.x，「18+」按印的等级
    assert R("18", "sdvx").ok(G.Chart("MXM", "18", 18.3))
    assert R("30+", "pjsk").label == "30+"


def test_is_answer():
    s = G.Song("mai", "1", "SUPER AMBULANCE", ["救护车"])
    assert G.is_answer("super ambulance", s) and G.is_answer("救护车", s) and G.is_answer("SUPERAMBULANCE!", s)
    assert G.is_answer("super ambulanc", s)            # one letter missing on a long title still counts
    assert not G.is_answer("super", s) and not G.is_answer("", s)


def test_mask_and_open():
    t = "Aleph-0 天使"
    assert G.mask(t, set()) == "*****-* ＊＊"
    assert G.mask(t, {"a", "天"}) == "A****-* 天＊"
    assert not G.fully_open(t, {"a", "l", "e", "p", "h", "0", "天"})
    assert G.fully_open(t, {"a", "l", "e", "p", "h", "0", "天", "使"})


def test_mosaic_blocks():
    im = Image.new("RGB", (300, 300))
    im.paste((255, 0, 0), (0, 0, 150, 150))
    m = G.mosaic(im, 4, size=400)
    assert m.size == (400, 400)
    assert m.getpixel((10, 10)) == (255, 0, 0) and m.getpixel((390, 390)) == (0, 0, 0)
    assert len(set(m.get_flattened_data())) <= 16


def _fake_chart_bg(lanes=3, measures_per_lane=4, mh=120, lane_w=150, gap=50):
    """An sdvx.in-like bg layer: opaque lanes, dim beat lines, bright measure lines."""
    h = measures_per_lane * mh + 40
    w = gap + lanes * (lane_w + gap)
    a = np.zeros((h, w, 4), dtype=np.uint8)
    for k in range(lanes):
        x0 = gap + k * (lane_w + gap)
        a[20:h - 20, x0:x0 + lane_w] = (8, 8, 12, 255)
        for m in range(measures_per_lane + 1):
            y = h - 20 - m * mh
            a[max(0, y - 1):y + 1, x0:x0 + lane_w] = (200, 200, 200, 255)
            if m < measures_per_lane:
                for b in (1, 2, 3):
                    yb = y - b * mh // 4
                    a[yb, x0:x0 + lane_w] = (60, 60, 60, 255)
    return Image.fromarray(a, "RGBA")


def test_chartcut_finds_measures_in_play_order():
    bg = _fake_chart_bg()
    r = measures(bg)
    assert len(r) == 12
    assert all(abs((b[3] - b[1]) - 121) <= 2 for b in r)           # beat lines are not measure lines
    assert r[0][0] < r[4][0]                                       # lane 1 before lane 2
    assert r[0][1] > r[1][1]                                       # inside a lane: bottom → top


def test_sdvx_measure_rects():
    from chart.sdvx_draw import measure_rects
    chart = {"totalPulses": 960 * 12, "wraps": [0, 960 * 6]}
    r = measure_rects(chart)
    assert len(r) == 12 and r[0][1] > r[1][1] and r[6][0] > r[5][0]


def test_stack_measures_bottom_up():
    img = Image.new("RGB", (100, 300))
    img.paste((255, 0, 0), (0, 200, 100, 300))     # measure 1 (bottom)
    img.paste((0, 0, 255), (0, 100, 100, 200))     # measure 2
    r1, r2 = (0, 200, 100, 300), (0, 100, 100, 200)
    # 默认：连成一条，早的小节在下面，中间没有缝
    out = G.stack_measures(img, [r1, r2], scale=1, min_w=0, min_ratio=0)
    assert out.size == (100, 200)
    assert out.getpixel((50, 150)) == (255, 0, 0) and out.getpixel((50, 50)) == (0, 0, 255)
    assert out.getpixel((50, 100)) == (255, 0, 0) and out.getpixel((50, 99)) == (0, 0, 255)
    # 太细长时左右补边，宽度 ≥ 高 × 0.4，谱面在正中间
    out = G.stack_measures(img, [r1, r2] * 4, scale=1, min_w=0)
    assert out.height == 800 and out.width == 320
    assert out.getpixel((160, 750)) == (255, 0, 0) and out.getpixel((5, 750)) != (255, 0, 0)
    # cols>1 仍可并排
    out = G.stack_measures(img, [r1, r2], scale=1, min_w=0, min_ratio=0, cols=4, gap=6)
    assert out.size == (206, 100)


# ---------------------------------------------------------------- full games with fake data

def _songs(game="mai", n=30):
    out = []
    for i in range(n):
        const = 12.0 + (i % 30) / 10
        out.append(G.Song(game, str(i), f"Song {chr(65 + i % 26)}{i}", [f"外号{i}"],
                          [G.Chart("MASTER", f"{int(const)}{'+' if const % 1 >= .6 else ''}", round(const, 1), (i, "mst"))]))
    return out


class FakeData:
    def __init__(self):
        self.mai = _songs()
        self.chu = _songs("chu")
        self.bg = _fake_chart_bg(lanes=4, measures_per_lane=5)

    def songs(self, game, region="jp"):
        return {"mai": self.mai, "chu": self.chu}.get(game, [])

    def chart_songs(self, game):
        return self.chu

    async def ensure_charts(self, game):
        return len(self.chu)

    async def chart_picture(self, chart):
        img = Image.new("RGB", self.bg.size, (0, 0, 0))
        img.paste(self.bg.convert("RGB"))
        return img, measures(self.bg)

    async def jacket(self, song):
        im = Image.new("RGB", (200, 200), (int(song.sid) * 8 % 255, 100, 50))
        return im


def _gc():
    return GameCommands(FakeData(), rnd=random.Random(7))


def test_letters_game_flow():
    gc = _gc()
    r = run(gc.handle("g1", Ctx(), "/猜歌 舞萌 13以上", command=True))
    assert "开字母 · 舞萌 · 定数 13以上 · 10 首" in r.texts[0]
    s = gc.sessions["g1"]
    assert all(p.chart.const >= 13 for p in s.picks)
    # plain chat during the game is not ours
    assert run(gc.handle("g1", Ctx(), "今天好热", command=False)) is None
    r = run(gc.handle("g1", Ctx(), "开 s", command=False))
    assert "10 首里有" in r.texts[0] and "S" in r.texts[0]
    r = run(gc.handle("g1", Ctx(), "开 s", command=False))
    assert "已经开过了" in r.texts[0]
    # guess by title and by alias
    t0 = s.picks[0].song.title
    r = run(gc.handle("g1", Ctx(name="小明"), t0.lower(), command=False))
    assert f"✓ 小明 猜中 1. {t0}" in r.texts[0]
    alias = s.picks[1].song.aliases[0]
    r = run(gc.handle("g1", Ctx(name="小红"), alias, command=False))
    assert "小红" in r.texts[0]
    # an explicit wrong guess gets an answer, a silent one does not
    assert run(gc.handle("g1", Ctx(), "猜 不存在的歌", command=False)).texts == ["不对哦"]
    assert run(gc.handle("g1", Ctx(), "不存在的歌", command=False)) is None
    r = run(gc.handle("g1", Ctx(), "结束", command=False))
    assert "全部答案" not in r.texts[0] and "答案" in r.texts[0] and "小明 ×1" in r.texts[0]
    assert "g1" not in gc.sessions


def test_letters_open_everything_ends_game():
    gc = _gc()
    run(gc.handle("g2", Ctx(), "/猜歌 舞萌 12.3", command=True))
    s = gc.sessions["g2"]
    assert len(s.picks) == 1
    title = s.picks[0].song.title
    chars = "".join(dict.fromkeys(c for c in title.lower() if c.isalnum()))
    r = run(gc.handle("g2", Ctx(), f"开 {chars}", command=False))
    assert "开出来了" in r.texts[0] and "g2" not in gc.sessions


def test_one_game_per_chat_and_bad_args():
    gc = _gc()
    run(gc.handle("g3", Ctx(), "/猜歌", command=True))
    r = run(gc.handle("g3", Ctx(), "/猜曲绘", command=True))
    assert "还有一局开字母没结束" in r.texts[0]
    r = run(gc.handle("g4", Ctx(), "/猜歌 舞萌 好难", command=True))
    assert "没看懂「好难」" in r.texts[0]
    r = run(gc.handle("g4", Ctx(), "/猜谱面 舞萌", command=True))
    assert "sdvx.in 没有舞萌" in r.texts[0]
    r = run(gc.handle("g4", Ctx(), "/猜歌 舞萌 99以上", command=True))
    assert "没有符合" in r.texts[0]
    # a start command in a group without slash / @ is just chat
    assert run(gc.handle("g5", Ctx(), "猜歌", command=False)) is None


def test_jacket_game_flow():
    gc = _gc()
    r = run(gc.handle("g6", Ctx(), "/猜曲绘 中二 13-14", command=True))
    assert r.image and "猜曲绘 · 中二 · 定数 13-14" in r.texts[0]
    first = Image.open(__import__("io").BytesIO(r.image))
    assert len(set(first.get_flattened_data())) <= 16                     # 4×4 blocks
    r = run(gc.handle("g6", Ctx(), "提示", command=False))
    assert r.image and "6×6" in r.texts[0]
    s = gc.sessions["g6"]
    r = run(gc.handle("g6", Ctx(name="小明"), s.picks[0].song.title, command=False))
    assert "✓ 小明 猜中了" in r.texts[0] and "答案：" in r.texts[1 if len(r.texts) > 1 else 0] or "答案" in r.texts[0]
    assert r.image and "g6" not in gc.sessions


def test_chart_game_flow():
    gc = _gc()
    r = run(gc.handle("g7", Ctx(), "/猜谱面 中二 14以上", command=True))
    assert r.image and "这是其中 1 个小节" in r.texts[0]
    one = Image.open(__import__("io").BytesIO(r.image))
    r = run(gc.handle("g7", Ctx(), "提示", command=False))
    two = Image.open(__import__("io").BytesIO(r.image))
    assert "2 个小节" in r.texts[0] and two.height > one.height
    r = run(gc.handle("g7", Ctx(), "结束", command=False))
    assert "答案：" in r.texts[0] and "MASTER" in r.texts[0]


def test_expired_session_is_dropped_but_answered():
    gc = _gc()
    run(gc.handle("g8", Ctx(), "/猜曲绘", command=True))
    gc.sessions["g8"].touched -= 3600
    assert run(gc.handle("g8", Ctx(), "随便聊一句今天好热啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊", command=False)) is None
    assert "g8" not in gc.sessions
    r = run(gc.handle("g8", Ctx(), "提示", command=False))       # 以前这里什么都不回
    assert r is not None and "自动结束" in r.texts[0] and "答案：" in r.texts[0]
    assert run(gc.handle("g8", Ctx(), "提示", command=False)) is None   # 只说一次


def test_expired_session_correct_guess_still_acknowledged():
    gc = _gc()
    run(gc.handle("g8b", Ctx(), "/猜曲绘", command=True))
    s = gc.sessions["g8b"]
    title = s.picks[0].song.title
    s.touched -= 3600
    gc.active("g8b")
    r = run(gc.handle("g8b", Ctx(), title, command=False))
    assert r is not None and "猜对了" in r.texts[0] and "自动结束" in r.texts[0]


def test_wrong_guesses_keep_game_alive():
    gc = _gc()
    run(gc.handle("g8c", Ctx(), "/猜曲绘", command=True))
    s = gc.sessions["g8c"]
    s.touched -= 7 * 60
    assert run(gc.handle("g8c", Ctx(), "这是什么歌", command=False)) is None
    s.touched -= 2 * 60                     # 不算刚才那条就过期了
    assert gc.active("g8c") is s


def test_second_start_while_first_is_fetching():
    gc = _gc()
    gc.starting["g8d"] = __import__("time").time()
    r = run(gc.handle("g8d", Ctx(), "/猜谱面 中二", command=True))
    assert "正在开" in r.texts[0] and "g8d" not in gc.sessions


def test_help():
    r = run(_gc().handle("g9", Ctx(), "/猜歌 帮助", command=True))
    assert "开字母" in r.texts[0] and "14以上" in r.texts[0]


def test_gamedata_uses_chartcommands_src():
    """真插件里 ChartCommands 把 sdvx.in 客户端放在 .src（v1.16.0 实测踩坑：写成了 .sdvx）。"""
    import asyncio
    from types import SimpleNamespace
    from games.sources import GameData
    from chart.commands import ChartCommands
    calls = []

    class Src:
        entries = {"chu": {}, "sdvx": {}}
        aliases = {}

        async def ensure(self, game):
            calls.append(game)
            return 7

    charts = ChartCommands.__new__(ChartCommands)
    charts.src = Src()
    gd = GameData(SimpleNamespace(charts=charts))
    assert asyncio.run(gd.ensure_charts("chu")) == 7 and calls == ["chu"]
    assert gd.chart_songs("sdvx") == []


def test_geki_borrows_aliases_from_chu_and_mai():
    from types import SimpleNamespace
    from games.sources import GameData

    class GD(GameData):
        def songs(self, game, region="jp"):
            if game == "chu":
                return [G.Song("chu", "1", "Aleph-0", ["a0", "阿列夫零"], [])]
            if game == "mai":
                return [G.Song("mai", "2", "ALEPH-0", ["a0", "阿雷夫"], [])]
            raise RuntimeError("no data")

    gd = GD(SimpleNamespace(charts=None))
    al = gd._with_borrowed("Aleph-0", ["自己的"])
    assert al == ["自己的", "a0", "阿列夫零", "阿雷夫"]
    song = G.Song("geki", "x", "Aleph-0", al, [])
    assert G.is_answer("阿列夫零", song) and G.is_answer("A0", song)
    assert gd._with_borrowed("没有这首", []) == []


def test_sdvx_pjsk_jacket_candidates():
    from chart.sdvxin import Entry, SdvxIn
    s = SdvxIn.__new__(SdvxIn)
    v = Entry("sdvx", "07112", "VICTIM", "", {"levels": {"nov": "_6", "adv": "_13", "exh": "16", "mxm": "183"}})
    assert s.jacket_candidates(v) == [
        "/07/jacket/07112m.png", "/sdvx/07/jacket/07112m.png",
        "/07/jacket/07112e.png", "/sdvx/07/jacket/07112e.png", "/07/jacket/07112.png"]
    p = Entry("pjsk", "0738", "プレデター", "", {"levels": {"mst": "30"}})
    assert s.jacket_candidates(p) == ["/prsk/jacket/0738.png"]
    assert s.jacket_candidates(Entry("chu", "1", "x", "", {})) == []


def test_jacket_and_letters_allow_sdvx_pjsk():
    gc = _gc()
    gc.data.chart_songs = lambda game: _songs(game)
    gc.data.songs = lambda game, region="jp": _songs(game)
    r = run(gc.handle("s1", Ctx(), "/猜曲绘 sdvx 14以上", command=True))
    assert r.image and "SDVX" in r.texts[0]
    run(gc.handle("s1", Ctx(), "结束", command=False))
    r = run(gc.handle("s2", Ctx(), "/猜歌 pjsk", command=True))
    assert "开字母 · PJSK" in r.texts[0]


def test_chu_pool_skips_deleted_songs():
    """2026-11-07 群里：/猜曲绘 中二 15以上 抽到了 SUN 就删掉的 ]-[|/34<#!。
    原因：日服定数表里没有它时，退回了曲库里的旧定数。现在表里没有 = 这个服没有。"""
    from types import SimpleNamespace
    from chuni.models import Difficulty as D
    from chuni.songdb import ChartInfo, SongInfo
    from games.sources import GameData

    alive = SongInfo(1, "Alive", intl=True, charts={D.MASTER: ChartInfo(D.MASTER, "15", 15.2)})
    gone = SongInfo(2, "]-[|/34<#!", intl=False, charts={D.MASTER: ChartInfo(D.MASTER, "15", 15.1)})

    class DB:
        songs = {1: alive, 2: gone}
        def aliases_of(self, s): return []

    def gd(jp, cn=None):
        svc = SimpleNamespace(songdb=DB(), consts=SimpleNamespace(jp=jp, cn=cn or {}))
        return GameData(SimpleNamespace(chu_svc=svc))

    titles = lambda songs: sorted(s.title for s in songs)  # noqa: E731
    g = gd({(1, D.MASTER): 15.3})
    assert titles(g.songs("chu", "jp")) == ["Alive"]
    assert g.songs("chu", "jp")[0].charts[0].const == 15.3          # 用日服表的定数，不是曲库的
    assert titles(g.songs("chu", "intl")) == ["Alive"]              # 国际服：intl=False 的删曲不出
    assert titles(gd({}).songs("chu", "jp")) == ["Alive"]           # 日服表还没加载：退回国际服在不在


def test_guess_simplified_kanji_and_main_title():
    """2026-11-07 群里：答案 『回帰』 ~Scherzo ~フォルトゥーナの悪戯~，大家发「回归」没被认。"""
    s = G.Song("chu", "1", "『回帰』 ~Scherzo ~フォルトゥーナの悪戯~")
    for guess in ("回归", "回帰", "回歸", "『回帰』 ~Scherzo ~フォルトゥーナの悪戯~", "回帰scherzoフォルトゥーナの悪戯"):
        assert G.is_answer(guess, s), guess
    assert not G.is_answer("scherzo", s) and not G.is_answer("回", s)
    assert G.is_answer("てるゆあわーるど", G.Song("pjsk", "2", "テルユアワールド"))
    assert G.title_parts("Garakuta Doll Play (Unlimited)") == ["Garakuta Doll Play"]
    assert G.title_parts("Aleph-0") == [] and G.title_parts("A") == []


def test_fuzzy_fold_kanji():
    from mai.data.fuzzy import fold
    assert fold("回归") == fold("回帰") == fold("回歸")
    assert fold("悪戯") == fold("恶戏")


def test_chart_region_passed_through():
    gc = GameCommands(FakeData(), rnd=random.Random(7))
    seen = []
    orig = gc.data.chart_songs

    def cs(game, region="jp"):
        seen.append(region)
        return orig(game)
    gc.data.chart_songs = cs
    run(gc.handle("cr", Ctx(), "/猜谱面 中二 14+ 国服", command=True))
    assert seen == ["cn"]
    gc.sessions.clear(); seen.clear()  # noqa: E702
    run(gc.handle("cr", Ctx(), "/猜谱面 音击 国服", command=True))
    assert seen == ["jp"]                               # 音击没有区服：照常


def test_letter_hint_per_song():
    from games import core as G
    gc = GameCommands(FakeData(), rnd=random.Random(3))
    run(gc.handle("lh", Ctx(), "/猜歌 舞萌", command=True))
    s = gc.sessions["lh"]
    s.picks[5].song.version = "X-VERSE"
    before = {i: G.mask(p.song.title, s.opened) for i, p in enumerate(s.picks)}
    r = run(gc.handle("lh", Ctx(uid="1"), "6. 提示", command=False))
    assert "第 6 首提示：版本：X-VERSE，开了一个" in r.texts[0]
    assert len(s.shown(5)) == 1
    assert all(G.mask(p.song.title, s.opened, s.shown(i)) == before[i] for i, p in enumerate(s.picks) if i != 5)
    assert "（X-VERSE）" in s.letters_board()
    assert not run(gc.handle("lh", Ctx(uid="2"), "提示 6", command=False)).texts      # 3 秒防抖
    s.data["last_hint_i"][5] -= 5
    r = run(gc.handle("lh", Ctx(uid="2"), "6提示", command=False))
    assert "版本" not in r.texts[0] and len(s.shown(5)) == 2                         # 第二次只开字
    assert "只有" in run(gc.handle("lh", Ctx(), "12 提示", command=False)).texts[0]
    assert "第几首" in run(gc.handle("lh", Ctx(), "提示", command=False)).texts[0]
    # 开到只剩一个字就不给了
    title = s.picks[5].song.title
    s.hinted[5] = set(G.hidden_positions(title, s.opened)[1:]) | s.shown(5)
    s.data["last_hint_i"][5] = 0
    hidden = G.hidden_positions(title, s.opened, s.shown(5))
    r = run(gc.handle("lh", Ctx(), "6 提示", command=False))
    assert len(hidden) <= 1 and ("最后一个字" in r.texts[0] or "开完" in r.texts[0])
