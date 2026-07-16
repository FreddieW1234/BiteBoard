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
        kwargs.setdefault("timeout", _TIMEOUT)
        return _session_get().request(method, url, **kwargs)
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
    result = _handle_response(resp, allow_404=True)
    if result is None:
        return {"files": []}
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


def _as_zpl_text(zpl: str | bytes) -> str:
    """Normalize FedEx/office label bytes into raw ZPL text (^XA…^XZ)."""
    if isinstance(zpl, bytes):
        text = zpl.decode("utf-8", errors="replace")
    else:
        text = str(zpl or "")
    text = text.strip()
    if not text:
        return ""

    upper = text.upper()
    if "^XA" in upper and "^XZ" in upper:
        return text

    # FedEx sometimes leaves us with base64 text instead of decoded ZPL.
    try:
        import base64
        import re

        compact = re.sub(r"\s+", "", text)
        decoded = base64.b64decode(compact, validate=False)
        as_text = decoded.decode("utf-8", errors="replace").strip()
        as_upper = as_text.upper()
        if "^XA" in as_upper and "^XZ" in as_upper:
            return as_text
    except Exception:
        pass
    return text


def store_label(
    order: str,
    item: str,
    zpl: str | bytes,
    *,
    tracking: str | None = None,
    carrier: str | None = None,
    item_label: str | None = None,
) -> dict:
    """``POST /orders/{order}/items/{item}/label`` — persist ZPL on office disk."""
    _require_config()
    order = (order or "").strip()
    item = (item or "").strip()
    if not order or not item:
        raise OfficeApiError("order and item are required to store a label")

    zpl_text = _as_zpl_text(zpl)
    if not zpl_text:
        raise OfficeApiError("No ZPL label data to store")
    upper = zpl_text.upper()
    if "^XA" not in upper or "^XZ" not in upper:
        preview = zpl_text[:80].replace("\n", "\\n")
        raise OfficeApiError(
            f"Label data is not valid ZPL (missing ^XA/^XZ). Preview: {preview!r}"
        )

    # Ensure the order/item folder exists (same as artwork/proof uploads).
    try:
        ensure_item(order, item, item_label or item)
    except OfficeApiError as exc:
        logger.warning("Office ensure_item before label store: %s", exc)

    payload: dict = {"zpl": zpl_text}
    if tracking:
        payload["tracking"] = str(tracking).strip()
    if carrier:
        payload["carrier"] = str(carrier).strip().lower()

    url = f"{_url(order, item)}/label"
    logger.info("Office store_label POST %s (zpl_len=%s)", url, len(zpl_text))
    resp = _request("POST", url, json=payload, timeout=_TIMEOUT)
    if not resp.ok:
        msg = _print_error_message(resp)
        logger.error(
            "Office store_label failed HTTP %s for %s / %s: %s | body=%s",
            resp.status_code,
            order,
            item,
            msg,
            (resp.text or "")[:300],
        )
        raise OfficeApiError(msg)
    result = _handle_response(resp)
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from label store")
    logger.info(
        "Office store_label ok for %s / %s → %s v%s",
        order,
        item,
        result.get("filename"),
        result.get("version"),
    )
    return result


def list_labels(order: str, item: str) -> dict:
    """``GET /orders/{order}/items/{item}/labels`` — newest first."""
    _require_config()
    url = f"{_url(order, item)}/labels"
    resp = _request("GET", url, timeout=_TIMEOUT)
    result = _handle_response(resp, allow_404=True)
    if result is None:
        return {"labels": [], "latest": None}
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from labels list")
    return result


def get_label(order: str, item: str, version: int | None = None) -> dict:
    """``GET /orders/{order}/items/{item}/label`` — latest ZPL, or ``?version=N``."""
    _require_config()
    url = f"{_url(order, item)}/label"
    params = {}
    if version is not None:
        params["version"] = int(version)
    resp = _request("GET", url, params=params or None, timeout=_TIMEOUT)
    result = _handle_response(resp, allow_404=True)
    if result is None:
        raise OfficeApiError("No stored label for this order line")
    if not isinstance(result, dict):
        raise OfficeApiError("Unexpected response from label fetch")
    zpl = _as_zpl_text(result.get("zpl") or "")
    if not zpl:
        raise OfficeApiError("Stored label has no ZPL content")
    return {**result, "zpl": zpl}


