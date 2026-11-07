"""绑定指南图：/网页绑定、/mai 绑定、/chu 绑定 回这张图 + 本人专用的绑定链接（链接要发成文字才点得开）。

内容不随用户变，只画一次存进图片缓存。
"""
from __future__ import annotations

import re

from PIL import ImageDraw

try:
    from ..mai.render import fonts as F
    from ..mai.render import kit as K
except ImportError:  # tests
    from mai.render import fonts as F
    from mai.render import kit as K

W, M = 1080, 32
try:
    from . import palette as P
except ImportError:  # tests
    from core import palette as P
PINK = P.CORE                  # 标题方块 / 步骤圆点：中性色（不和游戏色撞）
BLUE = P.REGION["国际服"]
RED = P.REQ
GREEN = P.REGION["国服"]
PURPLE = P.REGION["私服"]
TEXT = P.TEXT

STEPS = [
    ("点下面的链接", "10 分钟内有效，认的是你的 QQ", "第一个打开的设备才能用，别转发"),
    ("选游戏和区服", "舞萌 DX / 中二节奏 / 音击", "国际服 · 日服 · 国服 · 私服（音击只有私服）"),
    ("填好点提交", "凭据直接加密存给我", "绑好了我会回你一句"),
]

# (区服, 颜色, [(游戏, 填什么)], 怎么拿)
SERVERS = [
    ("国际服", BLUE, [("舞萌", "SEGA ID + 密码 或 clal"), ("中二", "SEGA ID + 密码 或 clal")],
     "推荐 SEGA ID + 密码：手机上直接填，clal 过期我能自动续登。"
     "clal 要在电脑上登录 NET 后，从 lng-tgk-aime-gw.am-all.net 的 Cookie 里复制（64 位）。"),
    ("日服", P.REGION["日服"], [("舞萌", "SEGA ID + 密码"), ("中二", "SEGA ID + 密码")],
     "就是登录 maimai DX NET / CHUNITHM-NET 用的那套账号。"),
    ("国服", GREEN, [("舞萌", "落雪授权 / 按 QQ / 水鱼"), ("中二", "落雪授权 / 按 QQ / 水鱼")],
     "推荐「落雪授权」：网页上点一下，跳到落雪确认，舞萌中二一起绑，能查全部成绩，不用复制密钥。"
     "「按 QQ」什么都不用填，只有 B50。"
     "水鱼要先在水鱼设置里允许别人查询。国服成绩是你传到查分器的那份，怎么传发 /mai 更新。"),
    ("私服", PURPLE, [("AquaDX", "网站用户名（音击也是它）"), ("RinNET", "账号 + 密码 或 令牌"), ("MuNET", "网站用户名（暂时用不了）")],
     "舞萌、中二、音击共用一个绑定，绑一次三边都能查；音击现在只有 AquaDX 能查。AquaDX / MuNET 填个人主页 /u/ 后面那段，不是密码。"
     "RinNET 只登录一次、只加密保存登录令牌；GitHub / 微软登录没有密码的，选「RinNET（令牌）」。"
     "MuNET 目前不允许第三方查分工具读数据。"),
]

SAFETY = [
    "凭据只在网页里填，不会出现在聊天记录里，我加密保存，不会发给大模型。",
    "群里千万别直接发 clal / 密码 / 密钥，我会撤回并提醒你让它失效。",
    "链接过期或被别人点开了，再发一次「/网页绑定」就是新链接，旧的作废。",
]

AFTER = ["/查分 账号", "/mai b50", "/chu b50", "/geki b50", "/mai 切换 日服"]


_NO_LINE_START = set("，。、；：！？）」』》,.;:!?)")   # 这些标点不放在行首（挂在上一行末尾）


def _wrap(text: str, kind: str, size: int, width: int) -> list[str]:
    """按宽度折行；英文单词 / 网址不从中间断开。"""
    tokens = re.findall(r"[A-Za-z0-9._\-+/:@]+|\s|.", text)
    lines, cur = [], ""
    for tok in tokens:
        if F.text_width(cur + tok, kind, size) > width and cur.strip() and tok not in _NO_LINE_START:
            lines.append(cur.rstrip())
            cur = tok.lstrip()
        else:
            cur += tok
    if cur.strip():
        lines.append(cur)
    return lines


