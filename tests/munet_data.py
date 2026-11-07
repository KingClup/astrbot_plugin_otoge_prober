"""MuNET 真实数据（player_a，2026-11-06 抓取），按接口原样的结构重建。

舞萌：服务器显示 DX Rating 16001，定数取 MuNET 的 version 26（客户端 1.66 = CiRCLE PLUS）。
中二：服务器显示 16.01，定数取 version 25000（客户端 2.50 = Mate）。
舞萌每行：musicId, level, romVersion, achievement, 定数, 曲名, comboStatus, syncStatus, dx分
"""

B35 = [
    (11752, 3, 25015, 1005799, 14.6, "雨露霜雪", 0, 5, 3320),
    (11315, 3, 22011, 1007373, 14.5, "Falsum Atlantis.", 1, 5, 2688),
    (11687, 3, 24500, 1007037, 14.5, "MarbleBlue.", 2, 5, 2859),
    (11517, 3, 23014, 1006306, 14.5, "最強STRONGER", 1, 0, 2883),
    (11860, 3, 25507, 1005425, 14.5, "MYTH Re：LEASE", 0, 5, 3040),
    (11823, 3, 25500, 1008086, 14.4, "Zitronectar", 2, 5, 2063),
    (11876, 3, 25518, 1007668, 14.4, "Retribution ～ Cycle of Redemption ～", 1, 0, 3028),
    (11461, 3, 23006, 1007567, 14.4, "#狂った民族２ PRAVARGYAZOOQA", 1, 5, 2604),
    (431, 3, 17005, 1006908, 14.4, "Contrapasso -paradiso-", 1, 0, 2788),
    (11618, 3, 24004, 1006381, 14.4, "Energizing Flame", 0, 5, 2650),
    (11550, 3, 23500, 1006142, 14.4, "FLUFFY FLASH", 0, 0, 2753),
    (11578, 3, 24000, 1005945, 14.4, "PUPA", 0, 5, 2608),
    (11625, 3, 24000, 1005848, 14.4, "GEOMETRIC DANCE", 1, 0, 2964),
    (11310, 3, 22013, 1005744, 14.4, "Trick tear", 1, 5, 2303),
    (11171, 3, 21007, 1005321, 14.4, "YURUSHITE", 0, 0, 2885),
    (11221, 3, 21001, 1005276, 14.4, '≠彡"/了→', 1, 0, 3009),
    (11643, 3, 24006, 1005265, 14.4, "天使光輪", 1, 5, 2862),
    (11479, 3, 23011, 1006258, 14.3, "Hainuwele", 1, 5, 2807),
    (11176, 3, 21007, 1006200, 14.3, "Climax", 0, 5, 3087),
    (11475, 3, 23003, 1005329, 14.3, "SUPER AMBULANCE", 1, 5, 2840),
    (11248, 3, 21513, 1005057, 14.3, "MEGATON BLAST", 0, 0, 3397),
    (456, 3, 16014, 1001309, 14.8, "Glorious Crown", 0, 5, 2994),
    (11771, 3, 25000, 1006941, 14.2, "Chronomia", 1, 5, 2536),
    (797, 3, 19900, 1005980, 14.2, "Scarlet Lance", 1, 0, 2776),
    (11754, 3, 25000, 1005856, 14.2, "Elemental Ethnic", 0, 5, 2943),
    (11576, 3, 23502, 1005239, 14.2, "Cthugha", 0, 5, 3157),
    (11209, 3, 21008, 1005176, 14.2, "Grievous Lady", 1, 5, 2754),
    (11472, 3, 23000, 1007427, 14.1, "Don't Fight The Music", 1, 5, 3028),
    (11759, 3, 25013, 1007329, 14.1, "R'N'R Monsta", 1, 5, 2218),
    (688, 3, 19006, 1006331, 14.1, "麒麟", 2, 5, 2253),
    (11842, 3, 25500, 1005986, 14.1, "Synthesis.", 1, 5, 2999),
    (11755, 3, 25000, 1005941, 14.1, "美夜月鏡", 1, 5, 2771),
    (772, 3, 19511, 1005539, 14.1, "FREEDOM DiVE (tpz Overcute Remix)", 0, 5, 2938),
    (11815, 3, 25512, 1005345, 14.1, "IMBRUED:FLUX", 0, 5, 2578),
    (11810, 3, 25503, 1000328, 14.7, "ATLAS RUSH", 0, 5, 2750),
]

