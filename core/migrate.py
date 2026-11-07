"""First start: copy the data of the two old plugins into the merged plugin's folder.

  plugin_data/astrbot_plugin_mai_net/      → plugin_data/astrbot_plugin_otoge_prober/mai/
  plugin_data/astrbot_plugin_chuni_intl/   → plugin_data/astrbot_plugin_otoge_prober/chu/

Copy, not move: the old plugins keep working until you uninstall them. Bindings stay encrypted with
their own secret.key (it is copied along). Runs only when the target folder is still empty.
"""
from __future__ import annotations

import json
import os
import shutil

OLD = {"mai": "astrbot_plugin_mai_net", "chu": "astrbot_plugin_chuni_intl"}
SKIP = {"render", "__pycache__"}


def _empty(path: str) -> bool:
    return not os.path.isdir(path) or not any(os.scandir(path))


def migrate(root: str) -> dict[str, str]:
    """root = this plugin's data dir. Returns {game: what happened}."""
    parent = os.path.dirname(os.path.abspath(root))
    report = {}
    for game, old in OLD.items():
        src, dst = os.path.join(parent, old), os.path.join(root, game)
        if not os.path.isdir(src):
            report[game] = "没有旧数据"
            continue
        if not _empty(dst):
            report[game] = "已存在，跳过"
            continue
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=lambda d, names: [n for n in names if n in SKIP])
            report[game] = f"已从 {old} 复制"
        except OSError as e:
            report[game] = f"复制失败：{e}"
    # old mai WebUI setting used the lowercase name
    p = os.path.join(root, "mai", "webui_settings.json")
    try:
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
        pass
    except (OSError, ValueError):
        pass
    return report