def _list_indicates_label(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("latest") or data.get("filename") or data.get("ok") is True:
        if data.get("latest") or data.get("filename"):
            return True
        # {"ok": true, "count": N} style
        count = data.get("count") or data.get("total")
        if isinstance(count, int) and count > 0:
            return True
    labels = data.get("labels")
    if labels is None:
        labels = data.get("files") or data.get("items") or data.get("label")
    if isinstance(labels, list) and len(labels) > 0:
        return True
    if isinstance(labels, dict) and labels:
        return True
    if isinstance(labels, str) and labels.strip():
        return True
    return False


def _filename_looks_like_label(name: str) -> bool:
    text = (name or "").strip().lower()
    if not text:
        return False
    base = text.rsplit("/", 1)[-1]
    return base.startswith("label-") or base.endswith(".zpl")


def _files_include_label(payload) -> bool:
    """True when office ``/files`` lists a stored shipping label."""
    files = []
    if isinstance(payload, dict):
        files = payload.get("files") or payload.get("items") or payload.get("labels") or []
    elif isinstance(payload, list):
        files = payload
    for entry in files:
        if isinstance(entry, str):
            if _filename_looks_like_label(entry):
                return True
            continue
        if not isinstance(entry, dict):
            continue
        name = (
            entry.get("filename")
            or entry.get("name")
            or entry.get("file")
            or entry.get("path")
            or ""
        )
        if _filename_looks_like_label(str(name)):
            return True
    return False


def _order_key_variants(order: str) -> list[str]:
    """Try both ``#S1065`` and ``S1065`` — office folders vary."""
    text = (order or "").strip()
    if not text:
        return []
    variants = [text]
    if text.startswith("#"):
        variants.append(text[1:].strip())
    else:
        variants.append(f"#{text}")
    out: list[str] = []
    seen: set[str] = set()
    for value in variants:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _probe_label_endpoint(order: str, item: str) -> bool | None:
    """Return True/False if we got a clear answer, None if inconclusive."""
    url = f"{_url(order, item)}/label"
    try:
        resp = _request("GET", url, timeout=12, stream=True)
    except Exception as exc:
        logger.warning("Office GET /label probe failed for %s / %s: %s", order, item, exc)
        return None
    try:
        code = resp.status_code
        if code == 200:
            # Confirm body looks like a label without reading the whole ZPL.
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "json" in ctype:
                try:
                    body = resp.json()
                except Exception:
                    body = {}
                if isinstance(body, dict) and (
                    body.get("zpl")
                    or body.get("filename")
                    or body.get("latest")
                    or body.get("ok") is True
                ):
                    return True
                # 200 JSON without those keys — still treat as present.
                return True
            return True
        if code == 404:
            return False
        logger.warning(
            "Office GET /label probe HTTP %s for %s / %s: %s",
            code,
            order,
            item,
            (resp.text or "")[:160],
        )
        return None
    finally:
        resp.close()


def _has_label_one(order: str, item: str) -> bool:
    """Check one order/item key pair on the office server."""
    # 1) Dedicated labels list.
    try:
        data = list_labels(order, item)
        if _list_indicates_label(data):
            logger.warning("has_label True via /labels for %s / %s", order, item)
            return True
        logger.warning(
            "has_label /labels empty for %s / %s keys=%s",
            order,
            item,
            list(data.keys()) if isinstance(data, dict) else type(data),
        )
    except Exception as exc:
        logger.warning("Office list_labels in has_label for %s / %s: %s", order, item, exc)

    # 2) Item files folder (labels live next to artwork/proofs).
    try:
        files = list_files(order, item)
        if _files_include_label(files):
            logger.warning("has_label True via /files for %s / %s", order, item)
            return True
        names = []
        raw = (files or {}).get("files") if isinstance(files, dict) else files
        if isinstance(raw, list):
            for entry in raw[:8]:
                if isinstance(entry, str):
                    names.append(entry)
                elif isinstance(entry, dict):
                    names.append(str(entry.get("filename") or entry.get("name") or ""))
        logger.warning(
            "has_label /files no label match for %s / %s sample=%s",
            order,
            item,
            names,
        )
    except Exception as exc:
        logger.warning("Office list_files in has_label for %s / %s: %s", order, item, exc)

    # 3) GET /label existence probe (do not download full ZPL into memory).
    probed = _probe_label_endpoint(order, item)
    if probed is True:
        logger.warning("has_label True via GET /label for %s / %s", order, item)
        return True
    if probed is False:
        return False
    return False


def has_label(order: str, item: str) -> bool:
    """True when the office server has a stored label for this order line."""
    item = (item or "").strip()
    if not item:
        return False
    try:
        _require_config()
    except OfficeApiError:
        return False

    for order_key in _order_key_variants(order):
        if _has_label_one(order_key, item):
            return True
    return False


def labels_status(pairs: list[tuple[str, str]]) -> dict[str, bool]:
    """Batch ``has_label`` keyed by ``order\\titem`` (parallel probes)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out: dict[str, bool] = {}
    cleaned: list[tuple[str, str, str]] = []
    for order, item in pairs:
        order_s = (order or "").strip()
        item_s = (item or "").strip()
        key = f"{order_s}\t{item_s}"
        if not order_s or not item_s:
            continue
        cleaned.append((key, order_s, item_s))

    if not cleaned:
        return out

    workers = min(6, len(cleaned))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(has_label, order, item): key
            for key, order, item in cleaned
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                out[key] = bool(fut.result())
            except Exception as exc:
                logger.warning("labels_status failed for %s: %s", key, exc)
                out[key] = False
    return out


def print_label(
    zpl: str | bytes,
    order: str | None = None,
    label_ref: str | None = None,
) -> dict:
    """``POST /print`` with raw ZPL for the office Zebra.

    Body: ``{zpl, order?, label_ref?}``. Raises OfficeApiError on non-200.
    """
    _require_config()
    zpl_text = _as_zpl_text(zpl)
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
