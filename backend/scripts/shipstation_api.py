"""Client for ShipStation API v2 (rates + labels)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from config import SHIPSTATION_API_KEY, SHIPSTATION_API_URL, SHIPSTATION_WAREHOUSE_ID  # type: ignore

logger = logging.getLogger(__name__)

_TIMEOUT = 45
_session: requests.Session | None = None


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


def _format_error_body(body: dict) -> str:
    detail = body.get("message") or body.get("error") or ""
    errors = body.get("errors")
    if errors:
        parts: list[str] = []
        for err in errors if isinstance(errors, list) else [errors]:
            if isinstance(err, dict):
                msg = str(err.get("message") or err)
                field = err.get("field_name")
                if field:
                    parts.append(f"{field}: {msg}")
                else:
                    parts.append(msg)
            else:
                parts.append(str(err))
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


def create_shipment(shipment: dict) -> dict:
    """Create a pending shipment and return the first created record."""
    data = _handle_response(_request("POST", "/v2/shipments", json={"shipments": [shipment]}))
    shipments = (data or {}).get("shipments") if isinstance(data, dict) else None
    if not shipments:
        raise ShipStationError("ShipStation did not return a shipment")
    return shipments[0]


def get_rates(shipment: dict, *, carrier_ids: list[str] | None = None) -> dict:
    """Return rate quote response from POST /v2/rates."""
    if not carrier_ids:
        carrier_ids = [
            str(c.get("carrier_id") or "")
            for c in list_carriers()
            if c.get("carrier_id")
        ]
    if not carrier_ids:
        raise ShipStationError("No carriers connected in ShipStation")

    rate_options = {"carrier_ids": carrier_ids}
    validate_address = shipment.pop("validate_address", "no_validation")

    inline_payload: dict[str, Any] = {
        "rate_options": rate_options,
        "validate_address": validate_address,
        "shipment": shipment,
    }
    resp = _request("POST", "/v2/rates", json=inline_payload)
    if resp.ok:
        return _handle_response(resp)

    inline_error = ""
    try:
        inline_error = _format_error_body(resp.json())
    except Exception:
        inline_error = (resp.text or "")[:300]
    logger.warning(
        "ShipStation inline rates failed (%s): %s — retrying via shipment_id",
        resp.status_code,
        inline_error,
    )

    created = create_shipment({**shipment, "validate_address": validate_address})
    shipment_id = str(created.get("shipment_id") or "")
    if not shipment_id:
        raise ShipStationError(inline_error or "ShipStation did not return a shipment_id")

    return _handle_response(
        _request(
            "POST",
            "/v2/rates",
            json={"rate_options": rate_options, "shipment_id": shipment_id},
        )
    )


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
        "shipment": shipment,
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
