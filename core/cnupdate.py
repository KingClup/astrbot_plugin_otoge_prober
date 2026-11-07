"""国服成绩怎么更新（/mai 更新、/chu 更新）。

国服没有 NET 可抓：插件读的是落雪 / 水鱼存的那份成绩，新不新取决于玩家上次什么时候上传。
这里只做「入口」：告诉玩家数据来自哪里、上传于什么时候、去哪里更新；真正的上传交给落雪 / 水鱼自己的工具。
链接放在配置里（lx_sync_url / df_mai_url / df_chu_url），他们改页面时在 WebUI 里改一下就行。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

STALE_DAYS = 7                      # 超过这么久没上传：提醒标「旧」

DEFAULT_LINKS = {
    "lx": "https://maimai.lxns.net/sync",
    "df_mai": "https://www.diving-fish.com/maimaidx/prober/",
    "df_chu": "https://www.diving-fish.com/chunithmprober/",
}

GAME_NAMES = {"mai": "舞萌", "chu": "中二"}
SOURCE_NAMES = {"lx": "落雪查分器", "df": "水鱼查分器"}
UPDATE_WORDS = ("更新", "更新成绩", "怎么更新", "上传", "上传成绩", "传分", "传成绩", "同步成绩", "怎么上传",
                "update", "upload")


def parse_time(iso: str | None) -> datetime | None:
    """落雪的 upload_time 是 ISO 8601（UTC，末尾 Z）；别的写法尽量也认。"""
    if not iso:
        return None
    s = str(iso).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _tz(tz: str | None):
    try:
        return ZoneInfo(tz) if tz else timezone.utc
    except Exception:  # noqa: BLE001
        return timezone.utc


def age_text(iso: str | None, tz: str | None = None, now: datetime | None = None) -> tuple[str, bool]:
    """→ (「上传于 11-05 14:20（2 天前）」, 是否已经很旧)。没有时间 → ('', False)。"""
    dt = parse_time(iso)
    if dt is None:
        return "", False
    now = now or datetime.now(timezone.utc)
    local = dt.astimezone(_tz(tz))
    delta = now - dt
    if delta < timedelta(minutes=1):
        ago = "刚刚"
    elif delta < timedelta(hours=1):
        ago = f"{int(delta.total_seconds() // 60)} 分钟前"
    elif delta < timedelta(days=1):
        ago = f"{int(delta.total_seconds() // 3600)} 小时前"
    else:
        ago = f"{delta.days} 天前"
    stale = delta >= timedelta(days=STALE_DAYS)
    return f"上传于 {local.strftime('%m-%d %H:%M')}（{ago}）", stale


def b50_note(game: str, source: str, iso: str | None, tz: str | None = None, now: datetime | None = None) -> str:
    """国服 B50 图下面那一行：数据来自哪、上传于什么时候、怎么更新。"""
    cmd = f"/{game} 更新"
    source = "lx" if source == "lxqq" else source
    src = SOURCE_NAMES.get(source, source)
    if source == "lx":
        when, stale = age_text(iso, tz, now)
        if not when:
            return f"数据来自{src}。刚打完想看新成绩：先去落雪同步，再发 /{game} 刷新；怎么同步发 {cmd}"
        head = f"⚠ 这份成绩有点旧了：{src}{when}" if stale else f"数据来自{src}，{when}"
        return f"{head}。更新成绩发 {cmd}"
    return f"数据来自{src}（水鱼不告诉我上传时间）。更新成绩发 {cmd}"


def update_card(game: str, source: str, iso: str | None, links: dict | None = None, tz: str | None = None,
                name: str = "", now: datetime | None = None) -> str:
    """/mai 更新、/chu 更新 的回复。"""
    links = {**DEFAULT_LINKS, **(links or {})}
    source = "lx" if source == "lxqq" else source
    g = GAME_NAMES.get(game, game)
    src = SOURCE_NAMES.get(source, source)
    lines = [f"{g}国服成绩怎么更新"]
    lines.append(f"你绑的是{src}" + (f"（{name}）" if name else "") + "。"
                 "国服没有官方查分网站，我查到的是查分器里存的那份；成绩要你自己传上去，我这边才会变。")
    if source == "lx":
        when, stale = age_text(iso, tz, now)
        if when:
            lines.append(("⚠ 已经有点旧了：" if stale else "") + when)
        lines += ["", "更新步骤：",
                  f"1. 打开 {links['lx']}，登录落雪，按页面说明同步（手机挂 HTTP 代理，在微信里打开舞萌 / 中二公众号）",
                  "2. 同步完回来发 /" + game + " 刷新，我就重新拉一次"]
        lines.append("（也可以用落雪页面上列的上传 bot / 工具，传完同样发 /" + game + " 刷新）")
    else:
        url = links["df_mai" if game == "mai" else "df_chu"]
        lines += ["", "更新步骤：",
                  f"1. 打开 {url}，登录水鱼，按页面上的「导入」说明上传（代理 / bot / 浏览器脚本都行）",
                  "2. 传完回来发 /" + game + " 刷新，我就重新拉一次"]
        lines.append("推荐换落雪：能查全部成绩、单曲成绩，还会告诉我上传时间。发 /网页绑定 改绑")
    lines.append("")
    lines.append("国际服 / 日服 / 私服不用这一步：查的时候就是直接抓 NET 的，打完发 /" + game + " 刷新 就行")
    return "\n".join(lines)


def not_cn_note(game: str, server_name: str) -> str:
    return (f"{server_name}不用更新：每次查都是我直接去抓的最新成绩（10 分钟内重复查用缓存，"
            f"刚打完想马上看就发 /{game} 刷新）。\n「更新」是给国服用的：国服成绩要自己传到落雪 / 水鱼，"
            f"绑了国服的发 /{game} 更新 国服 看步骤")
