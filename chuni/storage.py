"""绑定数据：QQ 号 → clal。

- 文件放在 AstrBot 的 data/plugin_data/astrbot_plugin_otoge_prober/chu/ 下，和陪伴插件、记忆完全分开。
- clal 用 Fernet 加密后存储，密钥单独放在 secret.key。这样能防止"误把绑定文件发给别人 / 被同步走"之类的意外，
  但防不住能读取整台电脑文件的人。
- 绝不把 clal 写进日志。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class BindingStore:
    def __init__(self, data_dir: Path, db_name: str = "bindings.json"):
        self.dir = data_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._key_path = self.dir / "secret.key"
        self._db_path = self.dir / db_name
        self._fernet = Fernet(self._load_key())
        self._data: dict[str, dict] = self._read()

    def _load_key(self) -> bytes:
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        try:
            os.chmod(self._key_path, 0o600)
        except OSError:
            pass
        return key

    def _read(self) -> dict[str, dict]:
        if not self._db_path.exists():
            return {}
        try:
            return json.loads(self._db_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self) -> None:
        tmp = self._db_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self._db_path)

    def set(self, qq: str, clal: str, name: str | None = None) -> None:
        self._data[str(qq)] = {
            "clal": self._fernet.encrypt(clal.encode()).decode(),
            "name": name,
            "bound_at": int(time.time()),
        }
        self._write()

    def get(self, qq: str) -> str | None:
        rec = self._data.get(str(qq))
        if not rec:
            return None
        try:
            return self._fernet.decrypt(rec["clal"].encode()).decode()
        except (InvalidToken, KeyError):
            return None

    def name(self, qq: str) -> str | None:
        rec = self._data.get(str(qq))
        return rec.get("name") if rec else None

    def remove(self, qq: str) -> bool:
        existed = self._data.pop(str(qq), None) is not None
        if existed:
            self._write()
        return existed

    def items(self) -> list[dict]:
        """列出绑定（不含 clal）。"""
        return [
            {"qq": qq, "name": rec.get("name"), "bound_at": rec.get("bound_at")}
            for qq, rec in sorted(self._data.items())
        ]

    def __contains__(self, qq: object) -> bool:
        return str(qq) in self._data


class JpBindingStore(BindingStore):
    """日服：QQ → {sega_id, password}（整段 JSON 用同一把 Fernet 密钥加密，存在 jp_bindings.json）。
    国际服用 SEGA ID 绑定时也用这个类，存在 intl_creds.json（clal 照样存在 bindings.json）。"""

    def __init__(self, data_dir: Path, db_name: str = "jp_bindings.json"):
        super().__init__(data_dir, db_name)

    def set_creds(self, qq: str, sega_id: str, password: str, name: str | None = None, aime_idx: int = 0) -> None:
        self.set(qq, json.dumps({"sega_id": sega_id, "password": password, "aime_idx": int(aime_idx)}), name)

    def creds(self, qq: str) -> dict | None:
        raw = self.get(qq)
        if not raw:
            return None
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return d if d.get("sega_id") and d.get("password") else None
