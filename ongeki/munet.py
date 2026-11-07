"""MuNET O.N.G.E.K.I. data -> GekiBest.

Public endpoints (by username), base https://apidashboard3-cf.mumur.net/api/v3/public/u/{username}:
  /ongeki/rating/new   Re:Fresh rating      -> {data: {bestOld, bestNew, hot, musicDetails, userDetails}}
  /ongeki/rating       bright MEMORY rating -> same shape (hot = recent 10)
  /ongeki/playlog      recent plays
  ""                   profile (rating, version, privacy)

Field names below come from the MuNET portal's own front-end code (2026-11-07):
  bestOld / bestNew / hot items: musicId, level, score, platinumScoreStar
    (Re:Fresh: bestOld = Best 50, bestNew = New 10, hot = Platinum 50;
     old system: bestOld = Best 30, bestNew = New 15, hot = Recent 10)
  userDetails: musicId, level, isFullCombo, isAllBreake (sic), isFullBell, techScoreRank
  musicDetails: id, name, charts
Not yet checked against a real response (no public MuNET player with O.N.G.E.K.I.
data found): constants are therefore taken from otoge-db only, never from
musicDetails.charts, and the technical-score maximum comes from the frame item.
"""
from __future__ import annotations

from . import rating, versions
from .models import GekiBest, GekiChart
from .music import LUNATIC, OngekiMusicDB


def _data(resp: dict | None) -> dict:
    if not isinstance(resp, dict):
        return {}
    d = resp.get("data", resp)
    return d if isinstance(d, dict) else {}


def _items(lst) -> list[dict]:
    return [x for x in (lst or []) if isinstance(x, dict) and int(x.get("musicId") or 0) > 0]


def client_version(profile: dict | None) -> int | None:
    """Best effort: the O.N.G.E.K.I. block of the public profile."""
    d = _data(profile)
    for block in (d.get("ongeki"), (d.get("user") or {}).get("ongeki") if isinstance(d.get("user"), dict) else None, d):
        if isinstance(block, dict):
            for k in ("lastRomVersion", "romVersion", "lastVersion", "version"):
                v = versions.parse_client(block.get(k))
                if v:
                    return v
    return None


def shown_rating(profile: dict | None) -> int | None:
    """Best effort: rating shown on the profile, in thousandths (accepts 21202 or 21.202)."""
    d = _data(profile)
    block = d.get("ongeki") if isinstance(d.get("ongeki"), dict) else None
    if block is None:
        return None
    for k in ("newPlayerRating", "playerRating", "rating"):
        v = block.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(round(v * 1000)) if v < 100 else int(v)
    return None


def build_best(resp: dict, db: OngekiMusicDB, *, refresh: bool, client: int | None = None,
               player: str = "", shown: int | None = None) -> GekiBest:
    d = _data(resp)
    names = {}
    for m in d.get("musicDetails") or []:
        if isinstance(m, dict) and m.get("id") is not None:
            names[int(m["id"])] = m
    lamps = {}
    for u in d.get("userDetails") or []:
        if isinstance(u, dict) and u.get("musicId") is not None:
            lamps[(int(u["musicId"]), int(u.get("level") or 0))] = u

    if client is None:
        client = 151 if refresh else 145

    def chart(it: dict, platinum_frame: bool = False) -> GekiChart:
        mid, diff = int(it["musicId"]), int(it.get("level") or 0)
        score = min(int(it.get("score") or 0), rating.MAX_SCORE)
        m = names.get(mid) or {}
        title = str(m.get("name") or f"#{mid}")
        song = db.match(title, m.get("artist") or m.get("composer"),
                        lunatic=diff == LUNATIC) if m else None
        const = None
        bonus = bool(song and song.bonus)
        if song is not None and not bonus:
            const = song.const(diff, client)
            if const is None:
                const = song.removed_const(diff)
        lp = lamps.get((mid, diff)) or {}
        c = GekiChart(music_id=mid, diff=diff, title=title, score=score, const=const,
                      bonus=bonus, stars=int(it.get("platinumScoreStar") or 0),
                      fc=bool(lp.get("isFullCombo")), ab=bool(lp.get("isAllBreake") or lp.get("isAllBreak")),
                      fb=bool(lp.get("isFullBell")),
                      best_score=rating.score_from_rank(lp.get("techScoreRank")))
        if c.known:
            if not refresh:
                c.rate = rating.old_rate(const, score)
            elif platinum_frame:
                c.ps = rating.ps_rate(const, c.stars)
            else:
                c.rate = rating.ts_rate(const, score, best_score=c.best_score,
                                        fc=c.fc, ab=c.ab, fb=c.fb)
        return c

    best = GekiBest(server="munet", player=player, client=client, shown=shown, refresh=refresh)
    best.best = [chart(i) for i in _items(d.get("bestOld"))]
    best.new = [chart(i) for i in _items(d.get("bestNew"))]
    if refresh:
        best.plat = [chart(i, True) for i in _items(d.get("hot"))]
    else:
        best.recent = [chart(i) for i in _items(d.get("hot"))]
    return best
