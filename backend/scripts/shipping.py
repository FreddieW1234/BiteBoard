"""Staff shipping — ShipStation parcels (phase 1); Palletways stub until API key."""

from __future__ import annotations

import logging
from datetime import date

from config import PALLETWAYS_API_KEY  # type: ignore
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
    return {
        "shipstation": _shipstation_configured(),
        "palletways": bool(PALLETWAYS_API_KEY),
        "print_server": _print_configured(),
    }


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
        }
        for li in (order.get("order_items") or [])
        if not li.get("is_fee")
    ]

    return {
        "success": True,
        "order_id": str(order.get("id") or order_id),
        "order_name": order.get("name") or "",
        "company": order.get("company") or "",
        "customer_email": order.get("customer_email") or "",
        "ship_to": ship_to,
        "items": items,
        "defaults": {
            "weight_kg": 1.0,
            "length_cm": 30,
            "width_cm": 25,
            "height_cm": 10,
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

        shipment = _build_shipstation_shipment(prep, payload)
        rate_resp = shipstation_api.get_rates(shipment)
        rates = _normalize_rates(rate_resp)
        return {
            "success": True,
            "shipment_type": "parcel",
            "order_name": prep.get("order_name"),
            "rates": rates,
        }
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


def _build_shipstation_shipment(prep: dict, payload: dict) -> dict:
    from scripts import shipstation_api  # type: ignore

    ship_to = prep.get("ship_to") or {}
    warehouse = shipstation_api.get_default_warehouse()
    ship_from = _warehouse_to_address(warehouse) if warehouse else None

    weight_kg = float(payload.get("weight_kg") or 1.0)
    length_cm = float(payload.get("length_cm") or 30)
    width_cm = float(payload.get("width_cm") or 25)
    height_cm = float(payload.get("height_cm") or 10)

    packages = [{
        "weight": {"value": max(0.01, weight_kg), "unit": "kilogram"},
        "dimensions": {
            "length": max(1, length_cm),
            "width": max(1, width_cm),
            "height": max(1, height_cm),
            "unit": "centimeter",
        },
        "package_code": "package",
    }]

    shipment: dict = {
        "validate_address": "no_validation",
        "ship_to": _to_shipstation_address(ship_to),
        "packages": packages,
        "external_order_id": prep.get("order_name") or "",
    }
    if ship_from:
        shipment["ship_from"] = ship_from
    if warehouse:
        wh_id = warehouse.get("warehouse_id") or warehouse.get("id")
        if wh_id:
            shipment["warehouse_id"] = wh_id
    return shipment


def _to_shipstation_address(addr: dict) -> dict:
    return {
        "name": (addr.get("name") or addr.get("company") or "Recipient").strip(),
        "company_name": (addr.get("company") or "").strip(),
        "phone": (addr.get("phone") or "").strip(),
        "address_line1": (addr.get("address1") or "").strip(),
        "address_line2": (addr.get("address2") or "").strip(),
        "city_locality": (addr.get("city") or "").strip(),
        "state_province": (addr.get("province") or "").strip(),
        "postal_code": (addr.get("zip") or "").strip(),
        "country_code": (addr.get("country_code") or "GB").strip().upper(),
        "address_residential_indicator": "unknown",
    }


def _warehouse_to_address(warehouse: dict) -> dict:
    origin = warehouse.get("origin_address") or warehouse.get("return_address") or warehouse
    return {
        "name": (origin.get("name") or warehouse.get("name") or "Warehouse").strip(),
        "company_name": (origin.get("company_name") or origin.get("company") or "").strip(),
        "phone": (origin.get("phone") or "").strip(),
        "address_line1": (origin.get("address_line1") or origin.get("address1") or "").strip(),
        "address_line2": (origin.get("address_line2") or origin.get("address2") or "").strip(),
        "city_locality": (origin.get("city_locality") or origin.get("city") or "").strip(),
        "state_province": (origin.get("state_province") or origin.get("state") or "").strip(),
        "postal_code": (origin.get("postal_code") or origin.get("postalCode") or "").strip(),
        "country_code": (origin.get("country_code") or origin.get("countryCode") or "GB").strip().upper(),
        "address_residential_indicator": "unknown",
    }


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
