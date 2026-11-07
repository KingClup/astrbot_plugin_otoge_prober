"""自然语言查分：@机器人 帮我看下舞萌日服 b50 → (game=mai, action=b50, server=jp).

1. 关键词粗筛：没有音游 / 查分相关的词就直接放行，不调用大模型（陪伴插件照常聊天）
2. 大模型只输出一行 JSON
3. 大模型不可用或输出不合法 → 规则匹配
是否启用由 core.prefs 的群开关决定（默认关闭，省 token）。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Awaitable, Callable

_L = r"(?<![a-z0-9])"
_R = r"(?![a-z0-9])"
ACTIONS = ("b50", "b50_text", "profile", "recent", "song", "ds", "theory", "bind", "update", "help", "none")

MAI = re.compile(rf"舞萌|maimai|{_L}mai{_R}|洗衣机|乌蒙|でらっくす", re.I)
CHU = re.compile(r"中二|chuni|chunithm|チュウニ|ちゅうに", re.I)
OTHER = re.compile(rf"sdvx|ボルテ|音击|ongeki|オンゲキ|arcaea|{_L}arc{_R}|pjsk|プロセカ|osu|太鼓|taiko|jubeat|iidx|"
                   r"popn|wacca|phigros", re.I)
GATE = re.compile(rf"{_L}b\s?[345]0{_R}|best\s?[345]0|{_L}n20{_R}|{_L}r10{_R}|查分|定数|rating|{_L}ra{_R}|"
                  r"查歌|分数线|最近打|成绩|什么歌|啥歌|哪首|什么曲|外号|别名|谱面|什么是|绑定|怎么绑|理论|更新|上传|传分", re.I)
# 「6A景区是什么歌」「反叛是哪首」「什么是潘」「救护车是啥歌」 → the name is a song nickname
SONG_QUESTION = re.compile(r"^\s*(?:请问|问下|问一下)?\s*(?:(?P<q1>.+?)\s*(?:是|指的是|说的是)\s*(?:什么|啥|哪首|哪一首|哪个)"
                           r"(?:歌|曲子|曲|谱面?)?|什么是\s*(?P<q2>.+?)|(?P<q3>.+?)\s*(?:是|指)?\s*(?:什么|啥|哪首|哪一首)\s*"
                           r"(?:歌|曲子|曲))\s*[?？吗呢啊呀]*\s*$")
# 「我在听什么歌」「你唱的是什么歌」: about the speaker, not a song name → only answered when the name clearly is a song
PRONOUN_Q = re.compile(r"^(?:这|那|你|我|他|她|它|咱|大家|有人|谁|别人)|听|唱|放的|在放|在打|打的|在玩|玩的|推荐|好听|最")
COMMAND_FORM = re.compile(r"^\s*/", re.I)
# a real request, not just talking about b50 / a song (「我b50好低啊」「这歌好难」 are chat)
REQUEST = re.compile(r"查|看看|看下|看一下|瞅|发[一个张下]|发我|来[个张一]|给我|帮我|多少|是什么|是啥|是哪|哪首|几分|"
                     r"有哪些|有什么歌|啥歌|什么歌|什么曲|啥曲|什么是|打了啥|打了什么|怎么绑|怎么用|定数表|理论(?:ra|rating|值|最高)|"
                     r"怎么更新|怎么上传|怎么传|更新成绩|上传成绩|传分|同步成绩|"
                     r"show|check|what", re.I)


# the whole message is just the thing to look up: 「舞萌b50」「中二b30日服」「mai rating」「中二最近」
SHORT = re.compile(r"^(?:我的?)?(?:舞萌|maimai|mai|洗衣机|中二(?:节奏)?|chuni(?:thm)?)?(?:的)?(?:国际服|日服|国服|munet|mu服|rin服?|rinnet|林服|aqua(?:dx|服)?)?(?:的)?"
                   r"(?:b[345]0|best[345]0|n20|r10|rating|ra|最近|资料|定数表?[\d.+\-]*)(?:国际服|日服|国服|munet|mu服|rin服?|rinnet|林服|aqua(?:dx|服)?)?(?:文字版?)?"
                   r"[?？!！。~～]*$", re.I)


def is_request(text: str) -> bool:
    t = re.sub(r"\s+", "", text or "")
    return bool(REQUEST.search(t) or SHORT.match(t))
SERVERS = (("munet", re.compile(r"munet|mu服|木服", re.I)), ("rin", re.compile(r"(?<![a-z])rin(?:net|服)?(?![a-z])|林服", re.I)),
           ("aqua", re.compile(r"(?<![a-z])aqua(?:dx|服)?(?![a-z])", re.I)),
           ("jp", re.compile(r"日服|日本服|jp服", re.I)), ("cn", re.compile(r"国服|水鱼|落雪", re.I)),
           ("intl", re.compile(r"国际服|国际版|intl", re.I)))

SYSTEM_PROMPT = """你是音游查分机器人的指令解析器。判断用户这句话是不是在请求查询【舞萌 DX(maimai)】或【中二节奏(CHUNITHM)】的成绩/曲目信息，只输出一行 JSON，不要解释：
{"game": "...", "action": "...", "query": "...", "server": "..."}

