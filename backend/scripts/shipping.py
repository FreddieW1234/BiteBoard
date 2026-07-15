"""Staff shipping — ShipStation parcels (phase 1); Palletways stub until API key."""

from __future__ import annotations

import logging
from datetime import date

from config import (  # type: ignore
    PALLETWAYS_API_KEY,
    SHIPSTATION_ORIGIN_CITY,
    SHIPSTATION_ORIGIN_COUNTRY,
    SHIPSTATION_ORIGIN_LINE1,
    SHIPSTATION_ORIGIN_LINE2,
    SHIPSTATION_ORIGIN_NAME,
    SHIPSTATION_ORIGIN_PHONE,
    SHIPSTATION_ORIGIN_POSTCODE,
    SHIPSTATION_ORIGIN_STATE,
)
from scripts.order_helpers import fetch_order_by_id  # type: ignore

logger = logging.getLogger(__name__)

PALLET_WEIGHT_KG = 50.0

_CARRIER_MAP = {
    "royal_mail": "royal_mail",
    "fedex": "fedex",
    "stamps_com": "royal_mail",
    "fedex_uk": "fedex",
}


def _shipstation_configured() -> bool:
    try:
        from scripts import shipstation_api  # type: ignore
        return shipstation_api.configured()
    except Exception:
        return False


def shipping_status() -> dict:
    out = {
        "shipstation": _shipstation_configured(),
        "palletways": bool(PALLETWAYS_API_KEY),
        "print_server": _print_configured(),
    }
    if out["shipstation"]:
        try:
            from scripts import shipstation_api  # type: ignore
            warehouse = shipstation_api.get_default_warehouse()
            ship_from = _resolve_ship_from(warehouse)
            out["ship_from_ready"] = bool(ship_from.get("address_line1"))
            if warehouse:
                out["warehouse_name"] = (warehouse.get("name") or "").strip() or None
        except Exception as exc:
            logger.debug("Ship-from status check failed: %s", exc)
            out["ship_from_ready"] = False
    return out


def _print_configured() -> bool:
    try:
        from scripts import print_client  # type: ignore
        return print_client.configured()
    except Exception:
        return False


def prepare_shipment(order_id: str | int) -> dict:
    """Load order details for the shipping modal."""
    order = fetch_order_by_id(order_id)
    if not order:
        return {"success": False, "error": "Order not found"}

    ship_to = order.get("shipping_address")
    if not ship_to:
        return {"success": False, "error": "Order has no shipping address"}

    items = [
        {
            "line_number": li.get("line_number"),
            "title": li.get("title") or "",
            "sku": li.get("sku") or "",
            "quantity": li.get("quantity") or 1,
            "weight_kg": li.get("weight_kg") or 0,
        }
        for li in (order.get("order_items") or [])
        if not li.get("is_fee")
    ]

    total_weight_kg = sum(
        (li.get("weight_kg") or 0) * max(1, int(li.get("quantity") or 1))
        for li in items
    )
    if total_weight_kg <= 0:
        total_weight_kg = 1.0

    return {
        "success": True,
        "order_id": str(order.get("id") or order_id),
        "order_name": order.get("name") or "",
        "company": order.get("company") or "",
        "customer_email": order.get("customer_email") or "",
        "ship_to": ship_to,
        "items": items,
        "defaults": {
            "weight_kg": round(total_weight_kg, 3),
            "length_cm": None,
            "width_cm": None,
            "height_cm": None,
            "shipment_type": "parcel",
        },
        "providers": shipping_status(),
    }


def _resolve_shipment_type(payload: dict) -> str:
    explicit = (payload.get("shipment_type") or "parcel").strip().lower()
    if explicit == "pallet":
        return "pallet"
    weight = float(payload.get("weight_kg") or 0)
    if weight >= PALLET_WEIGHT_KG:
        return "pallet"
    return "parcel"


