"""音击官服自动查分：SEGA ID 绑定 → 登录 オンゲキ-NET → 把逐曲成绩同步进传分本（和手动传的是同一份）。

- 凭据：和中二日服一样，Fernet 加密存在数据目录 geki_official/（secret.key 单独一个文件），不进聊天、不进日志。
- 同步：BAS / ADV / EXP / MAS / LUNATIC 五页，每页一个请求；按曲名（+ 等级 / 分类区分同名歌）对上传分本曲库，
  写进去时和手动传一样只升不降。同一个人 5 分钟内只真正拉一次。
- 要账号开着 Standard（オンゲキ-NET 330 円/月）；没开时能登录、但成绩页是锁的 → 明说「没开 Standard」。
⚠ 没实测过（见 ongeki/net.py）。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

try:
    from ..chuni.client import ChuniError, LoginFailed, NetError, NoCards
    from ..chuni.storage import JpBindingStore
    from ..mai.data.fuzzy import fold
    from .net import DIFFS, GekiNetError, OngekiNetClient, PageChanged
except ImportError:  # tests import packages top-level
    from chuni.client import ChuniError, LoginFailed, NetError, NoCards
    from chuni.storage import JpBindingStore
    from mai.data.fuzzy import fold
    from ongeki.net import DIFFS, GekiNetError, OngekiNetClient, PageChanged

SYNC_COOLDOWN = 300


class GekiOfficial:
    def __init__(self, data_dir: str, scorebook, proxy: str | None = None, client_factory=None):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.creds = JpBindingStore(self.dir, "geki_official.json")
        self.book = scorebook
        self.proxy = proxy
        self._factory = client_factory or (lambda sid, pw, aime: OngekiNetClient(sid, pw, aime_idx=aime, proxy=proxy))
        self._meta_path = self.dir / "sync.json"
        try:
            self.meta: dict = json.loads(self._meta_path.read_text("utf-8"))
        except (OSError, ValueError):
            self.meta = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ---------- 绑定 ----------
    def bound(self, uid: str) -> bool:
        return self.creds.creds(str(uid)) is not None

    def count(self) -> int:
        return len(self.creds.items())

    def last(self, uid: str) -> dict:
        return dict(self.meta.get(str(uid)) or {})

    def _save_meta(self) -> None:
        tmp = self._meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.meta, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self._meta_path)

    async def bind(self, uid: str, name: str, sega_id: str, password: str, aime_idx: int = 0) -> str:
        """先登录验证（账号密码对不对、有没有卡），通过才存；顺手同步一次。"""
        try:
            async with self._factory(sega_id, password, aime_idx) as c:
                await c.login()
                std, prem = await c.course()
        except LoginFailed as e:
            return f"音击官服绑定失败：{e}"
        except NoCards:
            return "音击官服绑定失败：这个 SEGA ID 下面没有绑定 Aime 卡（先在机台上用卡玩过一次）"
        except (ChuniError, GekiNetError) as e:
            return f"音击官服绑定失败：{e}"
        self.creds.set_creds(str(uid), sega_id, password, name or None, aime_idx)
        head = "音击官服绑定成功（SEGA ID）。"
        if not std and not prem:
            return head + ("\n⚠ 这个账号没开 オンゲキ-NET Standard（330 円/月），官网不给看逐曲成绩，所以现在同步不了；"
                           "开了以后发「/geki 同步」。没开之前照样可以在传分网站手动传。")
        r = await self.sync(str(uid), force=True)
        return head + "\n" + r

    def unbind(self, uid: str) -> bool:
        self.meta.pop(str(uid), None)
        self._save_meta()
        return self.creds.remove(str(uid))

    # ---------- 同步 ----------
    async def sync(self, uid: str, force: bool = False) -> str:
        uid = str(uid)
        cr = self.creds.creds(uid)
        if cr is None:
            return "还没绑音击官服：发「/网页绑定」→ 音击 → 官服 → SEGA ID + 密码"
        lock = self._locks.setdefault(uid, asyncio.Lock())
        async with lock:
            m = self.meta.get(uid) or {}
            if not force and time.time() - float(m.get("t") or 0) < SYNC_COOLDOWN:
                return f"刚同步过（{int((time.time() - m['t']) / 60)} 分钟前），{SYNC_COOLDOWN // 60} 分钟内不重复拉"
            try:
                rows, std = await self._fetch(cr)
            except LoginFailed as e:
                return f"音击官服同步失败：{e}（改过密码的话重新绑一次）"
            except NoCards:
                return "音击官服同步失败：这个 SEGA ID 下面没有 Aime 卡"
            except PageChanged as e:
                return f"音击官服同步失败：{e}"
            except (NetError, ChuniError, GekiNetError) as e:
                return f"音击官服同步失败：{e}"
            if not std:
                self.meta[uid] = {"t": time.time(), "n": 0, "std": False}
                self._save_meta()
                return ("音击官服：这个账号没开 オンゲキ-NET Standard（330 円/月），官网不给看逐曲成绩，同步不了。"
                        "开了以后再发「/geki 同步」；之前可以在传分网站手动传。")
            res = self.apply(uid, rows)
            self.meta[uid] = {"t": time.time(), "n": res["saved"], "found": res["found"], "std": True,
                              "missing": res["missing"][:20]}
            self._save_meta()
        word = f"音击官服同步完成：官网上 {res['found']} 张打过的谱面，更新了 {res['changed']} 张"
        if res["missing"]:
            word += f"\n曲库里没对上的 {len(res['missing'])} 张（多半是新歌，曲库每天更新）：" + \
                    "、".join(res["missing"][:5]) + ("…" if len(res["missing"]) > 5 else "")
        return word

    async def _fetch(self, cr: dict):
        async with self._factory(cr["sega_id"], cr["password"], int(cr.get("aime_idx") or 0)) as c:
            await c.login()
            std, prem = await c.course()
            if not std and not prem:
                return [], False
            rows = []
            for code in DIFFS:
                rows += await c.scores(code)
            return rows, True

    def apply(self, uid: str, rows) -> dict:
        """官网成绩 → 传分本（只升不降）。同名歌按等级、分类挑。"""
        cat = self.book.cat("geki")
        by_title: dict[str, list] = {}
        for s in cat.songs.values():
            by_title.setdefault(fold(s.title), []).append(s)
        found = changed = saved = 0
        missing: list[str] = []
        for r in rows:
            found += 1
            cands = [s for s in by_title.get(fold(r.title), []) if r.diff in s.charts]
            if len(cands) > 1:
                same_lv = [s for s in cands if s.charts[r.diff].level == r.level]
                cands = same_lv or cands
            if len(cands) > 1 and r.genre:
                same_g = [s for s in cands if fold(s.genre) == fold(r.genre)]
                cands = same_g or cands
            if not cands:
                missing.append(f"{r.title} {r.diff}")
                continue
            ch = cands[0].charts[r.diff]
            try:
                res = self.book.store.put_geki(uid, ch.key, r.technical, r.lamp, r.fb, r.platinum,
                                               r.stars if r.platinum is None else None)
            except Exception:  # noqa: BLE001 —— 一张出错不影响别的
                missing.append(f"{r.title} {r.diff}")
                continue
            saved += 1
            changed += 1 if res.get("changed") else 0
        return {"found": found, "saved": saved, "changed": changed, "missing": missing}
