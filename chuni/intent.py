"""自然语言意图识别：@机器人 帮我查一下中二国际服b30 → action=b50。

流程：
  1. 关键词粗筛（不相关的消息直接放行，不调用大模型，也不影响陪伴插件）
  2. 调用 AstrBot 接入的大模型，判断"是不是要查中二"以及具体动作，要求只输出 JSON
  3. 大模型不可用或输出不合法时，退回规则匹配
"""

from __future__ import annotations

import json
import re

# 中文后面紧跟英文时 \b 不生效，改用"前后不是字母数字"
_L = r"(?<![a-z0-9])"
_R = r"(?![a-z0-9])"
from dataclasses import asdict, dataclass
from typing import Awaitable, Callable

ACTIONS = ("profile", "recent", "b50", "b50_text", "song", "bind", "help", "none")

# 粗筛：出现这些词才进入识别
GATE = re.compile(
    r"中二|chuni|chunithm|チュウニ|ちゅうに|"
    rf"{_L}b\s?[35]0{_R}|{_L}n20{_R}|best\s?30|new\s?20|"
    rf"查分|定数|rating|{_L}ra{_R}|op值|over\s?power",
    re.I,
)
CHUNI_WORDS = re.compile(r"中二|chuni|chunithm|チュウニ|ちゅうに", re.I)
OTHER_GAMES = re.compile(
    rf"maimai|舞萌|{_L}mai{_R}|sdvx|ボルテ|音击|ongeki|オンゲキ|arcaea|{_L}arc{_R}|pjsk|プロセカ|osu|太鼓|taiko|"
    r"jubeat|iidx|popn|wacca|phigros|喷射|splatoon",
    re.I,
)
# 已经是标准指令格式的消息交给指令处理器
COMMAND_FORM = re.compile(r"^\s*/?\s*(中二|chuni)(\s|$)", re.I)

SYSTEM_PROMPT = """你是一个指令解析器。判断用户这句话是不是在请求查询【中二节奏 CHUNITHM 国际服】的个人成绩，并输出 JSON。

只能输出一行 JSON，不要解释，不要代码块。格式：
{"action": "...", "query": "...", "game": "..."}

action 取值：
- "profile"  查玩家资料、rating、等级、OP、称号
- "recent"   查最近游玩记录、刚才打了什么、最近的成绩
- "b50"      查 b30 / b50 / best30 / new20 / 最好成绩 / rating 构成（默认发图片）
- "b50_text" 同 b50，但用户明确要求文字版
- "song"     查某一首歌的成绩或定数，此时 query 填歌名（保留原文，去掉"的成绩"之类的词）
- "bind"     想绑定账号 / 问怎么绑定、怎么获取 clal、怎么登录查分
- "help"     问这个查分功能怎么用
- "none"     不是查询请求（闲聊、问别的游戏、只是提到中二、在问别人的成绩等）

game 取值："chunithm"（明确是中二）、"other"（明确是别的游戏，如 maimai、SDVX、音击）、"unknown"（没说是什么游戏）。
注意：只是聊到中二但没有要查东西时，action 必须是 "none"。query 除了 song 以外都填 ""。

例子：
帮我查一下中二国际服b30 → {"action":"b50","query":"","game":"chunithm"}
中二b30 → {"action":"b50","query":"","game":"chunithm"}
看看我中二最近打了啥 → {"action":"recent","query":"","game":"chunithm"}
我中二 rating 多少了 → {"action":"profile","query":"","game":"chunithm"}
查下中二 Aleph-0 的成绩 → {"action":"song","query":"Aleph-0","game":"chunithm"}
b50 文字版 → {"action":"b50_text","query":"","game":"unknown"}
帮我查一下 maimai b50 → {"action":"none","query":"","game":"other"}
今天去打中二了好累 → {"action":"none","query":"","game":"chunithm"}
中二查分怎么用 → {"action":"help","query":"","game":"chunithm"}
中二怎么绑定账号 → {"action":"bind","query":"","game":"chunithm"}"""


