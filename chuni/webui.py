"""WebUI 管理页的后端接口（AstrBot 插件视图，views/manage/）。

页面通过 AstrBot 的 bridge 调用这些接口，需要登录 WebUI 才能访问。
clal 只在这里收一次，不会出现在聊天记录或 AstrBot 消息日志里，也绝不会被接口返回。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .client import ChuniError
from .render import b50_text, profile_text, recent_text

if TYPE_CHECKING:  # pragma: no cover
    from ..main import ChuniIntlPlugin


CREDITS = [
    {"name": "beer-psi/chuni-penguin", "url": "https://github.com/beer-psi/chuni-penguin",
     "what": "CHUNITHM-NET 登录与页面解析、rating 公式、B50 图片版式（Design by Tukkun）、曲目与定数接口（0BSD）"},
    {"name": "Tachi / Kamaitachi", "url": "https://github.com/zkldi/Tachi", "what": "备用曲目与定数数据"},
    {"name": "SEGA", "url": "https://chunithm.sega.com/", "what": "CHUNITHM、曲绘与官方素材的版权归 SEGA 所有"},
    {"name": "AstrBot", "url": "https://github.com/AstrBotDevs/AstrBot", "what": "机器人框架与插件视图"},
]


def register_web_apis(plugin: "ChuniIntlPlugin", context, plugin_name: str) -> None:
    from astrbot.api.web import PluginUploadFile, error_response, json_response, request

    svc = plugin.svc
    p = f"/{plugin_name}"

    async def status():
        db = svc.songdb
        return json_response({
            "version": getattr(plugin, "version_str", None),
            "bindings": svc.store.items(),
            "songdb": {
                "source": db.source,
                "count": len(db.songs),
                "intl_version": db.intl_version,
            },
            "nl": {
                "mode": plugin._cfg("nl_mode", "llm"),
                "require_wake": plugin._cfg("nl_require_wake", True),
                "provider": plugin._cfg("nl_provider_id", "") or "（跟随当前会话）",
            },
            "allowed_qq": plugin._cfg("allowed_qq", []),
            "refresh": {
                "enabled": bool(plugin._cfg("daily_refresh_enabled", True)),
                "time": f'{plugin._cfg("daily_refresh_time", "12:00")} ({plugin._cfg("daily_refresh_tz", "Asia/Shanghai")})',
                "next": plugin.next_refresh.strftime("%Y-%m-%d %H:%M") if plugin.next_refresh else None,
                "last": svc.last_refresh,
            },
            "jackets": len(svc.jackets.index),
            "version_info": {"current": svc.current_version, "detected": svc.songdb.current_version,
                        "override": plugin._cfg("theme_version", "auto")},
            "credits": CREDITS,
        })

    async def bind():
        body = await request.json(default={})
        qq = str(body.get("qq", "")).strip()
        clal = str(body.get("clal", ""))
        verify = bool(body.get("verify", True))
        try:
            profile = await svc.bind(qq, clal, verify=verify)
        except ChuniError as e:
            return error_response(str(e), status_code=400)
        if profile is None:
            return json_response({"ok": True, "verified": False, "message": "已保存（未验证）"})
        return json_response({
            "ok": True,
            "verified": True,
            "message": f"绑定成功：{profile.name}  Rating {profile.rating:.2f}",
        })

    async def unbind():
        body = await request.json(default={})
        ok = await svc.unbind(str(body.get("qq", "")).strip())
        return json_response({"ok": ok, "message": "已解绑" if ok else "没有这个绑定"})

    async def test_query():
        body = await request.json(default={})
        qq = str(body.get("qq", "")).strip()
        what = str(body.get("what", "profile"))
        tz = svc.settings.timezone
        try:
            if what == "recent":
                text = recent_text(await svc.recent(qq, force=True), tz, 5)
            elif what == "b50":
                prof, b = await svc.b50(qq, force=True)
                text = b50_text(prof.name, b)
            else:
                text = profile_text(await svc.profile(qq, force=True), tz)
        except ChuniError as e:
            return error_response(str(e), status_code=400)
        except Exception as e:  # noqa: BLE001
            return error_response(f"{type(e).__name__}: {e}", status_code=500)
        return json_response({"text": text})

    async def test_intent():
        body = await request.json(default={})
        text = str(body.get("text", ""))[:300]
        it = await plugin.recognize(text, None)
        return json_response(it.to_dict())

    async def refresh_songdb():
        res = await svc.refresh_data()  # 和每日定时任务走同一个流程
        if str(res.get("songdb", "")).startswith("失败"):
            return error_response(f"曲库刷新失败：{res['songdb']}", status_code=500)
        return json_response({"source": svc.songdb.source, "count": len(svc.songdb.songs),
                              "jackets": res.get("jackets")})

    # ---------- B50 主题素材 ----------

    def _scope_version(scope: str):
        return None if scope == "default" else svc.current_version

    async def theme_status():
        return json_response(svc.theme.status(svc.current_version))

    async def theme_upload(kind: str, scope: str):
        files = await request.files()
        up = files.get("file")
        if not isinstance(up, PluginUploadFile):
            return error_response("没有收到文件", status_code=400)
        data = await up.read()
        if len(data) > 40 * 1024 * 1024:
            return error_response("文件太大（上限 40MB）", status_code=400)
        try:
            path = svc.theme.save(kind, data, _scope_version(scope))
        except Exception as e:  # noqa: BLE001
            return error_response(f"保存失败：{e}", status_code=400)
        return json_response({"ok": True, "saved": str(path.relative_to(svc.theme.root))})

    async def logo_candidates():
        try:
            cands = await svc.theme.logo_candidates(svc.current_version)
        except Exception as e:  # noqa: BLE001
            return error_response(f"抓取失败：{e}", status_code=500)
        return json_response({"version": svc.current_version, "candidates": cands})

    async def logo_use():
        body = await request.json(default={})
        url = str(body.get("url", ""))
        if not url.startswith(("https://", "http://")):
            return error_response("URL 不合法", status_code=400)
        try:
            await svc.theme.use_logo_url(url, svc.current_version)
        except Exception as e:  # noqa: BLE001
            return error_response(f"下载失败：{e}", status_code=500)
        return json_response({"ok": True})

    async def theme_preview():
        """用曲库里的曲子拼一张示例 B50（不需要登录 CHUNITHM-NET），检查主题和曲绘。"""
        import asyncio
        import random
        import tempfile
        from pathlib import Path as _P

        from .b50img import render_b50
        from .models import Difficulty, Rank, Score
        from .rating import B50

        try:
            await svc.songdb.ensure_loaded()
        except Exception as e:  # noqa: BLE001
            return error_response(f"曲库不可用：{e}", status_code=500)
        cur = svc.current_version
        pool = [(s, s.charts[Difficulty.MASTER]) for s in svc.songdb.songs.values()
                if s.intl and Difficulty.MASTER in s.charts and s.charts[Difficulty.MASTER].const]
        pool.sort(key=lambda x: -x[1].const)
        rnd = random.Random(42)
        new_pool = [x for x in pool if x[0].version == cur][:20]
        old_pool = [x for x in pool if x[0].version != cur][:30]

        def mk(items):
            out = []
            for song, ch in items:
                sc = rnd.randint(1_005_000, 1_009_500)
                out.append(Score(song.id, song.title, Difficulty.MASTER, sc, rank=Rank.from_score(sc),
                                 const=ch.const, level=ch.level))
            return out

        best, new = mk(old_pool), mk(new_pool)
        b = B50(best=best, new=new)
        jackets = await svc.jackets_for(best + new)
        th = svc.theme
        body = await request.json(default={})
        max_kb = _max_kb(body.get("max_kb"))
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            out = _P(td) / "preview.jpg"
            await asyncio.to_thread(
                render_b50, "PREVIEW", b, out, jackets, font_path=svc.settings.font_path,
                tz=svc.settings.timezone, version=cur, bg_path=th.asset(cur, "bg"),
                logo_path=th.asset(cur, "logo"), digits=th.digits(), footer_left=f"{svc.settings.b50_footer} · 示例数据",
                max_kb=0, region_label="国际服" + (f" · {cur}" if cur else "") + " · 预览",
            )
            with Image.open(out) as im:
                _preview_cache["img"] = im.convert("RGB")
            _preview_cache["orig_kb"] = out.stat().st_size // 1024
        res = await _encode_preview(max_kb)
        res.update({"jackets": f"{len(jackets)}/{len(best) + len(new)} 首有曲绘", "version": cur})
        return json_response(res)

    _preview_cache: dict = {}

    def _max_kb(v) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return svc.settings.b50_max_kb
        return max(0, min(v, 50_000))

    async def _encode_preview(max_kb: int) -> dict:
        import asyncio
        import base64

        from .b50img import encode_jpeg

        img = _preview_cache["img"]
        data, info = await asyncio.to_thread(encode_jpeg, img, max_kb)
        return {"image": "data:image/jpeg;base64," + base64.b64encode(data).decode(),
                "size": info, "orig_kb": _preview_cache.get("orig_kb"), "max_kb": max_kb,
                "saved_max_kb": svc.settings.b50_max_kb}

    async def theme_preview_size():
        """只重新压缩上次的预览图，滑块拖动时用。"""
        if "img" not in _preview_cache:
            return error_response("先点「预览 B50 样式」生成一张", status_code=400)
        body = await request.json(default={})
        return json_response(await _encode_preview(_max_kb(body.get("max_kb"))))

    async def theme_size_save():
        """把滑块的大小保存成发送 B50 时用的上限（写进插件配置）。"""
        body = await request.json(default={})
        v = _max_kb(body.get("max_kb"))
        svc.settings.b50_max_kb = v
        try:
            plugin.config["b50_max_kb"] = v
            plugin.config.save_config()
        except Exception as e:  # noqa: BLE001
            return error_response(f"已对本次运行生效，但写入配置失败：{e}", status_code=500)
        return json_response({"saved_max_kb": v})

    context.register_web_api(f"{p}/theme/preview", theme_preview, ["POST"], "中二查分：预览 B50 样式")
    context.register_web_api(f"{p}/theme/preview/size", theme_preview_size, ["POST"], "中二查分：预览压缩")
    context.register_web_api(f"{p}/theme/size", theme_size_save, ["POST"], "中二查分：保存图片大小")
    context.register_web_api(f"{p}/theme", theme_status, ["GET"], "中二查分：主题素材")
    context.register_web_api(f"{p}/theme/upload/<kind>/<scope>", theme_upload, ["POST"], "中二查分：上传素材")
    context.register_web_api(f"{p}/theme/logo/candidates", logo_candidates, ["POST"], "中二查分：logo 候选")
    context.register_web_api(f"{p}/theme/logo/use", logo_use, ["POST"], "中二查分：使用 logo")
    context.register_web_api(f"{p}/status", status, ["GET"], "中二查分：状态")
    context.register_web_api(f"{p}/bind", bind, ["POST"], "中二查分：绑定 clal")
    context.register_web_api(f"{p}/unbind", unbind, ["POST"], "中二查分：解绑")
    context.register_web_api(f"{p}/test", test_query, ["POST"], "中二查分：测试查询")
    context.register_web_api(f"{p}/intent", test_intent, ["POST"], "中二查分：测试意图识别")
    context.register_web_api(f"{p}/songdb/refresh", refresh_songdb, ["POST"], "中二查分：刷新曲库")
