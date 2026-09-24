"""
Customer feed API keys for the Office Order API
===============================================

MERGE THIS into the office FastAPI app, next to stock_designs_addon.py, then
restart the service. The Render portal keeps no durable disk, so the office
server is the source of truth for feed keys (same as labels, diary, companies).

Storage: SQLite ``api_keys.db`` under DB_DIR (next to orders.db / companies.db).
Only the SHA-256 hash of each key is stored - the key itself never reaches the
office server.

Endpoints (all require X-API-Key):

    GET   /api-keys                  every key, including key_hash (the portal
                                     verifies feed requests against its copy)
    POST  /api-keys                  create - body has the hash, not the key
    POST  /api-keys/{key_id}/revoke  set revoked_at (idempotent)
    PUT   /api-keys/{key_id}/fields  replace the key's feed field groups
    POST  /api-keys/usage            batch usage flush from the portal

Register near the bottom of the office API:

    from api_keys_addon import register_api_key_routes
    register_api_key_routes(app, db_dir=DB_DIR, lock=LOCK, require_key_dep=require_key)
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel

_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_PREFIX_RE = re.compile(r"^[0-9a-f]{8}$")
_FIELD_RE = re.compile(r"^[a-z_]{1,32}$")

_COLUMNS = (
    "id", "label", "shopify_customer_id", "key_hash", "key_prefix",
    "created_at", "created_by", "last_used_at", "last_used_ip",
    "revoked_at", "expires_at", "request_count", "fields",
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(db_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(db_dir) / "api_keys.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_api_keys_db(db_dir: Path) -> None:
    Path(db_dir).mkdir(parents=True, exist_ok=True)
    with _connect(db_dir) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                shopify_customer_id TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                key_prefix TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT,
                last_used_at TEXT,
                last_used_ip TEXT,
                revoked_at TEXT,
                expires_at TEXT,
                request_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # Feed field groups (JSON list). NULL = the portal's defaults.
        try:
            conn.execute("ALTER TABLE api_keys ADD COLUMN fields TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()


def _row(row: sqlite3.Row) -> dict:
    out = {col: row[col] for col in _COLUMNS}
    try:
        out["fields"] = json.loads(out["fields"]) if out["fields"] else None
    except ValueError:
        out["fields"] = None
    return out


def _fields_json(fields: list[str] | None) -> str | None:
    if fields is None:
        return None
    clean = sorted({f.strip() for f in fields if isinstance(f, str) and f.strip()})
    if len(clean) > 40 or not all(_FIELD_RE.match(f) for f in clean):
        raise HTTPException(400, "fields must be a list of short lowercase group names.")
    return json.dumps(clean)


class ApiKeyCreate(BaseModel):
    id: str
    label: str
    shopify_customer_id: str
    key_hash: str
    key_prefix: str
    created_by: str | None = None
    expires_at: str | None = None
    fields: list[str] | None = None


class ApiKeyFields(BaseModel):
    fields: list[str]


class ApiKeyUsageItem(BaseModel):
    id: str
    count_delta: int = 0
    last_used_at: str | None = None
    last_used_ip: str | None = None


class ApiKeyUsage(BaseModel):
    usage: list[ApiKeyUsageItem] = []


def register_api_key_routes(app, *, db_dir: Path, lock, require_key_dep) -> None:
    init_api_keys_db(db_dir)

    @app.get("/api-keys", dependencies=[Depends(require_key_dep)])
    def list_api_keys():
        with _connect(db_dir) as conn:
            rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        return {"keys": [_row(r) for r in rows]}

    @app.post("/api-keys", dependencies=[Depends(require_key_dep)])
    def create_api_key(body: ApiKeyCreate):
        if not _KEY_ID_RE.match(body.id):
            raise HTTPException(400, "Invalid key id.")
        if not _HASH_RE.match(body.key_hash):
            raise HTTPException(400, "key_hash must be a SHA-256 hex digest.")
        if not _PREFIX_RE.match(body.key_prefix):
            raise HTTPException(400, "key_prefix must be 8 hex characters.")
        label = (body.label or "").strip()
        customer_id = (body.shopify_customer_id or "").strip()
        if not label or not customer_id.isdigit():
            raise HTTPException(400, "label and a numeric shopify_customer_id are required.")
        with lock, _connect(db_dir) as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO api_keys (id, label, shopify_customer_id, key_hash,
                        key_prefix, created_at, created_by, expires_at, request_count, fields)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (body.id, label, customer_id, body.key_hash, body.key_prefix,
                     _iso_now(), body.created_by, body.expires_at, _fields_json(body.fields)),
                )
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Key id or hash already exists.")
            conn.commit()
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (body.id,)).fetchone()
        return {"ok": True, "key": _row(row)}

    @app.post("/api-keys/{key_id}/revoke", dependencies=[Depends(require_key_dep)])
    def revoke_api_key(key_id: str):
        if not _KEY_ID_RE.match(key_id):
            raise HTTPException(400, "Invalid key id.")
        with lock, _connect(db_dir) as conn:
            conn.execute(
                "UPDATE api_keys SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
                (_iso_now(), key_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Key not found.")
        return {"ok": True, "key": _row(row)}

    @app.put("/api-keys/{key_id}/fields", dependencies=[Depends(require_key_dep)])
    def set_api_key_fields(key_id: str, body: ApiKeyFields):
        if not _KEY_ID_RE.match(key_id):
            raise HTTPException(400, "Invalid key id.")
        value = _fields_json(body.fields)
        with lock, _connect(db_dir) as conn:
            conn.execute("UPDATE api_keys SET fields = ? WHERE id = ?", (value, key_id))
            conn.commit()
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Key not found.")
        return {"ok": True, "key": _row(row)}

    @app.post("/api-keys/usage", dependencies=[Depends(require_key_dep)])
    def record_api_key_usage(body: ApiKeyUsage):
        updated = 0
        with lock, _connect(db_dir) as conn:
            for item in body.usage:
                if not _KEY_ID_RE.match(item.id):
                    continue
                cur = conn.execute(
                    """
                    UPDATE api_keys SET
                        request_count = request_count + ?,
                        last_used_at = CASE
                            WHEN ? IS NOT NULL AND (last_used_at IS NULL OR ? > last_used_at)
                            THEN ? ELSE last_used_at END,
                        last_used_ip = CASE
                            WHEN ? IS NOT NULL AND (last_used_at IS NULL OR ? >= last_used_at)
                            THEN ? ELSE last_used_ip END
                    WHERE id = ?
                    """,
                    (max(0, int(item.count_delta)),
                     item.last_used_at, item.last_used_at, item.last_used_at,
                     item.last_used_ip, item.last_used_at, item.last_used_ip,
                     item.id),
                )
                updated += cur.rowcount
            conn.commit()
        return {"ok": True, "updated": updated}
