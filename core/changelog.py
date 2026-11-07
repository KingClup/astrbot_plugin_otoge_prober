"""更新记录：读插件目录里的 CHANGELOG.md（新的在上面），给 /查分 更新记录 和 WebUI 用。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CHANGELOG.md")
_HEAD = re.compile(r"^##\s+(?P<ver>v[\d.]+(?:\s*[–-]\s*v?[\d.]+)?)\s*(?:·\s*(?P<title>.*?))?\s*(?:（(?P<date>[\d-]+)）)?\s*$")
WORDS = ("更新记录", "更新日志", "changelog", "版本记录", "改了什么", "更新了什么", "新版本")


@dataclass
class Entry:
    version: str
    title: str = ""
    date: str = ""
    items: list[str] = field(default_factory=list)

    def text(self) -> str:
        head = self.version + (f" · {self.title}" if self.title else "") + (f"（{self.date}）" if self.date else "")
        return "\n".join([head] + [f"· {x.replace('`', '')}" for x in self.items])   # QQ 里不显示 markdown


def parse(md: str) -> list[Entry]:
    out: list[Entry] = []
    cur: Entry | None = None
    for line in md.splitlines():
        if line.startswith("## "):
            m = _HEAD.match(line)
            cur = Entry(m.group("ver").strip(), (m.group("title") or "").strip(), m.group("date") or "") if m \
                else Entry(line[3:].strip())
            out.append(cur)
        elif cur is not None and line.startswith("- "):
            cur.items.append(line[2:].strip())
        elif cur is not None and line.startswith("  ") and cur.items and line.strip():
            cur.items[-1] += " " + line.strip()           # 缩进的续行
    return out


def load(path: str = PATH) -> list[Entry]:
    try:
        with open(path, encoding="utf-8") as f:
            return parse(f.read())
    except OSError:
        return []


def text(entries: list[Entry], n: int | None = 3, max_chars: int = 2800) -> str:
    """最近 n 版（None = 全部）；太长时截断并提示。"""
    if not entries:
        return "还没有更新记录"
    picked = entries if n is None else entries[:n]
    blocks, total = [], 0
    for e in picked:
        t = e.text()
        if total + len(t) > max_chars and blocks:
            blocks.append(f"（太长了，还有 {len(picked) - len(blocks)} 版没列；看 CHANGELOG.md）")
            break
        blocks.append(t)
        total += len(t) + 2
    head = "更新记录" + ("（最近 %d 版，全部发「/查分 更新记录 全」）" % len(picked) if n is not None and len(entries) > n else "")
    return head + "\n\n" + "\n\n".join(blocks)


def summary(entries: list[Entry], n: int = 3) -> list[dict]:
    return [{"version": e.version, "title": e.title, "date": e.date, "items": e.items} for e in entries[:n]]
