"""Client for the Office Order API (status pipeline + artwork/proof files)."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote

import requests

from config import OFFICE_API_URL, OFFICE_API_KEY  # type: ignore

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_session: requests.Session | None = None


class OfficeApiError(Exception):
    """Raised when the Office Order API returns an error or is unreachable."""


def _require_config() -> None:
    if not OFFICE_API_URL or not OFFICE_API_KEY:
        raise OfficeApiError("Order tracking is not configured")


def _session_get() -> requests.Session:
    global _session
    _require_config()
    if _session is None:
        _session = requests.Session()
        _session.headers["X-API-Key"] = OFFICE_API_KEY
    return _session


def slugify(text: str, max_len: int = 60) -> str:
    s = (text or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "item"


def order_key(shopify_order_name: str) -> str:
    return (shopify_order_name or "").strip()


def item_key(line_number: int, product_title: str) -> str:
    return f"{line_number}-{slugify(product_title)}"


def _path(*segments: str) -> str:
    return "/".join(quote(seg, safe="") for seg in segments)


def _url(order: str, *parts: str) -> str:
    """Build /orders/{order}/items/{item}/... paths per Office API spec."""
    base = OFFICE_API_URL.rstrip("/")
    segments = [_path(order), "items"] + [_path(p) for p in parts]
    return f"{base}/orders/{'/'.join(segments)}"


def _request(method: str, url: str, **kwargs) -> requests.Response:
    try:
        return _session_get().request(method, url, timeout=_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        logger.error("Office API request failed: %s", exc)
        raise OfficeApiError("Order tracking service unavailable") from exc


def _handle_response(resp: requests.Response, *, allow_404: bool = False):
    if resp.status_code == 404 and allow_404:
        return None
    if resp.status_code == 401:
        logger.error("Office API rejected API key")
        raise OfficeApiError("Order tracking authentication failed")
    if not resp.ok:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("error") or body.get("message") or ""
        except Exception:
            detail = (resp.text or "")[:200]
        logger.error("Office API HTTP %s: %s", resp.status_code, detail or resp.reason)
        raise OfficeApiError(detail or f"Order tracking request failed ({resp.status_code})")
    if resp.status_code == 204:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def ensure_item(order: str, item: str, label: str) -> dict:
    """Create-or-touch an item; returns status view."""
    url = _url(order, item)
    resp = _request("POST", url, json={"label": label})
    result = _handle_response(resp)
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from order tracking")
    return result


def get_item(order: str, item: str) -> dict | None:
    url = _url(order, item)
    resp = _request("GET", url)
    return _handle_response(resp, allow_404=True)


def get_order(order: str) -> dict | None:
    url = f"{OFFICE_API_URL.rstrip('/')}/orders/{_path(order)}"
    resp = _request("GET", url)
    return _handle_response(resp, allow_404=True)


def set_status(order: str, item: str, stage: str, note: str = "", by: str = "") -> dict:
    url = f"{_url(order, item)}/status"
    payload = {"stage": stage, "note": note or "", "by": by or ""}
    resp = _request("POST", url, json=payload)
    result = _handle_response(resp)
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from order tracking")
    return result


def upload_artwork(order: str, item: str, file_stream, filename: str) -> dict:
    url = f"{_url(order, item)}/artwork"
    resp = _request(
        "POST",
        url,
        files={"file": (filename, file_stream, "application/octet-stream")},
    )
    result = _handle_response(resp)
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from artwork upload")
    return result


def upload_proof(order: str, item: str, file_stream, filename: str) -> dict:
    url = f"{_url(order, item)}/proof"
    resp = _request(
        "POST",
        url,
        files={"file": (filename, file_stream, "application/octet-stream")},
    )
    result = _handle_response(resp)
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from proof upload")
    return result


def list_files(order: str, item: str) -> dict:
    url = f"{_url(order, item)}/files"
    resp = _request("GET", url)
    result = _handle_response(resp)
    return result if isinstance(result, dict) else {"files": []}


def fetch_file(order: str, item: str, filename: str) -> requests.Response:
    url = f"{_url(order, item, 'files', filename)}"
    resp = _request("GET", url, stream=True)
    if resp.status_code == 401:
        raise OfficeApiError("Order tracking authentication failed")
    if not resp.ok:
        logger.error("Office API file fetch HTTP %s for %s", resp.status_code, filename)
        raise OfficeApiError(f"Could not download file ({resp.status_code})")
    return resp