@dataclass
class Intent:
    action: str
    query: str = ""
    game: str = "unknown"
    source: str = "rules"  # llm / rules / gate
    raw: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def passes_gate(text: str) -> bool:
    return bool(text) and not COMMAND_FORM.match(text) and bool(GATE.search(text))


def parse_llm_output(raw: str) -> Intent | None:
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    action = str(data.get("action", "")).strip().lower()
    if action not in ACTIONS:
        return None
    game = str(data.get("game", "unknown")).strip().lower()
    if game not in ("chunithm", "other", "unknown"):
        game = "unknown"
    query = str(data.get("query") or "").strip()
    if action == "song" and not query:
        return None
    return Intent(action=action, query=query, game=game, source="llm", raw=raw[:300])


_SONG_PATTERNS = [
    # 查(一下)(中二)(国际服) <歌名> (的)(成绩|分数|定数)
    re.compile(
        r"(?:查|搜|看)(?:一下|一查|查|看|下)?(?:我的?)?(?:中二(?:节奏)?|chuni(?:thm)?)?(?:国际服)?(?:里|的)?\s*"
        r"[「『\"“]?(?P<q>.+?)[」』\"”]?\s*(?:这首)?(?:的)?(?:成绩|分数|定数|打得怎么样|记录)",
        re.I,
    ),
]


def rules_intent(text: str) -> Intent:
    t = text.strip()
    chuni = bool(CHUNI_WORDS.search(t))
    other = bool(OTHER_GAMES.search(t))
    game = "chunithm" if chuni else ("other" if other else "unknown")
    if other and not chuni:
        return Intent("none", game=game)

    asking = re.search(r"查|看|多少|发|给我|帮我|来个|来张|show|check|几", t, re.I) or re.fullmatch(
        r"\s*(?:中二(?:节奏)?|chuni(?:thm)?)?\s*(?:国际服)?\s*(?:b\s?[35]0|best\s?30|最近|资料|rating)\s*", t, re.I
    )

    if re.search(r"绑定|bind|登录|登陆|clal", t, re.I) and chuni:
        return Intent("bind", game=game)
    if re.search(r"怎么用|帮助|help|有哪些(?:指令|功能)", t, re.I) and chuni:
        return Intent("help", game=game)
    if re.search(rf"{_L}b\s?[35]0{_R}|best\s?30|new\s?20|{_L}n20{_R}", t, re.I):
        return Intent("b50_text" if re.search(r"文字|text", t, re.I) else "b50", game=game)
    for pat in _SONG_PATTERNS:
        if (m := pat.search(t)) and (q := m.group("q").strip(" 　的")):
            q = re.sub(r"^(?:中二(?:节奏)?|chuni(?:thm)?)(?:国际服)?", "", q, flags=re.I).strip()
            if q and not re.fullmatch(r"(?:最近|b\s?[35]0|资料|rating)", q, re.I):
                return Intent("song", query=q, game=game)
    if asking and re.search(r"最近|刚才|刚刚|上一把|recent|打了(?:啥|什么)", t, re.I):
        return Intent("recent", game=game)
    if asking and re.search(rf"rating|{_L}ra{_R}|资料|等级|op值|over\s?power|称号|信息|profile", t, re.I):
        return Intent("profile", game=game)
    return Intent("none", game=game)


LLMCall = Callable[[str, str], Awaitable[str]]  # (system_prompt, user_text) -> completion


async def classify(text: str, llm: LLMCall | None) -> Intent:
    """返回识别结果；llm 为 None 时只用规则。"""
    if not passes_gate(text):
        return Intent("none", source="gate")
    if llm is not None:
        try:
            raw = await llm(SYSTEM_PROMPT, text)
            if (it := parse_llm_output(raw)) is not None:
                return it
        except Exception:  # noqa: BLE001  大模型失败就用规则
            pass
    return rules_intent(text)
