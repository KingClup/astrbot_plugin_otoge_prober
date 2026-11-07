"""文字输出和 B50 图片。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from .models import Difficulty, Profile, RecentScore, Score
from .rating import B50, song_rating

DIFF_COLORS = {
    Difficulty.BASIC: (34, 177, 76),
    Difficulty.ADVANCED: (255, 152, 0),
    Difficulty.EXPERT: (230, 40, 60),
    Difficulty.MASTER: (142, 36, 170),
    Difficulty.ULTIMA: (40, 40, 40),
    Difficulty.WORLDS_END: (60, 60, 200),
}

FONT_CANDIDATES = [
    # Windows：日文曲名用 Meiryo / Yu Gothic 显示最完整，中文回退到微软雅黑
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    # Linux / macOS（测试用）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]


def _fmt_const(c: float | None) -> str:
    return f"{c:.1f}" if c is not None else "?"


def _fmt_rating(s: Score) -> str:
    return f"{song_rating(s.score, s.const):.2f}" if s.const is not None else "?"


def _local(dt: datetime | None, tz: str) -> str:
    if dt is None:
        return "?"
    return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


# ---------- 文字 ----------

def profile_text(p: Profile, tz: str) -> str:
    lines = [
        f"{p.name}  Lv.{p.level}" + (f"（转生 {p.reborn}）" if p.reborn else ""),
        f"Rating：{p.rating:.2f}",
    ]
    if p.over_power is not None:
        lines.append(f"OVER POWER：{p.over_power:.2f}（{p.over_power_pct:.2f}%）")
    if p.titles:
        lines.append("称号：" + " / ".join(p.titles))
    if p.team:
        lines.append(f"队伍：{p.team}")
    if p.play_count is not None:
        lines.append(f"游玩次数：{p.play_count}")
    lines.append(f"最后游玩：{_local(p.last_played, tz)}")
    return "\n".join(lines)


def recent_text(scores: list[RecentScore], tz: str, limit: int = 10) -> str:
    if not scores:
        return "没有最近游玩记录"
    lines = []
    for s in scores[:limit]:
        lamp = f" {s.lamp_text}" if s.lamp_text else ""
        new = " NEW" if s.is_new_record else ""
        lines.append(
            f"{_local(s.played_at, tz)[5:]} [{s.difficulty.short} {_fmt_const(s.const)}] {s.title}\n"
            f"    {s.score:,} {s.rank}{lamp}{new} → {_fmt_rating(s)}"
        )
    return "\n".join(lines)


def song_text(title: str, scores: list[Score], consts: dict[Difficulty, float | None]) -> str:
    lines = [title]
    played = [s for s in scores if s.score > 0]
    if not played:
        lines.append("还没有玩过这首")
    for s in played:
        s.const = consts.get(s.difficulty, s.const)
        lamp = f" {s.lamp_text}" if s.lamp_text else ""
        pc = f"，{s.play_count} 次" if s.play_count else ""
        lines.append(
            f"[{s.difficulty.short} {_fmt_const(s.const)}] {s.score:,} {s.rank}{lamp} → {_fmt_rating(s)}{pc}"
        )
    return "\n".join(lines)


def b50_text(name: str, b50: B50, source: str = "CHUNITHM-NET") -> str:
    def block(label: str, scores: list[Score]) -> list[str]:
        out = [label]
        for i, s in enumerate(scores, 1):
            out.append(f"{i:>2}. [{s.difficulty.short} {_fmt_const(s.const)}] {s.title}  {s.score:,} → {_fmt_rating(s)}")
        return out

    ver = (b50.version or "") + (f"（客户端 Ver.{b50.rom[:4]}）" if b50.rom else "")
    head = [f"{name} 的 B50" + (f" · {ver}" if ver else ""), f"计算 rating：{b50.total}（旧曲 {b50.best_avg} / 新曲 {b50.new_avg}）"]
    if b50.displayed_rating is not None:
        head.append(f"{source} 显示：{b50.displayed_rating:.2f}")
    if b50.missing_const:
        head.append(f"⚠ {len(b50.missing_const)} 首缺少定数，未计入")
    return "\n".join(head + [""] + block("【Best 30】", b50.best) + [""] + block("【New 20】", b50.new))


# ---------- 图片 ----------

def _font(size: int, override: str | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in ([override] if override else []) + FONT_CANDIDATES:
        if path and Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _clip(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def b50_image(name: str, b50: B50, out_path: Path, font_path: str | None = None) -> Path:
    W, ROW, PAD = 1100, 36, 28
    rows = len(b50.best) + len(b50.new)
    H = 170 + rows * ROW + 2 * 60 + PAD
    img = Image.new("RGB", (W, H), (248, 248, 252))
    d = ImageDraw.Draw(img)
    f_title, f_head, f_row, f_small = _font(40, font_path), _font(24, font_path), _font(20, font_path), _font(16, font_path)

    d.rectangle([0, 0, W, 140], fill=(30, 30, 46))
    d.text((PAD, 22), f"{name}  B50", font=f_title, fill=(255, 255, 255))
    sub = f"Rating {b50.total}    Best30 {b50.best_avg}    New20 {b50.new_avg}"
    if b50.displayed_rating is not None:
        sub += f"    (NET {b50.displayed_rating:.2f})"
    d.text((PAD, 84), sub, font=f_head, fill=(220, 220, 235))

    cols = [(PAD, "#"), (PAD + 50, "曲名"), (PAD + 620, "难度"), (PAD + 720, "定数"), (PAD + 800, "分数"), (PAD + 940, "Rating")]
    y = 150

    def section(label: str, scores: list[Score], y: int) -> int:
        d.text((PAD, y + 14), label, font=f_head, fill=(30, 30, 46))
        y += 50
        for x, h in cols:
            d.text((x, y - 4), h, font=f_small, fill=(120, 120, 140))
        y += 18
        for i, s in enumerate(scores, 1):
            if i % 2 == 0:
                d.rectangle([PAD - 8, y, W - PAD + 8, y + ROW], fill=(238, 238, 245))
            color = DIFF_COLORS.get(s.difficulty, (0, 0, 0))
            cy = y + 7
            d.text((cols[0][0], cy), str(i), font=f_row, fill=(90, 90, 110))
            d.text((cols[1][0], cy), _clip(d, s.title, f_row, 560), font=f_row, fill=(20, 20, 30))
            d.rounded_rectangle([cols[2][0], y + 6, cols[2][0] + 64, y + ROW - 6], 6, fill=color)
            d.text((cols[2][0] + 10, cy), s.difficulty.short, font=f_small, fill=(255, 255, 255))
            d.text((cols[3][0], cy), _fmt_const(s.const), font=f_row, fill=(20, 20, 30))
            d.text((cols[4][0], cy), f"{s.score:,}", font=f_row, fill=(20, 20, 30))
            d.text((cols[5][0], cy), _fmt_rating(s), font=f_row, fill=(20, 20, 30))
            y += ROW
        return y

    y = section("Best 30", b50.best, y)
    y = section("New 20", b50.new, y)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.crop((0, 0, W, min(H, y + PAD))).save(out_path)
    return out_path
