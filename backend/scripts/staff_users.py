"""Individual staff logins: username, hashed password, role (staff / admin).

Kept on the office server (named snapshot ``staff_users``) so accounts survive
redeploys. The two logins in config.STAFF_ACCOUNTS ("built-in") still work and
count as admins, so there is always a way in to set people up; admins can
switch a built-in login off from the Users page (``dev`` stays on).
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
ROLES = ("staff", "admin")
MIN_PASSWORD = 1  # no length rule - just not blank
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@!-]{1,39}$")
ALWAYS_ON_BUILTINS = frozenset({"dev"})

_LOCK = threading.Lock()
_CACHE: dict = {"at": 0.0, "data": None}
_CACHE_TTL = 30  # seconds; writes refresh it straight away


class UserError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _builtins() -> dict:
    from config import STAFF_ACCOUNTS  # type: ignore
    return dict(STAFF_ACCOUNTS)


def _load(force: bool = False) -> dict:
    """{"users": {lower_name: {...}}, "disabled_builtins": [...]} (cached)."""
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
        return {"users": {}, "disabled_builtins": [], "_unavailable": True}  # not cached
    data.setdefault("users", {})
    data.setdefault("disabled_builtins", [])
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


def _builtin_enabled(name: str, data: dict) -> bool:
    return name in ALWAYS_ON_BUILTINS or name not in (data.get("disabled_builtins") or [])


# ---------------------------------------------------------------- login / lookup

def authenticate(username: str, password: str) -> str | None:
    """The account's username on success, else None."""
    u = (username or "").strip()
    p = password or ""
    if not u or not p:
        return None
    data = _load()
    user = data["users"].get(u.lower())
    if user:
        if user.get("active", True) and check_password_hash(user.get("password_hash") or "", p):
            _touch_login(u.lower())
            return user["username"]
        return None
    builtins = _builtins()
    if u in builtins and builtins[u] == p and _builtin_enabled(u, data):
        return u
    return None


def _touch_login(key: str) -> None:
    try:
        with _LOCK:
            data = _load_for_write()
            if key in data["users"]:
                data["users"][key]["last_login"] = _now()
                _save(data, data["users"][key]["username"])
    except Exception as exc:
        log.warning("Could not record last login: %s", exc)


def account(username: str | None) -> dict | None:
    """{"username", "role", "builtin"} for an active account, else None."""
    u = (username or "").strip()
    if not u:
        return None
    data = _load()
    user = data["users"].get(u.lower())
    if user:
        if not user.get("active", True):
            return None
        return {"username": user["username"], "role": user.get("role") or "staff", "builtin": False}
    if data.get("_unavailable") and u not in _builtins():
        # Office server unreachable: keep them signed in as staff rather than
        # throwing everyone out; admin pages wait until it's back.
        return {"username": u, "role": "staff", "builtin": False}
    if u in _builtins() and _builtin_enabled(u, data):
        return {"username": u, "role": "admin", "builtin": True}
    return None


# ---------------------------------------------------------------- admin actions

def list_users() -> list[dict]:
    data = _load(force=True)
    out = []
    for name in _builtins():
        out.append({
            "username": name, "role": "admin", "builtin": True,
            "active": _builtin_enabled(name, data),
            "can_disable": name not in ALWAYS_ON_BUILTINS,
        })
    for user in sorted(data["users"].values(), key=lambda x: x["username"].lower()):
        out.append({
            "username": user["username"], "role": user.get("role") or "staff", "builtin": False,
            "active": user.get("active", True), "created_at": user.get("created_at"),
            "created_by": user.get("created_by"), "last_login": user.get("last_login"),
        })
    return out


def _active_admins(data: dict) -> set[str]:
    admins = {n.lower() for n in _builtins() if _builtin_enabled(n, data)}
    admins |= {k for k, v in data["users"].items() if v.get("active", True) and v.get("role") == "admin"}
    return admins


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise UserError("Enter a password")


def create_user(username: str, password: str, role: str, *, by: str) -> dict:
    u = (username or "").strip()
    if not _USERNAME_RE.match(u):
        raise UserError("Username must be 2-40 characters: letters, numbers, spaces and . _ @ ! -")
    if role not in ROLES:
        raise UserError("Role must be staff or admin")
    _check_password(password)
    with _LOCK:
        data = _load_for_write()
        if u.lower() in data["users"] or u.lower() in {n.lower() for n in _builtins()}:
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
        builtin = next((n for n in _builtins() if n.lower() == key), None)
        if builtin:
            if role is not None or password is not None:
                raise UserError("Built-in logins are set in config; you can only switch them on or off")
            if active is not None:
                if builtin in ALWAYS_ON_BUILTINS:
                    raise UserError(f"The {builtin} login can't be switched off")
                if not active and key == me:
                    raise UserError("You can't switch off the login you're using")
                disabled = set(data.get("disabled_builtins") or [])
                (disabled.discard if active else disabled.add)(builtin)
                data["disabled_builtins"] = sorted(disabled)
                if not _active_admins(data):
                    raise UserError("There must always be at least one admin")
                _save(data, by)
            return {"username": builtin}
        user = data["users"].get(key)
        if not user:
            raise UserError("No such user")
        if role is not None:
            if role not in ROLES:
                raise UserError("Role must be staff or admin")
            if key == me and role != "admin":
                raise UserError("You can't remove your own admin access")
            user["role"] = role
        if active is not None:
            if key == me and not active:
                raise UserError("You can't disable your own login")
            user["active"] = bool(active)
        if password is not None:
            _check_password(password)
            user["password_hash"] = generate_password_hash(password)
        if not _active_admins(data):
            raise UserError("There must always be at least one admin")
        user["updated_at"] = _now()
        _save(data, by)
        return {"username": user["username"], "role": user["role"], "active": user["active"]}


def delete_user(username: str, *, by: str) -> None:
    key = (username or "").strip().lower()
    with _LOCK:
        data = _load_for_write()
        if any(n.lower() == key for n in _builtins()):
            raise UserError("Built-in logins can't be deleted - switch them off instead")
        if key == (by or "").strip().lower():
            raise UserError("You can't delete your own login")
        if key not in data["users"]:
            raise UserError("No such user")
        del data["users"][key]
        if not _active_admins(data):
            raise UserError("There must always be at least one admin")
        _save(data, by)