B15 = [
    (11942, 3, 26009, 1005380, 14.5, "ヤミナベ!!!!", 1, 5, 2723),
    (11990, 3, 26502, 1006888, 14.3, "ZEUS", 0, 5, 3434),
    (11918, 3, 26000, 1005140, 14.3, "ニルヴの心臓", 0, 5, 2398),
    (11905, 3, 26016, 1006209, 14.2, "Daredevil Glaive", 1, 0, 2762),
    (11906, 4, 26000, 1006654, 14.1, "Unwelcome School", 1, 5, 2586),
    (11892, 3, 26008, 1005386, 14.1, "鬼女紅妖", 1, 0, 2509),
    (11897, 3, 26013, 1001140, 14.7, "Sky Trails", 1, 5, 2864),
    (11956, 3, 26502, 1000969, 14.7, "Break The Speakers", 1, 5, 2906),
    (11993, 3, 26503, 1000246, 14.7, "ANiMA", 0, 5, 2480),
    (11984, 3, 26500, 1008001, 14.0, "超ナイト・オブ・ナイツ", 1, 5, 2645),
    (11889, 3, 26005, 1001599, 14.6, "Get U ♭ack", 0, 5, 2666),
    (11985, 3, 26500, 1006617, 13.9, "浮世絵横丁", 1, 5, 2262),
    (11986, 3, 26500, 1003843, 14.4, "AiAe", 0, 5, 2851),
    (11933, 3, 26006, 1006031, 13.8, "トレジャーガーデン", 0, 5, 2919),
    (11921, 3, 26002, 1005164, 13.8, "しゅ～しん？変身☆ハカイシンzzZ", 1, 1, 2496),
]

SERVER_RATING = 16001
B35_SUM = 11255
B15_SUM = 4746


def rating_json(const_override: dict | None = None) -> dict:
    """/public/u/player_a/mai2/rating 的结构。const_override = {musicId: (version, 定数)} 额外加一个版本。"""
    songs: dict[int, dict] = {}
    details = []
    rows = []
    for table in (B35, B15):
        part = []
        for mid, lv, rom, ach, const, name, combo, sync, dx in table:
            part.append({"musicId": mid, "level": lv, "romVersion": rom, "achievement": ach})
            details.append({"musicId": mid, "level": lv, "achievement": ach, "comboStatus": combo,
                            "syncStatus": sync, "deluxscoreMax": dx, "scoreRank": 13, "playCount": 1})
            base = mid % 10000
            song = songs.setdefault(base, {"id": base, "name": name, "charts": []})
            consts = [{"version": 26, "constant": const}, {"version": 27, "constant": const}]
            if const_override and mid in const_override:
                v, c = const_override[mid]
                consts.append({"version": v, "constant": c})
            song["charts"].append({"difficulty": lv, "kind": 1 if mid >= 10000 else 0,
                                   "gameMusicId": mid, "utageId": 0, "constants": consts})
        rows.append(part)
    # 真实数据里 Glorious Crown 有一张宴谱，难度序号也是 0；放一张在 MASTER 前面
    songs[456]["charts"].insert(0, {"difficulty": 3, "kind": 0, "gameMusicId": 100456, "utageId": 10,
                                    "constants": [{"version": 26, "constant": 99.9}]})
    return {"error": 0, "data": {"b35": rows[0], "b15": rows[1], "userDetails": details,
                                 "musicDetails": list(songs.values())}}


