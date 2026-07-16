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


def _order_key_variants(order: str) -> list[str]:
    """Try both ``#S1065`` and ``S1065`` — disk folders vary."""
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


def _entry_name(entry) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if not isinstance(entry, dict):
        return ""
    return str(
        entry.get("name")
        or entry.get("filename")
        or entry.get("file")
        or entry.get("path")
        or entry.get("latest")
        or ""
    ).strip()


def _entry_kind(entry) -> str:
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("kind") or entry.get("type") or entry.get("role") or "").strip().lower()


def _filename_looks_like_label(name: str, kind: str = "") -> bool:
    """Match label files in the order/item folder (same place as artwork)."""
    kind_l = (kind or "").strip().lower()
    if kind_l in ("label", "shipping_label", "shipping-label", "zpl"):
        return True
    text = (name or "").strip().lower()
    if not text:
        return False
    base = text.rsplit("/", 1)[-1]
    if base.startswith("label-") or base.startswith("label_"):
        return True
    if base.endswith(".zpl") or base.endswith(".zplii"):
        return True
    if "label" in base and (base.endswith(".txt") or base.endswith(".raw")):
        return True
    return False


def _version_from_name(name: str) -> int:
    match = re.search(r"-v(\d+)\.(?:zpl|zplii|txt|raw)?$", (name or "").lower())
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    return 0


def _collect_names_from_payload(payload) -> list[tuple[str, str]]:
    """Return [(filename, kind), ...] from labels/files list payloads."""
    rows = []
    if isinstance(payload, dict):
        latest = payload.get("latest")
        if isinstance(latest, str) and latest.strip():
            rows.append((latest.strip(), "label"))
        for key in ("labels", "files", "items"):
            block = payload.get(key)
            if isinstance(block, list):
                rows.extend(_collect_names_from_payload(block))
            elif isinstance(block, dict):
                rows.extend(_collect_names_from_payload([block]))
        # Single-file style dict
        name = _entry_name(payload)
        if name and name != latest:
            rows.append((name, _entry_kind(payload)))
    elif isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, str):
                rows.append((entry.strip(), ""))
            elif isinstance(entry, dict):
                name = _entry_name(entry)
                if name:
                    rows.append((name, _entry_kind(entry)))
    return [(n, k) for n, k in rows if n]


def find_label_files(order: str, item: str) -> list[dict]:
    """Find shipping label files in the office order/item folder.

    Disk layout (via Office API):
      Online Store/orders/{order}/{item}/label-*.zpl
    HTTP:
      GET /orders/{order}/items/{item}/files
      GET /orders/{order}/items/{item}/labels  (optional)
    """
    order = (order or "").strip()
    item = (item or "").strip()
    found: list[dict] = []
    seen: set[str] = set()

    def _add(name: str, *, source: str, kind: str = "", order_key: str = "") -> None:
        if not name or name in seen:
            return
        if not _filename_looks_like_label(name, kind):
            return
        seen.add(name)
        found.append({
            "filename": name,
            "source": source,
            "kind": kind,
            "order_key": order_key or order,
            "version": _version_from_name(name),
        })

    for order_key in _order_key_variants(order):
        # Primary: same /files listing used for artwork/proofs in that folder.
        try:
            listed = list_files(order_key, item)
            for name, kind in _collect_names_from_payload(listed):
                _add(name, source="files", kind=kind, order_key=order_key)
            raw_files = (listed or {}).get("files") if isinstance(listed, dict) else listed
            sample = []
            if isinstance(raw_files, list):
                for entry in raw_files[:12]:
                    sample.append(_entry_name(entry) or str(entry)[:40])
            logger.warning(
                "label scan /files order=%s item=%s count=%s sample=%s",
                order_key,
                item,
                len(raw_files) if isinstance(raw_files, list) else 0,
                sample,
            )
        except Exception as exc:
            logger.warning("label scan /files failed for %s / %s: %s", order_key, item, exc)

        # Optional dedicated labels index.
        try:
            labels = list_labels(order_key, item)
            for name, kind in _collect_names_from_payload(labels):
                _add(name, source="labels", kind=kind or "label", order_key=order_key)
        except Exception as exc:
            logger.warning("label scan /labels failed for %s / %s: %s", order_key, item, exc)

    # Newest version first, then filename.
    found.sort(key=lambda row: (row.get("version") or 0, row.get("filename") or ""), reverse=True)
    return found


