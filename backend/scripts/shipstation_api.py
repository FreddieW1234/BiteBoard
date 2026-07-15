"""Client for ShipStation API v2 (rates + labels)."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from config import SHIPSTATION_API_KEY, SHIPSTATION_API_URL, SHIPSTATION_WAREHOUSE_ID  # type: ignore

logger = logging.getLogger(__name__)

_TIMEOUT = 45
_session: requests.Session | None = None

# Allowed address keys for ShipStation v2 request payloads.
_ADDRESS_KEYS = frozenset({
    "name", "phone", "email", "company_name",
    "address_line1", "address_line2", "address_line3",
    "city_locality", "state_province", "postal_code", "country_code",
    "address_residential_indicator", "instructions",
})

# Allowed keys on inline rate / create shipment objects.
_SHIPMENT_KEYS = frozenset({
    "validate_address", "ship_to", "ship_from", "packages",
})


class ShipStationError(Exception):
    """Raised when ShipStation returns an error or is unreachable."""


def configured() -> bool:
    return bool(SHIPSTATION_API_KEY and SHIPSTATION_API_URL)


def _session_get() -> requests.Session:
    global _session
    if not configured():
        raise ShipStationError("ShipStation is not configured (set SHIPSTATION_API_KEY)")
    if _session is None:
        _session = requests.Session()
        _session.headers["api-key"] = SHIPSTATION_API_KEY
        _session.headers["Content-Type"] = "application/json"
    return _session


def _url(path: str) -> str:
    base = SHIPSTATION_API_URL.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def _request(method: str, path: str, **kwargs) -> requests.Response:
    try:
        return _session_get().request(method, _url(path), timeout=_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        logger.error("ShipStation request failed: %s", exc)
        raise ShipStationError("ShipStation service unavailable") from exc


def scrub_address(addr: dict | None) -> dict:
    """Keep only ShipStation-allowed address fields with non-empty values."""
    if not isinstance(addr, dict):
        return {}
    return {
        k: v for k, v in addr.items()
        if k in _ADDRESS_KEYS and v is not None and v != ""
    }


def _scrub_package(pkg: dict) -> dict:
    out: dict[str, Any] = {}
    weight = pkg.get("weight")
    if isinstance(weight, dict):
        out["weight"] = {
            "value": max(0.01, float(weight.get("value") or 1)),
            "unit": weight.get("unit") or "kilogram",
        }
    code = (pkg.get("package_code") or "").strip()
    if code:
        out["package_code"] = code
    dims = pkg.get("dimensions")
    if isinstance(dims, dict):
        length = dims.get("length")
        width = dims.get("width")
        height = dims.get("height")
        if length and width and height:
            out["dimensions"] = {
                "length": float(length),
                "width": float(width),
                "height": float(height),
                "unit": dims.get("unit") or "centimeter",
            }
    return out


def scrub_shipment(shipment: dict) -> dict:
    """Strip unknown keys before sending to ShipStation."""
    out: dict[str, Any] = {}
    for key in _SHIPMENT_KEYS:
        if key not in shipment:
            continue
        val = shipment[key]
        if key in ("ship_to", "ship_from"):
            cleaned = scrub_address(val if isinstance(val, dict) else None)
            if cleaned:
                out[key] = cleaned
        elif key == "packages" and isinstance(val, list):
            packages = [_scrub_package(p) for p in val if isinstance(p, dict)]
            packages = [p for p in packages if p.get("weight")]
            if packages:
                out[key] = packages
        elif val is not None:
            out[key] = val
    return out


def _format_error_body(body: dict) -> str:
    detail = body.get("message") or body.get("error") or ""
    errors = body.get("errors")
    if errors:
        parts: list[str] = []
        seen: set[str] = set()
        for err in errors if isinstance(errors, list) else [errors]:
            if isinstance(err, dict):
                msg = str(err.get("message") or err).strip()
                field = err.get("field_name")
                if field and field not in msg:
                    line = f"{field}: {msg}"
                else:
                    line = msg
            else:
                line = str(err).strip()
            if line and line not in seen:
                seen.add(line)
                parts.append(line)
            if len(parts) >= 5:
                break
        if parts:
            return "; ".join(parts)
    return str(detail)


def _handle_response(resp: requests.Response) -> Any:
    if resp.status_code == 401:
        raise ShipStationError("ShipStation authentication failed — check SHIPSTATION_API_KEY")
    if not resp.ok:
        detail = ""
        try:
            body = resp.json()
            detail = _format_error_body(body if isinstance(body, dict) else {})
        except Exception:
            detail = (resp.text or "")[:300]
        logger.error("ShipStation HTTP %s: %s", resp.status_code, detail or resp.reason)
        raise ShipStationError(detail or f"ShipStation request failed ({resp.status_code})")
    if resp.status_code == 204:
        return None
    try:
        return resp.json()
    except Exception:
        return resp.text


def list_warehouses() -> list[dict]:
    data = _handle_response(_request("GET", "/v2/warehouses"))
    if isinstance(data, dict):
        return list(data.get("warehouses") or [])
    if isinstance(data, list):
        return data
    return []


def list_carriers() -> list[dict]:
    data = _handle_response(_request("GET", "/v2/carriers"))
    if isinstance(data, dict):
        return list(data.get("carriers") or [])
    if isinstance(data, list):
        return data
    return []


def get_default_warehouse() -> dict | None:
    warehouses = list_warehouses()
    if not warehouses:
        return None
    if SHIPSTATION_WAREHOUSE_ID:
        for wh in warehouses:
            if str(wh.get("warehouse_id") or wh.get("id") or "") == SHIPSTATION_WAREHOUSE_ID:
                return wh
    return warehouses[0]


def get_rates(shipment: dict, *, carrier_ids: list[str] | None = None) -> dict:
    """Quote rates via POST /v2/rates with inline shipment details."""
    if not carrier_ids:
        carrier_ids = [
            str(c.get("carrier_id") or "")
            for c in list_carriers()
            if c.get("carrier_id")
        ]
    if not carrier_ids:
        raise ShipStationError("No carriers connected in ShipStation")

    cleaned = scrub_shipment(shipment)
    if not cleaned.get("ship_to"):
        raise ShipStationError("Ship-to address is missing or invalid")
    if not cleaned.get("ship_from"):
        raise ShipStationError(
            "Ship-from address is missing. Add a warehouse in ShipStation "
            "(Settings → Shipping → Warehouses) or set SHIPSTATION_ORIGIN_* env vars on Render."
        )
    if not cleaned.get("packages"):
        raise ShipStationError("Package weight is required")

    payload = {
        "rate_options": {"carrier_ids": carrier_ids},
        "shipment": cleaned,
    }
    logger.info(
        "ShipStation rates request: shipment_keys=%s ship_to_keys=%s ship_from_keys=%s",
        sorted(cleaned.keys()),
        sorted(cleaned.get("ship_to", {}).keys()),
        sorted(cleaned.get("ship_from", {}).keys()),
    )
    resp = _request("POST", "/v2/rates", json=payload)
    if not resp.ok:
        try:
            logger.warning(
                "ShipStation rates payload rejected: %s",
                json.dumps(payload, default=str)[:800],
            )
        except Exception:
            pass
    return _handle_response(resp)


def create_label_from_rate(rate_id: str, *, label_format: str = "zpl") -> dict:
    """Purchase label using a previously quoted rate_id."""
    payload = {
        "label_format": label_format,
        "label_layout": "4x6",
    }
    return _handle_response(
        _request("POST", f"/v2/labels/rates/{rate_id}", json=payload)
    )


def create_label(shipment: dict, *, label_format: str = "zpl") -> dict:
    """Purchase label with full shipment payload."""
    payload = {
        "shipment": scrub_shipment(shipment),
        "label_format": label_format,
        "label_layout": "4x6",
    }
    return _handle_response(_request("POST", "/v2/labels", json=payload))


def download_label(url: str) -> bytes:
    """Download label bytes (ZPL/PDF) from ShipStation CDN URL."""
    try:
        resp = _session_get().get(url, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise ShipStationError("Could not download label file") from exc
    if not resp.ok:
        raise ShipStationError(f"Label download failed ({resp.status_code})")
    return resp.content
