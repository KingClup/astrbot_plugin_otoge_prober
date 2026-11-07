"""汉字归一：日文新字体、繁体都折成简体，让「回归」能对上「回帰」、「恶戏」对上「悪戯」。

对照表 kanji_fold.json 是用 OpenCC（Apache-2.0）的 TSCharacters + JPVariants 单字表生成的，
只做逐字替换，不做词组转换；猜歌、查歌两边都过一遍，所以只会多认，不会少认。
"""
from __future__ import annotations

import json
import os

_TABLE: dict[int, str] | None = None


def _table() -> dict[int, str]:
    global _TABLE
    if _TABLE is None:
        try:
            with open(os.path.join(os.path.dirname(__file__), "kanji_fold.json"), encoding="utf-8") as f:
                d = json.load(f)
            _TABLE = {ord(a): b for a, b in zip(d["src"], d["dst"])}
        except (OSError, ValueError, KeyError):
            _TABLE = {}
    return _TABLE


def fold_kanji(s: str) -> str:
    return (s or "").translate(_table())


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s or "")
