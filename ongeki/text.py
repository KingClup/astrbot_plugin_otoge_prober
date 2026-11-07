"""Text version of an O.N.G.E.K.I. best list (used before / instead of the image)."""
from __future__ import annotations

from .models import GekiBest, GekiChart
from .rating import fmt

SERVER_NAMES = {"aqua": "AquaDX", "munet": "MuNET", "rin": "RinNET"}


def _score(s: int) -> str:
    return f"{s:,}"


def _line(i: int, c: GekiChart, plat: bool = False) -> str:
    const = f"{c.const:.1f}" if c.const is not None else "?"
    marks = " ".join(x for x in (c.lamp, "FB" if c.fb else "") if x)
    if plat:
        value = fmt(c.ps) if c.ps is not None else "—"
        tail = f"★{min(c.stars, 5)}"
    else:
        value = fmt(c.rate) if c.rate is not None else "—"
        tail = f"{_score(c.score)} {c.rank}" + (f" {marks}" if marks else "")
    note = "（BONUS 不计）" if c.bonus else "（未知谱面）" if c.const is None else ""
    return f"{i:>2}. {c.title} [{c.diff_name} {const}] {tail} → {value}{note}"


def _section(title: str, charts: list[GekiChart], limit: int | None, plat: bool = False,
             stat: dict | None = None) -> list[str]:
    if not charts:
        return []
    head = f"── {title} ──"
    if stat and stat.get("n"):
        if stat["avg"] == stat["contrib"]:     # 满 50 张：平均就是加的分
            head = f"── {title}（均 +{fmt(stat['avg'])}）──"
        else:
            head = f"── {title}（均 {fmt(stat['avg'])} · +{fmt(stat['contrib'])}）──"
    out = [head]
    key = (lambda c: c.ps or 0) if plat else (lambda c: c.rate or 0)
    charts = sorted(charts, key=lambda c: (c.known, key(c)), reverse=True)
    shown = charts if limit is None else charts[:limit]
    out += [_line(i + 1, c, plat) for i, c in enumerate(shown)]
    if limit is not None and len(charts) > limit:
        out.append(f"    …还有 {len(charts) - limit} 首")
    return out


def render(b: GekiBest, *, best_limit: int | None = 15, plat_limit: int | None = 10) -> str:
    server = SERVER_NAMES.get(b.server, b.server)
    ver = b.version_name
    if b.client:
        ver += f"（{b.client // 100}.{b.client % 100:02d}）"
    lines = [f"音击 · {server} · {ver}", b.player or "?"]

    shown = fmt(b.shown) if b.shown is not None else "?"
    calc = b.calc
    if calc is None:
        lines.append(f"Rating {shown}（旧版规则，只显示服务器值）")
    elif b.shown is None or calc == b.shown:
        lines.append(f"Rating {fmt(calc)}")
    else:
        diff = calc - b.shown
        lines.append(f"Rating {shown}（计算 {fmt(calc)}，{'+' if diff > 0 else '-'}{fmt(abs(diff))}）")

    if b.refresh:
        lines.append("（每段标题里：均 = 这一段每张的平均，+ = 这一段给 rating 加了多少；满 50 张的段两个数一样，只写一个）")
    unknown = b.unknown
    if unknown:
        lines.append(f"有 {len(unknown)} 张谱没有定数，没算进去")

    st = b.frame_stats() if b.refresh else {}
    lines += _section(f"新曲 {'10' if b.refresh else '15'}", b.new, None, stat=st.get("new"))
    lines += _section(f"旧曲 {'50' if b.refresh else '30'}", b.best, best_limit, stat=st.get("best"))
    if b.refresh:
        lines += _section("P 分 50", b.plat, plat_limit, plat=True, stat=st.get("plat"))
    else:
        lines += _section("最近 10", b.recent, None)
    return "\n".join(lines)
