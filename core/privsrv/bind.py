"""两个游戏共用的私服绑定：解析参数 → 验证 / 登录 → 存绑定 → 读一下这个游戏的资料。

游戏侧（mai / chu 的 _bind_priv）只负责把 BindOutcome 排成回复，不再各写一遍。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import PrivError, PrivNotFound, PrivProfile
from .servers import SERVERS, parse_username

GAME_KEY = {"mai": "mai2", "chu": "chusan"}
OTHER = {"mai2": "chusan", "chusan": "mai2"}
TOKEN_WORDS = ("token", "令牌", "refreshtoken")


@dataclass
class BindOutcome:
    ok: bool
    text: str = ""                       # 失败 / 用法说明（ok=False 时回给用户）
    recall: bool = False                 # 用户那条消息带了密码 / 令牌 → 试着撤回
    account: str = ""                    # 私服网站用户名
    profile: PrivProfile | None = None   # 这个游戏的资料；None = 这个号还没玩过这个游戏


def usage(server: str, game: str) -> str:
    s = SERVERS[server]
    cmd = "/mai" if game == "mai" else "/chu"
    if s.auth == "login":
        return (f"{s.name} 要用你的账号登录才能查分，只能私聊我：\n"
                f"{cmd} 绑定 {server} <账号或邮箱> <密码>　（开了两步验证就在最后加 6 位验证码）\n"
                f"用 GitHub / 微软等第三方登录、没有密码的：{cmd} 绑定 {server} token <refreshToken>\n"
                "我只登录这一次，加密保存登录令牌，不存密码；发完我会撤回那条消息。舞萌中二绑一次都能查")
    return f"用法：{cmd} 绑定 {server} <网站用户名>\n用户名是 {s.site} 里那段（群里也能绑，舞萌中二绑一次都能查）"


async def bind(hub, qq: str, server: str, args: list[str], *, game: str, private: bool,
               redactor=None) -> BindOutcome:
    s = SERVERS[server]
    g = GAME_KEY[game]
    client = hub.client(server)

    if s.auth == "username":
        username = parse_username(" ".join(args))
        if not username:
            return BindOutcome(False, usage(server, game))
        try:
            prof, _ = await client.profile(username, g)
        except PrivNotFound as e:          # 这个游戏没记录：看看另一个游戏有没有，有就照样绑
            try:
                prof = None
                other, _ = await client.profile(username, OTHER[g])
                username = other.username or username
            except PrivError:
                return BindOutcome(False, f"绑定 {s.name} 失败：{e}")
        except PrivError as e:
            return BindOutcome(False, f"绑定 {s.name} 失败：{e}")
        account = prof.username if prof else username
        hub.bindings.set(qq, server, account, prof.name if prof else "")
        return BindOutcome(True, account=account, profile=prof)

    # ---- 要登录的服：只能私聊；只存令牌 ----
    if not private:
        return BindOutcome(False, ("刚才那条带了密码 / 令牌，我试着撤回了；保险起见去网站改一下密码。\n" if args else "")
                           + f"{s.name} 要账号密码，别在群里发：私聊我发「/{'mai' if game == 'mai' else 'chu'} 绑定 {server}」看用法",
                           recall=bool(args))
    if not args:
        return BindOutcome(False, usage(server, game))
    secrets = []
    try:
        if args[0].lower() in TOKEN_WORDS:
            if len(args) < 2:
                return BindOutcome(False, usage(server, game), recall=False)
            secrets = [args[1]]
            if redactor:
                redactor.remember(args[1])
            cred = await client.login_token(args[1])
        else:
            if len(args) < 2:
                return BindOutcome(False, usage(server, game), recall=True)
            code = args[-1] if len(args) >= 3 and re.fullmatch(r"\d{6}", args[-1]) else ""
            password = " ".join(args[1:-1] if code else args[1:])
            secrets = [password]
            if redactor:
                redactor.remember(password)
            cred = await client.login(args[0], password, code)
    except PrivError as e:
        return BindOutcome(False, f"绑定 {s.name} 失败：{e}", recall=True)
    finally:
        for x in secrets:
            if redactor:
                redactor.forget(x)
    if redactor:
        redactor.remember(cred["secret"])          # 令牌这次会话里也别进日志
    hub.bindings.set(qq, server, cred["username"], "", secret=cred["secret"],
                     extra={"aime": cred["aime"], "games": cred.get("games") or []})
    try:
        prof, _ = await client.profile(hub.cred(qq, server, game), g)
        hub.bindings.set(qq, server, cred["username"], prof.name, secret=cred["secret"],
                         extra={"aime": cred["aime"], "games": cred.get("games") or []})
    except PrivNotFound:
        prof = None
    except PrivError as e:            # 绑上了，只是这次没读到资料
        return BindOutcome(True, f"（读资料失败：{e}）", recall=True, account=cred["username"])
    return BindOutcome(True, recall=True, account=cred["username"], profile=prof)
