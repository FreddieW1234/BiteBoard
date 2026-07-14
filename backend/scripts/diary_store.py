"""SQLite persistence for staff Diary dispatch dates and carriers."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent
_DB_DIR = _BASE_DIR / "data"
_DB_PATH = _DB_DIR / "diary.db"

VALID_CARRIERS = frozenset({"royal_mail", "fedex", "frenni", ""})


def _connect() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS diary_entries (
                order_name TEXT NOT NULL,
                item_id TEXT NOT NULL,
                dispatch_date TEXT,
                dispatch_manual INTEGER NOT NULL DEFAULT 0,
                carrier TEXT,
                updated_at TEXT,
                PRIMARY KEY (order_name, item_id)
            )
            """
        )
        conn.commit()


def get_all_entries() -> dict[tuple[str, str], dict]:
    init_db()
    out: dict[tuple[str, str], dict] = {}
    with _connect() as conn:
        rows = conn.execute(
            "SELECT order_name, item_id, dispatch_date, dispatch_manual, carrier, updated_at FROM diary_entries"
        ).fetchall()
    for row in rows:
        key = (row["order_name"], row["item_id"])
        out[key] = {
            "dispatch_date": row["dispatch_date"] or "",
            "dispatch_manual": bool(row["dispatch_manual"]),
            "carrier": row["carrier"] or "",
            "updated_at": row["updated_at"] or "",
        }
    return out


def get_entry(order_name: str, item_id: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT dispatch_date, dispatch_manual, carrier, updated_at
            FROM diary_entries WHERE order_name = ? AND item_id = ?
            """,
            (order_name, item_id),
        ).fetchone()
    if not row:
        return None
    return {
        "dispatch_date": row["dispatch_date"] or "",
        "dispatch_manual": bool(row["dispatch_manual"]),
        "carrier": row["carrier"] or "",
        "updated_at": row["updated_at"] or "",
    }


def upsert_entry(
    order_name: str,
    item_id: str,
    *,
    dispatch_date: str | None = None,
    dispatch_manual: bool | None = None,
    carrier: str | None = None,
) -> dict:
    init_db()
    order_name = (order_name or "").strip()
    item_id = (item_id or "").strip()
    if not order_name or not item_id:
        raise ValueError("order_name and item_id are required")

    existing = get_entry(order_name, item_id) or {
        "dispatch_date": "",
        "dispatch_manual": False,
        "carrier": "",
        "updated_at": "",
    }

    if dispatch_date is not None:
        existing["dispatch_date"] = (dispatch_date or "").strip()
    if dispatch_manual is not None:
        existing["dispatch_manual"] = bool(dispatch_manual)
    if carrier is not None:
        c = (carrier or "").strip().lower()
        if c not in VALID_CARRIERS:
            raise ValueError("Invalid carrier")
        existing["carrier"] = c

    existing["updated_at"] = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO diary_entries (order_name, item_id, dispatch_date, dispatch_manual, carrier, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_name, item_id) DO UPDATE SET
                dispatch_date = excluded.dispatch_date,
                dispatch_manual = excluded.dispatch_manual,
                carrier = excluded.carrier,
                updated_at = excluded.updated_at
            """,
            (
                order_name,
                item_id,
                existing["dispatch_date"] or None,
                1 if existing["dispatch_manual"] else 0,
                existing["carrier"] or None,
                existing["updated_at"],
            ),
        )
        conn.commit()
    return existing
