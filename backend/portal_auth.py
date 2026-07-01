"""Lightweight staff login and client (customer) session helpers."""

from __future__ import annotations

from flask import session

from config import STAFF_USERNAME, STAFF_PASSWORD  # type: ignore

STAFF_SESSION_KEY = "staff_authenticated"
CLIENT_ID_SESSION_KEY = "client_customer_id"
CLIENT_EMAIL_SESSION_KEY = "client_email"


def check_staff_credentials(username: str, password: str) -> bool:
    u = (username or "").strip()
    p = password or ""
    return u == STAFF_USERNAME and p == STAFF_PASSWORD


def is_staff_authenticated() -> bool:
    return session.get(STAFF_SESSION_KEY) is True


def login_staff() -> None:
    session[STAFF_SESSION_KEY] = True
    session.permanent = True


def logout_staff() -> None:
    session.pop(STAFF_SESSION_KEY, None)


def establish_client_session(customer_id: str | int, email: str) -> None:
    session[CLIENT_ID_SESSION_KEY] = str(customer_id).strip()
    session[CLIENT_EMAIL_SESSION_KEY] = (email or "").strip().lower()
    session.permanent = True


def get_client_customer_id() -> str | None:
    cid = session.get(CLIENT_ID_SESSION_KEY)
    return str(cid).strip() if cid else None


def get_client_email() -> str | None:
    em = session.get(CLIENT_EMAIL_SESSION_KEY)
    return em if em else None


def clear_client_session() -> None:
    session.pop(CLIENT_ID_SESSION_KEY, None)
    session.pop(CLIENT_EMAIL_SESSION_KEY, None)


def is_client_path(path: str) -> bool:
    return (
        path.startswith("/client")
        or path.startswith("/api/client")
        or path == "/portal"
        or path.startswith("/portal/")
    )


def is_staff_public_path(path: str) -> bool:
    public = {"/staff/login", "/api/health", "/test"}
    return path in public
