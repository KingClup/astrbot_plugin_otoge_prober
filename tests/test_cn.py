"""国服: 水鱼 + 落雪 data sources, shared 日服 / 国际服 artwork, credential safety. Offline (mock transports)."""
from __future__ import annotations

import io
import json
import logging
import os
import re
import tempfile

import httpx
import pytest
from PIL import Image

from core import lxns as LX
from mai.bot.commands import Commands, Ctx
from mai.bot.guard import REDACTOR
from mai.bot.storage import UserStore
from mai.data.loader import CatalogStore
from mai.service import MaiService

TOKEN = "Abc123xYz0_-Pq9TokenQq42Zz8HhJj0KkLlMmN="

# (music_id, title, type, master ds on 国服, LXNS chart version, achievement, dx rating from LXNS)
MAI_ROWS = [
    (834, "PANDORA PARADOXXX", "standard", 14.9, 19900, 100.5, 333),
    (11311, "躯樹の墓守", "dx", 14.9, 22000, 100.2, 330),
    (11612, "Latent Kingdom", "dx", 14.9, 24000, 99.9, 320),
    (11753, "宙天", "dx", 14.9, 25000, 99.5, 310),
    (11823, "Zitronectar", "dx", 14.4, 25500, 100.5, 323),
    (11806, "Fraq", "dx", 13.7, 25500, 100.1, 300),
]


def mai_song_list():
    songs = {}
    for mid, title, typ, ds, ver, _a, _r in MAI_ROWS:
        base = mid % 10000
        s = songs.setdefault(base, {"id": base, "title": title, "version": ver, "difficulties": {"standard": [], "dx": []}})
        s["difficulties"][typ].append({"type": typ, "difficulty": 3, "level": "14+", "level_value": ds,
                                       "note_designer": "x", "version": ver})
    return {"songs": list(songs.values()), "genres": [],
            "versions": [{"id": 1, "title": "舞萌DX 2025", "version": 25000},
                         {"id": 2, "title": "舞萌DX 2026", "version": 25500},
                         {"id": 3, "title": "未来", "version": 30000}]}


def mai_scores():
    out = []
    for mid, title, typ, _ds, _v, ach, ra in MAI_ROWS:
        out.append({"id": mid % 10000, "song_name": title, "level": "14+", "level_index": 3, "achievements": ach,
                    "fc": "ap" if ach >= 100.5 else None, "fs": "fsd" if ach >= 100.5 else None,
                    "dx_score": 2500, "dx_rating": ra, "rate": "sssp" if ach >= 100.5 else "sss", "type": typ})
    out.append({"id": 100123, "song_name": "宴", "level": "13?", "level_index": 0, "achievements": 101,
                "dx_rating": 0, "rate": "sssp", "type": "utage"})
    return out