def _title(d, x, y, text, color):
    d.rounded_rectangle((x, y + 4, x + 8, y + 42), 4, fill=color)
    F.draw_text(d, (x + 22, y), text, "bold", 36, K.INK)


def render_bind_guide(bot_name: str = "AstrBot", assets=None) -> bytes:
    iw = W - 2 * M - 64                       # text width inside a panel
    srv = [(n, c, games, _wrap(how, "regular", 25, iw - 30)) for n, c, games, how in SERVERS]
    srv_h = 96 + sum(66 + 46 * len(games) + 36 * len(how) + 26 for _n, _c, games, how in srv)
    safe = [_wrap("· " + t, "regular", 26, iw) for t in SAFETY]
    safe_h = 96 + sum(len(ls) * 38 + 10 for ls in safe) + 10
    step_h = 120
    H = 30 + 170 + 24 + (step_h + 16) * len(STEPS) + 10 + srv_h + 24 + safe_h + 24 + 170 + 110
    im = K.background(assets, "", W, H, seed=11)
    d = ImageDraw.Draw(im)

    # ---- title ----
    K.panel(im, (M, 30, W - M, 200), r=36)
    d.rounded_rectangle((M + 28, 62, M + 116, 150), 26, fill=PINK)
    F.draw_text(d, (M + 45, 72), "绑", "bold", 54, (255, 255, 255))
    F.draw_text(d, (M + 140, 56), "绑定账号 · 网页绑定", "bold", 50, K.INK)
    F.draw_text(d, (M + 142, 124), "点我发在下面的链接，手机网页里选、填就行", "regular", 27, TEXT)
    y = 30 + 170 + 24

    # ---- three steps ----
    for i, (head, a, b) in enumerate(STEPS):
        K.panel(im, (M, y, W - M, y + step_h), r=28)
        d.ellipse((M + 26, y + 30, M + 86, y + 90), fill=PINK)
        F.draw_text(d, (M + 45, y + 32), str(i + 1), "latin", 42, (255, 255, 255))
        F.draw_text(d, (M + 110, y + 18), head, "bold", 36, K.INK)
        F.draw_text(d, (M + 112, y + 70), F.fit(f"{a}　·　{b}", "regular", 25, W - 2 * M - 140), "regular", 25, TEXT)
        y += step_h + 16
    y += 10

    # ---- what to fill in ----
    K.panel(im, (M, y, W - M, y + srv_h), r=32)
    _title(d, M + 28, y + 28, "每个服要填什么", P.CORE)
    sy = y + 96
    for name, col, games, how in srv:
        x0 = M + 32
        K.pill(d, x0, sy, name, size=28, h=50, pad=20, fg=(255, 255, 255), bg=col)
        sy += 66
        label_w = max(K.pill_width(g, 22, pad=12) for g, _w in games)
        for g, what in games:
            K.pill(d, x0 + 6, sy, g, size=22, h=36, pad=12, fg=col, bg=(255, 255, 255, 235), outline=col)
            F.draw_text(d, (x0 + 6 + max(label_w, 78) + 12, sy + 1), what, "bold", 28, K.INK)
            sy += 46
        for line in how:
            F.draw_text(d, (x0 + 8, sy + 2), line, "regular", 25, TEXT)
            sy += 36
        sy += 26
    y += srv_h + 24

    # ---- safety ----
    K.panel(im, (M, y, W - M, y + safe_h), r=32)
    _title(d, M + 28, y + 28, "安全", RED)
    ny = y + 96
    for ls in safe:
        for k, line in enumerate(ls):
            F.draw_text(d, (M + 36 + (26 if k else 0), ny), line, "regular", 26, TEXT)
            ny += 38
        ny += 10
    y += safe_h + 24

    # ---- after binding ----
    K.panel(im, (M, y, W - M, y + 170), r=32)
    _title(d, M + 28, y + 28, "绑好以后", P.CORE)
    px = M + 36
    for cmd in AFTER:
        if px + K.pill_width(cmd, 26, pad=16) > W - M - 20:
            break
        px = K.pill(d, px, y + 96, cmd, size=26, h=46, pad=16, fg=(110, 70, 170), bg=(244, 236, 252, 255)) + 12
    K.footer(im, bot_name, credit="")
    return K.to_png(im)
