"""O.N.G.E.K.I. client versions.

Client version strings look like "1.51.00". AquaDX tags each song with the
version it was added in as an int (1050 = 1.50). otoge-db tags it by name.
"""
from __future__ import annotations

# (version code, display name, otoge-db name)
VERSIONS = [
    (100, "オンゲキ", "ONGEKI"),
    (105, "オンゲキ PLUS", "ONGEKI Plus"),
    (110, "SUMMER", "SUMMER"),
    (115, "SUMMER PLUS", "SUMMER Plus"),
    (120, "R.E.D.", "RED"),
    (125, "R.E.D. PLUS", "RED Plus"),
    (130, "bright", "bright"),
    (135, "bright MEMORY Act.1", "bright MEMORY Act.1"),
    (140, "bright MEMORY Act.2", "bright MEMORY Act.2"),
    (145, "bright MEMORY Act.3", "bright MEMORY Act.3"),
    (150, "Re:Fresh", "Re:Fresh"),
    (160, "Re:Fresh Act.2", "Re:Fresh Act.2"),
]
_BY_OTOGE = {o: code for code, _, o in VERSIONS}
_BY_CODE = {code: name for code, name, _ in VERSIONS}

REFRESH = 150          # first client with the Re:Fresh rating system
# Constant tables shipped in data/ongeki_consts.json, keyed by the first client
# version they apply to (constants change at version updates).
CONST_TABLES = (145, 150, 160)


def parse_client(ver: str | int | None) -> int | None:
    """'1.51.00' / '1.51' / 1051 / 151 -> 151 (hundredths of the major version)."""
    if ver is None or ver == "":
        return None
    if isinstance(ver, int):
        return ver - 900 if ver >= 1000 else ver
    try:
        parts = str(ver).strip().split(".")
        return int(parts[0]) * 100 + int((parts[1] + "0")[:2])
    except (ValueError, IndexError):
        return None


def family(client: int | None) -> int:
    """Client -> the version it belongs to (1.51 -> 150, 1.47 -> 145). Unknown -> newest."""
    if client is None:
        return VERSIONS[-1][0]
    best = VERSIONS[0][0]
    for code, _, _ in VERSIONS:
        if client >= code:
            best = code
    return best


def name(client: int | None) -> str:
    if client is None:
        return "?"
    fam = family(client)
    return _BY_CODE.get(fam, f"Ver.{client // 100}.{client % 100:02d}")


def is_refresh(client: int | None) -> bool:
    return client is None or client >= REFRESH


def const_table(client: int | None) -> int:
    """Which shipped constant table a client uses."""
    if client is None:
        return CONST_TABLES[-1]
    pick = CONST_TABLES[0]
    for t in CONST_TABLES:
        if client >= t:
            pick = t
    return pick


def song_version(otoge_name: str | None = None, aqua_ver: int | None = None) -> int | None:
    if aqua_ver:
        return parse_client(aqua_ver)
    if otoge_name:
        return _BY_OTOGE.get(otoge_name.strip())
    return None


def is_new_song(song_ver: int | None, client: int | None) -> bool:
    """New-song frame membership.

    Re:Fresh: everything added since Re:Fresh (Act.2 included).
    bright MEMORY and earlier: only songs of the client's own version.
    """
    if song_ver is None:
        return False
    if is_refresh(client):
        return song_ver >= REFRESH
    return song_ver == family(client)
