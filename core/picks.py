"""「可能是这几首」之后直接回序号：同一个人在同一个会话里，15 秒内回 1 / 2 / 3 就照着那一项查。

每一项是 (游戏, 指令参数)（交给 main 的 _dispatch 再跑一次），或者一个 async 函数（→ Reply）。
"""
from __future__ import annotations

import re
import time

PICK_TTL = 15
_PICK_RE = re.compile(r"^\s*(?:第\s*)?([1-9])\s*(?:个|首|号)?\s*[。.!！]?\s*$")


class PickBox:
    def __init__(self, ttl: float = PICK_TTL, clock=time.monotonic) -> None:
        self.ttl = ttl
        self.clock = clock
        self._box: dict[tuple[str, str], tuple[float, list]] = {}

    def arm(self, key: tuple[str, str], picks: list) -> str:
        """记下候选，返回要加在回复后面的提示；没有候选返回空串。"""
        if not picks:
            return ""
        now = self.clock()
        self._box[key] = (now, list(picks))
        if len(self._box) > 200:
            self._box = {k: v for k, v in self._box.items() if now - v[0] <= self.ttl}
        n = len(picks)
        return f"（{self.ttl:g} 秒内直接回序号 1～{n} 就行）" if n > 1 else f"（{self.ttl:g} 秒内回 1 就查它）"

    def take(self, key: tuple[str, str], text: str):
        """这条是在回序号 → 那一项（用掉就删）；不是 / 过期 / 超出范围 → None（不吃掉这条消息）。"""
        got = self._box.get(key)
        if got is None:
            return None
        if self.clock() - got[0] > self.ttl:
            self._box.pop(key, None)
            return None
        m = _PICK_RE.match(text or "")
        if not m or int(m.group(1)) > len(got[1]):
            return None
        self._box.pop(key, None)
        return got[1][int(m.group(1)) - 1]
