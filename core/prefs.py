"""Cross-game preferences, stored in <data>/prefs.json.

  users.<qq>.last.<game>      server the user queried last (default for their next query)
  groups.<gid>.llm            natural-language (LLM) score queries allowed in this group
  private_llm                 natural-language queries in private chat
  catalog_server.<game>       default server for constants (查歌 / 定数 / 定数表)
"""
from __future__ import annotations

import json
import os
import threading
import time

try:
    from .privsrv import servers as _priv
except ImportError:  # tests import core as a top-level package
    from core.privsrv import servers as _priv

GAMES = ("mai", "chu")
GAME_NAMES = {"mai": "舞萌 DX", "chu": "中二节奏"}
BIND_SERVERS = {g: (*base, *(k for k in _priv.KEYS if _priv.supports(k, g)))   # where scores can be fetched
                for g, base in (("mai", ("intl", "jp", "cn")), ("chu", ("intl", "jp", "cn")))}
CATALOG_SERVERS = {"mai": ("intl", "jp", "cn"), "chu": ("intl", "jp", "cn")}  # whose constants we know
SERVER_NAMES = {"intl": "国际服", "jp": "日服", "cn": "国服", **_priv.NAMES}
SERVER_ALIASES = {
    "intl": "intl", "国际服": "intl", "国际": "intl", "int": "intl", "international": "intl", "外服": "intl",
    "jp": "jp", "日服": "jp", "日本": "jp", "japan": "jp",
    "cn": "cn", "国服": "cn", "中国": "cn", "china": "cn", "水鱼": "cn", "落雪": "cn",
}


class Prefs:
    def __init__(self, root: str):
        self.path = os.path.join(root, "prefs.json")
        self._lock = threading.Lock()
        try:
            with open(self.path, encoding="utf-8") as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}
        self.d.setdefault("users", {})
        self.d.setdefault("groups", {})
        self.d.setdefault("catalog_server", {"mai": "intl", "chu": "intl"})
        self.d.setdefault("private_llm", False)

    def _save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)

    # ---------- last-used server ----------
    def last(self, uid: str, game: str) -> str:
        return ((self.d["users"].get(str(uid)) or {}).get("last") or {}).get(game, "")

    def set_last(self, uid: str, game: str, server: str) -> None:
        u = self.d["users"].setdefault(str(uid), {})
        if (u.get("last") or {}).get(game) == server:
            return
        u.setdefault("last", {})[game] = server
        u["at"] = int(time.time())
        self._save()

    def last_game(self, uid: str) -> str:
        return (self.d["users"].get(str(uid)) or {}).get("last_game", "")

    def set_last_game(self, uid: str, game: str) -> None:
        u = self.d["users"].setdefault(str(uid), {})
        if u.get("last_game") != game:
            u["last_game"] = game
            self._save()

    # ---------- 图上 / 传分网站上显示哪些附加分数（每人一份，默认都显示） ----------
    SHOW_KEYS = {"sdvx_ex": "SDVX EX SCORE", "mai_dx": "舞萌 DX 分", "geki_plat": "音击白金分"}

    def show(self, uid: str, key: str) -> bool:
        return bool(((self.d["users"].get(str(uid)) or {}).get("show") or {}).get(key, True))

    def set_show(self, uid: str, key: str, on: bool) -> None:
        if key not in self.SHOW_KEYS:
            raise KeyError(key)
        u = self.d["users"].setdefault(str(uid), {})
        if self.show(uid, key) == bool(on):
            return
        u.setdefault("show", {})[key] = bool(on)
        self._save()

    def shows(self, uid: str) -> dict[str, bool]:
        return {k: self.show(uid, k) for k in self.SHOW_KEYS}

    # ---------- catalog default server ----------
    def catalog_server(self, game: str) -> str:
        return (self.d.get("catalog_server") or {}).get(game) or "intl"

    def set_catalog_server(self, game: str, server: str) -> None:
        self.d.setdefault("catalog_server", {})[game] = server
        self._save()

    # ---------- natural language switch ----------
    def llm_enabled(self, group_id: str | None) -> bool:
        if not group_id:
            return bool(self.d.get("private_llm", False))
        return bool((self.d["groups"].get(str(group_id)) or {}).get("llm", False))

    def set_llm(self, group_id: str | None, on: bool) -> None:
        if not group_id:
            self.d["private_llm"] = bool(on)
        else:
            g = self.d["groups"].setdefault(str(group_id), {})
            g["llm"] = bool(on)
            g["at"] = int(time.time())
        self._save()

    def llm_groups(self) -> dict[str, bool]:
        return {gid: bool(g.get("llm")) for gid, g in self.d["groups"].items()}

    # ---------- 热闹时邀请小游戏（每个群一个开关，默认关） ----------
    def invite_enabled(self, group_id: str | None) -> bool:
        return bool(group_id) and bool((self.d["groups"].get(str(group_id)) or {}).get("invite", False))

    def set_invite(self, group_id: str, on: bool) -> None:
        g = self.d["groups"].setdefault(str(group_id), {})
        g["invite"] = bool(on)
        g["at"] = int(time.time())
        self._save()

    def add_group(self, group_id: str) -> None:
        """WebUI 里先把群加进列表（两个开关都关着），之后再一个个打开。"""
        if str(group_id) not in self.d["groups"]:
            self.d["groups"][str(group_id)] = {"at": int(time.time())}
            self._save()

    def remove_group(self, group_id: str) -> None:
        if self.d["groups"].pop(str(group_id), None) is not None:
            self._save()

    def group_switches(self) -> dict[str, dict]:
        return {gid: {"llm": bool(g.get("llm")), "invite": bool(g.get("invite"))} for gid, g in self.d["groups"].items()}

    def invite_settings(self) -> dict:
        return dict(self.d.get("invite") or {})

    def set_invite_settings(self, values: dict) -> None:
        self.d["invite"] = dict(values)
        self._save()

    # ---------- 小游戏总开关（WebUI 里切，不用重载；None = 跟插件配置） ----------
    def games_enabled(self) -> bool | None:
        v = self.d.get("games_enabled")
        return None if v is None else bool(v)

    def set_games_enabled(self, on: bool) -> None:
        self.d["games_enabled"] = bool(on)
        self._save()

    # ---------- 群名（从 QQ 读到的，WebUI 显示在群号旁边） ----------
    def group_names(self) -> dict[str, str]:
        return dict(self.d.get("group_names") or {})

    def set_group_names(self, names: dict[str, str]) -> None:
        cur = self.d.setdefault("group_names", {})
        changed = False
        for k, v in names.items():
            if v and cur.get(str(k)) != v:
                cur[str(k)] = str(v)[:60]
                changed = True
        if changed:
            self._save()
