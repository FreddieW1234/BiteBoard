"""Individual staff logins: username, hashed password and access level.

Access levels:
  staff - everyday use of BiteBoard
  admin - also the Users page (add / change / remove staff and admins)
  dev   - everything: Users (including dev accounts) and the dev-only pages
          (Files, Artwork Updater)

Kept on the office server (named snapshot ``staff_users``) so accounts survive
redeploys. Usernames in config.STAFF_DEV_USERNAMES are always dev, so the
owner can never be locked out of dev access by someone else.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

log = logging.getLogger(__name__)

SNAPSHOT = "staff_users"
ROLES = ("staff", "admin", "dev")
MANAGER_ROLES = ("admin", "dev")  # can open the Users page
MIN_PASSWORD = 1  # no length rule - just not blank
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@!-]{1,39}$")

_LOCK = threading.Lock()
_CACHE: dict = {"at": 0.0, "data": None}
_CACHE_TTL = 30  # seconds; writes refresh it straight away


class UserError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fixed_devs() -> frozenset:
    from config import STAFF_DEV_USERNAMES  # type: ignore
    return frozenset(n.strip().lower() for n in STAFF_DEV_USERNAMES)


def _role_of(key: str, user: dict) -> str:
    if key in _fixed_devs():
        return "dev"
    role = user.get("role") or "staff"
    return role if role in ROLES else "staff"


def _load(force: bool = False) -> dict:
    """{"users": {lower_name: {...}}, "last_active": {...}} (cached)."""
    now = time.time()
    if not force and _CACHE["data"] is not None and now - _CACHE["at"] < _CACHE_TTL:
        return _CACHE["data"]
    from scripts.office_api import get_snapshot  # type: ignore
    try:
        doc = get_snapshot(SNAPSHOT) or {}
        data = doc.get("payload") or {}
    except Exception as exc:
        log.warning("Staff users unavailable: %s", exc)
        if _CACHE["data"] is not None:
            return _CACHE["data"]  # keep the last good copy if the office server blips
        return {"users": {}, "_unavailable": True}  # not cached
    data.setdefault("users", {})
    data.pop("disabled_builtins", None)  # left over from the old built-in logins
    _CACHE.update(at=now, data=data)
    return data


def _load_for_write() -> dict:
    """A fresh, separate copy to change - a refused change never touches the cache."""
    import copy
    data = _load(force=True)
    if data.get("_unavailable"):
        raise UserError("Can't reach the office server right now - try again in a minute")
    return copy.deepcopy(data)


def _save(data: dict, by: str) -> None:
    from scripts.office_api import put_snapshot  # type: ignore
    put_snapshot(SNAPSHOT, data, updated_by=by or "")
    _CACHE.update(at=time.time(), data=data)


# ---------------------------------------------------------------- login / lookup

def authenticate(username: str, password: str) -> str | None:
    """The account's username on success, else None."""
    u = (username or "").strip()
    p = password or ""
    if not u or not p:
        return None
    user = _load()["users"].get(u.lower())
    if user and user.get("active", True) and check_password_hash(user.get("password_hash") or "", p):
        mark_active(u.lower())
        return user["username"]
    return None


def account(username: str | None) -> dict | None:
    """{"username", "role"} for an active account, else None."""
    u = (username or "").strip()
    if not u:
        return None
    data = _load()
    key = u.lower()
    user = data["users"].get(key)
    if user:
        if not user.get("active", True):
            return None
        return {"username": user["username"], "role": _role_of(key, user)}
    if data.get("_unavailable"):
        # Office server unreachable: keep people signed in rather than throwing
        # everyone out; Users and dev pages wait until it's back.
        return {"username": u, "role": "staff"}
    return None


# ---------------------------------------------------------------- last active
# Any page opened or action taken counts. Kept in memory straight away and
# saved to the office server at most every ACTIVE_SAVE_EVERY seconds a person.
ACTIVE_SAVE_EVERY = 120
_ACTIVE: dict[str, str] = {}       # lower name -> ISO time (latest seen)
_ACTIVE_SAVED: dict[str, float] = {}


def mark_active(username: str | None) -> None:
    key = (username or "").strip().lower()
    if not key:
        return
    _ACTIVE[key] = _now()
    if time.time() - _ACTIVE_SAVED.get(key, 0) < ACTIVE_SAVE_EVERY:
        return
    _ACTIVE_SAVED[key] = time.time()
    threading.Thread(target=_save_active, args=(key,), daemon=True).start()