def get_label(order: str, item: str, version: int | None = None) -> dict:
    """Load ZPL for an order line from the office order/item folder.

    Prefers dedicated ``GET …/label``, then falls back to ``GET …/files/{filename}``
    for ``label-*.zpl`` files sitting beside artwork/proofs.
    """
    _require_config()
    order = (order or "").strip()
    item = (item or "").strip()
    if not order or not item:
        raise OfficeApiError("order and item are required")

    # 1) Dedicated label endpoint (when office implements it).
    for order_key in _order_key_variants(order):
        url = f"{_url(order_key, item)}/label"
        params = {"version": int(version)} if version is not None else None
        try:
            resp = _request("GET", url, params=params, timeout=_TIMEOUT)
        except Exception as exc:
            logger.warning("GET /label failed for %s / %s: %s", order_key, item, exc)
            continue
        if resp.status_code == 404:
            continue
        if not resp.ok:
            logger.warning(
                "GET /label HTTP %s for %s / %s: %s",
                resp.status_code,
                order_key,
                item,
                (resp.text or "")[:160],
            )
            continue
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "json" in ctype:
            try:
                body = resp.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                zpl = _as_zpl_text(body.get("zpl") or "")
                if zpl:
                    return {**body, "zpl": zpl, "order_key": order_key, "source": "label"}
        else:
            zpl = _as_zpl_text(resp.content or b"")
            if zpl:
                return {
                    "zpl": zpl,
                    "filename": "",
                    "order_key": order_key,
                    "source": "label-raw",
                }

    # 2) Read label-*.zpl from the item files folder (disk source of truth).
    candidates = find_label_files(order, item)
    if version is not None:
        versioned = [c for c in candidates if c.get("version") == int(version)]
        if versioned:
            candidates = versioned
    if not candidates:
        raise OfficeApiError(
            "No stored label in office folder "
            f"orders/{order}/{item}/ (looked for label-*.zpl via /files)"
        )

    chosen = candidates[0]
    order_key = chosen.get("order_key") or order
    filename = chosen["filename"]
    resp = fetch_file(order_key, item, filename)
    zpl = _as_zpl_text(resp.content or b"")
    if not zpl:
        raise OfficeApiError(f"Office file {filename!r} is not valid ZPL")
    return {
        "zpl": zpl,
        "filename": filename,
        "version": chosen.get("version"),
        "order_key": order_key,
        "source": "files",
        "carrier": "fedex" if "fedex" in filename.lower() else "",
    }


def has_label(order: str, item: str) -> bool:
    """True when a label file exists in the office order/item folder."""
    item = (item or "").strip()
    if not item:
        return False
    try:
        _require_config()
    except OfficeApiError:
        return False
    try:
        found = find_label_files(order, item)
        if found:
            logger.warning(
                "has_label True for %s / %s via %s (%s)",
                order,
                item,
                found[0].get("source"),
                found[0].get("filename"),
            )
            return True
    except Exception as exc:
        logger.warning("has_label scan failed for %s / %s: %s", order, item, exc)

    # Last resort: dedicated GET /label
    for order_key in _order_key_variants(order):
        url = f"{_url(order_key, item)}/label"
        try:
            resp = _request("GET", url, timeout=12, stream=True)
        except Exception:
            continue
        try:
            if resp.status_code == 200:
                logger.warning("has_label True via GET /label for %s / %s", order_key, item)
                return True
        finally:
            resp.close()
    return False


def labels_status(pairs: list[tuple[str, str]]) -> dict[str, dict]:
    """Batch label presence keyed by ``order\\titem``."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out: dict[str, dict] = {}
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

    def _probe(order: str, item: str) -> dict:
        found = find_label_files(order, item)
        if found:
            return {
                "has_label": True,
                "filename": found[0].get("filename"),
                "source": found[0].get("source"),
                "version": found[0].get("version"),
            }
        # Dedicated /label route only (files already scanned).
        for order_key in _order_key_variants(order):
            url = f"{_url(order_key, item)}/label"
            try:
                resp = _request("GET", url, timeout=12, stream=True)
            except Exception:
                continue
            try:
                if resp.status_code == 200:
                    return {"has_label": True, "source": "label", "filename": None}
            finally:
                resp.close()
        return {"has_label": False}

    workers = min(6, len(cleaned))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_probe, order, item): key
            for key, order, item in cleaned
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                out[key] = fut.result()
            except Exception as exc:
                logger.warning("labels_status failed for %s: %s", key, exc)
                out[key] = {"has_label": False, "error": str(exc)}
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
