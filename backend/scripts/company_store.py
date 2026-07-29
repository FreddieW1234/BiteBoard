"""SQLite persistence for staff-managed companies, members, and notes."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent
_DB_DIR = _BASE_DIR / "data"
_DB_PATH = _DB_DIR / "companies.db"


def _connect() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS company_members (
                company_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (customer_id),
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS company_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL,
                note_date TEXT NOT NULL,
                author TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return date.today().isoformat()


def list_companies() -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.name, c.created_at, c.updated_at,
                   COUNT(m.customer_id) AS member_count,
                   GROUP_CONCAT(m.customer_id) AS member_ids_csv
            FROM companies c
            LEFT JOIN company_members m ON m.company_id = c.id
            GROUP BY c.id
            ORDER BY c.name COLLATE NOCASE ASC
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "member_count": int(row["member_count"] or 0),
            "member_ids": [x for x in (row["member_ids_csv"] or "").split(",") if x],
        }
        for row in rows
    ]


def get_company(company_id: str) -> dict | None:
    init_db()
    cid = (company_id or "").strip()
    if not cid:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, created_at, updated_at FROM companies WHERE id = ?",
            (cid,),
        ).fetchone()
        if not row:
            return None
        members = conn.execute(
            """
            SELECT customer_id, added_at
            FROM company_members
            WHERE company_id = ?
            ORDER BY added_at ASC
            """,
            (cid,),
        ).fetchall()
        notes = conn.execute(
            """
            SELECT id, note_date, author, body, created_at
            FROM company_notes
            WHERE company_id = ?
            ORDER BY note_date DESC, id DESC
            """,
            (cid,),
        ).fetchall()
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "members": [
            {"customer_id": m["customer_id"], "added_at": m["added_at"]}
            for m in members
        ],
        "notes": [
            {
                "id": n["id"],
                "note_date": n["note_date"],
                "author": n["author"],
                "body": n["body"],
                "created_at": n["created_at"],
            }
            for n in notes
        ],
    }


def create_company(name: str) -> dict:
    init_db()
    name = (name or "").strip()
    if not name:
        raise ValueError("Company name is required")
    company_id = uuid.uuid4().hex
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO companies (id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (company_id, name, now, now),
        )
        conn.commit()
    return get_company(company_id) or {}


def update_company_name(company_id: str, name: str) -> dict:
    init_db()
    cid = (company_id or "").strip()
    name = (name or "").strip()
    if not cid:
        raise ValueError("Company id is required")
    if not name:
        raise ValueError("Company name is required")
    now = _now_iso()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE companies SET name = ?, updated_at = ? WHERE id = ?",
            (name, now, cid),
        )
        if cur.rowcount == 0:
            raise ValueError("Company not found")
        conn.commit()
    return get_company(cid) or {}


def add_member(company_id: str, customer_id: str) -> dict:
    init_db()
    cid = (company_id or "").strip()
    customer_id = str(customer_id or "").strip()
    if not cid or not customer_id:
        raise ValueError("Company id and customer id are required")
    with _connect() as conn:
        company = conn.execute(
            "SELECT id FROM companies WHERE id = ?",
            (cid,),
        ).fetchone()
        if not company:
            raise ValueError("Company not found")
        existing = conn.execute(
            "SELECT company_id FROM company_members WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        if existing and existing["company_id"] != cid:
            raise ValueError("Customer is already assigned to another company")
        conn.execute(
            """
            INSERT INTO company_members (company_id, customer_id, added_at)
            VALUES (?, ?, ?)
            ON CONFLICT(customer_id) DO UPDATE SET
                company_id = excluded.company_id,
                added_at = excluded.added_at
            """,
            (cid, customer_id, _now_iso()),
        )
        conn.commit()
    return get_company(cid) or {}


def remove_member(company_id: str, customer_id: str) -> dict:
    init_db()
    cid = (company_id or "").strip()
    customer_id = str(customer_id or "").strip()
    if not cid or not customer_id:
        raise ValueError("Company id and customer id are required")
    with _connect() as conn:
        conn.execute(
            "DELETE FROM company_members WHERE company_id = ? AND customer_id = ?",
            (cid, customer_id),
        )
        conn.commit()
    return get_company(cid) or {}


def member_company_id(customer_id: str) -> str:
    init_db()
    customer_id = str(customer_id or "").strip()
    if not customer_id:
        return ""
    with _connect() as conn:
        row = conn.execute(
            "SELECT company_id FROM company_members WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
    return (row["company_id"] if row else "") or ""


def add_note(
    company_id: str,
    *,
    author: str,
    body: str,
    note_date: str = "",
) -> dict:
    init_db()
    cid = (company_id or "").strip()
    author = (author or "").strip()
    body = (body or "").strip()
    note_date = (note_date or "").strip() or _today_iso()
    if not cid:
        raise ValueError("Company id is required")
    if not author:
        raise ValueError("Author is required")
    if not body:
        raise ValueError("Note text is required")
    with _connect() as conn:
        company = conn.execute(
            "SELECT id FROM companies WHERE id = ?",
            (cid,),
        ).fetchone()
        if not company:
            raise ValueError("Company not found")
        cur = conn.execute(
            """
            INSERT INTO company_notes (company_id, note_date, author, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cid, note_date, author, body, _now_iso()),
        )
        note_id = cur.lastrowid
        conn.commit()
        row = conn.execute(
            """
            SELECT id, note_date, author, body, created_at
            FROM company_notes WHERE id = ?
            """,
            (note_id,),
        ).fetchone()
    return {
        "id": row["id"],
        "note_date": row["note_date"],
        "author": row["author"],
        "body": row["body"],
        "created_at": row["created_at"],
    }


def delete_note(company_id: str, note_id: str) -> None:
    init_db()
    cid = (company_id or "").strip()
    if not cid:
        raise ValueError("Company id is required")
    try:
        nid = int(note_id)
    except (TypeError, ValueError):
        raise ValueError("Note id is required")
    with _connect() as conn:
        company = conn.execute(
            "SELECT id FROM companies WHERE id = ?",
            (cid,),
        ).fetchone()
        if not company:
            raise ValueError("Company not found")
        cur = conn.execute(
            "DELETE FROM company_notes WHERE id = ? AND company_id = ?",
            (nid, cid),
        )
        if cur.rowcount == 0:
            raise ValueError("Note not found")
        conn.commit()
