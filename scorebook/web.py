"""传分网站：挂在网页绑定那个小 HTTP 服务上（同一个端口 / 同一条 Cloudflare 隧道），路径 /scores。

登录：QQ 里发「/传分」→ 一次性链接 https://<域名>/scores#t=<令牌>（15 分钟，用一次就作废）
     → 网页把令牌换成 30 天的会话 cookie（HttpOnly + SameSite=Strict，只存哈希）。
不登录也能逛曲库；传分 / 加外号要登传。写操作要 JSON + X-SB 请求头（加上 SameSite=Strict，防跨站提交）。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time

from . import calc as K
from .store import ScoreError

try:
    from ..core.bindweb import RateLimit, mask_qq
except ImportError:  # tests import packages top-level
    from core.bindweb import RateLimit, mask_qq

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "scores")
COOKIE = "sb"
GAMES = ("sdvx", "geki")


class ScoreWeb:
    def __init__(self, book, *, bot_name: str = "AstrBot", log=None, notify=None):
        self.book = book
        self.bot_name = bot_name
        self.log = log or (lambda s: None)
        self.ip_api = RateLimit(240, 60)
        self.ip_login = RateLimit(10, 60)
        self.user_write = RateLimit(90, 60)
        self.user_alias = RateLimit(20, 3600)
        self.user_batch = RateLimit(60, 3600)
        self.ip_jk = RateLimit(1200, 60)
        self._payload: dict[str, tuple[int, bytes]] = {}
        self.bind = None                       # 同一个服务上的网页绑定（BindWeb）：绑定页上直接进传分网站用

    def attach_bind(self, bindweb) -> None:
        self.bind = bindweb

    def add_routes(self, app) -> None:
        r = app.router
        r.add_get("/scores", self.page)
        r.add_get("/scores/", self.page)
        r.add_get("/scores/app.js", self.static)
        r.add_get("/scores/app.css", self.static)
        r.add_get("/api/sb/me", self.api_me)
        r.add_post("/api/sb/login", self.api_login)
        r.add_post("/api/sb/logout", self.api_logout)
        r.add_post("/api/sb/pending", self.api_pending)
        r.add_post("/api/sb/show", self.api_show)
        r.add_get("/api/sb/catalog", self.api_catalog)
        r.add_get("/api/sb/search", self.api_search)
        r.add_get("/api/sb/scores", self.api_scores)
        r.add_post("/api/sb/score", self.api_score)
        r.add_post("/api/sb/delete", self.api_delete)
        r.add_post("/api/sb/alias", self.api_alias)
        r.add_get("/api/sb/export", self.api_export)
        r.add_get("/api/sb/jk/{game}/{name}", self.api_jacket)
        r.add_post("/api/sb/batch", self.api_batch)
        r.add_post("/api/sb/batch_apply", self.api_batch_apply)
        r.add_post("/api/sb/from_bind", self.api_from_bind)

    # ---------- 工具 ----------
    @staticmethod
    def _ip(request) -> str:
        try:
            from ..core.bindweb import BindWeb
        except ImportError:
            from core.bindweb import BindWeb
        return BindWeb.client_ip(request)

    def _json(self, data, status: int = 200):
        from aiohttp import web
        return web.json_response(data, status=status, dumps=lambda o: json.dumps(o, ensure_ascii=False))

    def _user(self, request) -> dict | None:
        return self.book.sessions.get(request.cookies.get(COOKIE, ""))

    @staticmethod
    def _secure(request) -> bool:
        return request.secure or request.headers.get("X-Forwarded-Proto", "") == "https" \
            or "https" in request.headers.get("CF-Visitor", "")

    async def _body(self, request) -> dict | None:
        if request.headers.get("Content-Type", "").split(";")[0].strip() != "application/json" \
                or request.headers.get("X-SB") != "1":
            return None
        try:
            d = await request.json()
            return d if isinstance(d, dict) else None
        except Exception:  # noqa: BLE001
            return None

    async def _body_big(self, request, limit: int = 2 * 1024 * 1024) -> dict | None:
        """批量传分（官网 CSV 一份能有一两百 KB）：绕开整个服务 16 KB 的请求上限，只在这两个接口上放宽到 2 MB。"""
        if request.headers.get("Content-Type", "").split(";")[0].strip() != "application/json" \
                or request.headers.get("X-SB") != "1":
            return None
        if request.content_length is not None and request.content_length > limit:
            return None
        buf = bytearray()
        while True:
            chunk = await request.content.read(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > limit:
                return None
        try:
            d = json.loads(bytes(buf).decode("utf-8"))
            return d if isinstance(d, dict) else None
        except (ValueError, UnicodeDecodeError):
            return None

    def _game(self, g) -> str | None:
        g = str(g or "")
        return g if g in GAMES and self.book.cat(g) is not None else None

    # ---------- 页面 ----------
    async def page(self, request):
        from aiohttp import web
        with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
            html = f.read().replace("{{BOT}}", _esc(self.bot_name))
        return web.Response(text=html, content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-cache"})

    async def static(self, request):
        from aiohttp import web
        name = request.path.rsplit("/", 1)[-1]
        ctype = "application/javascript" if name.endswith(".js") else "text/css"
        with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
            resp = web.Response(text=f.read(), content_type=ctype, charset="utf-8",
                                headers={"Cache-Control": "no-cache"})
        return resp

    # ---------- 登录 ----------
    async def api_me(self, request):
        if not self.ip_api.allow(self._ip(request)):
            return self._json({"error": "请求太频繁"}, 429)
        u = self._user(request)
        cats = {g: {"songs": len(c), "built": c.built} for g, c in self.book.cats.items()}
        if u is None:
            return self._json({"login": False, "bot": self.bot_name, "catalogs": cats})
        name = self.book.store.user(u["uid"]).get("name") or u.get("name") or ""
        return self._json({"login": True, "bot": self.bot_name, "qq": mask_qq(u["uid"]), "name": name,
                           "catalogs": cats, "show": self._shows(u["uid"])})

    def _shows(self, uid: str) -> dict:
        p = self.book.prefs
        return p.shows(uid) if p is not None else {"sdvx_ex": True, "mai_dx": True, "geki_plat": True}

    async def api_show(self, request):
        """网页上的「显示 EX / 白金分」开关：存到插件的用户设置里，出图也按这个。"""
        if not self.ip_api.allow(self._ip(request)):
            return self._json({"ok": False, "message": "太频繁了"}, 429)
        u = self._user(request)
        if u is None:
            return self._json({"ok": False, "message": "没登录"}, 401)
        b = await self._body(request)
        k = str((b or {}).get("k") or "")
        if b is None or k not in ("sdvx_ex", "mai_dx", "geki_plat"):
            return self._json({"ok": False, "message": "bad request"}, 400)
        if self.book.prefs is not None:
            self.book.prefs.set_show(u["uid"], k, bool(b.get("on")))
        return self._json({"ok": True, "show": self._shows(u["uid"])})

    async def api_login(self, request):
        ip = self._ip(request)
        if not self.ip_api.allow(ip) or not self.ip_login.allow(ip):
            return self._json({"ok": False, "message": "太频繁了，稍等一分钟"}, 429)
        body = await self._body(request)
        if body is None:
            return self._json({"ok": False, "message": "bad request"}, 400)
        got = self.book.sessions.redeem(str(body.get("t") or ""))
        if got is None:
            return self._json({"ok": False, "message": "登录链接过期了或者已经用过了。回 QQ 发「/传分」要一个新的"}, 401)
        sess, info = got
        if not sess:                                   # 群里发的链接：先出确认码，等本人在 QQ 回
            self.log(f"[otoge] scorebook login pending {mask_qq(info['uid'])} ({self._ua(request)})")
            return self._json({"ok": False, "pending": True, "pid": info["pid"], "code": info["code"],
                               "game": info.get("game") or "", "ttl": 300})
        return self._logged_in(request, sess, info)

    def _logged_in(self, request, sess: str, info: dict):
        self.book.store.set_name(info["uid"], info.get("name", ""))
        resp = self._json({"ok": True, "game": info.get("game") or ""})
        resp.set_cookie(COOKIE, sess, max_age=30 * 86400, httponly=True, samesite="Strict", path="/",
                        secure=self._secure(request))
        self.log(f"[otoge] scorebook login {mask_qq(info['uid'])} ({self._ua(request)}, secure={self._secure(request)})")
        return resp

    @staticmethod
    def _ua(request) -> str:
        """日志里只记浏览器的大类（排查「哪种浏览器登不上」用），不记完整 UA。"""
        ua = request.headers.get("User-Agent", "")
        for key, name in (("MicroMessenger", "wechat"), ("QQ/", "qq-app"), ("QQBrowser", "qqbrowser"), ("Electron", "electron"),
                          ("Edg/", "edge"), ("Firefox/", "firefox"), ("Chrome/", "chrome"), ("Safari/", "safari")):
            if key in ua:
                os_ = "ios" if "iPhone" in ua or "iPad" in ua else "android" if "Android" in ua else "mac" if "Mac OS" in ua \
                    else "win" if "Windows" in ua else "other"
                return f"{name}/{os_}"
        return "unknown"

    async def api_pending(self, request):
        if not self.ip_api.allow(self._ip(request)):
            return self._json({"ok": False, "message": "太频繁了，稍等一分钟"}, 429)
        body = await self._body(request)
        if body is None:
            return self._json({"ok": False, "message": "bad request"}, 400)
        got = self.book.sessions.poll(str(body.get("p") or ""))
        if got is None:
            self.log(f"[otoge] scorebook pending gone ({self._ua(request)})")     # 排查用：网页来问了，但这个确认已经不在了
            return self._json({"ok": False, "message": "确认码过期了。回 QQ 再发一次「/传分」"}, 401)
        if got == "wait":
            return self._json({"ok": False, "wait": True})
        sess, info = got
        return self._logged_in(request, sess, info)

    async def api_logout(self, request):
        body = await self._body(request)
        if body is None:
            return self._json({"ok": False}, 400)
        self.book.sessions.drop(request.cookies.get(COOKIE, ""))
        resp = self._json({"ok": True})
        resp.del_cookie(COOKIE, path="/")
        return resp

    # ---------- 曲库 ----------
    async def api_catalog(self, request):
        from aiohttp import web
        if not self.ip_api.allow(self._ip(request)):
            return self._json({"error": "请求太频繁"}, 429)
        g = self._game(request.query.get("game"))
        if g is None:
            return self._json({"error": "没有这个游戏的曲库"}, 404)
        cat = self.book.cat(g)
        stamp = id(cat) ^ hash(json.dumps(cat.aliases, ensure_ascii=False, sort_keys=True))
        hit = self._payload.get(g)
        if hit is None or hit[0] != stamp:
            hit = (stamp, json.dumps(cat.client_payload(), ensure_ascii=False, separators=(",", ":")).encode())
            self._payload[g] = hit
        resp = web.Response(body=hit[1], content_type="application/json", charset="utf-8")
        resp.enable_compression()
        return resp

    async def api_search(self, request):
        if not self.ip_api.allow(self._ip(request)):
            return self._json({"error": "请求太频繁"}, 429)
        g = self._game(request.query.get("game"))
        q = str(request.query.get("q") or "")[:60]
        if g is None or not q.strip():
            return self._json({"hits": []})
        hits = self.book.cat(g).search(q, 40)
        return self._json({"hits": [{"k": m.item.key, "s": round(m.score, 1), "by": m.name if m.by_alias else ""}
                                    for m in hits]})

    async def api_from_bind(self, request):
        """网页绑定页上选了「SDVX / 音击 官服 → 手动传分」：拿绑定链接的身份直接换一个传分网站登录码，
        不用再回 QQ 发 /传分。绑定链接本身不作废（还能接着绑别的）。"""
        ip = self._ip(request)
        if not self.ip_api.allow(ip) or not self.ip_login.allow(ip):
            return self._json({"ok": False, "message": "太频繁了，稍等一分钟"}, 429)
        if self.bind is None or request.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json({"ok": False, "message": "bad request"}, 400)
        _, s, err = self.bind._session(request)
        if s is None:
            return self._json({"ok": False, "message": "绑定链接过期了，回 QQ 发「/传分」拿传分网站的链接"},
                              409 if err == "claimed" else 401)
        try:
            b = await request.json()
        except Exception:  # noqa: BLE001
            b = {}
        g = self._game((b or {}).get("game")) or ""
        tok = self.book.sessions.issue_login(s.uid, s.name, g)
        self.log(f"[otoge] scorebook login via bind page {mask_qq(s.uid)}")
        return self._json({"ok": True, "url": "/scores#t=" + tok + ("&g=" + g if g else "")})

    # ---------- 成绩 ----------
    def summary(self, uid: str, g: str) -> dict:
        cat, book = self.book.cat(g), self.book.store.scores(uid, g)
        if g == "sdvx":
            rows = K.sdvx_rows(cat, book)
            total = K.sdvx_total(rows)
            return {"total": total, "total_text": K.fmt_k(total), "class": K.vf_class(total), "count": len(rows),
                    "b50": [r.key for r in rows[:50]], "vf": {r.key: r.vf for r in rows},
                    "floor": rows[49].vf if len(rows) >= 50 else 0}
        best = K.geki_best(cat, book)
        st = best.frame_stats()
        def keys(lst):
            return [getattr(c, "sb_key", None) for c in lst if getattr(c, "sb_key", None)]
        vals = {}
        for k in book:
            ch = cat.charts.get(k)
            if ch is not None:
                vals[k] = K.geki_chart_value(ch, book[k])
        return {"total": best.calc or 0, "total_text": K.GR.fmt(best.calc or 0), "count": len(book),
                "frames": {k: {"n": v["n"], "sum": K.GR.fmt(v["sum"]), "contrib": K.GR.fmt(v["contrib"])}
                           for k, v in st.items()},
                "new": keys(best.new), "best": keys(best.best), "plat": keys(best.plat), "vals": vals}

    async def api_scores(self, request):
        if not self.ip_api.allow(self._ip(request)):
            return self._json({"error": "请求太频繁"}, 429)
        u = self._user(request)
        if u is None:
            return self._json({"error": "login"}, 401)
        g = self._game(request.query.get("game"))
        if g is None:
            return self._json({"error": "game"}, 404)
        book = self.book.store.scores(u["uid"], g)
        recs = {k: {kk: vv for kk, vv in v.items() if kk != "h"} for k, v in book.items()}
        return self._json({"scores": recs, "summary": self.summary(u["uid"], g)})

    async def api_score(self, request):
        ip = self._ip(request)
        if not self.ip_api.allow(ip):
            return self._json({"ok": False, "message": "太频繁了"}, 429)
        u = self._user(request)
        if u is None:
            return self._json({"ok": False, "message": "登传过期了，回 QQ 发「/传分」重新登录"}, 401)
        if not self.user_write.allow(u["uid"]):
            return self._json({"ok": False, "message": "传得太快了，歇一下"}, 429)
        b = await self._body(request)
        g = self._game((b or {}).get("game"))
        if b is None or g is None:
            return self._json({"ok": False, "message": "bad request"}, 400)
        ch = self.book.cat(g).charts.get(str(b.get("key") or ""))
        if ch is None:
            return self._json({"ok": False, "message": "没有这张谱面（曲库可能刚更新，刷新页面）"})
        try:
            score = int(str(b.get("score")).replace(",", ""))
            over = bool(b.get("overwrite"))
            before = self.summary(u["uid"], g)
            if g == "sdvx":
                ex = b.get("ex")
                res = self.book.store.put_sdvx(u["uid"], ch.key, score, str(b.get("lamp") or "COMP"), over,
                                               int(str(ex).replace(",", "")) if ex not in (None, "") else None)
            else:
                plat = b.get("plat")
                stars = b.get("stars")
                res = self.book.store.put_geki(u["uid"], ch.key, score, str(b.get("lamp") or ""), bool(b.get("fb")),
                                               int(plat) if plat not in (None, "") else None,
                                               int(stars) if stars not in (None, "") else None, over)
        except (ScoreError, ValueError, TypeError) as e:
            msg = str(e) if isinstance(e, ScoreError) else "分数要填数字"
            return self._json({"ok": False, "message": msg})
        after = self.summary(u["uid"], g)
        rec = {k: v for k, v in res["new"].items() if k != "h"}
        return self._json({"ok": True, "record": rec, "kept_higher": res["kept_higher"], "changed": res["changed"],
                           "delta": after["total"] - before["total"], "summary": after})

    async def api_delete(self, request):
        u = self._user(request)
        b = await self._body(request)
        if u is None:
            return self._json({"ok": False, "message": "登传过期了"}, 401)
        g = self._game((b or {}).get("game"))
        if b is None or g is None:
            return self._json({"ok": False}, 400)
        ok = self.book.store.delete(u["uid"], g, str(b.get("key") or ""))
        return self._json({"ok": ok, "summary": self.summary(u["uid"], g)})

    async def api_alias(self, request):
        u = self._user(request)
        b = await self._body(request)
        if u is None:
            return self._json({"ok": False, "message": "登录以后才能加外号"}, 401)
        g = self._game((b or {}).get("game"))
        if b is None or g is None:
            return self._json({"ok": False, "message": "bad request"}, 400)
        if not self.user_alias.allow(u["uid"]):
            return self._json({"ok": False, "message": "一小时最多加 20 个，歇会儿"}, 429)
        try:
            msg = self.book.add_alias(g, str(b.get("song") or ""), str(b.get("alias") or ""))
        except ScoreError as e:
            return self._json({"ok": False, "message": str(e)})
        self.log(f"[otoge] scorebook alias {g} {mask_qq(u['uid'])}: {msg}")
        song = str(b.get("song") or "")
        return self._json({"ok": True, "message": msg, "aliases": self.book.cat(g).aliases.get(song, [])})

    # ---------- 曲绘 ----------
    async def api_jacket(self, request):
        from aiohttp import web
        if not self.ip_jk.allow(self._ip(request)):
            return web.Response(status=429)
        g = self._game(request.match_info.get("game"))
        name = request.match_info.get("name", "")
        key = name[:-4] if name.endswith(".jpg") else ""
        if g is None or not re.fullmatch(r"[\w-]{1,24}", key or "-") or key not in self.book.cat(g).songs:
            return web.Response(status=404)
        p = await self.book.jacket_thumb(g, key)
        if p is None:
            # 曲目表还没加载好 → 不许缓存（过一会儿就有了）；确实没有 → 只缓存 10 分钟
            cc = "public, max-age=600" if self.book.jacket_ready(g) else "no-store"
            return web.Response(status=404, headers={"Cache-Control": cc})
        return web.FileResponse(p, headers={"Cache-Control": "public, max-age=2592000, immutable",
                                            "Content-Type": "image/jpeg"})

    # ---------- 批量传分 ----------
    async def api_batch(self, request):
        """预览：一段文字 → 每行认成了什么（不写入）。不登录也能试格式。"""
        if not self.ip_api.allow(self._ip(request)):
            return self._json({"ok": False, "message": "太频繁了"}, 429)
        b = await self._body_big(request)
        g = self._game((b or {}).get("game"))
        if b is None or g is None:
            return self._json({"ok": False, "message": "内容太大或格式不对（最多 2 MB）"}, 400)
        text = str(b.get("text") or "")[:1_500_000]
        rows = self.book.parse_batch(g, text)
        u = self._user(request)
        if u is not None:                       # 标上之前的成绩，方便看「更高 / 一样 / 更低」
            book = self.book.store.scores(u["uid"], g)
            for r in rows:
                old = book.get(r.get("key") or "")
                if old:
                    r["old"] = {"s": old.get("s"), "l": old.get("l", "")}
        return self._json({"ok": True, "rows": rows, "max": 300, "csv": g == "sdvx" and self.book.is_eam_csv(text)})

    async def api_batch_apply(self, request):
        ip = self._ip(request)
        if not self.ip_api.allow(ip):
            return self._json({"ok": False, "message": "太频繁了"}, 429)
        u = self._user(request)
        if u is None:
            return self._json({"ok": False, "message": "登传过期了，回 QQ 发「/传分」重新登录"}, 401)
        if not self.user_batch.allow(u["uid"]):
            return self._json({"ok": False, "message": "一小时最多批量传 60 次，歇会儿"}, 429)
        b = await self._body_big(request)
        g = self._game((b or {}).get("game"))
        rows = (b or {}).get("rows")
        if b is None or g is None or not isinstance(rows, list):
            return self._json({"ok": False, "message": "bad request"}, 400)
        from .service import CSV_MAX
        rows = [r for r in rows if isinstance(r, dict)][:CSV_MAX]
        res = self.book.apply_batch(u["uid"], "", g, rows, bool(b.get("overwrite")))
        self.log(f"[otoge] scorebook batch {g} {mask_qq(u['uid'])}: {res['done']} rows")
        recs = self.book.store.scores(u["uid"], g)
        return self._json({"ok": True, **res, "summary": self.summary(u["uid"], g),
                           "scores": {k: {kk: vv for kk, vv in v.items() if kk != "h"} for k, v in recs.items()}})

    async def api_export(self, request):
        from aiohttp import web
        u = self._user(request)
        g = self._game(request.query.get("game"))
        if u is None or g is None:
            return self._json({"error": "login"}, 401)
        cat = self.book.cat(g)
        buf = io.StringIO()
        w = csv.writer(buf)
        if g == "sdvx":
            w.writerow(["title", "artist", "difficulty", "level", "score", "lamp", "vf", "updated"])
        else:
            w.writerow(["title", "artist", "difficulty", "level", "const", "score", "lamp", "fb", "platinum", "stars",
                        "updated"])
        for key, r in sorted(self.book.store.scores(u["uid"], g).items()):
            ch = cat.charts.get(key)
            if ch is None:
                continue
            t = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.get("t") or 0))
            if g == "sdvx":
                w.writerow([ch.song.title, ch.song.artist, ch.diff, ch.level, r["s"], r["l"],
                            K.fmt_song(K.sdvx_vf(ch.num, r["s"], r["l"])), t])
            else:
                w.writerow([ch.song.title, ch.song.artist, ch.diff, ch.level, ch.num, r["s"], r.get("l", ""),
                            1 if r.get("fb") else 0, r.get("p", ""), r.get("st", ""), t])
        data = ("﻿" + buf.getvalue()).encode("utf-8")
        return web.Response(body=data, content_type="text/csv", charset="utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{g}_scores.csv"'})


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
