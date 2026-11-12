"""RinNET 测试数据 + 假服务器。

中二部分是真实数据（玩家本人登录后读的 verse-rating / profile / recent，只留成绩字段）：
  profile.playerRating 1486（游戏 2026-06 最后一次游玩时存的值），verse-rating 算出来 (51047 + 24923) / 50 = 15.19。
舞萌部分是按 RinNET 前端代码的格式造的（这个号没有舞萌数据）。
"""
from __future__ import annotations

import json

import httpx

# musicId, level, score, ratingBase(定数×100), rating(×100，RinNET 算好的), musicName
CHU_OLD = [
    (2892, 3, 1008919, 1520, 1734, "Kaleidoscope"), (2888, 3, 1008091, 1520, 1725, "hyperreality"),
    (2718, 3, 1007868, 1520, 1723, "I Wanna"), (2089, 3, 1007816, 1520, 1723, "Love & Justice"),
    (76, 4, 1007130, 1530, 1722, "luna blu"), (2119, 3, 1006895, 1530, 1717, "parvorbital"),
    (972, 3, 1005804, 1550, 1716, "宿星審判"), (386, 3, 1007274, 1520, 1715, "神威"),
    (2889, 3, 1005743, 1550, 1714, "Deep Blue"), (2796, 3, 1008966, 1500, 1714, "Black MInD"),
    (619, 3, 1007666, 1510, 1711, "End Time"), (2199, 3, 1007573, 1510, 1710, "A Man In The Mirror"),
    (2838, 3, 1004862, 1560, 1708, "神鳴"), (2400, 3, 1006400, 1530, 1708, "LAMIA"),
    (455, 4, 1006928, 1520, 1708, "Vampire"), (2858, 3, 1005873, 1540, 1707, "Everything Will Be One"),
    (2699, 3, 1009826, 1490, 1705, "Chronomia"), (2554, 3, 1006628, 1520, 1702, "MarbleBlue."),
    (2660, 3, 1006074, 1530, 1701, "What's up? Pop!"), (978, 3, 1007392, 1500, 1697, "Ascension to Heaven"),
    (2477, 3, 1005618, 1530, 1692, "sølips"), (2140, 3, 1003676, 1550, 1686, "ピアノ協奏曲第１番”蠍火”"),
    (2651, 3, 1004429, 1540, 1684, "Acid God"), (1055, 3, 1006691, 1500, 1683, "Wizdomiot"),
    (2625, 3, 1006122, 1510, 1682, "Latent Kingdom"), (2800, 3, 1006274, 1500, 1675, "淵底のグレイ・ユークロニア"),
    (2475, 3, 1001550, 1560, 1675, "Chaotic Ørder"),
    (982, 3, 1000248, 1570, 1672, "The Metaverse -First story of the SeelischTact-"),
    (2703, 3, 1007659, 1470, 1671, "Ai C"), (2338, 3, 1003753, 1530, 1667, "Disruptor Array"),
]
CHU_NEW = [
    (2967, 3, 1008650, 1550, 1761, "YOUNITHM"), (2974, 3, 1007734, 1520, 1722, "Marigold"),
    (2978, 3, 1008296, 1500, 1707, "ALTER EGO"), (2966, 3, 1005109, 1550, 1702, "月葬"),
    (2999, 3, 1004019, 1560, 1700, "Melodiniq"), (2967, 4, 1001349, 1580, 1693, "YOUNITHM"),
    (2969, 3, 1003653, 1550, 1686, "μ3"), (2976, 3, 1004227, 1540, 1682, "DESTRUCTION 3,2,1"),
    (2948, 3, 1006655, 1490, 1673, "THE TRiANGLE"), (2999, 4, 990262, 1600, 1661, "Melodiniq"),
    (2938, 3, 995843, 1560, 1643, "Sweet & Sour"), (2954, 3, 997935, 1550, 1641, "Phantom Crisis"),
    (2968, 3, 994481, 1560, 1637, "PANDORA PARADOXXX"), (3000, 3, 1009294, 1350, 1565, "Linked Tune"),
    (2973, 3, 965161, 1510, 1450, "Lips XTC -Sorist Remix-"),          # S 以下，用来核对分段公式
]
CHU_COMPUTED = "15.19"      # (51047 + 24923) / 50
CHU_PROFILE = {"userName": "ＫΣｌｕｐＱωＱ", "level": 10, "playerRating": 1486, "highestRating": 1710,
               "lastRomVersion": "2.45.00", "lastDataVersion": "2.45.01", "playCount": 72,
               "firstPlayDate": "2026-05-15T00:43:12", "lastPlayDate": "2026-06-12T00:22:45", "overPowerRate": 345}