game：mai（舞萌/maimai/洗衣机）、chu（中二/chunithm）、unknown（没说是哪个）、other（明确是别的游戏）
action：
- b50       查 b50 / b30 / best / rating 构成（默认图片）
- b50_text  同上但要文字版
- profile   查资料、rating 多少、段位
- recent    最近打了什么 / 刚才的成绩
- song      查某首歌（谱面、定数、成绩），query 填歌名原文
- ds        查某个定数有哪些歌 / 定数表，query 填定数，如 "14.9" 或 "14+"
- theory    问理论最高 rating / 理论值 / 满分能有多少 ra（不是问自己的 rating）
- bind      问怎么绑定
- update    问国服成绩怎么更新 / 上传 / 同步到查分器
- help      问怎么用
- none      不是查询（闲聊、只是提到游戏、问别人的成绩、别的游戏）
server：intl（国际服）、jp（日服）、cn（国服/水鱼/落雪）、munet（私服 MuNET）、rin（私服 RinNET）、aqua（私服 AquaDX）、""（没说）
只是聊到游戏但没要查东西时 action 必须是 none。

例子：
帮我看下舞萌日服b50 → {"game":"mai","action":"b50","query":"","server":"jp"}
中二b30 → {"game":"chu","action":"b50","query":"","server":""}
查下 Aleph-0 的定数 → {"game":"unknown","action":"song","query":"Aleph-0","server":""}
6A景区是什么歌 → {"game":"unknown","action":"song","query":"6A景区","server":""}
反叛是哪首 → {"game":"unknown","action":"song","query":"反叛","server":""}
舞萌14.9有哪些歌 → {"game":"mai","action":"ds","query":"14.9","server":""}
国服中二理论ra → {"game":"chu","action":"theory","query":"","server":"cn"}
舞萌理论值多少 → {"game":"mai","action":"theory","query":"","server":""}
理论rating是多少 → {"game":"unknown","action":"theory","query":"","server":""}
我中二rating多少 → {"game":"chu","action":"profile","query":"","server":""}
今天去打中二了好累 → {"game":"chu","action":"none","query":"","server":""}
帮我查一下 sdvx 成绩 → {"game":"other","action":"none","query":"","server":""}"""


@dataclass
class Intent:
    action: str
    game: str = "unknown"
    query: str = ""
    server: str = ""
    source: str = "rules"
    raw: str = ""
    explicit: bool = False      # 「X是什么歌」: the user plainly asked about a song

    def to_dict(self) -> dict:
        return asdict(self)


def passes_gate(text: str) -> bool:
    if not text or COMMAND_FORM.match(text):
        return False
    return bool(MAI.search(text) or CHU.search(text) or GATE.search(text))


def _server(text: str) -> str:
    for s, pat in SERVERS:
        if pat.search(text):
            return s
    return ""


def parse_llm(raw: str) -> Intent | None:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    action = str(d.get("action", "")).lower().strip()
    if action not in ACTIONS:
        return None
    game = str(d.get("game", "unknown")).lower().strip()
    game = game if game in ("mai", "chu", "unknown", "other") else "unknown"
    server = str(d.get("server") or "").lower().strip()
    server = server if server in ("intl", "jp", "cn", "munet", "rin", "aqua") else ""
    query = str(d.get("query") or "").strip()
    if action in ("song", "ds") and not query:
        return None
    return Intent(action, game, query, server, "llm", raw[:300])


_SONG = re.compile(r"(?:查|搜|看)(?:一下|下|查)?(?:我的?)?(?:舞萌|maimai|中二(?:节奏)?|chuni(?:thm)?)?(?:国际服|日服|国服)?"
                   r"(?:里|的)?\s*[「『\"“]?(?P<q>.+?)[」』\"”]?\s*(?:这首)?(?:的)?(?:成绩|分数|定数|谱面|信息)", re.I)


def _song_q(m: re.Match) -> str:
    return (m.group("q1") or m.group("q2") or m.group("q3") or "").strip(" 　的「」\"“”")


def rules(text: str) -> Intent:
    t = text.strip()
    mai, chu, other = bool(MAI.search(t)), bool(CHU.search(t)), bool(OTHER.search(t))
    game = "mai" if mai and not chu else "chu" if chu and not mai else ("other" if other else "unknown")
    if game == "other":
        return Intent("none", game)
    srv = _server(t)
    asking = re.search(r"查|看|多少|发|给我|帮我|来个|来张|show|check|几", t, re.I)
    if re.search(r"怎么绑|绑定|bind|clal", t, re.I):
        return Intent("bind", game, server=srv)
    if re.search(r"怎么(?:更新|上传|传|同步)|(?:更新|上传|同步)(?:一下|下)?[^，。,.!！?？]{0,8}?(?:成绩|分数)|传分", t):
        return Intent("update", game, server=srv)
    if re.search(r"怎么用|帮助|help|有哪些(?:指令|功能)", t, re.I):
        return Intent("help", game)
    if re.search(r"理论\s*(?:最高)?\s*(?:rating|ra|值|分)|满分.*(?:rating|ra)", t, re.I):
        return Intent("theory", game, server=srv)
    if m := re.search(r"(\d{1,2}(?:\.\d)?\+?)\s*(?:的|有哪些|有什么)?\s*(?:歌|谱|定数表)", t):
        return Intent("ds", game, m.group(1), srv)
    if re.search(rf"{_L}b\s?[345]0(?:{_R}|(?=mu|rin|aqua))|best\s?[345]0|{_L}n20{_R}|{_L}r10{_R}", t, re.I):
        return Intent("b50_text" if re.search(r"文字|text", t, re.I) else "b50", game, server=srv)
    if (m := SONG_QUESTION.match(t)) and (q := _song_q(m)):
        q = re.sub(r"^(?:舞萌|maimai|中二(?:节奏)?|chuni(?:thm)?)(?:里|的)?", "", q, flags=re.I).strip()
        if q and len(q) <= 30:
            return Intent("song", game, q, srv)
    if (m := _SONG.search(t)) and (q := m.group("q").strip(" 　的")):
        q = re.sub(r"^(?:舞萌|maimai|中二(?:节奏)?|chuni(?:thm)?)(?:国际服|日服|国服)?", "", q, flags=re.I).strip()
        if q and not re.fullmatch(r"(?:最近|b\s?[345]0|资料|rating)", q, re.I):
            return Intent("song", game, q, srv)
    if (asking and re.search(r"最近|刚才|刚刚|上一把|recent", t, re.I)) or re.search(r"打了(?:啥|什么)", t):
        return Intent("recent", game, server=srv)
    if asking and re.search(rf"rating|{_L}ra{_R}|资料|段位|信息|profile", t, re.I):
        return Intent("profile", game, server=srv)
    return Intent("none", game)


LLMCall = Callable[[str, str], Awaitable[str]]

# 像在问问题 / 提要求（「能有几」「多少」「？」）：规则没认出来时才值得问一次大模型；
# 「今天去打中二了好累」这种既没请求词也没疑问语气的，直接当闲聊，一个 token 都不花
QUESTIONISH = re.compile(r"[?？]|吗|呢|多少|几|什么|啥|哪|怎么|怎样|如何|能不能|能否|有没有|可以|请|求|想看|想查|想知道|help|show|what|how",
                         re.I)

# 大模型判定结果的小缓存：同一句话（去空白、小写）10 分钟内不再问第二次
_LLM_CACHE: dict[str, tuple[float, Intent]] = {}
_LLM_CACHE_TTL = 600.0
_LLM_CACHE_MAX = 256


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _cache_get(key: str) -> Intent | None:
    hit = _LLM_CACHE.get(key)
    if hit is None:
        return None
    ts, it = hit
    if time.monotonic() - ts > _LLM_CACHE_TTL:
        _LLM_CACHE.pop(key, None)
        return None
    return Intent(**asdict(it))


def _cache_put(key: str, it: Intent) -> None:
    if len(_LLM_CACHE) >= _LLM_CACHE_MAX:
        oldest = min(_LLM_CACHE, key=lambda k: _LLM_CACHE[k][0])
        _LLM_CACHE.pop(oldest, None)
    _LLM_CACHE[key] = (time.monotonic(), Intent(**asdict(it)))


def rules_settle(text: str, quick: Intent) -> bool:
    """规则已经给出明确结论、不需要再问大模型的情形。"""
    if quick.game == "other":
        return True                                   # 明确是别的游戏
    if quick.action in ("bind", "help", "theory", "ds", "b50", "b50_text", "recent", "profile", "update"):
        return is_request(text)                       # 规则认出了查询且确实在要求查 → 直接用
    if quick.action == "song":
        return bool(SONG_QUESTION.match(text.strip()))   # 「X是什么歌」这种定式不用问
    return False


async def classify(text: str, llm: LLMCall | None, addressed: bool = False, rules_first: bool = True) -> Intent:
    """addressed = 私聊或者 @ 了机器人：这时大模型明确判成某个查询就信它，不再用请求词表否决。
    rules_first = 规则能拿准的句子不再调用大模型（省 token）；只有规则拿不准、而且句子像在提问时才问模型。"""
    if not passes_gate(text):
        return Intent("none", source="gate")
    it = None
    quick = rules(text) if (rules_first or llm is None) else None
    if quick is not None and rules_first and rules_settle(text, quick):
        it = quick
    elif llm is not None and (not rules_first or QUESTIONISH.search(text) or is_request(text)):
        key = _norm(text)
        it = _cache_get(key)
        if it is None:
            try:
                it = parse_llm(await llm(SYSTEM_PROMPT, text))
                if it is not None and not it.server:
                    it.server = _server(text)
                if it is not None:
                    _cache_put(key, it)
            except Exception:  # noqa: BLE001
                it = None
    if it is None:
        it = quick if quick is not None else rules(text)
    trusted = addressed and it.source == "llm" and it.action not in ("song",)   # 歌名还是要像在问
    if it.action not in ("none", "help") and not trusted and not is_request(text):
        return Intent("none", it.game, source=it.source + "+chat")      # talking about it, not asking
    if it.action == "song" and (m := SONG_QUESTION.match(text.strip())) and not PRONOUN_Q.search(_song_q(m)):
        it.explicit = True        # 「6A景区是什么歌」: answer even if nothing matches; 「我在听什么歌」: only if it's a song
    return it


def to_command(it: Intent) -> str:
    """Intent → argline for the game's command handler."""
    srv = {"intl": "国际服", "jp": "日服", "cn": "国服", "munet": "munet", "rin": "rin", "aqua": "aqua"}.get(it.server, "")
    if it.action == "b50":
        return f"b50 {srv}".strip()
    if it.action == "b50_text":
        return f"b50 文字 {srv}".strip()
    if it.action == "profile":
        return f"我 {srv}".strip()
    if it.action == "recent":
        return f"最近 {srv}".strip()
    if it.action == "song":
        return f"查歌 {it.query} {srv}".strip()
    if it.action == "ds":
        q = it.query
        return (f"定数表 {q} {srv}" if q.endswith("+") or "." not in q else f"定数 {q} {srv}").strip()
    if it.action == "theory":
        return f"理论 {srv}".strip()
    if it.action == "bind":
        return "绑定"
    if it.action == "update":
        return f"更新 {srv}".strip()
    return "帮助"
