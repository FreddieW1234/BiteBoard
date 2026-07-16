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
    if resp.status_code == 405:
        raise OfficeApiError(f"Order tracking request failed ({resp.status_code})")
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


def normalize_stage_for_api(stage: str) -> str:
    """Map portal stage keys to Office API valid stages."""
    if stage == "in_production":
        return "printing"
    return stage


def set_status(order: str, item: str, stage: str, note: str = "", by: str = "") -> dict:
    url = f"{_url(order, item)}/status"
    api_stage = normalize_stage_for_api(stage)
    payload = {"stage": api_stage, "note": note or "", "by": by or ""}
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


def delete_file(order: str, item: str, filename: str) -> dict | None:
    """Soft-delete (archive) a file — never passes permanent=true."""
    url = f"{_url(order, item, 'files', filename)}"
    resp = _request("DELETE", url)
    result = _handle_response(resp)
    return result if isinstance(result, dict) else None


def list_archived(order: str, item: str) -> dict:
    url = f"{_url(order, item, 'archive')}"
    resp = _request("GET", url)
    result = _handle_response(resp)
    return result if isinstance(result, dict) else {"files": []}


def restore_file(order: str, item: str, filename: str) -> dict:
    url = f"{_url(order, item, 'archive', filename, 'restore')}"
    resp = _request("POST", url, json={})
    result = _handle_response(resp)
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from file restore")
    return result


def get_notify(order: str) -> dict:
    url = f"{OFFICE_API_URL.rstrip('/')}/orders/{_path(order)}/notify"
    resp = _request("GET", url)
    result = _handle_response(resp, allow_404=True)
    if not result:
        return {"order": order, "enabled": True, "email": None, "updated_at": None}
    return result


def set_notify(order: str, enabled: bool, email: str = "") -> dict:
    url = f"{OFFICE_API_URL.rstrip('/')}/orders/{_path(order)}/notify"
    resp = _request("POST", url, json={"enabled": bool(enabled), "email": (email or "").strip()})
    result = _handle_response(resp)
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from notify update")
    return result


def get_diary_entries() -> dict:
    """All stored diary entries (dispatch date + carrier per order line).

    Expects the Office API to expose ``GET /diary`` returning
    ``{"entries": [{"order", "item", "dispatch_date", "dispatch_manual",
    "carrier", "updated_at"}, ...]}``. Raises OfficeApiError if the endpoint
    is missing/unreachable so callers can fall back to local storage.
    """
    url = f"{OFFICE_API_URL.rstrip('/')}/diary"
    resp = _request("GET", url)
    result = _handle_response(resp)
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from diary list")
    return result


def set_diary_entry(
    order: str,
    item: str,
    *,
    dispatch_date: str | None = None,
    dispatch_manual: bool | None = None,
    carrier: str | None = None,
    tracking_number: str | None = None,
    label_id: str | None = None,
    service_code: str | None = None,
    shipment_type: str | None = None,
) -> dict:
    """Upsert one diary entry via ``PUT /orders/{order}/items/{item}/diary``."""
    url = f"{_url(order, item)}/diary"
    payload: dict = {}
    if dispatch_date is not None:
        payload["dispatch_date"] = dispatch_date
    if dispatch_manual is not None:
        payload["dispatch_manual"] = bool(dispatch_manual)
    if carrier is not None:
        payload["carrier"] = carrier
    if tracking_number is not None:
        payload["tracking_number"] = tracking_number
    if label_id is not None:
        payload["label_id"] = label_id
    if service_code is not None:
        payload["service_code"] = service_code
    if shipment_type is not None:
        payload["shipment_type"] = shipment_type
    resp = _request("PUT", url, json=payload)
    result = _handle_response(resp)
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from diary update")
    return result


_PRINT_TIMEOUT = 45


def _print_error_message(resp: requests.Response) -> str:
    detail = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            detail = (
                body.get("error")
                or body.get("message")
                or body.get("detail")
                or ""
            )
    except Exception:
        detail = (resp.text or "")[:200]

    code = resp.status_code
    if code == 400:
        return detail or "Label data is not valid ZPL (missing ^XA/^XZ)."
    if code == 500:
        return detail or "Office printer is not configured on the server."
    if code == 502:
        return (
            detail
            or "Printer unreachable — the host PC may be asleep or the share is down."
        )
    if code == 504:
        return detail or "Printer did not respond within 30 seconds."
    return detail or f"Print request failed ({code})"


def print_health() -> dict:
    """``GET /print/health`` → ``{configured: bool, ...}``."""
    _require_config()
    url = f"{OFFICE_API_URL.rstrip('/')}/print/health"
    resp = _request("GET", url, timeout=10)
    if not resp.ok:
        logger.warning("Office print health check failed: HTTP %s", resp.status_code)
        return {"configured": False, "ok": False}
    try:
        body = resp.json()
    except Exception:
        return {"configured": False, "ok": False}
    if not isinstance(body, dict):
        return {"configured": False, "ok": False}
    configured = bool(body.get("configured"))
    return {**body, "configured": configured, "ok": True}


def print_label(
    zpl: str | bytes,
    order: str | None = None,
    label_ref: str | None = None,
) -> dict:
    """``POST /print`` with raw ZPL for the office Zebra.

    Body: ``{zpl, order?, label_ref?}``. Raises OfficeApiError on non-200.
    """
    _require_config()
    if isinstance(zpl, bytes):
        zpl_text = zpl.decode("utf-8", errors="replace")
    else:
        zpl_text = str(zpl or "")
    zpl_text = zpl_text.strip()
    if not zpl_text:
        raise OfficeApiError("No ZPL label data to print")

    payload: dict = {"zpl": zpl_text}
    if order:
        payload["order"] = str(order).strip()
    if label_ref:
        payload["label_ref"] = str(label_ref).strip()

    url = f"{OFFICE_API_URL.rstrip('/')}/print"
    resp = _request("POST", url, json=payload, timeout=_PRINT_TIMEOUT)
    if not resp.ok:
        msg = _print_error_message(resp)
        logger.error("Office print failed HTTP %s: %s", resp.status_code, msg)
        raise OfficeApiError(msg)
    try:
        body = resp.json()
    except Exception:
        body = {"ok": True}
    if not isinstance(body, dict):
        return {"ok": True}
    return body
