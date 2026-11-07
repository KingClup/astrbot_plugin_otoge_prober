"""WebUI backend: plain async functions (params dict in, JSON-able dict out). main.py maps them to routes.

The management page lives in views/manage/index.html and talks to these through AstrBot's
plugin-view bridge (AstrBotPluginView.apiGet / apiPost / upload).
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time

from .bot.commands import HELP, friendly_error
from .consts import REGION_NAMES, REGIONS
from .net.client import THROTTLE
from .render import text as T

ICON_NAMES = (
    [f"rank_{r}" for r in ("sssp", "sss", "ssp", "ss", "sp", "s", "aaa", "aa", "a", "bbb", "bb", "b", "c", "d")]
    + [f"fc_{f}" for f in ("fc", "fcp", "ap", "app")]
    + [f"fs_{f}" for f in ("sync", "fs", "fsp", "fsd", "fsdp")]
)
MAX_UPLOAD = 8 * 1024 * 1024


def _mask(uid: str) -> str:
    uid = str(uid)
    return uid if len(uid) <= 4 else uid[:2] + "*" * (len(uid) - 4) + uid[-2:]


class Settings:
    """Small JSON file for values changed from the WebUI (override _conf_schema defaults)."""

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "webui_settings.json")
        self.data: dict = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(self.path + ".tmp", self.path)


class WebUI:
    def __init__(self, plugin):
        self.p = plugin  # MaiNetPlugin (service, catalog, store, cmd, data_dir, settings, renderer)

    @property
    def svc(self):
        return self.p.service

    @property
    def db(self):
        return self.p.catalog.db

    # ---------- overview ----------
    async def status(self, params: dict) -> dict:
        cat = self.p.catalog
        st = self.db.stats()
        users = []
        for uid in self.p.store.all_uids():
            d = self.p.store.load(uid)
            regions = {}
            for r, v in d.get("regions", {}).items():
                if not v.get("creds"):
                    continue
                snap = self.svc.cached(uid, r)
                regions[r] = {
                    "bound_at": v.get("bound_at"),
                    "synced_at": snap.at if snap else None,
                    "rating": snap.profile.rating if snap and snap.profile else None,
                    "name": snap.profile.name if snap and snap.profile else None,
                    "method": self._method(uid, r),
                }
            if regions:
                users.append({"uid": uid, "uid_masked": _mask(uid), "regions": regions,
                              "default": d.get("default_region"), "public": bool(d.get("public")),
                              "consent": bool(d.get("consent"))})
        return {
            "version": self.p.VERSION,
            "catalog": {
                "source": cat.source, "updated_at": st["updated_at"], "songs": st["songs"], "charts": st["charts"],
                "loaded_at": int(cat.loaded_at), "last_error": cat.last_error,
            },
            "regions": {r: {
                "name": REGION_NAMES[r],
                "current": self.db.current_version.get(r),
                "detected": self.db.detected_version(r),
                "override": (cat.version_override or {}).get(r, "auto"),
                "new_versions": st["new_versions"][r],
            } for r in REGIONS},
            "versions": list(self.db.versions),
            "locks": THROTTLE.status(),
            "users": users,
            "settings": {
                "require_consent": self.p.cmd.require_consent,
                "cache_minutes": self.p.cmd.cache_seconds // 60,
                "b50_image": self.p.cmd.renderer is not None,
                "bot_name": getattr(self.p, "bot_name", "AstrBot"),
            },
            "help": HELP,
        }

    def _method(self, uid: str, region: str) -> str:
        c = self.p.store.get_creds(uid, region) or {}
        if c.get("sega_id") and c.get("clal"):
            return "SEGA ID（已缓存 clal）"
        if c.get("sega_id"):
            return "SEGA ID"
        return "clal" if c.get("clal") else "?"

    # ---------- catalog ----------
    async def catalog_refresh(self, params: dict) -> dict:
        await self.p.catalog.refresh()
        return {"ok": not self.p.catalog.last_error, "source": self.p.catalog.source,
                "error": self.p.catalog.last_error, "stats": self.db.stats()}

    async def set_version(self, params: dict) -> dict:
        region, version = params.get("region"), (params.get("version") or "auto").strip()
        if region not in REGIONS:
            raise ValueError("region 必须是 intl 或 jp")
        if version != "auto" and version not in self.db.versions:
            raise ValueError(f"未知版本：{version}")
        ov = dict(self.p.catalog.version_override or {})
        ov[region] = version
        self.p.catalog.set_version_override(ov)
        self.p.settings.set("version_override", ov)
        return {"current": self.db.current_version[region], "new_versions": sorted(self.db.new_versions(region), key=self.db.version_index)}

    async def song_search(self, params: dict) -> dict:
        q = (params.get("q") or "").strip()
        region = params.get("region") or "intl"
        hits = self.db.search(q, limit=8) if q else []
        return {"hits": [{"title": s.title, "ids": sorted(s.music_ids()), "cover": s.cover_url,
                          "text": T.song_text(s, self.db, region)} for s in hits]}

    async def command_test(self, params: dict) -> dict:
        """Run a catalog-only /mai command (no NET, no user context) and return the text reply."""
        from .bot.commands import Ctx
        line = (params.get("line") or "").strip()
        line = re.sub(r"^/?(mai|maimai|舞萌)\s*", "", line)
        sub = line.split()[0] if line.split() else ""
        if sub not in ("查歌", "查", "song", "id", "定数", "定数查歌", "定数表", "随歌", "随个", "分数线", "曲库",
                       "帮助", "help"):
            raise ValueError("这里只能测试不需要登录的指令：查歌 / 定数 / 定数表 / 随歌 / 分数线 / 曲库 / 帮助")
        r = await self.p.cmd.handle(Ctx(uid="webui", private=True, admin=True), line)
        img = None
        if r.image:
            import base64
            img = "data:image/jpeg;base64," + base64.b64encode(_shrink(r.image, 0.7)).decode()
        return {"text": "\n".join(r.texts), "image": img}

    # ---------- binding (owner) ----------
    async def bind_test(self, params: dict) -> dict:
        region = params.get("region") or "intl"
        creds = {k: (params.get(k) or "").strip() for k in ("clal", "sega_id", "password")}
        creds = {k: v for k, v in creds.items() if v}
        if params.get("aime_idx"):
            creds["aime_idx"] = int(params["aime_idx"])
        if not creds:
            raise ValueError("请填写 clal 或 SEGA ID + 密码")
        try:
            prof = await asyncio.wait_for(self.svc.verify(region, creds), 120)
        except Exception as e:
            return {"ok": False, "error": friendly_error(e)}
        saved = False
        uid = (params.get("uid") or "").strip()
        if params.get("save") and uid:
            if not uid.isdigit():
                raise ValueError("QQ 号只能是数字")
            self.p.store.set_creds(uid, region, creds)
            self.p.store.give_consent(uid)
            await self.svc.drop_session(uid, region)
            saved = True
        return {"ok": True, "saved": saved, "profile": prof.to_dict()}

    async def user_unbind(self, params: dict) -> dict:
        uid, region = str(params.get("uid") or ""), params.get("region") or None
        removed = self.p.store.unbind(uid, region)
        for r in removed:
            await self.svc.drop_session(uid, r)
        return {"removed": removed}

    async def user_sync(self, params: dict) -> dict:
        uid, region = str(params.get("uid") or ""), params.get("region") or "intl"
        try:
            snap = await asyncio.wait_for(self.svc.sync(uid, region), 180)
        except Exception as e:
            return {"ok": False, "error": friendly_error(e)}
        b = snap.best50(self.p.catalog)
        return {"ok": True, "scores": len(snap.scores), "net_rating": snap.profile.rating if snap.profile else None,
                "calc": b.total, "text": T.best50_text(b, snap.profile, self.db, snap.at)}

    # ---------- B50 preview ----------
    async def b50_preview(self, params: dict) -> dict:
        from .render.b50img import B50Renderer
        from .render.demo import demo_best50
        uid, region = params.get("uid") or "", params.get("region") or "intl"
        snap = self.svc.cached(str(uid), region) if uid else None
        if snap is not None:
            b, prof, at, src = snap.best50(self.p.catalog), snap.profile, snap.at, f"{_mask(uid)} 的缓存成绩"
        else:
            (b, prof), at, src = demo_best50(self.db, region), int(time.time()), "演示数据"
        renderer = self.p.cmd.renderer or B50Renderer(self.p.data_dir)
        t0 = time.time()
        png = await asyncio.get_running_loop().run_in_executor(None, lambda: renderer(b, prof, self.db, at))
        scale = float(params.get("scale") or 0.5)
        jpg = _shrink(png, scale)
        return {"image": "data:image/jpeg;base64," + base64.b64encode(jpg).decode(), "source": src,
                "ms": int((time.time() - t0) * 1000), "total": b.total}

    # ---------- theme / assets ----------
    def _themes(self) -> str:
        return os.path.join(self.p.data_dir, "themes")

    async def theme_list(self, params: dict) -> dict:
        root = self._themes()
        items = []
        for dirpath, _, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                rel = os.path.relpath(p, root).replace("\\", "/")
                items.append({"path": rel, "size": os.path.getsize(p), "mtime": int(os.path.getmtime(p))})
        hdd = os.path.join(self.p.data_dir, "jackets_hdd")
        cdn = os.path.join(self.p.data_dir, "jackets")
        icons = {n: os.path.exists(os.path.join(root, "icons", n + ".png")) for n in ICON_NAMES}
        return {"files": sorted(items, key=lambda x: x["path"]), "icons": icons,
                "jackets_hdd": len(os.listdir(hdd)) if os.path.isdir(hdd) else 0,
                "jackets_cdn": len(os.listdir(cdn)) if os.path.isdir(cdn) else 0,
                "versions": list(self.db.versions)}

    async def theme_upload(self, params: dict, filename: str, data: bytes) -> dict:
        kind = params.get("kind")
        if kind == "pack":
            return self._import_pack(data)
        if len(data) > MAX_UPLOAD:
            raise ValueError("文件太大（上限 8 MB）")
        if not data[:8].startswith(b"\x89PNG") and not data[:3] == b"\xff\xd8\xff":
            raise ValueError("只支持 PNG / JPG")
        root = self._themes()
        if kind in ("bg", "logo"):
            version = params.get("version") or "default"
            if version != "default" and version not in self.db.versions:
                raise ValueError(f"未知版本：{version}")
            dest = os.path.join(root, version, f"{kind}.png")
        elif kind == "icon":
            name = params.get("name") or ""
            if name not in ICON_NAMES:
                raise ValueError(f"未知图标名：{name}")
            dest = os.path.join(root, "icons", f"{name}.png")
        else:
            raise ValueError("kind 必须是 bg / logo / icon")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(data))
        im.save(dest, "PNG")
        self._reset_icon_cache()
        return {"saved": os.path.relpath(dest, root).replace("\\", "/"), "size": list(im.size)}

    async def theme_delete(self, params: dict) -> dict:
        rel = (params.get("path") or "").replace("\\", "/")
        root = os.path.realpath(self._themes())
        p = os.path.realpath(os.path.join(root, rel))
        if not p.startswith(root + os.sep) or not os.path.isfile(p):
            raise ValueError("路径不合法")
        os.remove(p)
        self._reset_icon_cache()
        return {"deleted": rel}

    def _import_pack(self, data: bytes) -> dict:
        """素材包：zip 里的 themes/... 或直接 icons/、<版本>/、logos/、deco/、fonts/ 解到 themes 下。"""
        import io
        import zipfile
        if len(data) > 200 * 1024 * 1024:
            raise ValueError("素材包太大（上限 200 MB）")
        if data[:2] != b"PK":
            raise ValueError("素材包要是 .zip")
        root = os.path.realpath(self._themes())
        n = 0
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                rel = info.filename.replace("\\", "/")
                if rel.startswith("themes/"):
                    rel = rel[len("themes/"):]
                if not rel.lower().endswith((".png", ".jpg", ".jpeg", ".ttf", ".otf", ".ttc")):
                    continue
                dest = os.path.realpath(os.path.join(root, rel))
                if not dest.startswith(root + os.sep):
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(info) as src, open(dest, "wb") as out:
                    out.write(src.read())
                n += 1
        self._reset_icon_cache()
        return {"saved": f"素材包 {n} 个文件", "size": [n, 0]}

    def _reset_icon_cache(self) -> None:
        if getattr(self.p, "imgcache", None) is not None:
            self.p.imgcache.clear()
        for r in (self.p.cmd.renderer, getattr(self.p.cmd, "cards", None)):
            if r is not None and hasattr(r, "assets"):
                r.assets._icon_cache.clear()
        if isinstance(getattr(self.p.cmd, "_img_memo", None), dict):
            self.p.cmd._img_memo.clear()

    async def settings_set(self, params: dict) -> dict:
        changed = {}
        if "require_consent" in params:
            self.p.cmd.require_consent = bool(params["require_consent"])
            changed["require_consent"] = self.p.cmd.require_consent
        if "cache_minutes" in params:
            m = max(0, min(int(params["cache_minutes"]), 1440))
            self.p.cmd.cache_seconds = m * 60
            changed["cache_minutes"] = m
        if str(params.get("bot_name") or "").strip():
            self.p.bot_name = str(params["bot_name"]).strip()[:32]
            changed["bot_name"] = self.p.bot_name
        if "b50_image" in params or "bot_name" in changed:
            from .render.b50img import B50Renderer
            from .render.cards import CardRenderer
            on = bool(params.get("b50_image", self.p.cmd.renderer is not None))
            name = getattr(self.p, "bot_name", "AstrBot")
            self.p.cmd.renderer = B50Renderer(self.p.data_dir, name) if on else None
            self.p.cmd.cards = CardRenderer(self.p.data_dir, name) if on else None
            changed["b50_image"] = on
        for k, v in changed.items():
            self.p.settings.set(k, v)
        return {"changed": changed}


def _shrink(png: bytes, scale: float) -> bytes:
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(png)).convert("RGB")
    scale = max(0.2, min(scale, 1.0))
    if scale < 1:
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return out.getvalue()


ROUTES = {
    # name: (method, handler attribute)
    "status": ("GET", "status"),
    "catalog/refresh": ("POST", "catalog_refresh"),
    "catalog/version": ("POST", "set_version"),
    "song/search": ("GET", "song_search"),
    "command/test": ("POST", "command_test"),
    "bind/test": ("POST", "bind_test"),
    "user/unbind": ("POST", "user_unbind"),
    "user/sync": ("POST", "user_sync"),
    "b50/preview": ("GET", "b50_preview"),
    "theme/list": ("GET", "theme_list"),
    "theme/delete": ("POST", "theme_delete"),
    "settings": ("POST", "settings_set"),
}
