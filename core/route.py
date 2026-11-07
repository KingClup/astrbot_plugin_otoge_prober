"""Decide whether a chat message is one of our commands, including the sloppy forms people actually type.

  /mai b50 · /舞萌b50 · /maib50 · /mai查歌 救护车     → game named (spaces optional)
  /mia b50 · /中2 b30                                 → game word misspelt (only with a slash)
  /b50 · /查歌 救护车 · /定数表 14+                    → 该隐-style, no game: use the one you used last
  mai b50 (private, no slash)                         → only when the next word really is a sub-command

Anything we route is answered by us and stopped at the highest priority, so the chat model and the
companion / memory plugins never see it (no confused replies, nothing learned from commands).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

GAME_WORDS = {
    "mai": ("maimaidx", "maimai", "舞萌dx", "舞萌", "mai", "洗衣机"),
    "chu": ("chunithm", "中二节奏", "中二", "chuni", "chu"),
    "core": ("查分", "score", "otoge"),
    # sdvx.in chart views only (no score lookup for these two)
    "sdvx": ("soundvoltex", "sdvx", "ボルテ", "sv"),
    "pjsk": ("projectsekai", "プロセカ", "世界计划", "啤酒烧烤", "烧烤", "pjsk", "prsk"),
    # 音击：私服查分 + sdvx.in 谱面
    "geki": ("ongeki", "オンゲキ", "音击", "音擊", "geki"),
}
CHART_SUBS = ("谱面", "谱面确认", "谱面图", "谱", "chart")
TYPO_WORDS = {"mia": "mai", "maii": "mai", "mai2": "mai", "maimia": "mai", "舞蒙": "mai", "舞盟": "mai", "午萌": "mai",
              "中2": "chu", "中二节凑": "chu", "chunni": "chu", "chuin": "chu", "chunithn": "chu", "chuuni": "chu",
              "查份": "core", "差分": "core"}
# sub-commands shared by both games (what each game accepts is checked again by its own handler)
SUBS = ("帮助", "help", "绑定", "绑定教程", "bind", "解绑", "unbind", "切换", "b50", "b40", "b30", "best50", "best",
        "刷新", "更新", "sync", "refresh", "我", "info", "资料", "me", "最近", "recent", "详情", "查歌", "查", "song",
        "id", "定数", "定数查歌", "定数表", "随歌", "随个", "分数线", "好友码", "公开", "曲库", "别名", "外号",
        "alias", "加别名", "添加别名", "删别名", "删除别名", "成绩", "单曲", "分数", "账号", "llm", "区服",
        "谱面", "谱面确认", "谱面图", "谱", "chart", "理论", "理论ra", "理论值", "理论rating", "理论最高")
# game-less 该隐-style commands we accept after a slash
BARE = ("b50", "b40", "b30", "best50", "查歌", "查谱", "定数查歌", "定数表", "定数", "别名", "外号", "加别名",
        "成绩", "单曲", "分数线", "随歌", "随个", "最近", "绑定", "解绑")
_ASCII_WORD = re.compile(r"[a-z]")


@dataclass
class Route:
    game: str              # mai / chu / core
    argline: str
    how: str = "exact"     # exact | glued | typo | bare | plain (no slash)


# without a slash, everything after the sub-command must look like a real argument
_ARG = re.compile(r"^(?:国际服|日服|国服|intl|jp|cn|文字|text|txt|dx|标准|std|sd|[绿黄红紫白]|开|关|on|off|状态|"
                  r"\d+(?:\.\d+)?\+?(?:-\d+(?:\.\d+)?)?)$", re.I)
FREE_ARG_SUBS = ("查", "查歌", "song", "id", "别名", "外号", "alias", "成绩", "单曲", "分数", "加别名", "添加别名",
                 "删别名", "删除别名", "绑定", "bind", "好友码", "详情", *CHART_SUBS)
SONG_SUBS = ("查", "查歌", "song", "id", "别名", "外号", "alias", "成绩", "单曲", "分数", *CHART_SUBS)
_CHATTY = re.compile(r"[了吧啊呀呢嘛哈啦哦噢喔吗么呗诶欸草好太真都也还就又才很超巨难累烦想要会能哭笑？?!！~～…。，,]")


def _clean_command(rest: str) -> bool:
    """No slash → only a tidy 「mai b50」「中二 查 Aleph-0」 counts; 「舞萌 最近好难」 is just chat."""
    words = rest.split()
    long_ok = bool(words) and words[0].lower() in ("绑定", "bind")   # 「mai 绑定 落雪 <44 位密钥>」
    if not words or len(words) > 5 or (len(rest.strip()) > 40 and not long_ok):
        return False
    if words[0].lower() not in SUBS:
        return False                                     # sub-command must be a whole word
    if words[0].lower() in FREE_ARG_SUBS:
        return len(words) >= 2          # song name / clal / 好友码: checked again by the guard (see main.py)
    return all(_ARG.match(w) for w in words[1:])


def _starts_with_sub(rest: str) -> bool:
    low = rest.strip().lower()
    return any(low == s or low.startswith(s + " ") or (len(s) >= 2 and low.startswith(s)) for s in SUBS)


# 「国服中二理论ra」「中二日服理论值」「舞萌理论rating多少」「理论ra」：游戏 / 区服 / 理论词随便排，带点口语词也行
_THEORY = re.compile(r"理论\s*(?:最高)?\s*(?:rating|ra|值|分|rt)?", re.I)
_THEORY_GAME = (("chu", re.compile(r"中二节奏|中二|chunithm|chuni|chu", re.I)),
                ("mai", re.compile(r"舞萌\s*dx|舞萌|maimai\s*dx|maimai|mai|洗衣机", re.I)))
_THEORY_SERVER = (("国际服", re.compile(r"国际服|国际|intl", re.I)), ("日服", re.compile(r"日服|jp", re.I)),
                  ("国服", re.compile(r"国服|cn", re.I)))
_THEORY_FILLER = re.compile(r"[查看下一帮我的是多少呢吗呀啊么有几求问请\s?？!！~～。，,]|是什么|有多少|能有|最高|当前|现在|版本")


def theory_phrase(body: str) -> Route | None:
    """理论最高 Rating 的口语问法 → /mai 理论 区服、/chu 理论 区服，或者不写游戏时的六服总览。"""
    if "理论" not in body or len(body) > 30:
        return None
    rest = _THEORY.sub(" ", body, count=1)
    game = server = None
    for g, rx in _THEORY_GAME:
        if rx.search(rest):
            game, rest = g, rx.sub(" ", rest, count=1)
            break
    for name, rx in _THEORY_SERVER:
        if rx.search(rest):
            server, rest = name, rx.sub(" ", rest, count=1)
            break
    if _THEORY_FILLER.sub("", rest).strip():
        return None                     # 还剩别的内容：「理论上我能推分」这种是聊天
    if game is None:
        return Route("core", "理论", "phrase")
    return Route(game, "理论" + (f" {server}" if server else ""), "phrase")


def route(raw: str, *, last_game: str = "") -> Route | None:
    text = (raw or "").strip()
    slash = text[:1] in ("/", "／")
    body = text[1:].lstrip() if slash else text
    low = body.lower()
    if not low:
        return None
    if (th := theory_phrase(body)) is not None:
        return th
    # 1. a game word, with or without a space after it
    for game, words in GAME_WORDS.items():
        for w in sorted(words, key=len, reverse=True):
            if not low.startswith(w):
                continue
            rest = body[len(w):]
            if not rest or rest[0].isspace():
                if slash:
                    return Route(game, rest.strip(), "exact")
                if not rest.strip() and game == "core":
                    return Route(game, "", "exact")
                return Route(game, rest.strip(), "plain") if _clean_command(rest) else None
            if not slash:
                return None     # without a slash, 「舞萌b50好低」 is chat, not a command
            # glued: 「舞萌b50」「maib50」「中二查Aleph-0」. An ASCII game word followed by more ASCII letters
            # only counts when those letters are a sub-command (「maib50」 yes, 「chuang」 no).
            if _ASCII_WORD.match(w[-1]) and _ASCII_WORD.match(rest[0].lower()):
                if _starts_with_sub(rest):
                    return Route(game, rest.strip(), "glued")
                continue
            if slash or _starts_with_sub(rest):
                return Route(game, rest.strip(), "glued")
            return None
    if not slash:
        return None
    # 2. misspelt game word (slash only)
    first, _, after = body.partition(" ")
    f = first.lower()
    guess = TYPO_WORDS.get(f)
    if guess is None and len(f) >= 3 and _ASCII_WORD.match(f):
        cands = {w: g for g, ws in GAME_WORDS.items() for w in ws if _ASCII_WORD.match(w)}
        close = difflib.get_close_matches(f, list(cands), n=1, cutoff=0.75)
        guess = cands[close[0]] if close else None
    if guess is not None:
        return Route(guess, after.strip(), "typo")
    # 3a. /网页绑定 → 群友自助绑定链接
    if low in ("网页绑定", "绑定网页", "网页登录"):
        return Route("core", "网页绑定", "bare")
    # 3b. /理论ra、/查理论ra、/理论值 → 三个服的理论最高 Rating 总览
    if low in ("理论", "理论ra", "理论rating", "理论值", "理论最高", "查理论", "查理论ra", "理论分", "最高ra"):
        return Route("core", "理论", "bare")
    # 3. 该隐-style command without a game; /谱面 <歌> searches CHUNITHM, ONGEKI, SDVX and PJSK together
    for s in sorted(CHART_SUBS, key=len, reverse=True):
        if len(s) >= 2 and (low == s or low.startswith(s)):
            return Route("chart", body[len(s):].strip(), "bare")
    for s in sorted(BARE, key=len, reverse=True):
        if low == s or low.startswith(s):
            return Route(last_game or "mai", body.strip(), "bare")
    return None
