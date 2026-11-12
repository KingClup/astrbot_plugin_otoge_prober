"""国服成绩怎么更新：/mai 更新、/chu 更新 的文案、上传时间、自然语言入口。"""
from __future__ import annotations

from datetime import datetime, timezone

from core import cnupdate as CU
from core import nl

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def test_parse_and_age():
    assert CU.parse_time("") is None and CU.parse_time("garbage") is None
    assert CU.parse_time("2026-11-07T11:30:00Z").hour == 11
    assert CU.age_text("2026-11-07T11:59:30Z", "Asia/Shanghai", NOW) == ("上传于 11-07 19:59（刚刚）", False)
    assert CU.age_text("2026-11-07T11:30:00Z", "Asia/Shanghai", NOW) == ("上传于 11-07 19:30（30 分钟前）", False)
    assert CU.age_text("2026-11-07T06:00:00Z", "Australia/Sydney", NOW) == ("上传于 11-07 17:00（6 小时前）", False)
    when, stale = CU.age_text("2026-10-25T06:00:00Z", "Asia/Shanghai", NOW)
    assert when.endswith("（13 天前）") and stale
    assert CU.age_text("2026-11-05T06:00:00Z", "Bad/Zone", NOW)[0].startswith("上传于 11-05 06:00")   # 坏时区 → UTC
    assert CU.age_text(None) == ("", False)


def test_b50_note():
    t = CU.b50_note("mai", "lx", "2026-11-05T06:00:00Z", "Asia/Shanghai", NOW)
    assert t.startswith("数据来自落雪查分器，上传于 11-05 14:00（2 天前）") and t.endswith("/mai 更新")
    t = CU.b50_note("chu", "lx", "2026-10-01T06:00:00Z", "Asia/Shanghai", NOW)
    assert t.startswith("⚠ 这份成绩有点旧了") and "/chu 更新" in t
    assert "落雪" in CU.b50_note("chu", "lx", "", None, NOW) and "/chu 更新" in CU.b50_note("chu", "lx", "", None, NOW)
    t = CU.b50_note("mai", "df", "", None, NOW)
    assert "水鱼" in t and "上传时间" in t and "/mai 更新" in t


def test_update_card_links_and_sources():
    t = CU.update_card("mai", "lx", "2026-11-05T06:00:00Z", None, "Asia/Shanghai", "KING", NOW)
    assert t.startswith("舞萌国服成绩怎么更新") and "落雪查分器（KING）" in t
    assert "https://maimai.lxns.net/sync" in t and "上传于 11-05 14:00" in t and "/mai 刷新" in t
    t = CU.update_card("chu", "df", "", {"df_chu": "https://example.com/chu"}, None, "", NOW)
    assert "水鱼查分器" in t and "https://example.com/chu" in t and "推荐换落雪" in t and "/网页绑定" in t
    assert "diving-fish" not in t
    t = CU.update_card("chu", "lx", "2026-10-01T00:00:00Z", None, None, "", NOW)
    assert "⚠ 已经有点旧了" in t
    assert "国际服" in CU.not_cn_note("mai", "国际服") and "/mai 刷新" in CU.not_cn_note("mai", "国际服")


def test_nl_update_intent():
    for text, game, srv in (("国服成绩怎么更新", "unknown", "cn"), ("舞萌国服怎么上传成绩", "mai", "cn"),
                            ("中二怎么传分", "chu", ""), ("帮我更新一下中二成绩", "chu", "")):
        it = nl.rules(text)
        assert (it.action, it.game, it.server) == ("update", game, srv), text
        assert nl.rules_settle(text, it)
        assert nl.to_command(it).startswith("更新")
    assert nl.rules("今天更新了舞萌").action == "none"        # 聊天，不是在问
    assert nl.to_command(nl.rules("舞萌国服怎么上传成绩")) == "更新 国服"


def test_changelog_parses_and_matches_version():
    import os
    import re
    from core import changelog as CL
    es = CL.load()
    assert len(es) >= 10 and es[0].items and es[0].date
    root = os.path.dirname(os.path.dirname(os.path.abspath(CL.__file__)))
    meta = open(os.path.join(root, "metadata.yaml"), encoding="utf-8").read()
    ver = re.search(r"^version:\s*v?([\d.]+)", meta, re.M).group(1)
    main_ver = re.search(r'^VERSION = "([\d.]+)"', open(os.path.join(root, "main.py"), encoding="utf-8").read(), re.M).group(1)
    assert es[0].version == f"v{ver}" == f"v{main_ver}"          # 发新版必须写一条
    t = CL.text(es, 3)
    assert t.startswith("更新记录（最近 3 版") and "`" not in t and f"v{ver}" in t
    assert "没列" not in CL.text(es, None, max_chars=100000)
    assert CL.summary(es, 2)[1]["version"].startswith("v")
    assert CL.parse("## v9.9.9 · 标题（2030-01-01）\n- 一\n  续行\n- 二\n")[0].items == ["一 续行", "二"]
