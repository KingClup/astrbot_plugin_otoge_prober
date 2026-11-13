"""RinNET 音击：把 AquaDX 那位公开玩家（1.51，网站 21.202）的数据改写成 RinNET 前端代码里的格式，
走 RinNET 的解析 → 同一套 build_best，结果要和 AquaDX 一样。"""
import json

from core.privsrv import rinnet
from ongeki import aquadx
from tests.test_ongeki_core import D, _all_music, _lamp_rows, db  # noqa: F401  (fixture)

import pytest


def _rin_payload():
    summary = json.loads((D / "aqua_ongeki_summary.json").read_text(encoding="utf-8"))
    lamps = {(r["musicId"], r["level"]): r for r in _lamp_rows()}
    comp = summary["ratingComposition"]

    def rows(key):
        out = []
        for it in aquadx.parse_items(comp.get(key)):
            lp = lamps.get((it[0], it[1]), {})
            out.append({"musicId": it[0], "level": it[1], "techScoreMax": it[2],
                        "platinumScoreStar": it[3] if len(it) > 3 else 0,
                        "platinumScoreMax": it[4] if len(it) > 4 else 0,
                        "isFullCombo": bool(lp.get("isFullCombo")), "isAllBreak": bool(lp.get("isAllBreake")),
                        "isFullBell": bool(lp.get("isFullBell"))})
        return out
    rating = {"status": {"code": 92001}, "data": {"new10": rows("new10"), "old50": rows("best50"),
                                                   "pScore": rows("pscore50")}}
    prof = {"userName": "PLAYER", "newPlayerRating": summary.get("rating"), "lastRomVersion": "1.51.00"}
    music = []
    for mid, m in _all_music().items():
        lv = [f"{int(n['lv'])},{round(n['lv'] * 100) % 100:02d}" for n in m["notes"]]
        row = {"id": int(mid), "name": m["name"], "artistName": m["composer"]}
        if m["lunatic"]:
            row.update({f"level{i}": "0,0" for i in range(4)}, level4=lv[0])
        else:
            row.update({f"level{i}": (lv + ["0,0"] * 5)[i] for i in range(4)}, level4="0,0")
        music.append(row)
    return prof, rating, music


def test_level_string():
    assert rinnet.geki_level("14,70") == 14.7 and rinnet.geki_level("0,0") is None and rinnet.geki_level("") is None


def test_rinnet_geki_matches_aquadx(db):  # noqa: F811
    prof, rating, music = _rin_payload()
    summary, lamps = rinnet.parse_geki_rating(prof, rating)
    best = aquadx.build_best(summary, lamps, rinnet.geki_music_to_aqua(music), db)
    assert best.client == 151 and best.shown == 21202
    assert best.calc == 21202
    assert any(c.ab for c in best.best) and len(best.plat) > 0


def test_rinnet_geki_errors():
    with pytest.raises(rinnet.PrivNotFound):
        rinnet.parse_geki_rating(None, {})
    with pytest.raises(rinnet.PrivError, match="Re:Fresh"):
        rinnet.parse_geki_rating({"userName": "x"}, {"status": {"code": 94001}})
    with pytest.raises(rinnet.PrivNotFound):
        rinnet.parse_geki_rating({"userName": "x"}, {"status": {"code": 92001}, "data": {"new10": [], "old50": []}})