def quote_shipment(payload: dict) -> dict:
    """Return carrier rates (ShipStation) or pallet placeholder."""
    order_id = payload.get("order_id")
    if not order_id:
        return {"success": False, "error": "order_id is required"}

    shipment_type = _resolve_shipment_type(payload)
    if shipment_type == "pallet":
        if not PALLETWAYS_API_KEY:
            return {
                "success": False,
                "error": "Palletways API key not configured — parcel shipping only for now",
                "shipment_type": "pallet",
                "palletways_pending": True,
            }
        return {"success": False, "error": "Palletways integration coming in phase 2"}

    if not _shipstation_configured():
        return {"success": False, "error": "ShipStation is not configured (set SHIPSTATION_API_KEY)"}

    prep = prepare_shipment(order_id)
    if not prep.get("success"):
        return prep

    try:
        from scripts import shipstation_api  # type: ignore
        from scripts.shipstation_api import ShipStationError  # type: ignore

        shipment = _build_shipstation_shipment(prep, payload)
        rate_resp = shipstation_api.get_rates(shipment)
        rates = _normalize_rates(rate_resp)
        return {
            "success": True,
            "shipment_type": "parcel",
            "order_name": prep.get("order_name"),
            "rates": rates,
        }
    except ShipStationError as exc:
        logger.warning("Shipping quote failed: %s", exc)
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("Shipping quote failed: %s", exc)
        return {"success": False, "error": str(exc)}


