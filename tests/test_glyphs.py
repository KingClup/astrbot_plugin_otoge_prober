import os

import pytest
from PIL import Image, ImageDraw, ImageFont

from core import glyphs as G

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
NOTO = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"


@pytest.mark.skipif(not (os.path.exists(DEJAVU) and os.path.exists(NOTO)), reason="needs local fonts")
def test_runs_fall_back_per_char():
    latin, cjk = ImageFont.truetype(DEJAVU, 30), ImageFont.truetype(NOTO, 30, index=2)
    assert not G.has(latin, "论") and G.has(cjk, "论") and G.has(latin, "✓")
    # 整行一个字体：DejaVu 只是符号字体，不当底字体 → 「理论 Rating」整行都用中文字体，不会一个字一个样
    parts = G.runs("理论 Rating", [latin, cjk])
    assert parts == [("理论 Rating", cjk)]
    # 日文字体里没有「论」：整行换成有「论」的字体，而不是只有「论」一个字换
    jp = ImageFont.truetype(NOTO, 30, index=0)
    assert G.pick_base("理论 Rating", [jp, cjk]) in (jp, cjk)
    assert len({id(f) for _t, f in G.runs("理论 Rating", [jp, cjk])}) == 1
    d = ImageDraw.Draw(Image.new("RGB", (400, 60)))
    x = G.draw(d, (200, 30), "理论 abc", [latin, cjk], (255, 255, 255), anchor="mm")
    assert abs(x - (200 + G.width("理论 abc", [latin, cjk]) / 2)) < 1
