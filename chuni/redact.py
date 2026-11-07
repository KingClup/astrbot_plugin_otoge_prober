"""日志打码：把 64 位 clal 从 AstrBot 的日志里替换成 <clal>。

AstrBot 的 event_bus 会在插件处理之前把每条消息原文写进日志（文件 + WebUI 实时日志）。
这里给 logging 的所有 handler 挂一个过滤器，在写出前改写 record。
注意：NapCat 自己的日志不经过这里。
"""

from __future__ import annotations

import logging
import re

CLAL_RE = re.compile(r"(?<![A-Za-z0-9])(?:clal=)?[a-z0-9]{64}(?![A-Za-z0-9])")
_FLAG = "_chuni_intl_redact"


def redact(text: str) -> str:
    return CLAL_RE.sub("<clal>", text)


def contains_clal(text: str) -> bool:
    return bool(CLAL_RE.search(text or ""))


def find_clal(text: str) -> str | None:
    m = CLAL_RE.search(text or "")
    if not m:
        return None
    v = m.group(0)
    return v[5:] if v.startswith("clal=") else v


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        if CLAL_RE.search(msg):
            record.msg = redact(msg)
            record.args = None
        return True


_filter = _RedactFilter()
setattr(_filter, _FLAG, True)


def _all_handlers():
    seen = set()
    loggers = [logging.getLogger()] + [
        lg for lg in logging.Logger.manager.loggerDict.values() if isinstance(lg, logging.Logger)
    ]
    for lg in loggers:
        for h in lg.handlers:
            if id(h) not in seen:
                seen.add(id(h))
                yield h


def install() -> int:
    """挂到当前所有 handler 上；返回挂上的数量。可以重复调用。"""
    n = 0
    for h in _all_handlers():
        if not any(getattr(f, _FLAG, False) for f in h.filters):
            h.addFilter(_filter)
            n += 1
    return n


def uninstall() -> None:
    for h in _all_handlers():
        for f in list(h.filters):
            if getattr(f, _FLAG, False):
                h.removeFilter(f)
