"""定数中心：解析、按优先级合并、冲突统计、写回两边曲库（离线假数据）。"""
from chuni.augment import apply_chu_consts
from chuni.models import Difficulty
from chuni.songdb import ChartInfo, SongInfo
from core import consts_hub as CH


def test_parsers_skip_estimates():
    reiwa = [{"idx": "3069", "diff": "MAS", "const": 15.2, "unknown": 0},
             {"idx": "3070", "diff": "MAS", "const": 14.0, "unknown": 1},       # 估计值：不要
             {"idx": "8000", "diff": "WE", "const": 0}]
    assert CH.parse_reiwa_chu(reiwa) == {(3069, 3): 15.2}
    zeta = {"songs": [{"title": "狂命", "sheets": [
        {"difficulty": "master", "internalLevel": "15.2", "internalLevelValue": 15.2, "regions": {"jp": True}},
        {"difficulty": "expert", "internalLevel": None, "internalLevelValue": 12, "regions": {"jp": True}}]}]}
    assert CH.make_zeta_parser("chu", "jp", lambda: {"狂命": 3069})(zeta) == {(3069, 3): 15.2}
    lx = {"songs": [{"id": 5, "title": "Ab c", "difficulties": {"dx": [{"difficulty": 3, "level_value": 14.4}],
                                                               "standard": [], "utage": [{"difficulty": 0}]}}]}
    assert CH.parse_lx_mai(lx) == {("abc", "dx", 3): 14.4}
    df = [{"id": "11568", "title": "INTERNET OVERDOSE", "type": "DX", "ds": [5, 8, 12.5, 14.4]},
          {"id": "161852", "title": "[龍]", "type": "DX", "ds": [13.7]}]          # 宴会场：不要
    assert CH.parse_df_mai(df) == {("internetoverdose", "dx", i): v for i, v in enumerate([5, 8, 12.5, 14.4])}


def test_tachi_takes_latest_tag_per_region():
    charts = [{"difficulty": "MASTER", "versions": ["xverse", "xversex", "xverse-intl"], "levelNum": 14.0,
               "data": {"inGameID": 1, "levelHistory": {"xverse-intl": {"levelNum": 13.8}}}},
              {"difficulty": "MASTER", "versions": ["xverse"], "levelNum": 13.0, "data": {"inGameID": 2}}]
    assert CH.make_tachi_parser("jp")(charts) == {(1, 3): 14.0}                  # 2 号不在最新的 xversex 里
    assert CH.make_tachi_parser("intl")(charts) == {(1, 3): 13.8}


def test_merge_priority_and_conflicts():
    m = CH.merge([("reiwa", {(1, 3): 14.5, (2, 3): 13.0}), ("tachi", {(1, 3): 14.3, (3, 3): 12.0})])
    assert m.values == {(1, 3): 14.5, (2, 3): 13.0, (3, 3): 12.0}
    assert m.chosen == {"reiwa": 2, "tachi": 1} and m.conflicts == 1


def test_hub_build_and_apply_chu(tmp_path):
    hub = CH.ConstsHub(str(tmp_path))
    hub.data = {"reiwa": {(1, 3): 15.2}, "Tachi 日服": {(1, 3): 14.9, (2, 3): 13.0}, "落雪 中二": {(1, 3): 14.8}}
    merged = hub.build({("chu", "jp"): ["reiwa", "Tachi 日服"], ("chu", "intl"): ["reiwa", "Tachi 日服"],
                        ("chu", "cn"): ["落雪 中二"]})
    assert "1 张来源说法不一" in hub.summary("chu", "jp")

    class Consts:
        jp, cn = {}, {}

    class DB:
        songs = {1: SongInfo(1, "a", charts={Difficulty.MASTER: ChartInfo(Difficulty.MASTER, "15", 14.9)})}

    class Svc:
        consts, songdb = Consts(), DB()
    svc = Svc()
    n = apply_chu_consts(svc, merged)
    assert svc.consts.jp[(1, Difficulty.MASTER)] == 15.2 and svc.consts.cn[(1, Difficulty.MASTER)] == 14.8
    assert svc.songdb.songs[1].charts[Difficulty.MASTER].const == 15.2
    assert n == {"jp": 2, "intl": 1, "cn": 1}


def test_apply_mai_cn_overrides_and_jp_fill():
    from mai.data.consts_apply import apply_mai_consts
    from mai.data.songdb import SongDB
    doc = {"versions": [{"version": "PRiSM"}], "songs": [
        {"id": "s1", "title": "Song A", "version": "PRiSM", "sheets": [
            {"type": "dx", "difficulty": "master", "level": "14", "internalLevelValue": 14.2,
             "regions": {"jp": True, "cn": True}, "version": "PRiSM"},
            {"type": "dx", "difficulty": "expert", "level": "12", "internalLevelValue": None,
             "regions": {"jp": True}, "version": "PRiSM"}]}]}
    db = SongDB(doc)
    merged = {("mai", "cn"): CH.merge([("落雪", {("songa", "dx", 3): 14.0})]),
              ("mai", "jp"): CH.merge([("otoge", {("songa", "dx", 2): 12.3, ("songa", "dx", 3): 99.0})])}
    n = apply_mai_consts(db, merged)
    ch_m = db.songs[0].chart("dx", "master")
    ch_e = db.songs[0].chart("dx", "expert")
    assert ch_m.ds_in("cn") == 14.0 and ch_m.ds_in("jp") == 14.2          # 日服已有的不覆盖
    assert ch_e.ds_in("jp") == 12.3                                         # 日服缺的补上
    assert n["cn"] == 1 and n["jp"] == 1


def test_mai_cn_availability_from_lxns():
    """落雪 / 水鱼国服曲目表里有、DXRating 还没标国服的谱面 → 标成国服可玩（国服新一批更新常见）。"""
    from mai.data.consts_apply import apply_mai_consts
    from mai.data.songdb import SongDB
    doc = {"versions": [{"version": "PRiSM PLUS"}], "songs": [
        {"id": "x", "title": "Xaleid◆scopiX", "version": "PRiSM PLUS", "sheets": [
            {"type": "dx", "difficulty": "master", "level": "14+", "internalLevelValue": 14.9,
             "regions": {"jp": True, "intl": True}, "version": "PRiSM PLUS"}]}]}
    db = SongDB(doc)
    ch = db.songs[0].chart("dx", "master")
    assert not ch.available("cn")
    n = apply_mai_consts(db, {("mai", "cn"): CH.merge([("落雪", {(CH.norm_title("Xaleid◆scopiX"), "dx", 3): 14.9})])})
    assert ch.available("cn") and ch.ds_in("cn") == 14.9 and n["cn_new"] == 1