def ship_order(payload: dict) -> dict:
    """Purchase label, optional print, save diary metadata."""
    order_id = payload.get("order_id")
    rate_id = (payload.get("rate_id") or "").strip()
    if not order_id:
        return {"success": False, "error": "order_id is required"}
    if not rate_id:
        return {"success": False, "error": "rate_id is required"}

    shipment_type = _resolve_shipment_type(payload)
    if shipment_type == "pallet":
        return {
            "success": False,
            "error": "Pallet shipping is not available until Palletways API key is configured",
        }

    if not _shipstation_configured():
        return {"success": False, "error": "ShipStation is not configured"}

    prep = prepare_shipment(order_id)
    if not prep.get("success"):
        return prep

    try:
        from scripts import print_client, shipstation_api  # type: ignore
        from scripts.Diary import save_diary_entry  # type: ignore

        label = shipstation_api.create_label_from_rate(rate_id, label_format="zpl")
        tracking = str(label.get("tracking_number") or "")
        label_id = str(label.get("label_id") or "")
        carrier_code = str(label.get("carrier_code") or "")
        carrier_friendly = str(label.get("carrier_friendly_name") or carrier_code)
        service_code = str(label.get("service_code") or "")

        downloads = label.get("label_download") or {}
        zpl_url = downloads.get("zpl") or downloads.get("href") or ""
        zpl_bytes = b""
        print_result: dict = {"skipped": True}
        if zpl_url:
            try:
                zpl_bytes = shipstation_api.download_label(zpl_url)
                print_result = print_client.send_print_job(
                    profile="parcel-4x6-zpl",
                    label_format="zpl",
                    data=zpl_bytes,
                    order_name=prep.get("order_name") or "",
                    tracking_number=tracking,
                )
            except Exception as print_exc:
                logger.warning("Label print failed (label still purchased): %s", print_exc)
                print_result = {"success": False, "error": str(print_exc)}

        carrier_slug = _map_carrier_slug(carrier_code)
        order_name = prep.get("order_name") or ""
        today_iso = date.today().isoformat()

        for item in prep.get("items") or []:
            ln = item.get("line_number")
            title = item.get("title") or ""
            if ln is None:
                continue
            from scripts.office_api import item_key  # type: ignore
            item_id = item_key(int(ln), title)
            save_diary_entry({
                "order_name": order_name,
                "item_id": item_id,
                "carrier": carrier_slug,
                "dispatch_date": today_iso,
                "dispatch_manual": True,
                "tracking_number": tracking,
                "label_id": label_id,
                "service_code": service_code,
                "shipment_type": "parcel",
            })

        return {
            "success": True,
            "order_name": order_name,
            "tracking_number": tracking,
            "label_id": label_id,
            "carrier": carrier_slug,
            "carrier_label": carrier_friendly,
            "service_code": service_code,
            "label_download": downloads,
            "print": print_result,
            "has_zpl": bool(zpl_bytes),
        }
    except Exception as exc:
        logger.warning("Shipping purchase failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _parse_dim(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        n = float(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _build_shipstation_shipment(prep: dict, payload: dict) -> dict:
    from scripts import shipstation_api  # type: ignore

    ship_to = prep.get("ship_to") or {}
    warehouse = shipstation_api.get_default_warehouse()

    weight_kg = float(payload.get("weight_kg") or prep.get("defaults", {}).get("weight_kg") or 1.0)
    length_cm = _parse_dim(payload.get("length_cm"))
    width_cm = _parse_dim(payload.get("width_cm"))
    height_cm = _parse_dim(payload.get("height_cm"))

    package: dict = {
        "weight": {"value": max(0.01, weight_kg), "unit": "kilogram"},
    }
    if length_cm and width_cm and height_cm:
        package["dimensions"] = {
            "length": length_cm,
            "width": width_cm,
            "height": height_cm,
            "unit": "centimeter",
        }
    package["package_code"] = "package"

    ship_from = _resolve_ship_from(warehouse)
    if not ship_from.get("address_line1"):
        from scripts.shipstation_api import ShipStationError  # type: ignore
        raise ShipStationError(
            "Ship-from address is not configured. In ShipStation go to Settings → Shipping → "
            "Warehouses and add your dispatch address, or set SHIPSTATION_ORIGIN_* env vars on Render."
        )

    return {
        "validate_address": "no_validation",
        "ship_to": _to_shipstation_address(ship_to),
        "ship_from": ship_from,
        "packages": [package],
    }


def _resolve_ship_from(warehouse: dict | None) -> dict:
    """Ship-from for rates: warehouse origin address, else SHIPSTATION_ORIGIN_* env vars."""
    if warehouse:
        origin = _warehouse_to_address(warehouse)
        if origin.get("address_line1"):
            return origin
    return _origin_from_env()


def _origin_from_env() -> dict:
    if not SHIPSTATION_ORIGIN_LINE1.strip():
        return {}
    return _finalize_ss_address({
        "name": _pick_str(SHIPSTATION_ORIGIN_NAME, default="Warehouse"),
        "phone": _pick_str(SHIPSTATION_ORIGIN_PHONE, default="0000000000"),
        "address_line1": SHIPSTATION_ORIGIN_LINE1.strip(),
        "address_line2": SHIPSTATION_ORIGIN_LINE2.strip() or None,
        "city_locality": SHIPSTATION_ORIGIN_CITY.strip(),
        "state_province": SHIPSTATION_ORIGIN_STATE.strip(),
        "postal_code": SHIPSTATION_ORIGIN_POSTCODE.strip(),
        "country_code": (SHIPSTATION_ORIGIN_COUNTRY or "GB").strip().upper(),
        "address_residential_indicator": "no",
    })


# Allowed keys on ShipStation v2 address objects (request payloads).
_SS_ADDRESS_KEYS = frozenset({
    "name", "phone", "email", "company_name",
    "address_line1", "address_line2", "address_line3",
    "city_locality", "state_province", "postal_code", "country_code",
    "address_residential_indicator", "instructions",
})


def _pick_str(*values: object, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _to_shipstation_address(addr: dict) -> dict:
    """Map Shopify or ShipStation address dict to a strict v2 address payload."""
    residential = _pick_str(
        addr.get("address_residential_indicator"),
        addr.get("addressResidentialIndicator"),
        default="unknown",
    ).lower()
    if residential not in ("unknown", "yes", "no"):
        residential = "unknown"

    mapped = {
        "name": _pick_str(addr.get("name"), addr.get("company"), default="Recipient"),
        "phone": _pick_str(addr.get("phone"), default="0000000000"),
        "email": _pick_str(addr.get("email")) or None,
        "company_name": _pick_str(addr.get("company_name"), addr.get("company")) or None,
        "address_line1": _pick_str(
            addr.get("address_line1"), addr.get("addressLine1"),
            addr.get("address1"), addr.get("address_line_1"),
        ),
        "address_line2": _pick_str(
            addr.get("address_line2"), addr.get("addressLine2"),
            addr.get("address2"), addr.get("address_line_2"),
        ) or None,
        "address_line3": _pick_str(
            addr.get("address_line3"), addr.get("addressLine3"), addr.get("address3"),
        ) or None,
        "city_locality": _pick_str(
            addr.get("city_locality"), addr.get("cityLocality"), addr.get("city"),
        ),
        "state_province": _pick_str(
            addr.get("state_province"), addr.get("stateProvince"),
            addr.get("province"), addr.get("state"),
        ),
        "postal_code": _pick_str(addr.get("postal_code"), addr.get("postalCode"), addr.get("zip")),
        "country_code": _pick_str(addr.get("country_code"), addr.get("countryCode"), default="GB").upper(),
        "address_residential_indicator": residential,
    }
    return _finalize_ss_address(mapped)


def _warehouse_to_address(warehouse: dict | None) -> dict:
    if not warehouse:
        return {}
    origin = warehouse.get("origin_address") or warehouse.get("return_address") or warehouse
    mapped = {
        "name": _pick_str(origin.get("name"), warehouse.get("name"), default="Warehouse"),
        "phone": _pick_str(origin.get("phone"), warehouse.get("phone"), default="0000000000"),
        "email": _pick_str(origin.get("email")) or None,
        "company_name": _pick_str(
            origin.get("company_name"), origin.get("company"), warehouse.get("company"),
        ) or None,
        "address_line1": _pick_str(
            origin.get("address_line1"), origin.get("addressLine1"),
            origin.get("address1"), origin.get("address_line_1"),
        ),
        "address_line2": _pick_str(
            origin.get("address_line2"), origin.get("addressLine2"),
            origin.get("address2"), origin.get("address_line_2"),
        ) or None,
        "address_line3": _pick_str(
            origin.get("address_line3"), origin.get("addressLine3"), origin.get("address3"),
        ) or None,
        "city_locality": _pick_str(
            origin.get("city_locality"), origin.get("cityLocality"), origin.get("city"),
        ),
        "state_province": _pick_str(
            origin.get("state_province"), origin.get("stateProvince"),
            origin.get("state"), origin.get("province"),
        ),
        "postal_code": _pick_str(
            origin.get("postal_code"), origin.get("postalCode"), origin.get("zip"),
        ),
        "country_code": _pick_str(
            origin.get("country_code"), origin.get("countryCode"), default="GB",
        ).upper(),
        "address_residential_indicator": "no",
    }
    return _finalize_ss_address(mapped)


def _finalize_ss_address(mapped: dict) -> dict:
    """Drop unknown keys and empty optional fields; keep required address fields."""
    out: dict = {}
    for key in _SS_ADDRESS_KEYS:
        value = mapped.get(key)
        if value is None or value == "":
            continue
        out[key] = value

    out.setdefault("name", "Recipient")
    out.setdefault("phone", "0000000000")
    out.setdefault("address_line1", mapped.get("address_line1") or "Address")
    out.setdefault("city_locality", mapped.get("city_locality") or "")
    out.setdefault("state_province", mapped.get("state_province") or "")
    out.setdefault("postal_code", mapped.get("postal_code") or "")
    out.setdefault("country_code", (mapped.get("country_code") or "GB").upper())
    out.setdefault("address_residential_indicator", "unknown")
    return out


def _normalize_rates(rate_resp: dict) -> list[dict]:
    rates = rate_resp.get("rate_response", {}).get("rates")
    if rates is None:
        rates = rate_resp.get("rates") or []
    out: list[dict] = []
    for r in rates or []:
        amount = r.get("shipping_amount") or r.get("total_amount") or {}
        if isinstance(amount, dict):
            price = amount.get("amount")
            currency = amount.get("currency") or "GBP"
        else:
            price = amount
            currency = "GBP"
        out.append({
            "rate_id": r.get("rate_id") or "",
            "carrier_id": r.get("carrier_id") or "",
            "carrier_code": r.get("carrier_code") or "",
            "carrier_friendly_name": r.get("carrier_friendly_name") or r.get("carrier_nickname") or "",
            "service_code": r.get("service_code") or "",
            "service_type": r.get("service_type") or r.get("service_code") or "",
            "delivery_days": r.get("delivery_days"),
            "price": price,
            "currency": currency,
        })
    out.sort(key=lambda x: (x.get("price") is None, x.get("price") or 999999))
    return out


def _map_carrier_slug(carrier_code: str) -> str:
    code = (carrier_code or "").lower()
    for key, slug in _CARRIER_MAP.items():
        if key in code:
            return slug
    if "fedex" in code:
        return "fedex"
    if "royal" in code or "mail" in code:
        return "royal_mail"
    return code or ""
