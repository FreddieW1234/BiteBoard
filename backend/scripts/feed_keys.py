"""Customer product-feed API keys: generation, verification, rate limit, usage.

Durable store is the office server (``office_api.*_api_key*``) - Render's disk
is ephemeral and the free instance restarts on every deploy and idle spin-down.
This module holds an in-memory copy so a feed request never waits on the office
server, and so revocation takes effect the moment staff click Revoke.

Key format: ``bite_live_<32 hex>``. Verification uses SHA-256(key). So staff
can copy a key again, the office also stores it sealed with FEED_KEY_SECRET,
which only Render holds - the office database alone can't reveal a key. The
displayed prefix is the first 8 hex chars AFTER ``bite_live_`` (the literal
prefix is identical for every key, so it would identify nothing).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

KEY_LITERAL = "bite_live_"
RATE_LIMIT_PER_HOUR = 60
_RATE_WINDOW_SECONDS = 3600
_REFRESH_SECONDS = 600   # re-read keys from the office server
_FLUSH_SECONDS = 300     # push usage counters to the office server

_LOCK = threading.Lock()
_KEYS: dict[str, dict] = {}            # id -> record (includes key_hash)
_LOADED_AT = 0.0
_LOCALLY_REVOKED: dict[str, str] = {}  # id -> revoked_at, survives office reloads
_USAGE: dict[str, dict] = {}           # id -> {count_delta, last_used_at, last_used_ip}
_HITS: dict[str, deque] = {}           # id -> request timestamps in the last hour
_BG_STARTED = False


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def key_prefix_of(raw_key: str) -> str:
    return raw_key[len(KEY_LITERAL):len(KEY_LITERAL) + 8] if raw_key.startswith(KEY_LITERAL) else ""


def display_prefix(prefix: str) -> str:
    return f"{KEY_LITERAL}{prefix}…"


# --------------------------------------------------------------------------- #
# Sealing keys so staff can copy them again. Stdlib only: HMAC-SHA256 in
# counter mode for the keystream, then HMAC-SHA256 over nonce+ciphertext.
# --------------------------------------------------------------------------- #

def _seal_secret() -> bytes | None:
    secret = (os.environ.get("FEED_KEY_SECRET") or "").strip()
    return secret.encode("utf-8") if len(secret) >= 16 else None


def _subkeys(secret: bytes) -> tuple[bytes, bytes]:
    return (hmac.new(secret, b"feed-key-enc", hashlib.sha256).digest(),
            hmac.new(secret, b"feed-key-mac", hashlib.sha256).digest())


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(enc_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def seal_key(raw_key: str) -> str | None:
    """Encrypted copy of the key for the office DB; None if no secret is set."""
    secret = _seal_secret()
    if secret is None:
        return None
    enc_key, mac_key = _subkeys(secret)
    nonce = secrets.token_bytes(16)
    plain = raw_key.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(plain, _keystream(enc_key, nonce, len(plain))))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return "v1." + base64.urlsafe_b64encode(nonce + ct + tag).decode("ascii").rstrip("=")


def unseal_key(sealed: str | None) -> str | None:
    secret = _seal_secret()
    if not secret or not sealed or not sealed.startswith("v1."):
        return None
    try:
        body = sealed[3:]
        blob = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (ValueError, TypeError):
        return None
    if len(blob) < 16 + 1 + 32:
        return None
    nonce, ct, tag = blob[:16], blob[16:-32], blob[-32:]
    enc_key, mac_key = _subkeys(secret)
    if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()):
        return None  # wrong secret or tampered
    try:
        return bytes(a ^ b for a, b in zip(ct, _keystream(enc_key, nonce, len(ct)))).decode("utf-8")
    except UnicodeDecodeError:
        return None


def reveal_key(key_id: str) -> str | None:
    """The raw key for staff to copy, or None if it was never sealed."""
    with _LOCK:
        rec = dict(_KEYS.get(key_id) or {})
    raw = unseal_key(rec.get("key_sealed"))
    if raw is None or not hmac.compare_digest(hash_key(raw), rec.get("key_hash") or ""):
        return None
    return raw


def _office():
    from scripts import office_api  # type: ignore
    return office_api


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def refresh_keys() -> None:
    """Replace the in-memory key set with the office server's. Raises on failure."""
    global _LOADED_AT
    records = _office().list_api_keys()
    fresh = {}
    for rec in records:
        if not isinstance(rec, dict) or not rec.get("id") or not rec.get("key_hash"):
            continue
        rec = dict(rec)
        # A revoke that failed to reach the office must not be undone by a reload.
        if rec["id"] in _LOCALLY_REVOKED and not rec.get("revoked_at"):
            rec["revoked_at"] = _LOCALLY_REVOKED[rec["id"]]
        fresh[rec["id"]] = rec
    with _LOCK:
        # Keep counters that have not been flushed yet visible in the UI.
        for kid, pending in _USAGE.items():
            if kid in fresh and pending.get("last_used_at"):
                fresh[kid]["last_used_at"] = pending["last_used_at"]
                fresh[kid]["last_used_ip"] = pending.get("last_used_ip")
        _KEYS.clear()
        _KEYS.update(fresh)
        _LOADED_AT = time.time()


