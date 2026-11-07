"""Manual check against the real NET (no AstrBot needed). Credentials are read interactively.

  python tools/verify_login.py intl            # asks for clal (or leave empty → SEGA ID + password)
  python tools/verify_login.py jp              # asks for SEGA ID + password
  python tools/verify_login.py intl --dump D:\\mai_pages   # also save raw HTML (for fixing parsers)
"""
import argparse
import asyncio
import getpass
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mai.calc.rating import attach_charts, build_best50  # noqa: E402
from mai.consts import DIFFS, DIFF_INDEX  # noqa: E402
from mai.data.loader import CatalogStore  # noqa: E402
from mai.net.client import (P_PLAYER, P_RECORD, P_TARGET, Credentials, NetSession, p_scores)  # noqa: E402
from mai.parse.profile import parse_profile  # noqa: E402
from mai.parse.record import parse_recent  # noqa: E402
from mai.parse.scores import parse_rating_target, parse_score_list  # noqa: E402
from mai.render.text import best50_text  # noqa: E402


async def run(a):
    c = Credentials(region=a.region)
    if a.region == "intl":
        c.clal = getpass.getpass("clal (empty = use SEGA ID): ").strip()
    if not c.clal:
        c.sega_id = input("SEGA ID: ").strip()
        c.password = getpass.getpass("password: ")
    s = NetSession(c)
    dump = pathlib.Path(a.dump) if a.dump else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)

    async def get(path, name):
        html = await s.get(path)
        if dump:
            (dump / f"{a.region}_{name}.html").write_text(html, "utf-8")
        return html

    try:
        prof = parse_profile(await get(P_PLAYER, "playerData"), a.region)
        print(f"OK  {prof.name}  NET rating {prof.rating}  title={prof.title}  plays={prof.play_count_version}/{prof.play_count_total}")
        scores = []
        for d in DIFFS:
            rows = parse_score_list(await get(p_scores(DIFF_INDEX[d]), f"scores_{d}"))
            print(f"    {d:<9} {len(rows)} played")
            scores += rows
        tgt = parse_rating_target(await get(P_TARGET, "ratingTarget"))
        print("    rating target sections:", {k: len(v) for k, v in tgt.items()})
        rec = parse_recent(await get(P_RECORD, "record"))
        print(f"    recent plays: {len(rec)}")
        db = CatalogStore(a.cache or os.path.join(ROOT, "tests", "_catalog")).load_local()
        attach_charts(scores, db, a.region)
        b = build_best50(scores, db, a.region)
        print()
        print(best50_text(b, prof, db))
        miss = [x for x in scores if x.music_id is None and x.song_id is None]
        if miss:
            print(f"\n{len(miss)} scores not matched to the song DB:", ", ".join(sorted({m.title for m in miss})[:20]))
    finally:
        await s.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("region", choices=["intl", "jp"])
    ap.add_argument("--dump", help="directory to save raw HTML pages")
    ap.add_argument("--cache", help="catalog cache dir")
    asyncio.run(run(ap.parse_args()))
