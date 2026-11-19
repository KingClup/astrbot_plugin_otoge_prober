import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
# 让脚本能 import 插件里的 chuni 包（不依赖 AstrBot）
sys.path.insert(0, str(PLUGIN_DIR))


def _astrbot_logger_stub() -> None:
    """插件模块用 AstrBot 的 logger（from astrbot.api import logger）。脱离 AstrBot 单独跑脚本时给一个打到 stderr 的替身。"""
    try:
        import astrbot.api  # noqa: F401
        return
    except ImportError:
        pass
    import types

    class _Log:
        filters: list = []
        handlers: list = []

        def _out(self, level, msg, *args, **_kw):
            print(f"[{level}] " + (str(msg) % args if args else str(msg)), file=sys.stderr)

        def debug(self, *a, **k): pass
        def info(self, *a, **k): self._out("INFO", *a, **k)
        def warning(self, *a, **k): self._out("WARN", *a, **k)
        def error(self, *a, **k): self._out("ERROR", *a, **k)
        exception = error
        def addFilter(self, f): pass
        def removeFilter(self, f): pass

    pkg = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
    pkg.__path__ = []
    api = types.ModuleType("astrbot.api")
    api.logger = _Log()
    pkg.api = api
    sys.modules["astrbot.api"] = api


_astrbot_logger_stub()


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
