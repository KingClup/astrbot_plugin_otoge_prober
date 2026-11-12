"""手动成绩 → VOLFORCE（SDVX）/ rating（音击 Re:Fresh）。

SDVX（∇ 起，社区叫 VF7，Tachi / rg-stats 同一套）：
  单曲 VF = 等级 × 2 × (分数 / 1000 万) × 评级系数 × 灯系数，截到 0.001
  评级系数 S 105 / AAA+ 102 / AAA 100 / AA+ 97 / AA 94 / A+ 91 / A 88 / B 85 / C 82 / D 80（÷100）
  灯系数   PUC 110 / UC 106（∇ 从 105 调到 106）/ MAXXIVE 104 / EXCESSIVE 102 / COMP 100 / 没过 50（÷100）
  等级用 ∇ 的小数等级（18.5 就按 18.5 算）
  总 VF = 最高 50 张之和。下面全用「千分之一」整数算，避免浮点误差。
音击：直接借用 ongeki/rating.py 的 Re:Fresh 公式，结果装进 GekiBest，/geki b50 的图直接能画。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

try:
    from ..ongeki import rating as GR
    from ..ongeki.models import GekiBest, GekiChart
except ImportError:  # tests import packages top-level
    from ongeki import rating as GR
    from ongeki.models import GekiBest, GekiChart

# ---------- SDVX ----------
SDVX_MAX = 10_000_000
# 网页 / 聊天里用的灯代码（从低到高）
LAMPS = ["PLAY", "COMP", "EXC", "MXV", "UC", "PUC"]
LAMP_NAME = {"PLAY": "PLAYED", "COMP": "COMPLETE", "EXC": "EX COMPLETE", "MXV": "MAXXIVE COMPLETE",
             "UC": "ULTIMATE CHAIN", "PUC": "PERFECT"}
LAMP_COEF = {"PLAY": 50, "COMP": 100, "EXC": 102, "MXV": 104, "UC": 106, "PUC": 110}
LAMP_WORDS = {
    "puc": "PUC", "perfect": "PUC", "p": "PUC", "理论": "PUC",
    "uc": "UC", "ultimate": "UC", "ultimatechain": "UC",
    "mxv": "MXV", "maxxive": "MXV", "mc": "MXV",
    "exc": "EXC", "ex": "EXC", "excessive": "EXC", "hard": "EXC", "exh": None,   # exh 是难度，不是灯
    "comp": "COMP", "complete": "COMP", "clear": "COMP", "c": "COMP", "通过": "COMP", "过": "COMP",
    "play": "PLAY", "played": "PLAY", "failed": "PLAY", "fail": "PLAY", "没过": "PLAY", "crash": "PLAY",
}
GRADES = [(9_900_000, "S", 105), (9_800_000, "AAA+", 102), (9_700_000, "AAA", 100), (9_500_000, "AA+", 97),
          (9_300_000, "AA", 94), (9_000_000, "A+", 91), (8_700_000, "A", 88), (8_000_000, "B", 85),
          (7_000_000, "C", 82), (0, "D", 80)]
CLASSES = [(23000, "IMPERIAL IV"), (22000, "IMPERIAL III"), (21000, "IMPERIAL II"), (20000, "IMPERIAL I"),
           (19750, "CRIMSON IV"), (19500, "CRIMSON III"), (19250, "CRIMSON II"), (19000, "CRIMSON I"),
           (18750, "ELDORA IV"), (18500, "ELDORA III"), (18250, "ELDORA II"), (18000, "ELDORA I"),
           (17750, "ARGENTO IV"), (17500, "ARGENTO III"), (17250, "ARGENTO II"), (17000, "ARGENTO I"),
           (16750, "CORAL IV"), (16500, "CORAL III"), (16250, "CORAL II"), (16000, "CORAL I"),
           (15750, "SCARLET IV"), (15500, "SCARLET III"), (15250, "SCARLET II"), (15000, "SCARLET I"),
           (14750, "CYAN IV"), (14500, "CYAN III"), (14250, "CYAN II"), (14000, "CYAN I"),
           (13500, "DANDELION IV"), (13000, "DANDELION III"), (12500, "DANDELION II"), (12000, "DANDELION I"),
           (11500, "COBALT IV"), (11000, "COBALT III"), (10500, "COBALT II"), (10000, "COBALT I"),
           (7500, "SIENNA IV"), (5000, "SIENNA III"), (2500, "SIENNA II"), (0, "SIENNA I")]


def grade(score: int) -> tuple[str, int]:
    for border, name, coef in GRADES:
        if score >= border:
            return name, coef
    return "D", 80


def lamp_rank(lamp: str) -> int:
    return LAMPS.index(lamp) if lamp in LAMPS else -1


def norm_lamp(word: str | None) -> str | None:
    if not word:
        return None
    w = word.strip().lower().replace(" ", "").replace("-", "")
    if w.upper() in LAMPS:
        return w.upper()
    return LAMP_WORDS.get(w)


def sdvx_vf(level: float, score: int, lamp: str) -> int:
    """单曲 VF，千分之一（0.462 → 462）。"""
    if score <= 0 or lamp not in LAMP_COEF:
        return 0
    lv10 = int(round(level * 10))
    _, g = grade(score)
    # 等级 × 2 × 分数/1e7 × g/100 × l/100，再 ÷1000 取整 —— 即 lv10·2·score·g·l ÷ 10^11
    return (lv10 * 2 * min(score, SDVX_MAX) * g * LAMP_COEF[lamp]) // 10**11


def vf_class(total_k: int) -> str:
    for border, name in CLASSES:
        if total_k >= border:
            return name
    return "SIENNA I"


def fmt_k(k: int) -> str:
    return f"{k // 1000}.{k % 1000:03d}"


def fmt_song(k: int) -> str:
    """单曲 VF ×50 显示（0.403 → 20.15），和中二 / 舞萌的单曲 rating 一样：50 张的平均 = 总 VF。
    单曲 VF 精确到 0.001，×50 后是 0.05 的倍数，两位小数正好不丢精度。"""
    v = k * 5                      # 千分之一 ×50 = 百分之一 ×5
    return f"{v // 100}.{v % 100:02d}"


@dataclass
class SdvxRow:
    key: str
    title: str
    diff: str
    level: str
    num: float
    score: int
    lamp: str
    vf: int
    current: int = 1
    ts: float = 0
    ex: int = 0                          # EX SCORE（没传就是 0）

    @property
    def grade(self) -> str:
        return grade(self.score)[0]


def sdvx_rows(cat, scores: dict) -> list[SdvxRow]:
    """{谱面键: {s, l, t}} → 按单曲 VF 从高到低（同分按等级、分数）。曲库里没有的谱面跳过。"""
    rows = []
    for key, r in scores.items():
        ch = cat.charts.get(key)
        if ch is None:
            continue
        s, lp = int(r.get("s") or 0), str(r.get("l") or "PLAY")
        rows.append(SdvxRow(key, ch.song.title, ch.diff, ch.level, ch.num, s, lp, sdvx_vf(ch.num, s, lp),
                            ch.current, float(r.get("t") or 0), int(r.get("x") or 0)))
    rows.sort(key=lambda x: (-x.vf, -x.num, -x.score))
    return rows


def sdvx_total(rows: list[SdvxRow], n: int = 50) -> int:
    return sum(r.vf for r in rows[:n])


# ---------- 音击 ----------
GEKI_LAMPS = ["", "FC", "AB"]          # AB+ = AB 且 1,010,000（自动判断）
GEKI_LAMP_WORDS = {"fc": "FC", "fullcombo": "FC", "ab": "AB", "allbreak": "AB", "ab+": "AB", "abp": "AB",
                   "理论": "AB"}
GEKI_MAX = GR.MAX_SCORE
GEKI_DIFF_ID = {"BAS": 0, "ADV": 1, "EXP": 2, "MAS": 3, "LUN": 10}
NEW_FROM = 150                          # Re:Fresh 起的歌进新曲框


def geki_stars(rec: dict, plat_max: int) -> int:
    if rec.get("p") and plat_max:
        return GR.stars_of(int(rec["p"]), plat_max)
    return max(0, min(int(rec.get("st") or 0), 6))


def geki_best(cat, scores: dict, player: str = "") -> GekiBest:
    """手动成绩 → GekiBest（新曲 10 + 旧曲 50 + P 分 50），和私服查出来的同一种东西。"""
    best = GekiBest(server="manual", player=player, client=None, shown=None, refresh=True)
    ts_new, ts_old, ps_all = [], [], []
    for key, r in scores.items():
        ch = cat.charts.get(key)
        if ch is None:
            continue
        score = min(int(r.get("s") or 0), GEKI_MAX)
        lamp = str(r.get("l") or "")
        stars = geki_stars(r, ch.plat_max)
        c = GekiChart(music_id=0, diff=GEKI_DIFF_ID.get(ch.diff, 3), title=ch.song.title, score=score,
                      const=None if ch.song.bonus else ch.num or None, best_score=score,
                      fc=lamp in ("FC", "AB"), ab=lamp == "AB", fb=bool(r.get("fb")), stars=stars,
                      platinum=int(r.get("p") or 0), bonus=ch.song.bonus)
        if not c.known:
            continue
        c.sb_key = key                          # 录分网站用：这张卡对应哪个谱面键
        if score > 0:
            c.rate = GR.ts_rate(c.const, score, best_score=score, fc=c.fc, ab=c.ab, fb=c.fb)
            (ts_new if ch.song.version_code >= NEW_FROM else ts_old).append(c)
        if stars:
            pc = dataclasses.replace(c)
            pc.sb_key = key
            pc.rate, pc.ps = None, GR.ps_rate(c.const, stars)
            ps_all.append(pc)
    best.new = sorted(ts_new, key=lambda c: -(c.rate or 0))[:10]
    best.best = sorted(ts_old, key=lambda c: -(c.rate or 0))[:50]
    best.plat = sorted(ps_all, key=lambda c: -(c.ps or 0))[:50]
    return best


def geki_chart_value(ch, rec: dict) -> dict:
    """网页上「这一条值多少」：TS rate、P 分 rate（千分之一）。"""
    if ch.song.bonus or not ch.num:
        return {"rate": None, "ps": None}
    score = min(int(rec.get("s") or 0), GEKI_MAX)
    lamp = str(rec.get("l") or "")
    rate = GR.ts_rate(ch.num, score, best_score=score, fc=lamp in ("FC", "AB"), ab=lamp == "AB",
                      fb=bool(rec.get("fb"))) if score else None
    stars = geki_stars(rec, ch.plat_max)
    return {"rate": rate, "ps": GR.ps_rate(ch.num, stars) if stars else None}
