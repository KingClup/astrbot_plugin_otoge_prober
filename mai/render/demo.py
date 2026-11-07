"""Demo Best 50 for theme previews (no login needed): random charts from the song DB."""
from __future__ import annotations

import random

from ..calc.rating import Best50, attach_charts, build_best50
from ..data.songdb import SongDB
from ..models import Profile, Score


def demo_best50(db: SongDB, region: str = "intl", seed: int = 7) -> tuple[Best50, Profile]:
    rng = random.Random(seed)
    rv = db.current_version.get(region)
    charts = [c for s in db.songs for c in s.charts
              if c.type != "utage" and c.diff in ("master", "remaster", "expert") and c.available(region)
              and (c.ds_in(region, rv) or 0) >= 13.6]
    rng.shuffle(charts)
    old = [c for c in charts if not db.is_new(c, region)][:40]
    new = [c for c in charts if db.is_new(c, region)][:18]
    scores = []
    for c in old + new:
        ach = rng.choice([1005000 + rng.randint(0, 5000), 1000000 + rng.randint(0, 4999), 995000 + rng.randint(0, 4999)])
        tot = (c.notes.get("total") or 900) * 3
        scores.append(Score(title=c.song.title, type=c.type, diff=c.diff, level=c.level_in(region), ach=ach,
                            dx=int(tot * rng.uniform(0.86, 0.99)), dx_max=tot,
                            fc=rng.choice([None, None, "fc", "fcp", "ap", "app"]),
                            fs=rng.choice([None, "sync", "sync", "fs", "fsp", "fsd", "fsdp"])))
    attach_charts(scores, db, region)
    b = build_best50(scores, db, region)
    prof = Profile(name="ＤＥＭＯ", rating=b.total, title="主题预览", title_kind="gold", stars=123,
                   play_count_version=42, play_count_total=1234, region=region)
    return b, prof
