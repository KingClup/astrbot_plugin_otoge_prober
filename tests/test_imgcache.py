import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.imgcache import ImageCache  # noqa: E402


def test_hit_miss_version_and_daily(tmp_path, monkeypatch):
    c = ImageCache(tmp_path, version="1.0")
    calls = []

    async def make():
        calls.append(1)
        return b"PNG"
    run = asyncio.new_event_loop().run_until_complete
    assert run(c.cached("help", ("Bot",), make, daily=False)) == b"PNG"
    assert run(c.cached("help", ("Bot",), make, daily=False)) == b"PNG" and len(calls) == 1
    assert run(c.cached("help", ("Other",), make, daily=False)) and len(calls) == 2      # different args
    assert ImageCache(tmp_path, version="1.1").get("help", "Bot", daily=False) is None  # new plugin version
    c.put("song", b"X", 834, "intl")
    monkeypatch.setattr(time, "strftime", lambda fmt, *a: "2099-01-01")
    assert c.get("song", 834, "intl") is None                                            # next day → redraw


def test_prune_and_clear(tmp_path):
    c = ImageCache(tmp_path, version="v", max_mb=0)
    c.max_bytes = 10
    for i in range(5):
        c.put("k", b"123456", i, daily=False)
        p = c._path("k", (i,), False)
        os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    r = c.prune()
    assert r["files"] == 1 and c.get("k", 4, daily=False) == b"123456"                  # newest kept
    old = c._path("k", (4,), False)
    os.utime(old, (time.time() - 10 * 86400,) * 2)
    assert c.prune()["files"] == 0
    c.put("k", b"1", 9, daily=False)
    assert c.clear() == 1 and c.get("k", 9, daily=False) is None
