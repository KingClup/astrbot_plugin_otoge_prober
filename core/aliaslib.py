"""本机别名库导出：把这个 bot 自己收的外号（「加别名」+ 猜歌投票通过的）按游戏整理成 JSON，方便看、备份、开源。

输出在插件数据目录 alias_library/：
  mai.json / chu.json / geki.json / sdvx.json / pjsk.json   每个游戏一份
  README.md                                                  格式说明
不含任何 QQ 号、群号；投票只留票数。
"""
from __future__ import annotations

import datetime as dt
import json
import os

GAMES = {"mai": "maimai DX（舞萌 DX）", "chu": "CHUNITHM（中二节奏）", "geki": "O.N.G.E.K.I.（音击）",
         "sdvx": "SOUND VOLTEX", "pjsk": "Project SEKAI（世界计划）"}
ID_SPACES = {
    "mai": "maimai 基础曲目 ID（标准 / DX 谱共用，< 10000；水鱼 / 落雪的 DX ID 减 10000 即可）",
    "chu": "CHUNITHM 官方曲目 ID（与落雪 / otoge-db 一致）",
    "sdvxin": "sdvx.in 的曲目编号（谱面网站 sdvx.in 上的 ID）",
}
SCHEMA = "otoge-community-aliases"
LICENSE = "CC0-1.0"

README = """# 音游外号（别名）库 · 本 bot 收录部分

由 astrbot_plugin_otoge_prober 自动生成。只包含**这个 bot 自己收的**外号：
群友用「/mai 加别名」「/chu 加别名」「/sdvx 加别名」… 加的（source = "manual"），
以及猜歌时大模型挑出、群里投票通过的（source = "vote"，带票数）。
落雪 / Yuzuchan 等公共别名库里本来就有的不在这里。

## 文件
每个游戏一个 JSON：mai.json、chu.json、geki.json、sdvx.json、pjsk.json。

```json
{
  "schema": "otoge-community-aliases", "version": 1,
  "game": "chu", "game_name": "CHUNITHM（中二节奏）",
  "generated": "2026-11-08T18:00:00+11:00", "license": "CC0-1.0",
  "id_spaces": {"chu": "CHUNITHM 官方曲目 ID …", "sdvxin": "sdvx.in 的曲目编号 …"},
  "songs": [
    {"title": "Aleph-0", "ids": {"chu": 2338, "sdvxin": "01234"},
     "aliases": [{"alias": "阿列夫", "source": "vote", "added": "2026-11-08", "votes": {"yes": 3, "no": 0}}]}
  ]
}
```

- `ids`：同一首歌在不同编号体系里的 ID，至少有一个。按标题合并。
- `aliases[].source`：`manual` = 指令加的；`vote` = 猜歌投票通过的（`votes` 是赞成 / 反对票数）。
- `added`：收录日期（指令加的老数据没有日期）。
- 不含 QQ 号、群号或任何个人信息。

## 许可
默认 CC0-1.0（公共领域），可以直接合并进别的别名库。歌名版权归各自权利人。
"""


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Lib:
    def __init__(self):
        self.games: dict[str, dict[str, dict]] = {g: {} for g in GAMES}     # game → title → song

    def add(self, game: str, title: str, space: str, sid, alias: str, source: str = "manual",
            added: str = "", votes: dict | None = None) -> None:
        if game not in self.games or not alias or not title:
            return
        s = self.games[game].setdefault(title, {"title": title, "ids": {}, "aliases": []})
        if sid not in (None, ""):
            s["ids"].setdefault(space, int(sid) if str(sid).isdigit() and space != "sdvxin" else str(sid))
        for a in s["aliases"]:
            if a["alias"] == alias:
                if source == "vote":                                  # 投票信息覆盖「手动」
                    a.update({"source": "vote", "added": added or a.get("added", ""), "votes": votes or {}})
                return
        item = {"alias": alias, "source": source}
        if added:
            item["added"] = added
        if votes:
            item["votes"] = votes
        s["aliases"].append(item)

    def doc(self, game: str) -> dict:
        songs = sorted(self.games[game].values(), key=lambda s: s["title"].casefold())
        spaces = sorted({k for s in songs for k in s["ids"]})
        return {"schema": SCHEMA, "version": 1, "game": game, "game_name": GAMES[game], "generated": _now(),
                "license": LICENSE, "id_spaces": {k: ID_SPACES.get(k, k) for k in spaces}, "songs": songs}

    def counts(self) -> dict[str, int]:
        return {g: sum(len(s["aliases"]) for s in d.values()) for g, d in self.games.items()}


def collect(p) -> Lib:
    """从插件各处的本机别名存储收集（p = 插件主体；拿不到的部分跳过）。"""
    lib = Lib()
    votes = {}
    for k, v in (getattr(getattr(p, "alias_votes", None), "history", None) or {}).items():
        if v.get("result") == "pass":
            votes[(k.split("|")[0], v.get("alias"))] = v
    date = lambda ts: dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d") if ts else ""  # noqa: E731

    def meta(game, alias):
        v = votes.get((game, alias)) or votes.get((game, alias.replace(" ", "")))
        if not v:
            return "manual", "", None
        return "vote", date(v.get("ts")), {"yes": int(v.get("yes") or 0), "no": int(v.get("no") or 0)}

    # 舞萌：local_aliases.json {外号: 基础 ID}
    try:
        db = p.cmd.db
        for alias, sid in (p.cmd.aliases.local() if p.cmd.aliases else {}).items():
            s = db.song_by_any_id(int(sid)) if db is not None else None
            lib.add("mai", s.title if s else f"#{sid}", "mai", sid, alias, *meta("mai", alias))
    except Exception:  # noqa: BLE001
        pass
    # 中二
    try:
        db = p.chu_svc.songdb
        for alias, sid in (p.chu.aliases.local() if p.chu.aliases else {}).items():
            s = db.get(int(sid))
            lib.add("chu", s.title if s else f"#{sid}", "chu", sid, alias, *meta("chu", alias))
    except Exception:  # noqa: BLE001
        pass
    # sdvx.in 那份（/sdvx /pjsk /geki 加别名、猜谱面投票）
    try:
        src = p.charts.src
        for game, table in (src.aliases or {}).items():
            ents = src.entries.get(game) or {}
            for sid, lst in (table or {}).items():
                e = ents.get(sid)
                for alias in lst:
                    lib.add(game, e.title if e else f"sdvx.in {sid}", "sdvxin", sid, alias, *meta(game, alias))
    except Exception:  # noqa: BLE001
        pass
    return lib


def write(lib: Lib, out_dir: str) -> dict[str, int]:
    os.makedirs(out_dir, exist_ok=True)
    for g in GAMES:
        path = os.path.join(out_dir, f"{g}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lib.doc(g), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(README)
    return lib.counts()
