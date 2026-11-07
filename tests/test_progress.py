"""版本进度核实 + 中二补曲库（离线，用假数据）。"""
import asyncio

from chuni.augment import augment_jp_consts, augment_songdb
from chuni.models import Difficulty
from chuni.songdb import ChartInfo, SongInfo
from core.progress import ProgressTracker, chu_key, chu_name, mai_code_name


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def tracker(tmp_path, *, mai_jp_magical=6, chu_intl_mate=6):
    t = ProgressTracker(str(tmp_path))
    t.official = {
        ("mai", "jp"): [{"title": f"m{i}", "version": "27000", "catcode": "maimai"} for i in range(mai_jp_magical)]
        + [{"title": f"c{i}", "version": "26500", "catcode": "maimai"} for i in range(10)]
        + [{"title": "宴", "version": "27500", "catcode": "宴会場"} for _ in range(9)],
        ("mai", "intl"): [{"title": f"c{i}", "version": "26500", "catcode": "maimai"} for i in range(10)],
        ("chu", "jp"): [{"id": str(i)} for i in range(1, 21)],
        ("chu", "intl"): [{"id": str(i)} for i in range(1, 1 + chu_intl_mate)] + [{"id": str(i)} for i in range(11, 21)],
    }
    t.otoge = {"chu": [{"id": str(i), "title": f"新歌{i}", "artist": "a", "version": "Mate", "catname": "ORIGINAL",
                        "lev_mas": "14+", "lev_mas_i": "14.7", "lev_exp": "12", "lev_exp_i": ""} for i in range(1, 11)]
               + [{"id": str(i), "title": f"旧歌{i}", "version": "X-VERSE-X", "lev_mas": "14", "lev_mas_i": "14.2"}
                  for i in range(11, 21)]}
    return t


def test_names():
    assert mai_code_name("27004") == "MAGiCAL" and mai_code_name("26500") == "CiRCLE PLUS"
    assert chu_key("LUMINOUS+") == chu_key("luminousplus") == chu_key("CHUNITHM LUMINOUS PLUS")
    assert chu_name("LUMINOUS+") == "LUMINOUS PLUS" and chu_name("mate") == "Mate"


def test_versions_from_official_lists(tmp_path):
    t = tracker(tmp_path)
    st = run(t.refresh({("chu", "intl"): "X-VERSE-X", ("chu", "jp"): "xversex", ("mai", "jp"): "CiRCLE PLUS",
                        ("mai", "intl"): "CiRCLE PLUS"}, download=False))
    assert st.get("mai", "jp").current == "MAGiCAL" and st.get("mai", "jp").official_new == 6   # 宴不算
    assert st.get("mai", "intl").current == "CiRCLE PLUS"
    assert st.get("chu", "intl").official == "Mate" and st.get("chu", "intl").current == "Mate"
    assert st.get("chu", "jp").current == "Mate"
    assert any("曲库还停在" in n for n in st.get("chu", "jp").notes)


def test_too_few_songs_do_not_count_and_changes_are_reported(tmp_path):
    t = tracker(tmp_path, mai_jp_magical=2)
    st = run(t.refresh({}, download=False))
    assert st.get("mai", "jp").official == "CiRCLE PLUS"
    t.official[("mai", "jp")] += [{"title": f"n{i}", "version": "27001", "catcode": "maimai"} for i in range(5)]
    st = run(t.refresh({}, download=False))
    assert st.changes == [] or any("舞萌日服" in c for c in st.changes)
    # timeline already says MAGiCAL for 日服, so the jump shows only if the timeline didn't cover it
    assert st.get("mai", "jp").current == "MAGiCAL"


def test_augment_chu_songdb_and_jp_consts(tmp_path):
    t = tracker(tmp_path)

    class DB:
        songs = {11: SongInfo(11, "旧歌11", intl=False, version=None,
                              charts={Difficulty.MASTER: ChartInfo(Difficulty.MASTER, "14", None)})}
    db = DB()
    stats = augment_songdb(db, t)
    assert stats["added"] == 19                       # 曲库里没有的都补：Mate 1..10 + 旧歌 12..20
    assert db.songs[1].version == "Mate" and db.songs[1].intl is True       # 官方国际服有 1..6
    assert db.songs[8].intl is False
    assert db.songs[1].charts[Difficulty.MASTER].const == 14.7
    assert db.songs[1].charts[Difficulty.EXPERT].const is None
    assert db.songs[11].intl is True and db.songs[11].charts[Difficulty.MASTER].const == 14.2
    assert db.songs[11].version == "X-VERSE-X"

    class C:
        jp = {(11, Difficulty.MASTER): 14.0}
    c = C()
    n = augment_jp_consts(c, t)
    assert c.jp[(1, Difficulty.MASTER)] == 14.7 and c.jp[(11, Difficulty.MASTER)] == 14.2 and n >= 11


def test_saved_and_reloaded(tmp_path):
    t = tracker(tmp_path)
    run(t.refresh({}, download=False))
    t2 = ProgressTracker(str(tmp_path))
    assert t2.state.get("chu", "intl").current == "Mate"
