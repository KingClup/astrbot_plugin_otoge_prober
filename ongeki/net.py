"""オンゲキ-NET（官服，ongeki-net.com）：SEGA ID + 密码登录，读逐曲成绩。

⚠ 没有实测过（写的时候手上没有开着 Standard 的账号）。依据：
  - 登录：和中二日服 / 舞萌日服同一套 SEGA「-mobile」模板（插件里中二日服已经在用）：
      GET  /ongeki-mobile/                 登录页（带 token）
      POST /ongeki-mobile/submit/          segaId / password / save_cookie / token
      GET  /ongeki-mobile/aimeList/submit/?idx=N   选 Aime
      GET  /ongeki-mobile/home/
  - 成绩页结构参考了公开的 オンゲキ総合スコアツール 书签脚本对页面的描述（只参考页面结构，没有用它的代码）：
      GET /ongeki-mobile/record/musicGenre/search/?genre=99&diff=0|1|2|3|10   （10 = LUNATIC）
      .container3 里依次是分类标题 div.p_5.f_20 和每首歌 div.basic_btn：
        .music_label 曲名、.score_level 等级（13+）、.score_value ×3 = OVER DAMAGE% / BATTLE SCORE / TECHNICAL SCORE、
        灯是图片 music_icon_ab / abplus / fc / fb.png、白金分 .platinum_high_score_text_block（"1234/5678"）、
        星 .platinum_high_score_star_block .f_b、input[name=idx]。
      GET /ongeki-mobile/courseDetail/   .back_course_standard / .back_course_premium 里 span = 「利用中」就是开着。
  - 没开 Standard 时成绩页是锁的（能登录、看不到分）。
页面改版的话这里要跟着改；解析不到东西时报「页面格式变了」，不会写进奇怪的数据。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from selectolax.lexbor import LexborHTMLParser

try:
    from ..chuni.client import ChuniError, ChuniJpClient, LoginFailed, NetError, NoCards
except ImportError:  # tests import packages top-level
    from chuni.client import ChuniError, ChuniJpClient, LoginFailed, NetError, NoCards

BASE = "https://ongeki-net.com"
PREFIX = "/ongeki-mobile/"
DIFFS = {0: "BAS", 1: "ADV", 2: "EXP", 3: "MAS", 10: "LUN"}


class GekiNetError(ChuniError):
    pass


class PageChanged(GekiNetError):
    def __init__(self, what: str = "") -> None:
        super().__init__("オンゲキ-NET 页面格式变了" + (f"（{what}）" if what else "") + "，等插件更新")


@dataclass
class GekiNetScore:
    title: str
    diff: str               # BAS / ADV / EXP / MAS / LUN
    level: str              # 「13+」这种
    genre: str
    technical: int
    battle: int
    lamp: str               # "" / FC / AB
    fb: bool
    platinum: int | None
    stars: int | None
    idx: str = ""


def _soup(content) -> LexborHTMLParser:
    return LexborHTMLParser(content, is_fragment=False)


def _int(s: str) -> int:
    s = re.sub(r"[^\d]", "", s or "")
    return int(s) if s else 0


def _classes(node) -> set[str]:
    return set(str(node.attributes.get("class") or "").split())


def parse_error(html: str) -> tuple[int, str] | None:
    """错误页：找「ERROR CODE：100001」这种。"""
    m = re.search(r"(?:ERROR\s*CODE|エラーコード)\s*[:：]\s*(\d+)", html)
    if not m:
        return None
    soup = _soup(html)
    desc = ""
    for n in soup.css(".font_small, .t_c, p"):
        t = n.text(strip=True)
        if t and "ERROR" not in t.upper() and len(t) < 200:
            desc = t
            break
    return int(m.group(1)), desc


def parse_course(html: str) -> tuple[bool, bool]:
    """courseDetail → (Standard 开着, Premium 开着)。"""
    soup = _soup(html)

    def on(sel: str) -> bool:
        node = soup.css_first(sel)
        return bool(node is not None and any("利用中" in s.text() for s in node.css("span")))
    return on(".back_course_standard"), on(".back_course_premium")


def parse_scores(html: str, diff_code: int) -> list[GekiNetScore]:
    """某个难度的成绩一览 → 打过的谱面（技术分 0 的跳过）。"""
    soup = _soup(html)
    root = soup.css_first(".container3")
    if root is None:
        raise PageChanged("成绩页没有 .container3")
    diff = DIFFS[diff_code]
    out: list[GekiNetScore] = []
    genre = ""
    for node in root.css("div"):
        cls = _classes(node)
        if {"p_5", "f_20"} <= cls:
            genre = node.text(strip=True)
            continue
        if "basic_btn" not in cls:
            continue
        title_n = node.css_first(".music_label")
        if title_n is None:
            continue
        title = title_n.text(strip=True).replace(" ", " ")
        vals = [n.text(strip=True) for n in node.css(".score_value")]
        tech = _int(vals[2]) if len(vals) >= 3 else (_int(vals[-1]) if vals else 0)
        if not tech:
            continue
        srcs = " ".join(str(i.attributes.get("src") or "") for i in node.css("img"))
        lamp = "AB" if ("music_icon_ab.png" in srcs or "music_icon_abplus.png" in srcs) else \
               ("FC" if "music_icon_fc.png" in srcs else "")
        plat_n = node.css_first(".platinum_high_score_text_block")
        plat = _int(plat_n.text().split("/")[0]) if plat_n is not None else None
        star_n = node.css_first(".platinum_high_score_star_block .f_b")
        stars = _int(star_n.text()) if star_n is not None else None
        lv_n = node.css_first(".score_level")
        idx_n = node.css_first("input[name=idx]")
        out.append(GekiNetScore(
            title=title, diff=diff, level=lv_n.text(strip=True) if lv_n is not None else "", genre=genre,
            technical=tech, battle=_int(vals[1]) if len(vals) >= 2 else 0, lamp=lamp,
            fb="music_icon_fb.png" in srcs, platinum=plat or None, stars=stars,
            idx=str(idx_n.attributes.get("value") or "") if idx_n is not None else ""))
    return out


class OngekiNetClient(ChuniJpClient):
    """沿用中二日服客户端的会话 / 重登逻辑，只换站点、路径和报错文字。"""
    BASE = BASE
    HOST = "ongeki-net.com"
    PREFIX = PREFIX
    REGION = "geki"

    def _path(self, path: str) -> str:
        return path

    async def _get(self, path: str) -> httpx.Response:
        try:
            resp = await self._http.get(path)
        except httpx.TimeoutException as e:
            raise GekiNetError("连接 オンゲキ-NET 超时") from e
        except httpx.HTTPError as e:
            raise GekiNetError(f"连接 オンゲキ-NET 失败：{type(e).__name__}") from e
        self._check_common(resp)
        return resp

    def _raise_error_page(self, resp: httpx.Response, default: str) -> None:
        if resp.url.path.startswith(self.PREFIX + "error"):
            err = parse_error(resp.text)
            code, desc = err or (0, default)
            if code == 100101 or (not err and "login" in default):
                raise LoginFailed("オンゲキ-NET 登录失败：SEGA ID 或密码不对")
            raise NetError(code, desc or "オンゲキ-NET 出错（可能在维护）")

    async def login(self) -> None:
        self._reset_cookies()
        if not self._sega_id or not self._password:
            raise LoginFailed("音击官服要用 SEGA ID + 密码绑定")
        top = await self._get(self.PREFIX)
        self._raise_error_page(top, "打开登录页时出错")
        inp = _soup(top.content).css_first("input[name=token]")
        token = str(inp.attributes.get("value") or "") if inp is not None else ""
        if not token:
            raise PageChanged("登录页没找到 token")
        try:
            resp = await self._http.post(self.PREFIX + "submit/", data={
                "segaId": self._sega_id, "password": self._password, "save_cookie": "on", "token": token})
        except httpx.HTTPError as e:
            raise GekiNetError(f"连接 オンゲキ-NET 失败：{type(e).__name__}") from e
        self._check_common(resp)
        self._raise_error_page(resp, "login")
        if self._looks_like_auth_redirect(resp):
            raise LoginFailed("オンゲキ-NET 登录失败：SEGA ID 或密码不对")
        sel = await self._get(f"{self.PREFIX}aimeList/submit/?idx={self._aime_idx}")
        if sel.url.path.startswith(self.PREFIX + "error"):
            err = parse_error(sel.text)
            if err and err[0] in (100106,):
                raise NetError(*err)
            raise NoCards()
        home = await self._get(self.PREFIX + "home/")
        self._raise_error_page(home, "进入首页时出错")
        if self._looks_like_auth_redirect(home):
            raise LoginFailed("オンゲキ-NET 登录失败：登录后没能进入首页")
        self._logged_in = True

    async def _html(self, path: str) -> str:
        soup = await self.request("GET", path)
        return soup.html or ""

    async def course(self) -> tuple[bool, bool]:
        return parse_course(await self._html(self.PREFIX + "courseDetail/"))

    async def scores(self, diff_code: int) -> list[GekiNetScore]:
        return parse_scores(await self._html(f"{self.PREFIX}record/musicGenre/search/?genre=99&diff={diff_code}"),
                            diff_code)
