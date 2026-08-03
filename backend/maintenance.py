"""Application-level maintenance mode.

Serves a 503 maintenance page to everyone except holders of a bypass key, so
staff can keep using the site normally while it is switched on. Render's own
maintenance toggle is not usable for this because it blocks every request,
including ours.

Configuration (all via environment variables, read once at import — Render
restarts the service when an env var changes, so there is nothing to re-read
at runtime):

    MAINTENANCE_MODE    "1" / "true" / "yes" / "on" (case-insensitive) = ON.
                        Anything else, including unset, is OFF.
    MAINT_KEY           Bypass secret. Visiting any path with ?maint=<key>
                        sets the bypass cookie.
    MAINT_BYPASS_HOURS  Bypass cookie lifetime in hours (default 8).
"""

from __future__ import annotations

import hmac
import logging
import os
import sys
from urllib.parse import urlencode

from flask import jsonify, make_response, redirect, render_template, request

from config import FLASK_SESSION_SECURE  # type: ignore

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}

MAINTENANCE_MODE = (os.environ.get("MAINTENANCE_MODE") or "").strip().lower() in _TRUTHY
MAINT_KEY = (os.environ.get("MAINT_KEY") or "").strip()

try:
    MAINT_BYPASS_HOURS = int(os.environ.get("MAINT_BYPASS_HOURS") or 8)
except ValueError:
    MAINT_BYPASS_HOURS = 8

BYPASS_COOKIE = "maint_bypass"
QUERY_PARAM = "maint"

# The health check must never return 503. Render polls it and will mark the
# service unhealthy and restart the instance if it fails, which would take the
# site down for real in the middle of planned maintenance.
HEALTH_PATHS = ("/healthz", "/api/health")

# /static/ stays open so the maintenance page can load its own assets, and
# /maint-exit stays open so the bypass cookie can always be cleared again.
ALWAYS_ALLOW_PATHS = ("/maint-exit",)
ALWAYS_ALLOW_PREFIXES = ("/static/",)


def _ensure_log_handler() -> None:
    """Bypass activity must be visible in the Render log stream.

    Gunicorn leaves the root logger without handlers, so INFO records would
    otherwise be dropped by logging.lastResort (WARNING and above only).
    """
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[maintenance] %(levelname)s %(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _client_ip() -> str:
    """Real client IP behind Render's proxy (ProxyFix is not installed)."""
    forwarded = request.headers.get("X-Forwarded-For") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _key_matches(candidate: str) -> bool:
    """Constant-time comparison; never a plain == on the secret."""
    if not candidate or not MAINT_KEY:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), MAINT_KEY.encode("utf-8"))


def _wants_json() -> bool:
    if (request.path or "").startswith("/api/"):
        return True
    accept = request.accept_mimetypes
    return bool(accept.accept_json and not accept.accept_html)


def _maintenance_response():
    """Identical for a wrong key and for no key at all — no hints either way."""
    if _wants_json():
        response = make_response(jsonify({"status": "maintenance"}), 503)
    else:
        response = make_response(render_template("maintenance.html"), 503)
    response.headers["Retry-After"] = "3600"
    response.headers["Cache-Control"] = "no-store, private"
    return response


def _path_without_key() -> str:
    """Same path, minus ?maint=, so the secret leaves the URL bar and history."""
    args = request.args.to_dict(flat=False)
    args.pop(QUERY_PARAM, None)
    query = urlencode(args, doseq=True)
    return f"{request.path}?{query}" if query else request.path


def _healthz():
    response = make_response("ok", 200)
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    response.headers["Cache-Control"] = "no-store, private"
    return response


def _maint_exit():
    response = make_response("Maintenance bypass cleared for this browser.", 200)
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    response.headers["Cache-Control"] = "no-store, private"
    response.delete_cookie(BYPASS_COOKIE, path="/")
    return response


def _maintenance_gate():
    path = request.path or ""

    if path in HEALTH_PATHS or path in ALWAYS_ALLOW_PATHS:
        return None
    if path.startswith(ALWAYS_ALLOW_PREFIXES):
        return None

    supplied = request.args.get(QUERY_PARAM)
    if supplied is not None:
        if _key_matches(supplied):
            response = redirect(_path_without_key(), code=302)
            response.set_cookie(
                BYPASS_COOKIE,
                MAINT_KEY,
                max_age=MAINT_BYPASS_HOURS * 3600,
                httponly=True,
                secure=bool(FLASK_SESSION_SECURE),
                samesite="Lax",
                path="/",
            )
            logger.info("bypass activated ip=%s path=%s", _client_ip(), path)
            return response
        logger.warning("bypass rejected ip=%s path=%s", _client_ip(), path)
        return _maintenance_response()

    if _key_matches(request.cookies.get(BYPASS_COOKIE) or ""):
        return None

    return _maintenance_response()


def init_maintenance(app):
    """Register the health check, the bypass exit route, and the gate.

    Must be called before any other before_request handler is registered:
    Flask runs them in registration order, and the maintenance page has to win
    over the staff auth redirect in portal_auth_gate.
    """
    app.add_url_rule("/healthz", "healthz", _healthz, methods=["GET"])
    app.add_url_rule("/maint-exit", "maint_exit", _maint_exit, methods=["GET"])

    # When OFF, no hook is registered at all — zero per-request overhead.
    if not MAINTENANCE_MODE:
        return

    _ensure_log_handler()

    if not MAINT_KEY:
        logger.warning(
            "MAINTENANCE_MODE is ON but MAINT_KEY is empty — no bypass is possible. "
            "Every visitor, including staff, will see the maintenance page."
        )
    else:
        logger.info("Maintenance mode ENABLED — bypass configured, cookie lasts %sh", MAINT_BYPASS_HOURS)

    app.before_request(_maintenance_gate)
