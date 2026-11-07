"""私服查分的公共数据类型。

各私服客户端（munet.py，以后 rinnet.py / aquadx.py）只负责把自己服务器的 JSON 转成这里的类型；
mai/privsrv.py、chuni/privsrv.py 再把这里的类型转成各游戏插件已有的 Score / Profile，
之后的 B50 计算、出图沿用插件原来的代码，不认服务器格式。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# 舞萌 comboStatus / syncStatus 是游戏原生编号，转成插件 mai 用的 fc / fs 键
MAI_FC = {1: "fc", 2: "fcp", 3: "ap", 4: "app"}
MAI_FS = {1: "fs", 2: "fsp", 3: "fsd", 4: "fsdp", 5: "sync"}


class PrivError(Exception):
    """私服查询失败，message 可以直接回给用户。"""


class PrivNotFound(PrivError):
    pass


class PrivHidden(PrivError):
    """用户在私服网站上把这部分数据设成了隐藏。"""

    def __init__(self, server_name: str, what: str):
        self.what = what
        super().__init__(f"你在 {server_name} 把「{what}」设成了隐藏，去网站的隐私设置里打开后再查。")


@dataclass
class PrivProfile:
    server: str            # munet …
    game: str              # mai2 / chusan
    username: str          # 私服网站用户名（绑定用的那个）
    name: str              # 游戏内昵称
    rating: int            # 舞萌是 DX Rating；中二是 rating×100（1601 = 16.01）
    rating_highest: Optional[int] = None
    server_rank: Optional[int] = None
    rom_version: str = ""  # 玩家客户端版本，如 "1.66.00" / "2.50.00"
    last_play: str = ""
    plays: Optional[int] = None


# ---------------------------------------------------------------- 舞萌

@dataclass
class MaiScore:
    music_id: int          # 游戏 ID：标准谱 < 10000，DX 谱 = 10000 + 基础 ID
    level_index: int       # 0 BASIC … 4 Re:MASTER
    achievement: int       # ×10000，1005799 = 100.5799%
    title: str = ""
    const: Optional[float] = None
    fc: str = ""
    fs: str = ""
    dx_score: Optional[int] = None
    play_count: Optional[int] = None
    rom_version: Optional[int] = None  # 谱面加入的游戏版本号，如 26009
    const_hint: Optional[float] = None  # 服务器自己曲目表里的定数（只有一个版本）；插件曲库没有这张谱时才用

    @property
    def kind(self) -> str:
        return "dx" if self.music_id >= 10000 else "std"


@dataclass
class MaiBest:
    old: list[MaiScore] = field(default_factory=list)  # B35
    new: list[MaiScore] = field(default_factory=list)  # B15


@dataclass
class MaiPlay:
    music_id: int
    level_index: int
    achievement: int
    title: str = ""
    dx_score: int = 0
    fc: str = ""
    fs: str = ""
    new_record: bool = False
    rating_after: Optional[int] = None
    played_at: str = ""
    track: Optional[int] = None


# ---------------------------------------------------------------- 中二

@dataclass
class ChuScore:
    music_id: int
    level_index: int       # 0 BASIC … 3 MASTER, 4 ULTIMA
    score: int
    title: str = ""
    const: Optional[float] = None
    full_combo: bool = False
    all_justice: bool = False
    play_count: Optional[int] = None


@dataclass
class ChuBest:
    best: list[ChuScore] = field(default_factory=list)  # 旧曲 B30
    new: list[ChuScore] = field(default_factory=list)   # 新曲 N20


@dataclass
class ChuPlay:
    music_id: int
    level_index: int
    score: int
    title: str = ""
    full_combo: bool = False
    all_justice: bool = False
    new_record: bool = False
    played_at: str = ""
    track: Optional[int] = None
