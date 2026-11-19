import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 插件运行时只用 AstrBot 的 logger（from astrbot.api import logger）。测试环境没装 AstrBot：
# 用一个同名（"astrbot"）的标准 logger 顶上，caplog 也照样抓得到。
if "astrbot.api" not in sys.modules:
    try:
        import astrbot.api  # noqa: F401
    except ImportError:
        import logging
        import types

        _pkg = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
        _pkg.__path__ = []
        _api = types.ModuleType("astrbot.api")
        _api.logger = logging.getLogger("astrbot")
        _pkg.api = _api
        sys.modules["astrbot.api"] = _api
