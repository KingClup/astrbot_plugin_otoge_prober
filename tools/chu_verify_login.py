"""阶段 1：最小查分验证（不经过 AstrBot）。

用法（在 Win11 上，用 AstrBot 内嵌的 Python）：
    python tools\\verify_login.py
    python tools\\verify_login.py --clal-file C:\\path\\clal.txt --out C:\\path\\report.txt

结果同时打印出来并写进报告文件（报告里不含 clal），方便通过同步文件夹回传。
"""

import argparse
import asyncio
import platform
import sys
import time
import traceback
from pathlib import Path

from _common import PLUGIN_DIR, default_data_dir, read_clal

from chuni.client import AIME_HOST, ChuniNetClient, is_valid_clal, normalize_clal  # noqa: E402
from chuni.rating import B50  # noqa: E402
from chuni.render import b50_text, profile_text, recent_text  # noqa: E402
from chuni.songdb import SongDB  # noqa: E402


async def reachability(lines: list[str]) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as c:
        for url in (f"https://{AIME_HOST}/", "https://chunithm-net-eng.com/mobile/",
                    "https://raw.githubusercontent.com/", "https://chunithm.beerpsi.cc/songs"):
            t = time.perf_counter()
            try:
                r = await c.head(url)
                lines.append(f"  [连通] {url} → HTTP {r.status_code}（{(time.perf_counter()-t)*1000:.0f} ms）")
            except Exception as e:  # noqa: BLE001
                lines.append(f"  [失败] {url} → {type(e).__name__}: {e}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clal-file")
    ap.add_argument("--out", default=str(PLUGIN_DIR / "verify_report.txt"))
    ap.add_argument("--tz", default="Asia/Shanghai")
    ap.add_argument("--skip-b50", action="store_true")
    args = ap.parse_args()

    lines: list[str] = [
        f"verify_login @ {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Python {sys.version.split()[0]} / {platform.platform()}",
        "",
        "== 连通性 ==",
    ]
    await reachability(lines)

    clal = normalize_clal(read_clal(args.clal_file))
    lines += ["", f"== clal 格式：{'正确' if is_valid_clal(clal) else '不正确（应为 64 位字母数字）'}（长度 {len(clal)}） =="]

    ok = True
    try:
        async with ChuniNetClient(clal) as c:
            t = time.perf_counter()
            p = await c.profile()
            lines += ["", f"== 登录 + 资料（{time.perf_counter()-t:.1f}s） ==", profile_text(p, args.tz)]

            recent = await c.recent()
            db = SongDB(default_data_dir() / "songdb")
            try:
                await db.ensure_loaded()
                lines += ["", f"== 曲库：{db.source}，{len(db.songs)} 首 =="]
            except Exception as e:  # noqa: BLE001
                lines += ["", f"== 曲库加载失败：{e} =="]
            for s in recent:
                db.fill(s)
            lines += ["", f"== 最近记录（共 {len(recent)} 条，显示 3 条） ==", recent_text(recent, args.tz, 3)]

            if not args.skip_b50:
                best, new = await c.best30(), await c.new20()
                for s in best + new:
                    db.fill(s)
                b = B50(best=best, new=new, displayed_rating=p.rating)
                diff = float(b.total) - p.rating
                lines += ["", f"== B50（旧曲 {len(best)} / 新曲 {len(new)}，计算值 - 显示值 = {diff:+.2f}） ==", b50_text(p.name, b)]
    except Exception as e:  # noqa: BLE001
        ok = False
        lines += ["", f"== 失败：{type(e).__name__}: {e} ==", traceback.format_exc()]

    report = "\n".join(lines).replace(clal, "<clal>") if clal else "\n".join(lines)
    print(report)
    Path(args.out).write_text(report, "utf-8")
    print(f"\n报告已写入：{args.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
