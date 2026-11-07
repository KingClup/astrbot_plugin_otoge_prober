"""私服绑定：QQ → {私服: 账号}。舞萌、中二共用（同一个私服号两个游戏都能查）。

- MuNET 这类「按用户名查」的服：只存公开的网站用户名，不是凭据。
- RinNET 这类「要登录」的服：存登录令牌（refreshToken），用本目录 secret.key 的 Fernet 加密；不存密码。
"""
from __future__ import annotations

import json
import os
import threading
import time

from cryptography.fernet import Fernet, InvalidToken


class PrivBindings:
    def __init__(self, root: str):
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, "privsrv_bindings.json")
        key_path = os.path.join(root, "secret.key")
        if not os.path.exists(key_path):
            with open(key_path, "wb") as f:
                f.write(Fernet.generate_key())
        with open(key_path, "rb") as f:
            self._fernet = Fernet(f.read().strip())
        self._lock = threading.Lock()
        try:
            with open(self.path, encoding="utf-8") as f:
                self.d: dict = json.load(f)
        except (OSError, ValueError):
            self.d = {}

    def _save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)

    def _row(self, qq: str, server: str) -> dict:
        return (self.d.get(str(qq)) or {}).get(server) or {}

    def get(self, qq: str, server: str) -> str:
        """网站用户名（显示用）。"""
        return self._row(qq, server).get("username", "")

    def cred(self, qq: str, server: str) -> dict | None:
        """→ {"username", "name", "secret"(已解密), **extra}；没绑定或密钥读不出来时 None。"""
        row = self._row(qq, server)
        if not row.get("username"):
            return None
        out = {k: v for k, v in row.items() if k != "secret_enc"}
        if row.get("secret_enc"):
            try:
                out["secret"] = self._fernet.decrypt(row["secret_enc"].encode()).decode()
            except InvalidToken:
                return None
        return out

    def set(self, qq: str, server: str, username: str, name: str = "", *, secret: str | None = None,
            extra: dict | None = None) -> None:
        row = {"username": username, "name": name, "at": int(time.time()), **(extra or {})}
        if secret:
            row["secret_enc"] = self._fernet.encrypt(secret.encode()).decode()
        self.d.setdefault(str(qq), {})[server] = row
        self._save()

    def remove(self, qq: str, server: str | None = None) -> list[str]:
        mine = self.d.get(str(qq)) or {}
        gone = [s for s in list(mine) if server in (None, s)]
        for s in gone:
            mine.pop(s, None)
        if not mine:
            self.d.pop(str(qq), None)
        if gone:
            self._save()
        return gone

    def bound(self, qq: str) -> list[str]:
        return [s for s, v in (self.d.get(str(qq)) or {}).items() if v.get("username")]
