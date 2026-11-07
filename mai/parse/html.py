"""Thin selectolax wrapper + page-level checks (error / maintenance / logged out)."""
from __future__ import annotations

import re

try:  # lexbor backend is faster and handles broken markup better
    from selectolax.lexbor import LexborHTMLParser as _Parser
except Exception:  # pragma: no cover - older selectolax
    from selectolax.parser import HTMLParser as _Parser  # type: ignore


def parse(html: str):
    return _Parser(html or "")


def text(node, strip: bool = True) -> str:
    if node is None:
        return ""
    return node.text(strip=strip) or ""


def direct_text(node) -> str:
    """Text of the node's own text children only (ignores nested elements)."""
    if node is None:
        return ""
    parts = []
    child = node.child
    while child is not None:
        if child.tag == "-text":
            parts.append(child.text_content or child.text() or "")
        child = child.next
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def attr(node, name: str) -> str:
    if node is None:
        return ""
    return (node.attributes.get(name) or "").strip()


class NetPageError(Exception):
    """NET showed its error page (code is e.g. '200001' for the rate-limit lock)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"NET error {code}: {message}".strip())
        self.code = code
        self.message = message


class NetMaintenance(Exception):
    pass


class NetLoggedOut(Exception):
    pass


MAINTENANCE_MARKERS = ("定期メンテナンス中です", "Sorry, servers are under maintenance", "メンテナンス中")
LOGIN_MARKERS = ('name="segaId"', "common_auth/login", 'name="sid"', "aimeList")


def check_page(html: str) -> None:
    """Raise if the page is an error / maintenance / login page instead of real content."""
    if any(m in (html or "") for m in MAINTENANCE_MARKERS):
        raise NetMaintenance()
    if "container_red" in (html or ""):
        tree = parse(html)
        box = tree.css_first(".container_red")
        blocks = box.css(".p_5") if box else []
        code_txt = text(blocks[0]) if blocks else text(box)
        m = re.search(r"(\d{5,})", code_txt)
        msg = text(blocks[1]) if len(blocks) > 1 else ""
        raise NetPageError(m.group(1) if m else "unknown", msg)
    if any(m in (html or "") for m in LOGIN_MARKERS) and "name_block" not in (html or "") \
            and "music_name_block" not in (html or "") and "playlog" not in (html or ""):
        raise NetLoggedOut()