def lx_handler(game_scores, song_list, player, *, bad_token=False, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append((req.url.path, dict(req.headers)))
        path = req.url.path
        if "/user/" in path:
            if bad_token or req.headers.get("x-user-token") != TOKEN:
                return httpx.Response(401, json={"success": False, "code": 401, "message": "invalid token"})
            if path.endswith("/player"):
                return httpx.Response(200, json={"success": True, "code": 200, "data": player})
            if path.endswith("/player/scores"):
                return httpx.Response(200, json={"success": True, "code": 200, "data": game_scores})
            if path.endswith("/player/recents"):
                return httpx.Response(200, json={"success": True, "code": 200, "data": game_scores[:2]})
        if path.endswith("/song/list"):
            return httpx.Response(200, json=song_list)
        return httpx.Response(404, json={"success": False, "code": 404, "message": "nope"})
    return httpx.MockTransport(handler)


MAI_PLAYER = {"name": "ＫＩＮＧ", "rating": 15039, "friend_code": 123456789, "course_rank": 10, "class_rank": 3,
              "upload_time": "2026-11-01T03:04:05Z",
              "star": 520, "trophy": {"id": 1, "name": "国服称号", "color": "Gold"}, "icon": {"id": 101}}


@pytest.fixture()
def mai_env(tmp_path):
    store = UserStore(str(tmp_path / "mai"))
    catalog = CatalogStore(str(tmp_path / "mai"))
    catalog.load_local()
    svc = MaiService(store, catalog)
    calls: list = []
    t = lx_handler(mai_scores(), mai_song_list(), MAI_PLAYER, calls=calls)
    svc.lx_transport = t
    svc.lx_songs.transport = t
    cmd = Commands(svc, require_consent=True, cache_minutes=10)
    return svc, cmd, calls


# ---------------- core.lxns ----------------
def test_find_token_and_secret_detection():
    assert LX.find_token(["落雪", TOKEN]) == TOKEN
    assert LX.find_token(["落雪"]) == ""
    assert LX.looks_like_lxns_secret(f"/mai 绑定 落雪 {TOKEN}")
    assert LX.looks_like_lxns_secret(f"mai 绑定 lxns {TOKEN}")
    assert not LX.looks_like_lxns_secret(f"绑定 国服 {TOKEN}")        # no 落雪 word → not ours (clal rules apply)
    assert not LX.looks_like_lxns_secret("落雪查分器真好用")


def test_redactor_masks_lxns_key():
    rec = logging.LogRecord("astrbot", logging.INFO, __file__, 1, f"[收到] /mai 绑定 落雪 {TOKEN}", None, None)
    REDACTOR.filter(rec)
    assert TOKEN not in rec.getMessage() and "<lxns>" in rec.getMessage()
    rec2 = logging.LogRecord("astrbot", logging.INFO, __file__, 1, "落雪 normal_words_only_here", None, None)
    REDACTOR.filter(rec2)
    assert "normal_words_only_here" in rec2.getMessage()


def test_song_index_current_version_ignores_future_entries(tmp_path):
    idx = LX.SongIndex("maimai", str(tmp_path))
    idx.load(mai_song_list())
    assert idx.current == 25500                        # 30000 (未来) has no charts → not current
    assert idx.version_title() == "舞萌DX 2026"
    assert idx.is_new(11823, "dx", 3) is True
    assert idx.is_new(834, "standard", 3) is False
    assert idx.get(1823, "dx", 3)[0] == 14.4          # base id lookup


def test_song_index_chunithm_list_shape(tmp_path):
    idx = LX.SongIndex("chunithm", str(tmp_path))
    idx.load({"songs": [{"id": 2338, "title": "x", "version": 23000,
                         "difficulties": [{"difficulty": 3, "level": "15", "level_value": 15.2, "version": 23000}]},
                        {"id": 100, "title": "old", "version": 10000,
                         "difficulties": [{"difficulty": 3, "level": "13", "level_value": 13.4, "version": 10000}]}],
              "versions": [{"title": "中二节奏 2027", "version": 23000}]})
    assert idx.current == 23000
    assert idx.is_new(2338, "", 3) and not idx.is_new(100, "", 3)


async def test_bad_key_message():
    t = lx_handler([], {}, {}, bad_token=True)
    with pytest.raises(LX.LxnsError, match="密钥不对"):
        await LX.player("maimai", TOKEN, transport=t)


# ---------------- 舞萌 国服 via 落雪 ----------------
async def test_mai_lx_fetch_split_and_ratings(mai_env):
    svc, _cmd, calls = mai_env
    prof, scores, split = await svc._cn_fetch({"source": "lx", "token": TOKEN})
    assert prof.name == "ＫＩＮＧ" and prof.rating == 15039 and prof.title_kind == "gold"
    assert prof.icon_url.endswith("/maimai/icon/101.png")
    assert len(scores) == 6                               # 宴 skipped
    assert {tuple(k)[0] for k in split["new"]} == {"Zitronectar", "Fraq"}
    by = {s.title: s for s in scores}
    assert by["PANDORA PARADOXXX"].music_id == 834 and by["Zitronectar"].music_id == 11823
    assert by["Zitronectar"].rating == 323 and by["Zitronectar"].ds == 14.4 and by["Zitronectar"].ds_exact
    # the key only ever goes in the header, never in a URL
    assert all(TOKEN not in p for p, _h in calls)
    assert any(h.get("x-user-token") == TOKEN for p, h in calls if "/user/" in p)


async def test_mai_lx_bind_flow_private_with_consent(mai_env):
    svc, cmd, _ = mai_env
    ctx = Ctx(uid="10001", private=True, admin=False)
    r = await cmd.handle(ctx, f"绑定 落雪 {TOKEN}")
    assert r.recall and "同意" in r.texts[0]
    assert svc.store.get_creds("10001", "cn") is None
    r = await cmd.on_flow_message(ctx, "同意")
    assert "落雪查分器" in r.texts[0] and r.recall
    creds = svc.store.get_creds("10001", "cn")
    assert creds == {"source": "lx", "token": TOKEN}
    # encrypted at rest
    raw = "".join(open(os.path.join(svc.store.users_dir, f), encoding="utf-8").read()
                  for f in os.listdir(svc.store.users_dir))
    assert TOKEN not in raw
    # b50 text + 成绩 + 我
    r = await cmd.handle(ctx, "b50 文字")
    text = "\n".join(r.texts)
    assert "Zitronectar" in text and "PANDORA" in text
    assert "数据来自落雪查分器" in text and "上传于 11-01" in text and "/mai 更新" in text     # 国服：说明来源和上传时间
    assert svc.cn_uploaded_at("10001") == "2026-11-01T03:04:05Z"
    r = await cmd.handle(ctx, "我")
    assert "落雪查分器" in r.texts[0] and "15039" in r.texts[0]
    r = await cmd.handle(ctx, "最近")
    assert "最近游玩" in r.texts[0]


async def test_mai_lx_bind_refused_in_group(mai_env):
    svc, cmd, _ = mai_env
    r = await cmd.handle(Ctx(uid="10002", private=False, admin=False), f"绑定 落雪 {TOKEN}")
    assert r.recall and "网页绑定" in r.texts[0]
    assert TOKEN not in "".join(r.texts)
    assert svc.store.get_creds("10002", "cn") is None


async def test_mai_lx_bad_key_reports_and_recalls(mai_env):
    _svc, cmd, _ = mai_env
    r = await cmd.handle(Ctx(uid="10003", private=True, admin=True), "绑定 落雪 Wrong0Token0Value0000000000")
    assert r.recall and "密钥不对" in r.texts[0]


async def test_mai_lx_howto_without_key(mai_env):
    _svc, cmd, _ = mai_env
    r = await cmd.handle(Ctx(uid="10004", private=True, admin=True), "绑定 落雪")
    assert "个人 API 密钥" in r.texts[0]


# ---------------- 舞萌 国服 via 水鱼 (unchanged path, still works) ----------------
async def test_mai_df_bind_and_b50(mai_env):
    svc, cmd, _ = mai_env

    def handler(req):
        body = json.loads(req.content)
        assert body.get("qq") == "10005" and body.get("b50")
        return httpx.Response(200, json={"nickname": "fish", "rating": 15000, "plate": "",
                                         "charts": {"sd": [{"achievements": 100.5, "ds": 14.9, "dxScore": 1, "fc": "app",
                                                            "fs": "", "level": "14+", "level_index": 3, "ra": 337,
                                                            "rate": "sssp", "song_id": 834, "title": "PANDORA PARADOXXX",
                                                            "type": "SD"}],
                                                    "dx": []}})
    svc.df_transport = httpx.MockTransport(handler)
    ctx = Ctx(uid="10005", private=False, admin=False)
    r = await cmd.handle(ctx, "绑定 国服")
    assert "水鱼查分器" in r.texts[0]
    r = await cmd.handle(ctx, "最近")
    assert "水鱼" in r.texts[0]
    r = await cmd.handle(ctx, "成绩 Fraq")
    assert "落雪" in "".join(r.texts)


# ---------------- shared artwork ----------------
def _png(color, size=(300, 120)):
    im = Image.new("RGBA", size, color)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


async def test_mai_cn_b50_uses_shared_theme_and_version_logo(mai_env, tmp_path):
    from mai.render import b50img as R
    svc, cmd, _ = mai_env
    root = tmp_path / "render"
    themes = root / "themes"
    (themes / "CiRCLE PLUS").mkdir(parents=True)
    (themes / "logos").mkdir(parents=True)
    (themes / "CiRCLE PLUS" / "bg.png").write_bytes(_png((10, 200, 10, 255), (64, 64)))
    (themes / "CiRCLE PLUS" / "logo.png").write_bytes(_png((255, 0, 0, 255)))
    (themes / "logos" / "prism_plus.png").write_bytes(_png((0, 0, 255, 255), (90, 30)))
    db = svc.catalog.db
    assert db.current_version["cn"] == "PRiSM PLUS"
    store = R.AssetStore(str(root))
    R.share_versions(db)
    # 国服 has no theme of its own → the 国际服 background is used
    assert store.theme_file("PRiSM PLUS", "bg.png").endswith(os.path.join("CiRCLE PLUS", "bg.png"))
    # logo: PRiSM PLUS version logo (blue), never the 国际服 (red) one
    lg = R._logo(store, "PRiSM PLUS")
    assert lg is not None and lg.getpixel((lg.width // 2, lg.height // 2))[:3] == (0, 0, 255)
    assert lg.height >= 150                         # small tab logo scaled up
    # full render through the command, 落雪 source in the footer
    ctx = Ctx(uid="10006", private=True, admin=True)
    await cmd.handle(ctx, f"绑定 落雪 {TOKEN}")
    snap = await cmd._snapshot("10006", "cn")
    b = snap.best50(svc.catalog)
    b.source = "落雪查分器"
    png = R.B50Renderer(str(root), "Bot")(b, snap.profile, db, snap.at)
    im = Image.open(io.BytesIO(png))
    assert im.width == R.W and im.height > 1000
    im.save(os.environ.get("CN_B50_OUT") or (tmp_path / "cn_b50.png"))


# ---------------- 中二 国服 ----------------
CHU_ROWS = [  # id, title, diff, score, const, lxns version
    (2338, "新曲A", 3, 1009000, 15.2, 23000), (2339, "新曲B", 3, 1005000, 14.8, 23000),
    (100, "旧曲A", 3, 1008000, 15.0, 10000), (101, "旧曲B", 4, 1001000, 15.4, 12000),
    (102, "WE", 5, 1000000, None, 12000),
]


def chu_fixture():
    songs = [{"id": i, "title": t, "version": v,
              "difficulties": [{"difficulty": d, "level": "15", "level_value": c, "version": v}]}
             for i, t, d, _s, c, v in CHU_ROWS if d < 5]
    scores = [{"id": i, "song_name": t, "level": "15", "level_index": d, "score": s,
               "full_combo": "alljustice" if s >= 1008000 else None, "rank": "sss"} for i, t, d, s, _c, _v in CHU_ROWS]
    player = {"name": "CHUKING", "level": 99, "rating": 16.12, "friend_code": 1}
    return songs, scores, player


@pytest.fixture()
def chu_env(tmp_path):
    from chuni.commands import ChuCommands
    from chuni.service import ChuniService
    svc = ChuniService(tmp_path / "chu")
    songs, scores, player = chu_fixture()
    t = lx_handler(scores, {"songs": songs, "versions": [{"title": "x", "version": 23000}]}, player)
    svc.lx_transport = t
    svc.lx_songs.transport = t
    cmd = ChuCommands(svc, tmp_path / "chu", renderer=None, tz="Australia/Sydney")
    return svc, cmd


async def test_chu_lx_bind_encrypted_and_b50_split(chu_env, tmp_path):
    svc, cmd = chu_env
    from chuni.commands import Ctx as CCtx
    ctx = CCtx(uid="20001", private=True, admin=False) if "admin" in CCtx.__dataclass_fields__ else CCtx(uid="20001", private=True)
    r = await cmd.handle(ctx, f"绑定 落雪 {TOKEN}")
    assert r.recall and "落雪查分器" in r.texts[0]
    raw = (tmp_path / "chu" / "cn_bindings.json").read_text("utf-8")
    assert TOKEN not in raw and "token_enc" in raw
    assert svc._lx_token("20001") == TOKEN
    prof, b = await svc.b50_cn("20001")
    assert prof.name == "CHUKING"
    assert [s.title for s in b.new] == ["新曲A", "新曲B"]
    assert {s.title for s in b.best} == {"旧曲A", "旧曲B"}            # WORLD'S END skipped
    assert all(s.const is not None for s in b.best + b.new)
    r = await cmd.handle(ctx, "b50 文字")
    assert "新曲A" in "\n".join(r.texts)
    assert "数据来自落雪查分器" in "\n".join(r.texts) and "/chu 更新" in "\n".join(r.texts)
    r = await cmd.handle(ctx, "我")
    assert "N20" in r.texts[0]


async def test_chu_lx_refused_in_group(chu_env):
    svc, cmd = chu_env
    from chuni.commands import Ctx as CCtx
    ctx = CCtx(uid="20002", private=False, admin=False) if "admin" in CCtx.__dataclass_fields__ else CCtx(uid="20002", private=False)
    r = await cmd.handle(ctx, f"绑定 落雪 {TOKEN}")
    assert r.recall and "网页绑定" in r.texts[0]
    assert "20002" not in svc.cn


def test_chu_cn_base_version_table():
    from chuni.cn import cn_base_version
    assert cn_base_version("2026-01-01") == "VERSE"
    assert cn_base_version("2026-09-10") == "X-VERSE"
    assert cn_base_version("2026-11-06") == "X-VERSE"


def test_chu_cn_render_layouts(tmp_path):
    from chuni.b50img import render_b50
    from chuni.models import Difficulty, Rank, Score
    from chuni.rating import B50
    sc = [Score(song_id=i, title=f"曲{i}", difficulty=Difficulty.MASTER, score=1007000, rank=Rank.SSS) for i in range(50)]
    for s in sc:
        s.const = 14.5
    for server, n_new in (("cn", 10), ("cn_lx", 20)):
        out = render_b50("国服测试", B50(best=sc[:30], new=sc[30:50]), tmp_path / f"{server}.jpg", {},
                         version="X-VERSE-X", server=server)
        im = Image.open(out)
        assert im.width > 1000
    # 落雪 (B30 + N20) is taller than 水鱼 (B30 + R10)
    assert Image.open(tmp_path / "cn_lx.jpg").height > Image.open(tmp_path / "cn.jpg").height


# ---------------- route / guard helpers ----------------
def test_route_accepts_long_bind_without_slash():
    from core.route import route
    rt = route(f"mai 绑定 落雪 {TOKEN}")
    assert rt is not None and rt.game == "mai" and rt.how == "plain"
    assert route("舞萌 最近好难") is None


async def test_plugin_cn_update_and_accounts(mai_env, chu_env, tmp_path):
    """main.OtogeScore._cn_update / accounts_text：用 __new__ 绕开 AstrBot，只装上需要的部件。"""
    import importlib
    import sys
    import types
    pytest.importorskip("astrbot")                      # 没装 AstrBot 的环境跳过（其余测试不受影响）
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.dirname(root) not in sys.path:
        sys.path.insert(0, os.path.dirname(root))
    M = importlib.import_module(os.path.basename(root) + ".main")
    from core.prefs import Prefs
    svc, cmd, _ = mai_env
    csvc, ccmd = chu_env
    p = M.OtogeScore.__new__(M.OtogeScore)
    p.service, p.cmd, p.store = svc, cmd, svc.store
    p.chu_svc, p.chu = csvc, ccmd
    p.prefs = Prefs(str(tmp_path / "prefs"))
    p.priv = types.SimpleNamespace(bindings=types.SimpleNamespace(get=lambda *a: ""))
    p.config = {"timezone": "Asia/Shanghai"}
    cmd.prefs = ccmd.prefs = p.prefs
    ctx = Ctx(uid="30001", private=True, admin=True)
    # 没绑定：交给原指令回「还没绑定」
    r = await p._cn_update(ctx, "mai", "")
    assert "绑定" in "\n".join(r.texts)
    # 舞萌落雪
    await cmd.handle(ctx, f"绑定 落雪 {TOKEN}")
    r = await p._cn_update(ctx, "mai", "")
    t = "\n".join(r.texts)
    assert t.startswith("舞萌国服成绩怎么更新") and "上传于 11-01 11:04" in t and "maimai.lxns.net/sync" in t
    assert "落雪 · 上传于 11-01 11:04" in p.accounts_text("30001") and "/mai 更新" in p.accounts_text("30001")
    # 中二落雪（玩家资料没有 upload_time → 不写时间，但仍给链接）
    from chuni.commands import Ctx as CCtx
    cctx = CCtx(uid="30001", private=True, admin=True) if "admin" in CCtx.__dataclass_fields__ else CCtx(uid="30001", private=True)
    await ccmd.handle(cctx, f"绑定 落雪 {TOKEN}")
    r = await p._cn_update(ctx, "chu", "国服")
    t = "\n".join(r.texts)
    assert t.startswith("中二国服成绩怎么更新") and "上传于" not in t and "/chu 刷新" in t
    # 配置里的链接优先
    p.config = {"timezone": "Asia/Shanghai", "lx_sync_url": "https://example.org/sync"}
    assert "https://example.org/sync" in "\n".join((await p._cn_update(ctx, "mai", "")).texts)
    # /查分 更新记录
    r = await p._core(None, ctx, "更新记录")
    assert r.texts[0].startswith("更新记录") and p.VERSION in r.texts[0]