CHU_RECENT = {"page": 0, "totalElements": 215, "totalPages": 22, "content": [
    {"musicId": 2647, "level": 3, "score": 1002956, "rank": 10, "isFullCombo": False, "isAllJustice": False,
     "isNewRecord": True, "isClear": True, "track": 3, "userPlayDate": "2026-06-12T00:21:36", "playerRating": 1486},
    {"musicId": 393, "level": 3, "score": 994520, "rank": 9, "isFullCombo": False, "isAllJustice": False,
     "isNewRecord": True, "isClear": True, "track": 2, "userPlayDate": "2026-06-12T00:17:43", "playerRating": 1486},
    {"musicId": 2199, "level": 3, "score": 1007573, "rank": 12, "isFullCombo": True, "isAllJustice": False,
     "isNewRecord": True, "isClear": True, "track": 3, "userPlayDate": "2026-06-12T00:08:25", "playerRating": 1486},
]}


def verse_json() -> dict:
    row = lambda m, lv, sc, base, ra, name: {"musicId": m, "level": lv, "score": sc, "ratingBase": base,  # noqa: E731
                                             "rating": ra, "musicName": name, "artistName": "x"}
    return {"old": [row(*r) for r in CHU_OLD], "new": [row(*r) for r in CHU_NEW]}


# 舞萌（造的）：两首旧曲两首新曲，DXRating 曲库里都有
MAI_OLD = "11752:3:25015:1005799,11315:3:22011:1007373"
MAI_NEW = "11823:3:25500:1008086,834:3:19900:1005000"
MAI_PROFILE = {"userName": "ＫΣｌｕｐ", "playerRating": 1200, "highestRating": 1200, "lastRomVersion": "1.55.00",
               "playCount": 3}

GOOD_PW, TOTP_PW, TOTP_CODE = "pw-ok", "pw-2fa", "123456"
REFRESH, ACCESS = "RT-0123456789abcdefghijklmnopqrstuvwxyz0123", "AT.jwt.token"
CARD = 900001


def server(calls: list | None = None, *, games=("chusan",), with_mai=False, card=True, refresh_ok=True):
    """假 RinNET。calls 记 (方法, 路径)；不检查明文密码以外的东西就放行。"""
    state = {"refresh_ok": refresh_ok}

    def ok(data):
        return httpx.Response(200, json={"status": {"code": 92001, "message": "OK"}, "data": data})

    def fail(code, msg="", http=200, data=None):
        return httpx.Response(http, json={"status": {"code": code, "message": msg}, "data": data})

    def handler(req: httpx.Request):
        path = req.url.path
        if calls is not None:
            calls.append((req.method, path))
        body = json.loads(req.content or b"{}") if req.method == "POST" else {}
        if path == "/api/auth/signin":
            pw = body.get("password")
            if pw == GOOD_PW:
                return ok({"tokenType": "Bearer", "accessToken": ACCESS, "refreshToken": REFRESH})
            if pw == TOTP_PW:
                return fail(34014, "TOTP required", data={"totpToken": "TT"})
            if pw == "banned":
                return fail(34031, "banned")
            return fail(34011, "login failed")
        if path == "/api/auth/signin/totp":
            if body.get("totpToken") == "TT" and body.get("code") == TOTP_CODE:
                return ok({"tokenType": "Bearer", "accessToken": ACCESS, "refreshToken": REFRESH})
            return fail(34011, "bad code")
        if path == "/api/auth/refresh":
            if body.get("refreshToken") == REFRESH and state["refresh_ok"]:
                return ok({"accessToken": ACCESS})
            return fail(94011, "invalid refresh token", http=401)
        if req.headers.get("authorization") != f"Bearer {ACCESS}":
            return httpx.Response(401, json={"status": {"code": 94011}})
        if path == "/api/user/me":
            cards = [{"id": 1, "extId": CARD, "default": True}] if card else []
            return ok({"username": "PlayerA", "cards": cards, "games": list(games)})
        if req.url.params.get("aimeId") != str(CARD):
            return httpx.Response(400, json={})
        if path == "/api/game/chuni/v2/profile":
            return httpx.Response(200, json=CHU_PROFILE) if "chusan" in games else httpx.Response(404)
        if path == "/api/game/chuni/v2/verse-rating":
            return httpx.Response(200, json=verse_json())
        if path == "/api/game/chuni/v2/recent":
            return httpx.Response(200, json=CHU_RECENT)
        if path == "/api/game/maimai2/profile":
            return httpx.Response(200, json=MAI_PROFILE) if with_mai else httpx.Response(404)
        if path == "/api/game/maimai2/rating":
            return httpx.Response(200, json={"data": MAI_OLD})
        if path == "/api/game/maimai2/new_rating":
            return httpx.Response(200, json={"data": MAI_NEW})
        if path == "/api/game/maimai2/recent":
            return httpx.Response(200, json={"content": [{"musicId": 11823, "level": 3, "achievement": 1008086,
                                                          "deluxscore": 2000, "comboStatus": 2, "syncStatus": 0,
                                                          "isAchieveNewRecord": True, "trackNo": 1,
                                                          "userPlayDate": "2026-06-01T10:00:00"}]})
        return httpx.Response(404)

    t = httpx.MockTransport(handler)
    t.state = state
    return t