def profile_json(game: str = "mai2", privacy: int = 0, rom: str | None = None) -> dict:
    """/public/u/player_a?game=… 的结构；舞萌和中二的 homepage 长得不一样。"""
    if game == "chusan":
        home = {"chusan": {"lastVersion": rom or "2.50.00", "ratingHighest": 1732, "serverRank": 330, "plays": 15,
                           "firstPlay": "2026-08-14T17:20:07Z", "lastPlay": "2026-10-03T01:54:11Z",
                           "userBox": {"name": "☆ＫΣｌｕｐ†☆", "rating": 1601, "level": 3}},
                "mai2": None}
    else:
        home = {"mai2": {"name": "☆ＫΣｌｕｐ†☆",
                         "nameplate": {"iconId": 650302, "plateId": 550101, "lastRomVersion": rom or "1.66.00"},
                         "rating": 16001, "ratingHighest": 16001, "serverRank": 780, "plays": 71,
                         "firstPlay": "2026-08-08 19:26:39.0", "lastPlay": "2026-09-24 00:24:10.0"},
                "chusan": None}
    return {
        "error": 0,
        "user": {"username": "player_a", "displayName": "", "privacy": privacy},
        "data": {"mai2": {"name": "☆ＫΣｌｕｐ†☆", "rating": 16001, "lastPlay": "2026-09-24 00:24:10.0"},
                 "chusan": {"name": "☆ＫΣｌｕｐ†☆", "rating": 1601, "lastPlay": "2026-10-03 01:54:11"},
                 "ongeki": None},
        "cardId": 58886,
        "homepage": {"game": game, **home, "ongeki": None},
    }


def playlog_json() -> dict:
    p = [
        (11901, 3, 867, 4, 0, 0, False, 16001, 16001, "2026-09-24T00:23:13Z", 1),
        (11901, 3, 990432, 3695, 0, 0, False, 15973, 15973, "2026-09-13T00:13:40Z", 7),
        (11901, 3, 275479, 1085, 0, 0, False, 15973, 15973, "2026-09-13T00:12:17Z", 6),
    ]
    return {"code": 0, "data": {
        "playlog": [{"musicId": m, "level": lv, "achievement": a, "deluxscore": dx, "comboStatus": c,
                     "syncStatus": s, "isAchieveNewRecord": nr, "beforeDeluxRating": b,
                     "afterDeluxRating": af, "userPlayDate": t, "trackNo": tr, "placeName": "x"}
                    for m, lv, a, dx, c, s, nr, b, af, t, tr in p],
        "musicData": [{"id": 1901, "name": "テスト曲"}],
        "userData": {},
    }}


