"""Fetch O.N.G.E.K.I. data from private servers.

The HTTP layer is injected so this can sit on the plugin's own client
(core/privsrv Hub) later:  get(url) / post(url, json=None) are async and return
(status, parsed_json_or_None).
"""
from __future__ import annotations

from typing import Awaitable, Callable
from urllib.parse import quote

from . import aquadx, munet
from .models import GekiBest
from .music import OngekiMusicDB

AQUA_API = "https://aquadx.net/aqua/api/v2/game/ongeki"
AQUA_MUSIC = "https://aquadx.net/d/ongeki/00/all-music.json"
MUNET_API = "https://apidashboard3-cf.mumur.net/api/v3/public/u"

Http = Callable[..., Awaitable[tuple[int, object]]]


class GekiError(Exception):
    """User-facing error; str(e) is the reply."""


class NotFound(GekiError):
    pass


class NoData(GekiError):
    pass


class Hidden(GekiError):
    pass


class ServerDown(GekiError):
    pass


def _check(status: int, server: str, username: str) -> None:
    if status == 404:
        raise NotFound(f"{server} 上找不到用户 {username}")
    if status in (401, 403):
        raise Hidden(f"{server} 上 {username} 的音击数据没有公开")
    if status >= 500 or status == 0:
        raise ServerDown(f"{server} 暂时连不上（{status or '超时'}），稍后再试")
    if status >= 400:
        raise GekiError(f"{server} 返回错误 {status}")


async def aquadx_best(post: Http, get: Http, username: str, db: OngekiMusicDB,
                      all_music: dict | None = None) -> GekiBest:
    u = quote(username, safe="")
    status, summary = await post(f"{AQUA_API}/user-summary?username={u}")
    _check(status, "AquaDX", username)
    if not isinstance(summary, dict):
        raise ServerDown("AquaDX 返回的数据看不懂")
    comp = summary.get("ratingComposition") or {}
    if not any(comp.get(k) for k in (*aquadx.REFRESH_FRAMES, *aquadx.OLD_FRAMES)):
        raise NoData(f"AquaDX 上 {username} 还没有音击 rating 记录，打一局再查")
    ids = aquadx.music_ids(summary)
    status, lamps = await post(f"{AQUA_API}/user-music-from-list?username={u}", json=ids)
    if status != 200 or not isinstance(lamps, list):
        lamps = []          # still usable; FB/FC/AB bonuses will be missing (calc shows lower)
    if all_music is None:
        status, all_music = await get(AQUA_MUSIC)
        if status != 200 or not isinstance(all_music, dict):
            all_music = {}
    return aquadx.build_best(summary, lamps, all_music, db)


async def munet_best(get: Http, username: str, db: OngekiMusicDB) -> GekiBest:
    u = quote(username, safe="")
    status, profile = await get(f"{MUNET_API}/{u}")
    _check(status, "MuNET", username)
    client = munet.client_version(profile)
    refresh = client is None or client >= 150
    status, resp = await get(f"{MUNET_API}/{u}/ongeki/rating{'/new' if refresh else ''}")
    _check(status, "MuNET", username)
    best = munet.build_best(resp, db, refresh=refresh, client=client, player=username,
                            shown=munet.shown_rating(profile))
    if not (best.best or best.new):
        raise NoData(f"MuNET 上 {username} 没有音击 rating 记录（或在隐私设置里隐藏了）")
    return best
