import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
# 让脚本能 import 插件里的 chuni 包（不依赖 AstrBot）
sys.path.insert(0, str(PLUGIN_DIR))


def default_data_dir() -> Path:
    """中二部分的数据目录：<AstrBot 数据目录>/plugin_data/astrbot_plugin_otoge_prober/chu"""
    env = os.environ.get("CHUNI_DATA_DIR")
    if env:
        return Path(env)
    # 插件装在 <data>/plugins/astrbot_plugin_otoge_prober 时，往上两级就是 data 目录
    data = PLUGIN_DIR.parent.parent
    if (data / "cmd_config.json").exists():
        return data / "plugin_data" / "astrbot_plugin_otoge_prober" / "chu"
    return Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_otoge_prober" / "chu"


def read_clal(args_file: str | None) -> str:
    if args_file:
        return Path(args_file).read_text("utf-8").strip()
    import getpass

    return getpass.getpass("粘贴 clal（输入不会显示，粘贴后按回车）: ").strip()
