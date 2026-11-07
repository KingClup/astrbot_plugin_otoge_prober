"""国服 scores through 水鱼查分器 (Diving-Fish, www.diving-fish.com).

Public query endpoints (no token needed; respects the player's privacy setting on 水鱼):
  POST /api/maimaidxprober/query/player   {"username"|"qq": ..., "b50": true}
       → {nickname, rating, plate, charts: {sd: [...b35], dx: [...b15]}}
       record: {achievements, ds, dxScore, fc, fs, level, level_index, level_label, ra, rate, song_id, title, type}
  POST /api/chunithmprober/query/player   {"username"|"qq": ...}
       → {nickname, rating, records: {b30: [...], r10: [...]}}
       record: {mid, cid, title, level_index, level_label, level, score, fc, ra, ds}
  GET  /api/chunithmprober/music_data     chart constants of the 国服 version
"""
from __future__ import annotations

import httpx

BASE = "https://www.diving-fish.com/api"
UA = {"User-Agent": "astrbot_plugin_otoge_prober"}


class DivingFishError(Exception):
    pass


def _ident(binding: dict) -> dict:
    if binding.get("username"):
        return {"username": binding["username"]}
    if binding.get("qq"):
        return {"qq": str(binding["qq"])}
    raise DivingFishError("没有水鱼用户名或 QQ")


async def _post(path: str, body: dict, timeout: float = 15, transport=None) -> dict:
    async with httpx.AsyncClient(timeout=timeout, headers=UA, transport=transport) as c:
        r = await c.post(BASE + path, json=body)
    if r.status_code == 400:
        raise DivingFishError("水鱼上找不到这个用户（用户名不对，或者没在水鱼绑定这个 QQ）")
    if r.status_code == 403:
        raise DivingFishError("这个水鱼账号设置了隐私 / 没同意用户协议，查不到。去水鱼查分器个人设置里打开就行")
    if r.status_code != 200:
        raise DivingFishError(f"水鱼返回 {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise DivingFishError("水鱼返回的不是 JSON") from e


async def mai_player(binding: dict, transport=None) -> dict:
    return await _post("/maimaidxprober/query/player", {**_ident(binding), "b50": True}, transport=transport)


async def chu_player(binding: dict, transport=None) -> dict:
    return await _post("/chunithmprober/query/player", _ident(binding), transport=transport)


async def chu_music_data(timeout: float = 30, transport=None) -> list[dict]:
    async with httpx.AsyncClient(timeout=timeout, headers=UA, transport=transport) as c:
        r = await c.get(BASE + "/chunithmprober/music_data")
    r.raise_for_status()
    return r.json()
