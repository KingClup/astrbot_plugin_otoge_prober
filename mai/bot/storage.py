"""Per-QQ user store. Credentials are Fernet-encrypted; snapshots are plain JSON (no secrets)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ..models import Profile, Score

CONSENT_VERSION = 1


def _safe(uid: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]", "_", str(uid))


class UserStore:
    def __init__(self, root: str):
        self.root = root
        self.users_dir = os.path.join(root, "users")
        self.snap_dir = os.path.join(root, "snapshots")
        os.makedirs(self.users_dir, exist_ok=True)
        os.makedirs(self.snap_dir, exist_ok=True)
        key_path = os.path.join(root, "secret.key")
        if not os.path.exists(key_path):
            with open(key_path, "wb") as f:
                f.write(Fernet.generate_key())
        with open(key_path, "rb") as f:
            self._fernet = Fernet(f.read().strip())
        self._lock = threading.Lock()

    # ---------- raw ----------
    def _path(self, uid: str) -> str:
        return os.path.join(self.users_dir, f"{_safe(uid)}.json")

    def load(self, uid: str) -> dict[str, Any]:
        p = self._path(uid)
        if not os.path.exists(p):
            return {"uid": str(uid), "regions": {}, "default_region": "", "public": False, "consent": None}
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def save(self, uid: str, data: dict[str, Any]) -> None:
        with self._lock:
            p = self._path(uid)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)

    def all_uids(self) -> list[str]:
        return [n[:-5] for n in os.listdir(self.users_dir) if n.endswith(".json")]

    # ---------- credentials ----------
    def set_creds(self, uid: str, region: str, creds: dict[str, Any]) -> None:
        d = self.load(uid)
        token = self._fernet.encrypt(json.dumps(creds).encode()).decode()
        d["regions"].setdefault(region, {})["creds"] = token
        d["regions"][region]["bound_at"] = int(time.time())
        if not d.get("default_region"):
            d["default_region"] = region
        self.save(uid, d)

    def get_creds(self, uid: str, region: str) -> dict[str, Any] | None:
        token = (self.load(uid).get("regions", {}).get(region) or {}).get("creds")
        if not token:
            return None
        try:
            return json.loads(self._fernet.decrypt(token.encode()))
        except InvalidToken:
            return None

    def unbind(self, uid: str, region: str | None = None) -> list[str]:
        d = self.load(uid)
        regions = [region] if region else list(d.get("regions", {}))
        removed = []
        for r in regions:
            if d.get("regions", {}).pop(r, None) is not None:
                removed.append(r)
            sp = self._snap_path(uid, r)
            if os.path.exists(sp):
                os.remove(sp)
        if d.get("default_region") in removed:
            d["default_region"] = next(iter(d.get("regions", {})), "")
        self.save(uid, d)
        return removed

    def bound_regions(self, uid: str) -> list[str]:
        return [r for r, v in self.load(uid).get("regions", {}).items() if v.get("creds")]

    def default_region(self, uid: str) -> str:
        d = self.load(uid)
        r = d.get("default_region") or ""
        bound = self.bound_regions(uid)
        if r in bound:
            return r
        return bound[0] if bound else ""

    def set_default_region(self, uid: str, region: str) -> None:
        d = self.load(uid)
        d["default_region"] = region
        self.save(uid, d)

    # ---------- consent / privacy ----------
    def has_consent(self, uid: str) -> bool:
        c = self.load(uid).get("consent") or {}
        return c.get("version") == CONSENT_VERSION

    def give_consent(self, uid: str) -> None:
        d = self.load(uid)
        d["consent"] = {"version": CONSENT_VERSION, "at": int(time.time())}
        self.save(uid, d)

    def set_public(self, uid: str, public: bool) -> None:
        d = self.load(uid)
        d["public"] = bool(public)
        self.save(uid, d)

    def is_public(self, uid: str) -> bool:
        return bool(self.load(uid).get("public"))

    # ---------- snapshots ----------
    def _snap_path(self, uid: str, region: str) -> str:
        return os.path.join(self.snap_dir, f"{_safe(uid)}_{region}.json")

    def save_snapshot(self, uid: str, region: str, profile: Profile | None, scores: list[Score],
                      extra: dict[str, Any] | None = None) -> None:
        data = {"at": int(time.time()), "region": region,
                "profile": profile.to_dict() if profile else None,
                "scores": [s.to_dict() for s in scores], **(extra or {})}
        p = self._snap_path(uid, region)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)

    def load_snapshot(self, uid: str, region: str) -> tuple[int, Profile | None, list[Score], dict] | None:
        p = self._snap_path(uid, region)
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        prof = Profile.from_dict(d["profile"]) if d.get("profile") else None
        return d.get("at", 0), prof, [Score.from_dict(x) for x in d.get("scores", [])], d
