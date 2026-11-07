"""AquaDX O.N.G.E.K.I. data -> GekiBest.

Endpoints (POST, public, by username) under https://aquadx.net/aqua/api/v2/game/ongeki/:
  user-summary          rating, lastVersion, ratingComposition
                        Re:Fresh:  best50 / new10 / pscore50 (+ *_candidates)
                                   item = musicId:difficultId:score:platinumStar:platinumScore
                        older:     best30 / new15 / recent10, item = musicId:difficultId:score
  user-music-from-list  body = [musicId, ...] -> per-chart best: techScoreMax, isFullCombo,
                        isAllBreake (sic), isFullBell, platinumScoreStar, platinumScoreMax
  recent                last plays
Song names / AquaDX's own constants: https://aquadx.net/d/ongeki/00/all-music.json
(id -> {name, composer, lunatic, ver: 1050, notes: [{lv}, ...]}).

Only parsing lives here; the HTTP side goes into core/privsrv/aquadx.py when this
is merged into the plugin.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import rating, versions
from .models import GekiBest, GekiChart
from .music import LUNATIC, OngekiMusicDB

REFRESH_FRAMES = ("new10", "best50", "pscore50")
OLD_FRAMES = ("new15", "best30", "recent10")


@dataclass
class Lamp:
    best_score: int
    fc: bool
    ab: bool
    fb: bool
    stars: int
    platinum: int


def parse_items(s: str | None) -> list[tuple[int, ...]]:
    out = []
    for item in (s or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            t = tuple(int(x) for x in item.split(":"))
        except ValueError:
            continue
        if len(t) >= 3 and t[0] > 0:     # the game pads short frames with 0:0:0:0:0
            out.append(t)
    return out


def parse_lamps(rows: list[dict]) -> dict[tuple[int, int], Lamp]:
    out = {}
    for r in rows or []:
        try:
            key = (int(r["musicId"]), int(r["level"]))
        except (KeyError, TypeError, ValueError):
            continue
        out[key] = Lamp(
            # AquaDX stores 1,010,001 / 1,010,002 on some theoretical-max charts
            best_score=min(int(r.get("techScoreMax") or 0), rating.MAX_SCORE),
            fc=bool(r.get("isFullCombo")), ab=bool(r.get("isAllBreake") or r.get("isAllBreak")),
            fb=bool(r.get("isFullBell")), stars=int(r.get("platinumScoreStar") or 0),
            platinum=int(r.get("platinumScoreMax") or 0))
    return out


def music_ids(summary: dict) -> list[int]:
    """Music ids to ask user-music-from-list about."""
    comp = summary.get("ratingComposition") or {}
    ids = []
    for k in (*REFRESH_FRAMES, *OLD_FRAMES):
        for it in parse_items(comp.get(k)):
            if it[0] not in ids:
                ids.append(it[0])
    return ids


class ChartResolver:
    """music id + difficulty -> title / constant, for one client version."""

    def __init__(self, db: OngekiMusicDB, all_music: dict, client: int | None):
        self.db, self.meta, self.client = db, all_music or {}, client

    def resolve(self, music_id: int, diff: int) -> tuple[str, float | None, bool]:
        m = self.meta.get(str(music_id)) or self.meta.get(music_id) or {}
        title = str(m.get("name") or f"#{music_id}")
        lunatic = diff == LUNATIC or bool(m.get("lunatic"))
        notes = [n.get("lv") for n in (m.get("notes") or [])]
        server_consts = None
        if notes:
            server_consts = [None, None, None, None, notes[0]] if lunatic else (notes + [None] * 5)[:5]
        song = self.db.match(title, m.get("composer"), lunatic=lunatic,
                             server_consts=server_consts) if m else None
        if song is not None:
            if song.bonus:
                return title, None, True
            c = song.const(diff, self.client)
            if c is not None:
                return title, c, False
        # AquaDX's own constant (game data), then a removed song's last known one
        if notes:
            idx = 0 if lunatic else diff
            if 0 <= idx < len(notes) and notes[idx]:
                return title, float(notes[idx]), False
        if song is not None and song.removed_const(diff) is not None:
            return title, song.removed_const(diff), False
        return title, None, False


def build_best(summary: dict, lamps: list[dict] | dict, all_music: dict,
               db: OngekiMusicDB) -> GekiBest:
    client = versions.parse_client(summary.get("lastVersion"))
    comp = summary.get("ratingComposition") or {}
    lamp_map = lamps if isinstance(lamps, dict) else parse_lamps(lamps)
    res = ChartResolver(db, all_music, client)
    # which frames the server stored decides the rating system, not the version string
    refresh = any(comp.get(k) for k in REFRESH_FRAMES) or (
        versions.is_refresh(client) and not any(comp.get(k) for k in OLD_FRAMES))
    best = GekiBest(server="aqua", player=str(summary.get("name") or ""), client=client,
                    shown=summary.get("rating"), refresh=refresh)

    def chart(item: tuple[int, ...], platinum_frame: bool = False) -> GekiChart:
        mid, diff, score = item[0], item[1], item[2]
        stars = item[3] if len(item) > 3 else 0
        plat = item[4] if len(item) > 4 else 0
        title, const, bonus = res.resolve(mid, diff)
        lp = lamp_map.get((mid, diff))
        c = GekiChart(music_id=mid, diff=diff, title=title, score=min(score, rating.MAX_SCORE),
                      const=const, bonus=bonus, stars=stars, platinum=plat,
                      best_score=lp.best_score if lp else 0,
                      fc=bool(lp and lp.fc), ab=bool(lp and lp.ab), fb=bool(lp and lp.fb))
        if c.known:
            if not refresh:
                c.rate = rating.old_rate(const, c.score)
            elif platinum_frame:
                c.ps = rating.ps_rate(const, stars)
            else:
                c.rate = rating.ts_rate(const, c.score, best_score=c.best_score,
                                        fc=c.fc, ab=c.ab, fb=c.fb)
        return c

    if refresh:
        best.new = [chart(i) for i in parse_items(comp.get("new10"))]
        best.best = [chart(i) for i in parse_items(comp.get("best50"))]
        best.plat = [chart(i, True) for i in parse_items(comp.get("pscore50"))]
    else:
        best.new = [chart(i) for i in parse_items(comp.get("new15"))]
        best.best = [chart(i) for i in parse_items(comp.get("best30"))]
        best.recent = [chart(i) for i in parse_items(comp.get("recent10"))]
    return best