def keys_loaded() -> bool:
    return _LOADED_AT > 0


def ensure_loaded() -> bool:
    """Load keys if never loaded. Returns False if the office server is unreachable."""
    if keys_loaded():
        return True
    try:
        refresh_keys()
        return True
    except Exception as exc:
        logger.warning("Feed keys: office load failed (%s)", exc)
        print(f"[warn] Feed keys: office load failed: {exc}", flush=True)
        return False


# --------------------------------------------------------------------------- #
# Verification + rate limit
# --------------------------------------------------------------------------- #

def _is_active(rec: dict) -> bool:
    if rec.get("revoked_at"):
        return False
    expires = (rec.get("expires_at") or "").strip()
    if expires and expires <= _iso_now():
        return False
    return True


def verify_key(raw_key: str) -> dict | None:
    """Return the active key record for ``raw_key``, else None. Constant-time on the hash."""
    if not raw_key or not raw_key.startswith(KEY_LITERAL) or len(raw_key) != len(KEY_LITERAL) + 32:
        return None
    candidate_hash = hash_key(raw_key)
    prefix = key_prefix_of(raw_key)
    match = None
    with _LOCK:
        for rec in _KEYS.values():
            if rec.get("key_prefix") != prefix:
                continue
            if hmac.compare_digest(str(rec.get("key_hash") or ""), candidate_hash):
                match = dict(rec)
                break
    if match is None or not _is_active(match):
        return None
    return match


def check_rate_limit(key_id: str) -> int:
    """Record one request. Returns 0 if allowed, else seconds until the next slot frees."""
    now = time.time()
    with _LOCK:
        hits = _HITS.setdefault(key_id, deque())
        while hits and hits[0] <= now - _RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= RATE_LIMIT_PER_HOUR:
            return max(1, int(hits[0] + _RATE_WINDOW_SECONDS - now) + 1)
        hits.append(now)
        return 0


def record_use(key_id: str, ip: str | None) -> None:
    now = _iso_now()
    with _LOCK:
        u = _USAGE.setdefault(key_id, {"count_delta": 0})
        u["count_delta"] += 1
        u["last_used_at"] = now
        u["last_used_ip"] = ip
        rec = _KEYS.get(key_id)
        if rec is not None:
            rec["last_used_at"] = now
            rec["last_used_ip"] = ip


def flush_usage() -> None:
    with _LOCK:
        batch = [{"id": kid, **u} for kid, u in _USAGE.items() if u.get("count_delta")]
        _USAGE.clear()
    if not batch:
        return
    try:
        _office().record_api_key_usage(batch)
    except Exception as exc:
        # Put the counts back so the next flush retries them.
        with _LOCK:
            for item in batch:
                u = _USAGE.setdefault(item["id"], {"count_delta": 0})
                u["count_delta"] += item["count_delta"]
                u.setdefault("last_used_at", item.get("last_used_at"))
                u.setdefault("last_used_ip", item.get("last_used_ip"))
        print(f"[warn] Feed keys: usage flush failed, will retry: {exc}", flush=True)


def _background_loop() -> None:
    time.sleep(3)
    ensure_loaded()
    last_refresh = time.time()
    while True:
        time.sleep(_FLUSH_SECONDS)
        flush_usage()
        if time.time() - last_refresh >= _REFRESH_SECONDS:
            try:
                refresh_keys()
            except Exception as exc:
                print(f"[warn] Feed keys: refresh failed, keeping cached keys: {exc}", flush=True)
            last_refresh = time.time()


def start_background() -> None:
    """Load keys off the request path and start the usage flush / refresh loop."""
    global _BG_STARTED
    with _LOCK:
        if _BG_STARTED:
            return
        _BG_STARTED = True
    threading.Thread(target=_background_loop, name="feed-keys", daemon=True).start()


