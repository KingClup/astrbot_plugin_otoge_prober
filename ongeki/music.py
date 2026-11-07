"""O.N.G.E.K.I. song database: chart constants per client version.

Constants come from data/ongeki_consts.json (built from otoge-db by
tools/build_ongeki_consts.py). Private servers identify songs by the game's
music id, which otoge-db does not have, so songs are matched by title
(+ artist when the title is ambiguous). A server's own constant can be passed
as a fallback for songs otoge-db does not know.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import versions

DIFF_NAMES = ("BASIC", "ADVANCED", "EXPERT", "MASTER", "LUNATIC")
DIFF_SHORT = ("BAS", "ADV", "EXP", "MAS", "LUN")
LUNATIC = 10          # game difficulty id of LUNATIC / Re:MASTER


def diff_index(game_diff: int) -> int:
    """Game difficulty id (0-3, 10) -> 0..4."""
    return 4 if game_diff == LUNATIC else int(game_diff)


def norm(s: str | None) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "").lower())


@dataclass
class Song:
    key: str
    title: str
    artist: str
    lunatic: bool
    bonus: bool
    version: int | None            # version code the song was added in (150 = Re:Fresh)
    consts: dict[int, list] = field(default_factory=dict)   # table -> [bas, adv, exp, mas, lun]
    removed_consts: list | None = None   # removed from the arcade: last known constants

    def removed_const(self, game_diff: int) -> float | None:
        return self.removed_consts[diff_index(game_diff)] if self.removed_consts else None

    def const(self, game_diff: int, client: int | None) -> float | None:
        table = versions.const_table(client)
        # newest table at or below the client's; songs newer than the client fall through
        for t in sorted(self.consts, reverse=True):
            if t <= table:
                v = self.consts[t][diff_index(game_diff)]
                if v is not None:
                    return v
        # the client is older than every table that has the song (or the chart):
        # take the oldest known value
        for t in sorted(self.consts):
            v = self.consts[t][diff_index(game_diff)]
            if v is not None:
                return v
        return None


class OngekiMusicDB:
    def __init__(self, data: dict):
        self.snapshots = data.get("snapshots", {})
        self.songs: dict[str, Song] = {}
        for key, (title, artist, lun, bonus, ver) in data["songs"].items():
            self.songs[key] = Song(key, title, artist, bool(lun), bool(bonus), ver)
        for table, rows in data["tables"].items():
            for key, consts in rows.items():
                if key in self.songs:
                    self.songs[key].consts[int(table)] = consts
        for key, consts in (data.get("deleted") or {}).items():
            if key in self.songs:
                self.songs[key].removed_consts = consts
        self._by_title: dict[tuple[str, bool], list[Song]] = {}
        for s in self.songs.values():
            self._by_title.setdefault((norm(s.title), s.lunatic), []).append(s)

    @classmethod
    def load(cls, path: str | Path) -> "OngekiMusicDB":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def match(self, title: str, artist: str | None = None, *, lunatic: bool = False,
              server_consts: list | None = None) -> Song | None:
        """Find a song. `lunatic` means the game's LUNATIC/Re:MASTER entry (music id 8xxx).

        BONUS TRACKs share titles with normal songs; they are only picked when
        nothing else matches, and callers exclude them from rating.
        """
        cands = self._by_title.get((norm(title), lunatic), [])
        if len(cands) > 1:
            plain = [s for s in cands if not s.bonus]
            cands = plain or cands
        if len(cands) > 1 and artist:
            same = [s for s in cands if norm(s.artist) == norm(artist)]
            cands = same or cands
        if len(cands) > 1 and server_consts:
            # pick the one whose newest constants are closest to the server's
            def dist(s: Song):
                row = s.consts[max(s.consts)] if s.consts else []
                return sum(abs((a or 0) - (b or 0)) for a, b in zip(row, server_consts))
            cands = sorted(cands, key=dist)[:1]
        return cands[0] if cands else None