def _save_active(key: str) -> None:
    try:
        with _LOCK:
            data = _load_for_write()
            data.setdefault("last_active", {})[key] = _ACTIVE.get(key) or _now()
            _save(data, "activity")
    except Exception as exc:
        log.warning("Could not record last active for %s: %s", key, exc)


def _last_active(key: str, data: dict) -> str | None:
    seen = [t for t in (_ACTIVE.get(key), (data.get("last_active") or {}).get(key),
                        (data["users"].get(key) or {}).get("last_login")) if t]
    return max(seen) if seen else None


# ---------------------------------------------------------------- managing users

def _actor_role(by: str, data: dict) -> str:
    key = (by or "").strip().lower()
    user = data["users"].get(key)
    return _role_of(key, user) if user else "staff"


def list_users() -> list[dict]:
    data = _load(force=True)
    out = []
    for key, user in sorted(data["users"].items(), key=lambda kv: kv[1]["username"].lower()):
        out.append({
            "username": user["username"], "role": _role_of(key, user),
            "role_fixed": key in _fixed_devs(),
            "active": user.get("active", True), "created_at": user.get("created_at"),
            "created_by": user.get("created_by"),
            "last_active": _last_active(key, data),
        })
    return out


def _managers_left(data: dict) -> bool:
    return any(v.get("active", True) and _role_of(k, v) in MANAGER_ROLES for k, v in data["users"].items())


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise UserError("Enter a password")


def _check_role(role: str, actor_role: str) -> None:
    if role not in ROLES:
        raise UserError("Access must be Staff, Admin or Dev")
    if role == "dev" and actor_role != "dev":
        raise UserError("Only a dev can give dev access")


def create_user(username: str, password: str, role: str, *, by: str) -> dict:
    u = (username or "").strip()
    if not _USERNAME_RE.match(u):
        raise UserError("Username must be 2-40 characters: letters, numbers, spaces and . _ @ ! -")
    _check_password(password)
    with _LOCK:
        data = _load_for_write()
        _check_role(role, _actor_role(by, data))
        if u.lower() in data["users"]:
            raise UserError("That username is already taken")
        data["users"][u.lower()] = {
            "username": u, "role": role, "active": True,
            "password_hash": generate_password_hash(password),
            "created_at": _now(), "created_by": by, "updated_at": _now(),
        }
        _save(data, by)
    return {"username": u, "role": role}


def update_user(username: str, *, by: str, role: str | None = None, active: bool | None = None,
                password: str | None = None) -> dict:
    key = (username or "").strip().lower()
    me = (by or "").strip().lower()
    with _LOCK:
        data = _load_for_write()
        user = data["users"].get(key)
        if not user:
            raise UserError("No such user")
        actor = _actor_role(by, data)
        if _role_of(key, user) == "dev" and actor != "dev":
            raise UserError("Only a dev can change a dev account")
        if role is not None:
            _check_role(role, actor)
            if key in _fixed_devs() and role != "dev":
                raise UserError(f"{user['username']} is always a dev")
            if key == me and role != _role_of(key, user):
                raise UserError("You can't change your own access")
            user["role"] = role
        if active is not None:
            if key == me and not active:
                raise UserError("You can't disable your own login")
            user["active"] = bool(active)
        if password is not None:
            _check_password(password)
            user["password_hash"] = generate_password_hash(password)
        if not _managers_left(data):
            raise UserError("There must always be at least one admin or dev")
        user["updated_at"] = _now()
        _save(data, by)
        return {"username": user["username"], "role": _role_of(key, user), "active": user.get("active", True)}


def delete_user(username: str, *, by: str) -> None:
    key = (username or "").strip().lower()
    with _LOCK:
        data = _load_for_write()
        user = data["users"].get(key)
        if not user:
            raise UserError("No such user")
        if key == (by or "").strip().lower():
            raise UserError("You can't delete your own login")
        if key in _fixed_devs():
            raise UserError(f"{user['username']} can't be deleted")
        if _role_of(key, user) == "dev" and _actor_role(by, data) != "dev":
            raise UserError("Only a dev can delete a dev account")
        del data["users"][key]
        if not _managers_left(data):
            raise UserError("There must always be at least one admin or dev")
        _save(data, by)
