"""只给机器人主人看的使用统计：每天多少人在用、哪些指令用得多、绑定链接发出去有多少人真的绑完、网站被点开多少次。

只记数，不记内容：用户和群只存一个加盐的短哈希（用来数「几个人」），不存 QQ 号、不存发了什么。
存在插件数据目录的 stats.json 里，保留最近 120 天。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import time
from zoneinfo import ZoneInfo

KEEP_DAYS = 120
GAME_NAME = {"mai": "舞萌", "chu": "中二", "geki": "音击", "sdvx": "SDVX", "pjsk": "PJSK", "chart": "谱面",
             "core": "通用", "games": "小游戏"}
# 记到「指令」这一栏里的子指令；别的（歌名之类）一律算「其他」，不把用户打的字存下来
KNOWN_SUBS = {
    "b50", "理论", "成绩", "我", "最近", "详情", "刷新", "更新", "查歌", "定数", "定数表", "分数线", "随歌", "谱面",
    "别名", "加别名", "删别名", "绑定", "解绑", "切换", "公开", "好友码", "网页绑定", "传分", "传", "批量传", "雷达",
    "领航员", "帮助", "账号", "进度", "邀请", "统计", "名片", "同步", "曲库", "绑定教程", "文字", "ex", "dx分", "白金分",
    "猜歌", "猜曲绘", "猜谱面", "提示", "结束",
}
_ALIAS = {"best": "b50", "best50": "b50", "vf": "b50", "ra": "b50", "rating": "b50", "me": "我", "info": "我", "资料": "我",
          "recent": "最近", "bind": "绑定", "unbind": "解绑", "help": "帮助", "theory": "理论", "max": "理论",
          "理论ra": "理论", "理论值": "理论", "chart": "谱面", "查": "查歌", "song": "查歌", "sync": "同步"}


def norm_sub(sub: str) -> str:
    s = (sub or "").strip().lower()
    s = _ALIAS.get(s, s)
    if not s:
        return "帮助"
    return s if s in KNOWN_SUBS else "其他"


class Stats:
    def __init__(self, path: str, tz: str = "Australia/Sydney"):
        self.path = path
        self.tz = tz
        self._dirty = 0
        self._saved = 0.0
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("salt", secrets.token_hex(8))
        self.data.setdefault("days", {})

    # ---------- 记 ----------
    def today(self) -> str:
        try:
            return dt.datetime.now(ZoneInfo(self.tz)).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return dt.datetime.now().strftime("%Y-%m-%d")

    def _day(self) -> dict:
        d = self.data["days"].setdefault(self.today(), {})
        for k in ("cmd", "users", "groups", "funnel", "web", "ref"):
            d.setdefault(k, {})
        d.setdefault("priv", 0)
        d.setdefault("grp", 0)
        d.setdefault("official", 0)
        return d

    def _hash(self, x: str) -> str:
        return hashlib.sha1((self.data["salt"] + str(x)).encode()).hexdigest()[:10]

    def hit(self, uid: str, game: str, sub: str = "", *, private: bool = True, official: bool = False,
            group: str = "") -> None:
        """一条被当成指令处理的消息。"""
        try:
            d = self._day()
            key = f"{game or 'core'}.{norm_sub(sub)}"
            d["cmd"][key] = d["cmd"].get(key, 0) + 1
            h = self._hash(uid)
            d["users"][h] = d["users"].get(h, 0) + 1
            if private:
                d["priv"] += 1
            else:
                d["grp"] += 1
                if group:
                    g = self._hash("g" + group)
                    d["groups"][g] = d["groups"].get(g, 0) + 1
            if official:
                d["official"] += 1
            self._touch()
        except Exception:  # noqa: BLE001
            pass

    def bump(self, kind: str, key: str, n: int = 1) -> None:
        """kind = funnel（绑定 / 传分链接的几步）、web（页面被打开）、ref（从哪来的）。"""
        try:
            d = self._day()
            d.setdefault(kind, {})
            d[kind][key] = d[kind].get(key, 0) + n
            self._touch()
        except Exception:  # noqa: BLE001
            pass

    def _touch(self) -> None:
        self._dirty += 1
        if self._dirty >= 20 or time.time() - self._saved > 30:
            self.save()

    def save(self) -> None:
        if not self._dirty:
            return
        days = self.data["days"]
        for k in sorted(days)[:-KEEP_DAYS]:
            days.pop(k, None)
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self.path)
            self._dirty = 0
            self._saved = time.time()
        except OSError:
            pass

    # ---------- 看 ----------
    def _range(self, n: int) -> list[tuple[str, dict]]:
        end = dt.date.fromisoformat(self.today())
        out = []
        for i in range(n - 1, -1, -1):
            k = (end - dt.timedelta(days=i)).isoformat()
            out.append((k, self.data["days"].get(k) or {}))
        return out

    def summary(self, n: int = 7) -> dict:
        days = self._range(n)
        users, groups, cmd, funnel, web, ref = set(), set(), {}, {}, {}, {}
        priv = grp = official = 0
        per_day = []
        for k, d in days:
            users |= set(d.get("users") or {})
            groups |= set(d.get("groups") or {})
            for src, dst in ((d.get("cmd"), cmd), (d.get("funnel"), funnel), (d.get("web"), web), (d.get("ref"), ref)):
                for kk, v in (src or {}).items():
                    dst[kk] = dst.get(kk, 0) + v
            priv += d.get("priv", 0)
            grp += d.get("grp", 0)
            official += d.get("official", 0)
            per_day.append((k, len(d.get("users") or {}), sum((d.get("cmd") or {}).values()),
                            sum((d.get("web") or {}).values())))
        return {"days": n, "users": len(users), "groups": len(groups), "cmd": cmd, "funnel": funnel, "web": web,
                "ref": ref, "priv": priv, "grp": grp, "official": official, "per_day": per_day}

    def report(self, n: int = 7) -> str:
        n = max(1, min(int(n or 7), KEEP_DAYS))
        s = self.summary(n)
        total = sum(s["cmd"].values())
        if not total and not s["web"] and not s["funnel"]:
            return f"最近 {n} 天还没有记到任何使用（统计是从装上这一版开始记的）。"
        out = [f"使用统计 · 最近 {n} 天（到 {self.today()}）", ""]
        out.append(f"用过的人：{s['users']} 个　指令：{total} 次　有人用的群：{s['groups']} 个")
        out.append(f"私聊 {s['priv']} 次 / 群里 {s['grp']} 次" + (f"　其中官方机器人 {s['official']} 次" if s["official"] else ""))
        by_game: dict[str, int] = {}
        for k, v in s["cmd"].items():
            g = k.split(".", 1)[0]
            by_game[g] = by_game.get(g, 0) + v
        if by_game:
            out += ["", "按游戏：" + "　".join(f"{GAME_NAME.get(g, g)} {v}" for g, v in sorted(by_game.items(), key=lambda x: -x[1]))]
        top = sorted(s["cmd"].items(), key=lambda x: -x[1])[:10]
        if top:
            out.append("用得最多：")
            for k, v in top:
                g, _, sub = k.partition(".")
                out.append(f"  {GAME_NAME.get(g, g)} {sub}　{v}")
        f = s["funnel"]
        if f:
            out.append("")
            bi, bo, bd = f.get("bind_issued", 0), f.get("bind_opened", 0), f.get("bind_done", 0)
            if bi or bo or bd:
                rate = f"（发出去的里 {bd * 100 // bi}% 绑完了）" if bi else ""
                out.append(f"绑定链接：发出 {bi} → 打开 {bo} → 绑成 {bd}{rate}")
            si, so = f.get("score_issued", 0), f.get("score_login", 0)
            if si or so:
                out.append(f"传分链接：发出 {si} → 登录 {so}")
            sr = f.get("score_saved", 0)
            if sr:
                out.append(f"网页上传了 {sr} 条成绩")
            pv = f.get("card_view", 0)
            if pv or f.get("card_on", 0):
                out.append(f"名片：新开 {f.get('card_on', 0)} 张，被看了 {pv} 次")
        w = s["web"]
        if w:
            names = {"home": "主页", "bind": "绑定页", "scores": "传分站", "card": "名片页"}
            out += ["", "网站被打开：" + "　".join(f"{names.get(k, k)} {v}" for k, v in sorted(w.items(), key=lambda x: -x[1]))]
            r = s["ref"]
            if r:
                out.append("从哪来的：" + "　".join(f"{k} {v}" for k, v in sorted(r.items(), key=lambda x: -x[1])[:6]))
        if n > 1:
            out += ["", "每天（人数 / 指令 / 网站）："]
            for k, u, c, wv in s["per_day"][-14:]:
                out.append(f"  {k[5:]}　{u} / {c} / {wv}")
        out += ["", "只记次数，不记内容；用户和群只存一个打乱过的短码用来数人数。看更久：/查分 统计 30"]
        return "\n".join(out)
