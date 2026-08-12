"""Lightweight staff login and client (customer) session helpers."""

from __future__ import annotations

from flask import session

from config import STAFF_ACCOUNTS, STAFF_DEV_TOOL_USERNAMES  # type: ignore

STAFF_SESSION_KEY = "staff_authenticated"
STAFF_USERNAME_SESSION_KEY = "staff_username"
CLIENT_ID_SESSION_KEY = "client_customer_id"
CLIENT_EMAIL_SESSION_KEY = "client_email"

# Pages / APIs only the "dev" staff user may open.
STAFF_DEV_ONLY_PATH_PREFIXES = (
    "/app/Artwork_Updater",
    "/app/Files",
    "/app/Dev",
    "/app/Collections",
    "/api/dev/",
    "/api/collections",
)


def authenticate_staff(username: str, password: str) -> str | None:
    """Return the matched username on success, else None."""
    u = (username or "").strip()
    p = password or ""
    expected = STAFF_ACCOUNTS.get(u)
    if expected is not None and p == expected:
        return u
    return None


def check_staff_credentials(username: str, password: str) -> bool:
    return authenticate_staff(username, password) is not None


def is_staff_authenticated() -> bool:
    return session.get(STAFF_SESSION_KEY) is True


def get_staff_username() -> str | None:
    if not is_staff_authenticated():
        return None
    u = session.get(STAFF_USERNAME_SESSION_KEY)
    return str(u).strip() if u else None


def staff_can_access_dev_tools() -> bool:
    """Files / Dev / Artwork Updater — only the dedicated dev account."""
    u = get_staff_username()
    return bool(u and u in STAFF_DEV_TOOL_USERNAMES)


def staff_user_type_label() -> str | None:
    """Display label for the signed-in staff account: Dev or Staff."""
    if not is_staff_authenticated():
        return None
    if staff_can_access_dev_tools():
        return "Dev"
    return "Staff"


def is_staff_dev_only_path(path: str) -> bool:
    p = path or ""
    return any(p == prefix.rstrip("/") or p.startswith(prefix) for prefix in STAFF_DEV_ONLY_PATH_PREFIXES)


def login_staff(username: str | None = None) -> None:
    session[STAFF_SESSION_KEY] = True
    if username:
        session[STAFF_USERNAME_SESSION_KEY] = str(username).strip()
    session.permanent = True


def logout_staff() -> None:
    session.pop(STAFF_SESSION_KEY, None)
    session.pop(STAFF_USERNAME_SESSION_KEY, None)


def establish_client_session(customer_id: str | int, email: str, shop_url: str | None = None) -> None:
    session[CLIENT_ID_SESSION_KEY] = str(customer_id).strip()
    session[CLIENT_EMAIL_SESSION_KEY] = (email or "").strip().lower()
    if shop_url:
        session["client_shop_url"] = shop_url.rstrip("/")
    session.permanent = True


def get_client_shop_url() -> str | None:
    url = session.get("client_shop_url")
    return url.rstrip("/") if url else None


def get_client_customer_id() -> str | None:
    cid = session.get(CLIENT_ID_SESSION_KEY)
    return str(cid).strip() if cid else None


def get_client_email() -> str | None:
    em = session.get(CLIENT_EMAIL_SESSION_KEY)
    return em if em else None


def clear_client_session() -> None:
    session.pop(CLIENT_ID_SESSION_KEY, None)
    session.pop(CLIENT_EMAIL_SESSION_KEY, None)
    session.pop("client_shop_url", None)


def is_client_path(path: str) -> bool:
    return (
        path.startswith("/client")
        or path.startswith("/api/client")
        or path == "/portal"
        or path.startswith("/portal/")
        or path == "/portal-register"
    )


def is_staff_public_path(path: str) -> bool:
    # /healthz must stay reachable for Render's health check, and /maint-exit
    # must stay reachable to clear the maintenance bypass cookie.
    public = {"/staff/login", "/api/health", "/test", "/healthz", "/maint-exit"}
    if path in public:
        return True
    # Storefront stock-designs: product page checks /exists and downloads /latest
    # without a portal staff session. Staff list/upload/delete stay protected.
    if path.startswith("/api/stock-designs/") and (
        path.endswith("/exists") or path.endswith("/latest")
    ):
        return True
    return False


def can_access_order(order_id: str | int) -> bool:
    """Staff may access any order; clients only their own."""
    if is_staff_authenticated():
        return True
    cid = get_client_customer_id()
    if not cid:
        return False
    from scripts.order_helpers import resolve_order_access  # type: ignore
    return resolve_order_access(order_id, client_customer_id=cid) is not None
