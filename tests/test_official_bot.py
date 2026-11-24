"""v3.0.0：QQ 官方机器人和个人号并存。官方那边 uid 是 openid（不是 QQ 号）；查分插件的功能两边一样全开。"""
import os
import re

from core.bindweb import mask_qq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_mask_openid_and_qq():
    assert mask_qq("1234567890") == "12******90"
    oid = "A1B2C3D4E5F60718293A4B5C6D7E8F90"
    assert mask_qq(oid) == "A1B2…90" and len(mask_qq(oid)) < 10


def test_official_ctx_and_gates_in_main():
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert 'str(event.get_platform_name() or "").startswith("qq_official")' in src
    assert "official=self._is_official(event)" in src
    # 小游戏、别名投票在官方机器人那边也开（用户定的：整个查分插件都开，关的是人格那边的插件）
    assert "self._games_on() and not ctx.official" not in src and "not ctx.private and not ctx.official" not in src


def test_no_qq_number_paths_for_openid():
    web = open(os.path.join(ROOT, "core", "bindweb.py"), encoding="utf-8").read()
    assert '"official": not str(s.uid).isdigit()' in web and "self.binder.lx_options(s.uid)" in web
    assert re.search(r'if method in \("df", "lxqq"\) and not value and not str\(uid\)\.isdigit\(\):', web)
    for p, cmd in (("mai/bot/commands.py", "/mai"), ("chuni/commands.py", "/chu")):
        s = open(os.path.join(ROOT, p), encoding="utf-8").read()
        assert "if not name and not str(ctx.uid).isdigit():" in s and f"{cmd} 绑定 国服 <水鱼用户名>" in s


def test_other_bots_are_ignored_on_personal_side():
    """v3.0.1：个人号这边不理别的机器人说的话（两个 bot 不互相接话）。main.py 要 AstrBot 才能导入，这里只看源码。"""
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    pat = re.search(r'_BOT_QQ_RE = re\.compile\(r"([^"]+)"\)', src).group(1)
    bot = re.compile(pat)
    for uid in ("3889001234", "2854196310"):
        assert bot.fullmatch(uid), uid
    for uid in ("1234567890", "38890012345", "388900123", "2854296310", ""):
        assert not bot.fullmatch(uid), uid
    assert "if not ctx.official and self._is_other_bot(ctx.uid):" in src
    assert src.index("self._is_other_bot(ctx.uid)") < src.index("pick = self.picks.take(")      # 在指令、小游戏之前就拦掉
    assert 'self._cfg("ignore_other_bots", True)' in src and 'self._cfg("ignore_qq_list", [])' in src
    import json
    schema = json.load(open(os.path.join(ROOT, "_conf_schema.json"), encoding="utf-8"))
    assert schema["ignore_other_bots"]["default"] is True and schema["ignore_qq_list"]["type"] == "list"