def _after_fork_in_child() -> None:
    """If gunicorn forks the worker from a master that imported the app, the
    usage flush loop stayed behind in the master. Start this process's own."""
    global _LOCK, _BG_STARTED
    _LOCK = threading.Lock()
    was_started = _BG_STARTED
    _BG_STARTED = False
    if was_started:
        start_background()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)


# --------------------------------------------------------------------------- #
# Staff admin
# --------------------------------------------------------------------------- #

def _public(rec: dict) -> dict:
    """Record as shown to staff - no hash."""
    pending = _USAGE.get(rec["id"]) or {}
    return {
        "id": rec["id"],
        "label": rec.get("label") or "",
        "shopify_customer_id": str(rec.get("shopify_customer_id") or ""),
        "prefix": display_prefix(rec.get("key_prefix") or ""),
        "created_at": rec.get("created_at"),
        "created_by": rec.get("created_by"),
        "last_used_at": rec.get("last_used_at"),
        "last_used_ip": rec.get("last_used_ip"),
        "revoked_at": rec.get("revoked_at"),
        "expires_at": rec.get("expires_at"),
        "request_count": int(rec.get("request_count") or 0) + int(pending.get("count_delta") or 0),
        "can_copy": bool(rec.get("key_sealed")) and _seal_secret() is not None,
        "status": "revoked" if rec.get("revoked_at") else ("active" if _is_active(rec) else "expired"),
        "fields": list(groups_of(rec)),
    }


def groups_of(rec: dict) -> tuple[str, ...]:
    """Every key receives every field group."""
    from scripts.product_feed import FIELD_GROUPS  # type: ignore
    return tuple(FIELD_GROUPS)


def list_keys_for_staff(*, refresh: bool = True) -> list[dict]:
    if refresh or not keys_loaded():
        refresh_keys()
    with _LOCK:
        records = [dict(r) for r in _KEYS.values()]
    records.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return [_public(r) for r in records]


def generate_key(*, label: str, shopify_customer_id: str, created_by: str | None,
                 expires_at: str | None = None, fields: list[str] | None = None) -> tuple[str, dict]:
    """Create a key on the office server. Returns (raw_key, public record).

    The raw key is never logged; it is stored only sealed (see ``seal_key``).
    """
    raw_key = f"{KEY_LITERAL}{secrets.token_hex(16)}"
    record = {
        "id": uuid.uuid4().hex,
        "label": label,
        "shopify_customer_id": str(shopify_customer_id),
        "key_hash": hash_key(raw_key),
        "key_prefix": key_prefix_of(raw_key),
        "key_sealed": seal_key(raw_key),
        "created_by": created_by,
        "expires_at": expires_at,
        "fields": list(fields) if fields is not None else None,
    }
    stored = _office().create_api_key(record)
    from scripts.product_feed import normalise_groups, DEFAULT_GROUPS  # type: ignore
    if (fields is not None and stored.get("fields") is None
            and normalise_groups(fields) != DEFAULT_GROUPS):
        # Office server predates field choices - it dropped them. Don't hand
        # out a key that silently gets the defaults instead.
        _office().revoke_api_key(stored["id"])
        raise RuntimeError("Office server needs the updated api_keys_addon.py before keys can have field choices")
    with _LOCK:
        _KEYS[stored["id"]] = dict(stored)
    return raw_key, _public(stored)


def set_fields(key_id: str, fields: list[str]) -> dict | None:
    """Persist a key's field groups, then apply them. Returns the public record."""
    with _LOCK:
        if key_id not in _KEYS:
            return None
    stored = _office().set_api_key_fields(key_id, fields)
    with _LOCK:
        _KEYS[key_id] = {**_KEYS.get(key_id, {}), **stored}
        return _public(dict(_KEYS[key_id]))


def revoke_key(key_id: str) -> tuple[dict | None, str | None]:
    """Revoke immediately in memory, then persist. Returns (record, office_error)."""
    now = _iso_now()
    with _LOCK:
        rec = _KEYS.get(key_id)
        if rec is None:
            return None, None
        rec["revoked_at"] = rec.get("revoked_at") or now
        _LOCALLY_REVOKED[key_id] = rec["revoked_at"]
    try:
        stored = _office().revoke_api_key(key_id)
        with _LOCK:
            _KEYS[key_id] = {**_KEYS.get(key_id, {}), **stored}
        return _public(_KEYS[key_id]), None
    except Exception as exc:
        print(f"[warn] Feed keys: revoke {key_id} held in memory only - office save failed: {exc}", flush=True)
        with _LOCK:
            return _public(dict(_KEYS[key_id])), str(exc)
