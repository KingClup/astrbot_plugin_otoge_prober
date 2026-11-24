"""公开名片：自己发「/名片 开」才有。开了以后每次查 B50，名片上那个游戏的成绩图和 rating 跟着更新。

名片是一个固定的公开链接（<网站>/u/<随机短码>），不用登录谁都能看，所以只放成绩图本来就有的东西：
游戏里的名字（在图上）、rating、更新时间。QQ 号不出现在名片上。发「/名片 关」就整张删掉。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time

GAMES = ("mai", "chu", "geki", "sdvx")
GAME_NAME = {"mai": "舞萌 DX", "chu": "中二节奏", "geki": "音击", "sdvx": "SOUND VOLTEX"}
HIST_MAX = 120
_SLUG = re.compile(r"^[a-z0-9]{8,16}$")
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _slug() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(10))


class Cards:
    def __init__(self, root: str):
        self.root = root
        self.dir = os.path.join(root, "cards")
        self.path = os.path.join(root, "cards.json")
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("users", {})
        self._by_slug = {u["slug"]: uid for uid, u in self.data["users"].items() if u.get("slug")}

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        os.makedirs(self.root, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, self.path)

    # ---------- 开 / 关 ----------
    def get(self, uid: str) -> dict | None:
        u = self.data["users"].get(str(uid))
        return u if u and u.get("on") else None

    def enable(self, uid: str, name: str = "") -> dict:
        uid = str(uid)
        u = self.data["users"].get(uid)
        if u is None or not u.get("slug"):
            s = _slug()
            while s in self._by_slug:
                s = _slug()
            u = {"slug": s, "created": int(time.time()), "games": {}}
            self.data["users"][uid] = u
            self._by_slug[s] = uid
        u["on"] = True
        if name:
            u["name"] = name[:24]
        self._save()
        return u

    def disable(self, uid: str) -> bool:
        uid = str(uid)
        u = self.data["users"].pop(uid, None)
        if u is None:
            return False
        self._by_slug.pop(u.get("slug", ""), None)
        if u.get("slug") and _SLUG.match(u["slug"]):
            shutil.rmtree(os.path.join(self.dir, u["slug"]), ignore_errors=True)
        self._save()
        return True

    def relink(self, uid: str) -> dict | None:
        """换一个链接（旧链接马上失效），图和记录留着。"""
        u = self.get(uid)
        if u is None:
            return None
        old = u["slug"]
        s = _slug()
        while s in self._by_slug:
            s = _slug()
        if os.path.isdir(os.path.join(self.dir, old)):
            os.replace(os.path.join(self.dir, old), os.path.join(self.dir, s))
        self._by_slug.pop(old, None)
        self._by_slug[s] = str(uid)
        u["slug"] = s
        self._save()
        return u

    # ---------- 更新 ----------
    def update(self, uid: str, game: str, image: bytes, rating: float | None = None, label: str = "",
               name: str = "") -> bool:
        u = self.get(uid)
        if u is None or game not in GAMES or not image:
            return False
        d = os.path.join(self.dir, u["slug"])
        os.makedirs(d, exist_ok=True)
        ext = "png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
        for old in ("png", "jpg"):
            if old != ext:
                try:
                    os.remove(os.path.join(d, f"{game}.{old}"))
                except OSError:
                    pass
        tmp = os.path.join(d, f"{game}.{ext}.tmp")
        with open(tmp, "wb") as f:
            f.write(image)
        os.replace(tmp, os.path.join(d, f"{game}.{ext}"))
        now = int(time.time())
        g = u["games"].setdefault(game, {"hist": []})
        g.update({"ts": now, "ext": ext, "label": label[:24]})
        if rating is not None:
            r = round(float(rating), 3)
            g["rating"] = r
            hist = g.setdefault("hist", [])
            day = time.strftime("%Y-%m-%d", time.gmtime(now + 8 * 3600))       # 按北京时间分天
            if hist and hist[-1][0] == day:
                hist[-1][1] = r
            else:
                hist.append([day, r])
            del hist[:-HIST_MAX]
        if name and not u.get("name"):
            u["name"] = name[:24]
        self._save()
        return True

    # ---------- 给网页 ----------
    def public(self, slug: str) -> dict | None:
        if not _SLUG.match(slug or ""):
            return None
        uid = self._by_slug.get(slug)
        u = self.data["users"].get(uid or "")
        if not u or not u.get("on"):
            return None
        games = []
        for k in GAMES:
            g = u["games"].get(k)
            if not g or not g.get("ts"):
                continue
            hist = g.get("hist") or []
            games.append({"game": k, "name": GAME_NAME[k], "rating": g.get("rating"), "label": g.get("label", ""),
                          "ts": g["ts"], "img": f"/u/{slug}/{k}.{g.get('ext', 'jpg')}?t={g['ts']}",
                          "hist": hist[-60:],
                          "delta": round(hist[-1][1] - hist[-2][1], 3) if len(hist) >= 2 else None})
        return {"name": u.get("name", ""), "created": u.get("created", 0), "games": games}

    def image_path(self, slug: str, fname: str) -> str | None:
        if not _SLUG.match(slug or "") or slug not in self._by_slug:
            return None
        m = re.match(r"^(mai|chu|geki|sdvx)\.(jpg|png)$", fname or "")
        if not m:
            return None
        u = self.data["users"].get(self._by_slug[slug]) or {}
        if not u.get("on"):
            return None
        p = os.path.join(self.dir, slug, fname)
        return p if os.path.isfile(p) else None
