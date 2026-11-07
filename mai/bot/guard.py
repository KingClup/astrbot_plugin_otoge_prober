"""Credential safety: binding conversation state, secret detection and log redaction."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

CLAL_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{64}(?![A-Za-z0-9])")
FLOW_TTL = 300  # seconds a binding conversation stays open

CONSENT_TEXT = """绑定前请先看完：
1. 我会用你提供的 clal Cookie（国际服）或 SEGA ID 账号密码（日服 / 国际服）登录 maimai DX NET，只读取你的游戏资料和成绩，不会修改任何设置，也不会进行任何购买或好友操作。
2. 凭据会加密保存在 bot 主人的电脑上，不会发进群聊，不会交给 AI 模型，日志里也会打码；但 bot 主人在技术上能接触到这台电脑。介意的话请只用 clal 方式，或者不要绑定。
3. 这是非官方工具，SEGA 改版或者限流都可能让它失效，账号因此出现的问题由你自己承担。
4. 随时可以发 /mai 解绑 删除凭据和成绩缓存。
同意请回复「同意」，5 分钟内有效；回复「取消」放弃。"""


@dataclass
class BindFlow:
    uid: str
    region: str
    step: str                      # consent / method / clal / sega_id / password
    data: dict = field(default_factory=dict)
    expires: float = 0.0

    def alive(self) -> bool:
        return time.time() < self.expires

    def touch(self) -> None:
        self.expires = time.time() + FLOW_TTL


class FlowBook:
    def __init__(self):
        self._flows: dict[str, BindFlow] = {}

    def get(self, uid: str) -> BindFlow | None:
        f = self._flows.get(uid)
        if f and not f.alive():
            self._flows.pop(uid, None)
            REDACTOR.forget(f.data.get("password", ""))
            return None
        return f

    def start(self, uid: str, region: str, step: str, **data) -> BindFlow:
        f = BindFlow(uid=uid, region=region, step=step, data=dict(data))
        f.touch()
        self._flows[uid] = f
        return f

    def end(self, uid: str) -> None:
        f = self._flows.pop(uid, None)
        if f:
            REDACTOR.forget(f.data.get("password", ""))


LX_CONSENT_TEXT = """绑定落雪前请先看完：
1. 我会用你的落雪「个人 API 密钥」读取你在落雪查分器上的舞萌 / 中二国服资料和成绩，只读，不会上传或修改任何成绩。
2. 密钥会加密保存在 bot 主人的电脑上，不会发进群聊，不会交给 AI 模型，日志里也会打码；但 bot 主人在技术上能接触到这台电脑。介意的话可以改用水鱼（/mai 绑定 国服 <水鱼用户名>，不需要密钥），或者不要绑定。
3. 这是非官方工具，随时可以发 /mai 解绑 国服 删除密钥；也可以在落雪网站上重新生成密钥让旧的作废。
同意请回复「同意」，5 分钟内有效。"""


# 日服 / 国际服 SEGA ID + 密码；私服 RinNET 账号 + 密码 / token + 令牌
_PW_BIND = re.compile(r"(?:绑定|bind|登录)\s*(?:日服|jp|日本|国际服|intl|国际|rin|rinnet|rin服|林服|naominet)\s+\S+\s+\S+",
                      re.I)


def looks_like_password_bind(text: str) -> bool:
    """「/chu 绑定 日服 <SEGA ID> <密码>」这类一行带密码的绑定：群里要撤回，私聊也不能进大模型。"""
    return bool(_PW_BIND.search(text or ""))


def looks_like_clal(text: str) -> bool:
    return bool(CLAL_RE.search(text or ""))


class Redactor(logging.Filter):
    """Masks clal-shaped tokens and any password currently in a binding flow."""

    def __init__(self):
        super().__init__()
        self._secrets: set[str] = set()

    def remember(self, s: str) -> None:
        if s and len(s) >= 4:
            self._secrets.add(s)

    def forget(self, s: str) -> None:
        self._secrets.discard(s)

    def scrub(self, text: str) -> str:
        text = CLAL_RE.sub("<clal>", text)
        if any(k in text.lower() for k in ("落雪", "lxns", "luoxue")):
            text = _LX_TOKEN_RE.sub(_mask_lx, text)
        for s in self._secrets:
            text = text.replace(s, "<secret>")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = self.scrub(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


_LX_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9+/=_.-])[A-Za-z0-9+/=_.-]{20,512}(?![A-Za-z0-9+/=_.-])")


def _mask_lx(m: re.Match) -> str:
    t = m.group(0)
    # keep ordinary words / paths readable; a key mixes letters and digits
    return "<lxns>" if re.search(r"[0-9]", t) and re.search(r"[A-Za-z]", t) else t


REDACTOR = Redactor()


def install_redactor(names=("astrbot", "")) -> None:
    for name in names:
        lg = logging.getLogger(name)
        if REDACTOR not in lg.filters:
            lg.addFilter(REDACTOR)
        for h in lg.handlers:
            if REDACTOR not in h.filters:
                h.addFilter(REDACTOR)
