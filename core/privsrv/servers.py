"""私服登记表：名字、别名、客户端版本 → 版本名。舞萌、中二、帮助、自然语言都从这里取，不各写一份。

加一个私服 = 写一个客户端文件 + 在 SERVERS 里加一行。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from . import aquadx, munet, rinnet


@dataclass(frozen=True)
class PrivServer:
    key: str
    name: str
    aliases: tuple[str, ...]
    games: tuple[str, ...]            # 支持查分的游戏：mai / chu
    site: str                         # 绑定提示里告诉用户去哪儿
    make_client: Callable             # (hub) -> 客户端
    auth: str = "username"            # username = 公开主页按用户名查；login = 要玩家登录（只存加密令牌）


SERVERS: dict[str, PrivServer] = {
    "munet": PrivServer("munet", "MuNET", ("munet", "mu", "mu服", "木服", "mumur"), ("mai", "chu"),
                        "portal.mumur.net/u/<用户名>", lambda hub: munet.MunetClient(hub.get_json)),
    "rin": PrivServer("rin", "RinNET", ("rin", "rinnet", "rin服", "林服", "naominet"), ("mai", "chu"),
                      "portal.naominet.live", lambda hub: rinnet.RinClient(hub), auth="login"),
    "aqua": PrivServer("aqua", "AquaDX", ("aqua", "aquadx", "aqua服"), ("mai", "chu"),
                       "aquadx.net/u/<用户名>", lambda hub: aquadx.AquadxClient(hub)),
}
KEYS: tuple[str, ...] = tuple(SERVERS)
ALIASES: dict[str, str] = {a.lower(): s.key for s in SERVERS.values() for a in (s.key, s.name, *s.aliases)}
NAMES: dict[str, str] = {k: s.name for k, s in SERVERS.items()}


def is_priv(server: str | None) -> bool:
    return server in SERVERS


def supports(server: str, game: str) -> bool:
    s = SERVERS.get(server)
    return bool(s and game in s.games)


# 私服跟日服 / 国际服用同一套客户端；客户端版本号 → 版本名（出图的 logo、标签用）
MAI_ROM_NAMES = {40: "BUDDiES", 45: "BUDDiES PLUS", 50: "PRiSM", 55: "PRiSM PLUS",
                 60: "CiRCLE", 65: "CiRCLE PLUS", 70: "MAGiCAL"}
CHU_ROM_NAMES = {20: "LUMINOUS", 25: "LUMINOUS PLUS", 30: "VERSE", 50: "Mate"}


def _rom_minor(rom: str, major: int) -> int | None:
    m = re.match(rf"^\s*{major}\.(\d{{2}})", rom or "")
    return int(m.group(1)) if m else None


def mai_version_name(rom: str) -> str:
    """'1.66.00' → 'CiRCLE PLUS'；认不出返回空串。"""
    minor = _rom_minor(rom, 1)
    if minor is None:
        return ""
    return MAI_ROM_NAMES.get(minor // 5 * 5, "")


def chu_version_name(rom: str) -> str:
    """'2.50.00' → 'Mate'；表里没有的版本返回空串（标签上改写 Ver.2.45）。"""
    minor = _rom_minor(rom, 2)
    if minor is None:
        return ""
    return CHU_ROM_NAMES.get(minor // 5 * 5, "")


def rom_label(rom: str) -> str:
    m = re.match(r"^\s*(\d+\.\d{2})", rom or "")
    return f"Ver.{m.group(1)}" if m else ""


def parse_username(text: str) -> str:
    """私服网站用户名：也接受整条主页链接（…/u/<用户名>/mai2）和前面的 @；不像用户名的返回空串。"""
    t = (text or "").strip()
    if (m := re.search(r"/u/([^/?#\s]+)", t)):
        t = m.group(1)
    t = t.split()[0].lstrip("@") if t else ""
    return t if re.fullmatch(r"[A-Za-z0-9_.\-]{1,64}", t) else ""