# ---------------------------------------------------------------- 中二
# 每行：musicId, level, score, 定数(v25000), 曲名, isFullCombo, isAllJustice
CHU_B30 = [
    (2967, 3, 1008650, 15.5, "YOUNITHM", 1, 0), (2869, 3, 1009028, 15.4, "OUTRAGE", 0, 0),
    (2648, 3, 1007692, 15.5, "Tuatha Dé Danann", 0, 0), (2889, 3, 1007593, 15.5, "Deep Blue", 0, 0),
    (2838, 3, 1006888, 15.6, "神鳴", 0, 0), (788, 3, 1007280, 15.4, "Rebellion", 0, 0),
    (2121, 3, 1007959, 15.3, "Strange Love", 0, 0), (2892, 3, 1008919, 15.2, "Kaleidoscope", 1, 0),
    (2888, 3, 1008952, 15.2, "hyperreality", 0, 0), (881, 3, 1007885, 15.3, "Trrricksters!!", 0, 0),
    (2606, 3, 1007719, 15.3, "リ・フィクション・O", 0, 0), (2660, 3, 1007763, 15.3, "What's up? Pop!", 0, 0),
    (1017, 3, 1007616, 15.3, "ANU", 0, 0), (386, 3, 1008607, 15.2, "神威", 0, 0),
    (2570, 3, 1008692, 15.2, "ZegalltA", 1, 0), (2974, 3, 1008427, 15.2, "Marigold", 1, 0),
    (317, 4, 1008467, 15.2, "Air", 1, 0), (2233, 3, 1006424, 15.5, "Λzure Vixen", 0, 0),
    (2338, 3, 1007406, 15.3, "Disruptor Array", 0, 0), (2650, 3, 1008223, 15.2, "MeteorSnow", 0, 0),
    (2891, 3, 1005348, 15.7, "創 -汝ら新世界へ歩む者なり-", 0, 0), (2718, 3, 1008187, 15.2, "I Wanna", 0, 0),
    (328, 3, 1008065, 15.2, "★LittlE HearTs★", 0, 0), (232, 4, 1009211, 15.1, "Elemental Creation", 1, 0),
    (2485, 3, 1009153, 15.1, "Singularity", 0, 0), (2340, 3, 1006239, 15.5, "To：Be Continued", 0, 0),
    (321, 4, 1008921, 15.1, "ERIS -Legend of Gaidelia-", 1, 0), (2400, 3, 1007163, 15.3, "LAMIA", 0, 0),
    (2089, 3, 1007816, 15.2, "Love & Justice", 0, 0), (2554, 3, 1007688, 15.2, "MarbleBlue.", 1, 0),
]
CHU_N20 = [
    (3025, 3, 1007800, 15.3, "Tachy∅n", 0, 0), (3014, 3, 1007873, 15.2, "零號車輛", 0, 0),
    (242, 3, 1001595, 15.6, "Garakuta Doll Play (sasakure.UK clutter remix)", 0, 0),
    (3015, 3, 1005534, 15.1, "RE:UNION -Duo Blade Against-", 0, 0), (3021, 3, 1009811, 14.5, "ALLNIGHT_DANCER", 1, 1),
    (3079, 3, 1007647, 14.6, "Hello! My World!!", 0, 0), (3023, 3, 1008658, 14.5, "Luminous CANDY", 0, 0),
    (3020, 3, 1005691, 14.9, "勦滅", 0, 0), (3029, 3, 1008467, 14.4, "ちゅ、お注射。", 0, 0),
    (3010, 4, 1009328, 14.3, "お返事まだカナ？おじさん構文！", 0, 0),
    (3030, 3, 1002966, 15.1, "チュウニペンギンのテーマ～左下より愛をこめて～", 0, 0),
    (3085, 3, 1006215, 14.6, "OMAKENO Stroke", 0, 0),
    (3012, 3, 1005562, 14.7, "最終鬼畜妹フランドール・S (原口沙輔は鬼畜なのか？remix)", 0, 0),
    (3024, 3, 1007669, 14.3, "SOMA TONE", 0, 0), (3011, 4, 1007573, 14.3, "テレパシ", 0, 0),
    (3089, 3, 1009653, 14.0, "Cryogenic", 1, 0), (3025, 2, 1009222, 13.7, "Tachy∅n", 0, 0),
]
CHU_RATING = "16.01"


def chu_rating_json(old_const: dict | None = None) -> dict:
    """/public/u/player_a/chusan/rating 的结构。old_const = {musicId: 定数} 给 version 24500 放一个不同的值。"""
    songs: dict[int, dict] = {}
    details = []
    part = {}
    for key, table in (("b30", CHU_B30), ("n20", CHU_N20)):
        part[key] = []
        for mid, lv, score, const, name, fc, aj in table:
            part[key].append({"musicId": mid, "level": lv, "achievement": score})
            details.append({"musicId": mid, "level": lv, "scoreMax": score, "isFullCombo": bool(fc),
                            "isAllJustice": bool(aj), "playCount": 1, "id": 1, "userId": 74819})
            song = songs.setdefault(mid, {"id": mid, "name": name, "charts": []})
            old = (old_const or {}).get(mid, const)
            song["charts"].append({"difficulty": lv, "constants": [{"version": 24500, "constant": old},
                                                                   {"version": 25000, "constant": const}]})
    return {"error": 0, "data": {**part, "r10": part["n20"][:10], "userDetails": details,
                                 "musicDetails": list(songs.values())}}


def chu_playlog_json() -> dict:
    return {"code": 0, "data": {
        "playlog": [{"musicId": 2570, "level": 3, "score": 1007480, "isFullCombo": False, "isAllJustice": False,
                     "isNewRecord": False, "userPlayDate": "2026-10-03T10:53:47+09:00", "track": 4,
                     "romVersion": "2.50.00", "user": {"huge": "x" * 100}},
                    {"musicId": 442, "level": 3, "score": 1008392, "isFullCombo": True, "isAllJustice": False,
                     "isNewRecord": True, "userPlayDate": "2026-10-03T10:47:22+09:00", "track": 2,
                     "romVersion": "2.50.00", "user": {}}],
        "musicData": [{"id": 2570, "name": "ZegalltA"}, {"id": 442, "name": "Ignis Danse"}],
        "userData": {},
    }}
