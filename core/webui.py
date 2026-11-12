"""通用管理页（views/a_overview）的后端：总览（五个游戏 + 小游戏 + 缓存）、自然语言群开关、定数默认区服、
小游戏在玩的局、帮助图预览（总览 / 各主题 / 全部）、意图测试、查账号、素材。"""
from __future__ import annotations

import asyncio
import base64
import io

from . import nl as NL
from .assets import RULES as ASSET_RULES, TIPS as ASSET_TIPS, AssetManager
from .help import TOPICS, TOPIC_ORDER, render_full, render_help, render_topic
from .prefs import CATALOG_SERVERS, GAME_NAMES, SERVER_NAMES


def _jpeg(png: bytes, scale: float = 0.5) -> str:
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class CoreWebUI:
    def __init__(self, plugin):
        self.p = plugin

    def _safe(self, f, default=None):
        try:
            return f()
        except Exception:  # noqa: BLE001
            return default

    async def status(self, params: dict) -> dict:
        import time
        p = self.p
        mai_users = len(p.store.all_uids())
        sx = self._safe(lambda: p.charts.src)
        entries = (lambda g: self._safe(lambda: sx.load_cached(g), 0)) if sx is not None else (lambda g: 0)
        img_dir = self._safe(lambda: sx.dir and __import__("os").path.join(sx.dir, "img"))
        chart_imgs = self._safe(lambda: len(__import__("os").listdir(img_dir)), 0) if img_dir else 0
        priv = self._safe(lambda: {s: sum(1 for v in p.priv.bindings.d.values() if (v.get(s) or {}).get("username"))
                                   for s in ("aqua", "rin", "munet")}, {})
        cache = self._safe(lambda: p.imgcache.prune(), {}) or {}
        games = self._safe(lambda: p.games.sessions, {}) or {}
        from ..games.core import GAME_LABEL, KIND_LABEL
        now = time.time()
        sessions = [{"origin": o, "kind": KIND_LABEL.get(s.kind, s.kind), "game": GAME_LABEL.get(s.game, s.game),
                     "range": s.range_text, "n": len(s.picks), "solved": sum(1 for v in s.solved.values() if v),
                     "stage": s.stage, "age_min": int((now - s.started) / 60), "idle_min": int((now - s.touched) / 60)}
                    for o, s in games.items()]
        from . import changelog as CL
        return {
            "version": p.VERSION,
            "changelog": CL.summary(CL.load(), 3),
            "bot_name": p.bot_name,
            "migration": p.migration,
            "private_llm": p.prefs.llm_enabled(None),
            "llm_groups": p.prefs.llm_groups(),
            "catalog_server": {g: p.prefs.catalog_server(g) for g in GAME_NAMES},
            "catalog_servers": {g: [{"key": s, "name": SERVER_NAMES[s]} for s in CATALOG_SERVERS[g]]
                                for g in GAME_NAMES},
            "games": {
                "mai": {"name": GAME_NAMES["mai"], "versions": p.catalog.db.current_version,
                        "songs": len(p.catalog.db.songs), "users": mai_users},
                "chu": {"name": GAME_NAMES["chu"], "version": p.chu_svc.current_version,
                        "songs": len(p.chu_svc.songdb.songs), "intl_users": len(p.chu_svc.store.items()),
                        "cn_users": len(p.chu_svc.cn.items()), "jp_consts": len(p.chu_svc.consts.jp),
                        "cn_consts": len(p.chu_svc.consts.cn), "jp_version": p.chu_svc.consts.jp_version},
                "geki": {"name": "音击", "songs": entries("geki"), "consts": self._safe(lambda: len(p.geki.db.songs), 0)},
                "charts": {"chu": entries("chu"), "geki": entries("geki"), "sdvx": entries("sdvx"), "pjsk": entries("pjsk"),
                           "images": chart_imgs},
            },
            "priv_users": priv,
            "scorebook": self._safe(lambda: {"users": p.scorebook.store.count_users(),
                                             "songs": {g: len(c) for g, c in p.scorebook.cats.items()},
                                             "web": self._web_status()}, {}),
            "lxns": self._lx_status(),
            "minigames": {"enabled": self._safe(p._games_on, True), "sessions": sessions,
                          "from_webui": self._safe(lambda: p.prefs.games_enabled() is not None, False)},
            "groups": await self._groups_safe(),
            "invite_cfg": self._safe(p._invite_cfg, {}),
            "imgcache": {"files": cache.get("files", 0), "mb": round(cache.get("bytes", 0) / 1048576, 1)},
            "nl": {"require_wake": bool(p._cfg("nl_require_wake", True)),
                   "provider": p._cfg("nl_provider_id", "") or "（跟随当前会话）"},
        }

    # ---------- 传分网站（SDVX / 音击官服手动传分） ----------
    def _web_status(self) -> dict:
        p = self.p
        bw = getattr(p, "bindweb", None)
        url = self._safe(p.bindweb_url, "") or ""
        return {"enabled": bw is not None, "running": bool(bw is not None and bw.running), "url": url,
                "scores_url": (url + "/scores") if url else "", "port": getattr(bw, "port", None),
                "from": "配置 bind_web_url" if str(p._cfg("bind_web_url", "") or "").strip() else
                        ("数据目录 bindweb.json（隧道脚本写的）" if url else "没配")}

    async def scorebook(self, params: dict) -> dict:
        import os
        import time
        try:
            from ..scorebook import calc as K
        except ImportError:  # tests import packages top-level
            from scorebook import calc as K
        from .bindweb import mask_qq
        sb = self.p.scorebook
        cats = {}
        for g, c in sb.cats.items():
            cats[g] = {"songs": len(c), "charts": len(c.charts), "built": c.built, "source": getattr(c, "source", ""),
                       "aliases": sum(len(v) for v in (c.aliases or {}).values()),
                       "last_refresh": time.strftime("%Y-%m-%d %H:%M", time.localtime(sb.last_refresh[g]))
                       if sb.last_refresh.get(g) else "", "error": sb.last_error.get(g, "")}
        jk_dir = os.path.join(sb.root, "jk")
        jk = self._safe(lambda: len(os.listdir(jk_dir)), 0) or 0
        sessions = self._safe(sb.sessions.per_user, {}) or {}
        users = []
        for uid in self._safe(sb.store.uids, []) or []:
            d = self._safe(lambda uid=uid: sb.store.user(uid), {}) or {}
            sd, gk = d.get("sdvx") or {}, d.get("geki") or {}
            if not sd and not gk and uid not in sessions and not (getattr(self.p, "geki_official", None) and
                                                                    self._safe(lambda uid=uid: self.p.geki_official.bound(uid), False)):
                continue
            row = {"uid": uid, "qq": mask_qq(uid), "name": d.get("name", ""), "sdvx": len(sd), "geki": len(gk),
                   "sessions": sessions.get(uid, 0), "vf": "", "rating": "", "official": "",
                   "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(max(
                       [float(r.get("t") or 0) for r in (*sd.values(), *gk.values())] or [0]))) if (sd or gk) else ""}
            off = getattr(self.p, "geki_official", None)
            if off is not None and self._safe(lambda uid=uid: off.bound(uid), False):
                m = off.last(uid)
                row["official"] = ("没开 Standard" if m.get("std") is False else
                                   (f"同步 {time.strftime('%m-%d %H:%M', time.localtime(m['t']))}" if m.get("t") else "已绑定"))
            if sd:
                row["vf"] = self._safe(lambda: K.fmt_k(K.sdvx_total(K.sdvx_rows(sb.cats["sdvx"], sd))), "")
            if gk:
                row["rating"] = self._safe(lambda: K.GR.fmt(K.geki_best(sb.cats["geki"], gk).calc or 0), "")
            users.append(row)
        users.sort(key=lambda r: r["updated"], reverse=True)
        off = getattr(self.p, "geki_official", None)
        return {"web": self._web_status(), "catalogs": cats, "jackets": jk, "users": users,
                "geki_official": self._safe(lambda: off.count(), 0) if off is not None else 0,
                "sessions": sum(sessions.values())}

    async def scorebook_refresh(self, params: dict) -> dict:
        """马上重新拉 SDVX（Tachi）/ 音击（otoge-db）曲库。"""
        sb = self.p.scorebook
        out = {}
        for g in ("sdvx", "geki"):
            try:
                out[g] = {"ok": True, "songs": await sb.refresh(g, force=True)}
            except Exception as e:  # noqa: BLE001
                out[g] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
        self._safe(sb.sync_aliases)
        return out

    async def scorebook_logout(self, params: dict) -> dict:
        uid = str(params.get("uid") or "").strip()
        if not uid.isdigit():
            raise ValueError("QQ 号不对")
        return {"dropped": self.p.scorebook.sessions.drop_user(uid)}

    def _lx_status(self) -> dict:
        p = self.p
        mai_qq = self._safe(lambda: sum(1 for u in p.store.all_uids()
                                        if (p.store.get_creds(u, "cn") or {}).get("source") == "lxqq"), 0)
        chu_qq = self._safe(lambda: sum(1 for b in p.chu_svc.cn.d.values() if (b or {}).get("source") == "lxqq"), 0)
        from_cfg = bool(str(p._cfg("lx_dev_token", "") or "").strip())
        oa = getattr(p, "lx_oauth", None)
        mai_oa = self._safe(lambda: sum(1 for u in p.store.all_uids()
                                        if (p.store.get_creds(u, "cn") or {}).get("source") == "lxoauth"), 0)
        chu_oa = self._safe(lambda: sum(1 for b in p.chu_svc.cn.d.values() if (b or {}).get("source") == "lxoauth"), 0)
        return {"configured": bool(getattr(p.service, "lx_dev", "")), "from": "配置" if from_cfg else "数据目录文件",
                "mai_qq": mai_qq, "chu_qq": chu_qq,
                "oauth": {"configured": bool(oa is not None and oa.configured),
                          "client_id": (oa.client_id[:8] + "…") if oa is not None and oa.client_id else "",
                          "has_secret": bool(oa is not None and oa.client_secret),
                          "redirect": p.lx_oauth_redirect(), "users": len(oa.users()) if oa is not None else 0,
                          "mai": mai_oa, "chu": chu_oa}}

    async def lx_oauth_set(self, params: dict) -> dict:
        """保存 / 清除落雪 OAuth 应用（client_id + 密钥）：写数据目录 lx_oauth.json，马上生效。不回传密钥。"""
        import os
        from .lxoauth import save_client
        p = self.p
        if params.get("clear"):
            try:
                os.remove(os.path.join(p.root, "lx_oauth.json"))
            except OSError:
                pass
            p.lx_oauth.client_id = p.lx_oauth.client_secret = ""
            return self._lx_status()
        cid = str(params.get("client_id") or "").strip()
        sec = str(params.get("client_secret") or "").strip()
        if not cid or len(cid) > 128 or any(c.isspace() for c in cid):
            raise ValueError("client_id（应用 ID）格式不对")
        if len(sec) > 256 or any(c.isspace() for c in sec):
            raise ValueError("密钥格式不对")
        if not sec and cid == p.lx_oauth.client_id:
            sec = p.lx_oauth.client_secret            # 只改 ID 时保留原来的密钥
        save_client(p.root, cid, sec)
        p.lx_oauth.client_id, p.lx_oauth.client_secret = cid, sec
        return self._lx_status()

    async def lx_token(self, params: dict) -> dict:
        """保存 / 清除落雪开发者令牌：写数据目录 lx_dev_token.txt，马上生效（不用重载）。不回传令牌本身。"""
        import os
        p = self.p
        path = os.path.join(p.root, "lx_dev_token.txt")
        tok = str(params.get("token") or "").strip()
        if params.get("clear"):
            try:
                os.remove(path)
            except OSError:
                pass
            p.service.lx_dev = p.chu_svc.lx_dev = str(p._cfg("lx_dev_token", "") or "").strip()
            return self._lx_status()
        if not tok or len(tok) > 512 or any(c.isspace() for c in tok):
            raise ValueError("令牌格式不对：粘贴落雪开发者中心里的完整一串")
        if params.get("test", True):
            from .lxns import LxnsError, NotFoundOnLxns, player_by_qq
            try:
                await player_by_qq("maimai", "10000", tok, transport=p.service.lx_transport)
            except NotFoundOnLxns:
                pass                                   # 令牌有效，只是这个 QQ 没账号
            except LxnsError as e:
                if "令牌无效" in str(e):
                    raise ValueError("落雪说这个令牌无效") from e
        os.makedirs(p.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(tok)
        p.service.lx_dev = p.chu_svc.lx_dev = str(p._cfg("lx_dev_token", "") or "").strip() or tok
        return self._lx_status()

    # ---------- 别名收集 ----------
    async def aliases(self, params: dict) -> dict:
        import time
        from . import aliaslib as AL
        p = self.p
        av = p.alias_votes
        now = time.time()
        votes = [{"origin": o, "game": v.game, "alias": v.alias, "title": v.title, "reason": v.reason,
                  "yes": len(v.yes), "no": len(v.no), "left_min": max(0, int((v.started + av.minutes * 60 - now) / 60)),
                  "queued": len(av.queue.get(o) or [])} for o, v in av.active.items()]
        hist = sorted(({"key": k, **v} for k, v in av.history.items()), key=lambda x: -float(x.get("ts") or 0))[:80]
        for h in hist:
            h["game"] = h["key"].split("|")[0]
            h["date"] = time.strftime("%m-%d %H:%M", time.localtime(float(h.get("ts") or 0)))
            h.pop("key", None)
        lib = await asyncio.to_thread(AL.collect, p)
        provs = []
        for prov in self._safe(lambda: p.context.get_all_providers(), []) or []:
            m = self._safe(lambda prov=prov: prov.meta())
            if m is not None:
                provs.append({"id": str(m.id), "model": str(getattr(m, "model", "") or "")})
        return {"settings": p.alias_settings(), "auto_provider": p._alias_provider_id(), "providers": provs,
                "votes": votes, "history": hist, "counts": lib.counts(),
                "library": {g: lib.doc(g)["songs"] for g in AL.GAMES},
                "export_dir": __import__("os").path.join(p.root, "alias_library")}

    async def alias_settings(self, params: dict) -> dict:
        return {"settings": self.p.set_alias_settings(params or {})}

    async def alias_vote_end(self, params: dict) -> dict:
        """结束一个在投的：result = pass（直接收录）/ reject（作罢）/ cancel（不算，以后还能再提）。"""
        p, origin, result = self.p, str(params.get("origin") or ""), str(params.get("result") or "")
        v = p.alias_votes.active.get(origin)
        if v is None:
            raise ValueError("这个投票已经结束了")
        p.alias_votes.active.pop(origin, None)
        if result == "pass":
            p.alias_votes._remember(v, "pass")
            err = p._alias_apply(v)
            if err:
                raise ValueError(err)
        elif result == "reject":
            p.alias_votes._remember(v, "reject")
        nxt = p.alias_votes.next_intro(origin)
        if nxt:
            await p._notify_private(origin, nxt)
        return {"ok": True}

    async def alias_delete(self, params: dict) -> dict:
        game, alias = str(params.get("game") or ""), str(params.get("alias") or "")
        ids = params.get("ids") or {}
        ok = False
        for space, sid in (ids.items() if isinstance(ids, dict) else []):     # 同一首歌可能在几份表里都有
            ok = await asyncio.to_thread(self.p.alias_remove, game, str(space), str(sid), alias) or ok
        if not ok:
            raise ValueError("没删掉（可能已经不在了）")
        return {"ok": True}

    async def game_end(self, params: dict) -> dict:
        origin = str(params.get("origin") or "")
        s = self.p.games.sessions.get(origin)
        if s is None:
            raise ValueError("这局已经结束了")
        self.p.games.sessions.pop(origin, None)
        return {"origin": origin}

    async def _groups_safe(self) -> list[dict]:
        try:
            return await self._groups()
        except Exception:  # noqa: BLE001
            return []

    async def _groups(self) -> list[dict]:
        """自然语言 / 热闹邀请两个开关的群列表，带群名（从 QQ 读，读不到用上次的）。"""
        p = self.p
        names = await p._refresh_group_names() if hasattr(p, "_refresh_group_names") else {}
        cfg = self._safe(p._invite_cfg, {}) or {}
        out = []
        for gid, sw in sorted(p.prefs.group_switches().items()):
            row = {"group": gid, "name": (names or {}).get(gid, ""), **sw}
            if cfg and hasattr(p, "invite"):
                row["invite_state"] = self._safe(lambda gid=gid: p.invite.snapshot(gid, cfg), {})
            out.append(row)
        return out

    async def group_names(self, params: dict) -> dict:
        return {"names": await self.p._refresh_group_names(force=True)}

    async def invite_set(self, params: dict) -> dict:
        gid = str(params.get("group") or "").strip()
        if not gid.isdigit():
            raise ValueError("群号应该是数字")
        on = bool(params.get("on"))
        self.p.prefs.set_invite(gid, on)
        return {"group": gid, "on": on}

    async def group_add(self, params: dict) -> dict:
        gid = str(params.get("group") or "").strip()
        if not gid.isdigit():
            raise ValueError("群号应该是数字")
        self.p.prefs.add_group(gid)
        return {"group": gid}

    async def group_remove(self, params: dict) -> dict:
        gid = str(params.get("group") or "").strip()
        self.p.prefs.remove_group(gid)
        return {"group": gid}

    async def invite_settings(self, params: dict) -> dict:
        try:
            from ..games.invite import clamp_settings
        except ImportError:  # tests import packages top-level
            from games.invite import clamp_settings
        vals = clamp_settings(params.get("settings") or {})
        self.p.prefs.set_invite_settings(vals)
        return {"settings": vals}

    async def games_switch(self, params: dict) -> dict:
        on = bool(params.get("on"))
        self.p.prefs.set_games_enabled(on)
        if not on:
            self.p.games.sessions.clear()            # 关掉就把正在玩的局也收了
        return {"on": on}

    async def llm_set(self, params: dict) -> dict:
        gid = str(params.get("group") or "").strip() or None
        if gid and not gid.isdigit():
            raise ValueError("群号应该是数字（留空 = 私聊）")
        on = bool(params.get("on"))
        self.p.prefs.set_llm(gid, on)
        return {"group": gid, "on": on}

    async def catalog_server(self, params: dict) -> dict:
        game, server = params.get("game"), params.get("server")
        if game not in CATALOG_SERVERS or server not in CATALOG_SERVERS[game]:
            raise ValueError("游戏或区服不对")
        self.p.prefs.set_catalog_server(game, server)
        return {"game": game, "server": server}

    async def help_preview(self, params: dict) -> dict:
        """topic：空 = 总览；mai / chu / geki / chart / games / more；all = 全部。"""
        topic = str(params.get("topic") or "")
        name = self.p.bot_name
        if topic == "all":
            png = await asyncio.to_thread(render_full, name)
        elif topic in TOPICS:
            png = await asyncio.to_thread(render_topic, topic, name)
        else:
            png = await asyncio.to_thread(render_help, name, None, self.p._help_versions())
        return {"image": _jpeg(png, 0.5), "topic": topic,
                "topics": [{"key": k, "title": TOPICS[k].title} for k in TOPIC_ORDER]}

    async def nl_test(self, params: dict) -> dict:
        text = str(params.get("text") or "")[:300]
        use_llm = bool(params.get("llm"))
        # 勾了「用大模型」就真的问一次模型（跳过规则优先），这样测试页看到的是模型的判断
        it = await NL.classify(text, await self.p._llm_call(None) if use_llm else None, addressed=True,
                               rules_first=not use_llm)
        d = it.to_dict()
        d["command"] = "" if it.action == "none" else ("/mai " if it.game == "mai" else "/chu " if it.game == "chu"
                                                         else "（按用户上次玩的游戏）") + NL.to_command(it)
        return d

    async def accounts(self, params: dict) -> dict:
        uid = str(params.get("qq") or "").strip()
        if not uid.isdigit():
            raise ValueError("QQ 号应该是数字")
        return {"text": self.p.accounts_text(uid)}

    # ---------- 素材（图标 / logo / 背景） ----------
    def assets_manager(self) -> AssetManager:
        p = self.p
        return AssetManager(p.root, p.catalog.db.versions, p.chu_svc.current_version)

    def _assets_changed(self) -> None:
        p = self.p
        if getattr(p, "imgcache", None) is not None:
            p.imgcache.clear()
        try:
            p.mai_webui._reset_icon_cache()
        except Exception:  # noqa: BLE001
            pass
        cards = getattr(p.chu, "cards", None)
        if cards is not None and hasattr(cards, "logos"):
            cards.logos._cache.clear()
        for h in (p.cmd, p.chu, getattr(p, "geki", None)):          # 个人 B50 图的备忘也作废
            for attr in ("_img_memo", "_img_cache"):
                if h is not None and isinstance(getattr(h, attr, None), dict):
                    getattr(h, attr).clear()

    async def assets(self, params: dict) -> dict:
        import os
        m = self.assets_manager()
        cur = list(dict.fromkeys(v for v in self.p.catalog.db.current_version.values() if v))
        groups = await asyncio.to_thread(m.groups, cur)
        count = lambda d: len([f for f in os.listdir(d) if f.lower().endswith(".png")]) if os.path.isdir(d) else 0  # noqa: E731
        return {"groups": groups,
                "extras": {"mai_deco": count(os.path.join(m.root, "mai", "themes", "deco")),
                           "mai_jacket": count(os.path.join(m.root, "mai", "jackets_hdd"))},
                "rules": [{"what": a, "pattern": b, "example": c} for a, b, c in ASSET_RULES],
                "tips": ASSET_TIPS}

    async def assets_upload(self, filename: str, data: bytes, key: str = "") -> dict:
        r = await asyncio.to_thread(self.assets_manager().upload, filename, data, key)
        self._assets_changed()
        return r

    async def assets_delete(self, params: dict) -> dict:
        r = self.assets_manager().delete(str(params.get("rel") or ""))
        self._assets_changed()
        return r

    async def assets_thumb(self, params: dict) -> dict:
        return await asyncio.to_thread(self.assets_manager().thumb, str(params.get("rel") or ""))


ROUTES = {
    "scorebook": ("GET", "scorebook"),
    "scorebook/refresh": ("POST", "scorebook_refresh"),
    "scorebook/logout": ("POST", "scorebook_logout"),
    "aliases": ("GET", "aliases"),
    "aliases/settings": ("POST", "alias_settings"),
    "aliases/vote": ("POST", "alias_vote_end"),
    "aliases/delete": ("POST", "alias_delete"),
    "assets": ("GET", "assets"),
    "assets/delete": ("POST", "assets_delete"),
    "assets/thumb": ("GET", "assets_thumb"),
    "status": ("GET", "status"),
    "llm": ("POST", "llm_set"),
    "invite": ("POST", "invite_set"),
    "invite/settings": ("POST", "invite_settings"),
    "group/add": ("POST", "group_add"),
    "group/remove": ("POST", "group_remove"),
    "group/names": ("POST", "group_names"),
    "games/switch": ("POST", "games_switch"),
    "catalog_server": ("POST", "catalog_server"),
    "help": ("GET", "help_preview"),
    "game_end": ("POST", "game_end"),
    "nl": ("POST", "nl_test"),
    "accounts": ("POST", "accounts"),
    "lx_token": ("POST", "lx_token"),
    "lx_oauth": ("POST", "lx_oauth_set"),
}
