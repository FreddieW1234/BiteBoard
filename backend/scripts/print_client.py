"""Send label print jobs to the office LAN print server."""

from __future__ import annotations

import base64
import logging

import requests

from config import OFFICE_PRINT_SERVER_KEY, OFFICE_PRINT_SERVER_URL  # type: ignore

logger = logging.getLogger(__name__)

_TIMEOUT = 30


class PrintClientError(Exception):
    pass


def configured() -> bool:
    return bool(OFFICE_PRINT_SERVER_URL)


def send_print_job(
    *,
    profile: str,
    label_format: str,
    data: bytes,
    order_name: str = "",
    tracking_number: str = "",
) -> dict:
    """POST a print job to the office print server.

    Expected office server contract (phase 1):
      POST {OFFICE_PRINT_SERVER_URL}/print
      { profile, format, data_base64, order_name, tracking_number }
    """
    if not configured():
        logger.info(
            "Print server not configured — skipping print for %s (%s)",
            order_name,
            tracking_number,
        )
        return {"success": True, "skipped": True, "reason": "print_server_not_configured"}

    headers = {"Content-Type": "application/json"}
    if OFFICE_PRINT_SERVER_KEY:
        headers["X-Print-Key"] = OFFICE_PRINT_SERVER_KEY

    payload = {
        "profile": profile,
        "format": label_format,
        "data_base64": base64.b64encode(data).decode("ascii"),
        "order_name": order_name,
        "tracking_number": tracking_number,
    }
    try:
        resp = requests.post(
            f"{OFFICE_PRINT_SERVER_URL}/print",
            json=payload,
            headers=headers,
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise PrintClientError("Office print server unreachable") from exc

    if not resp.ok:
        detail = (resp.text or "")[:200]
        raise PrintClientError(detail or f"Print server error ({resp.status_code})")

    try:
        body = resp.json()
    except Exception:
        body = {"success": True}
    return body if isinstance(body, dict) else {"success": True}
