"""Staff shipping — direct carrier APIs (Royal Mail, FedEx, Palletways).

FedEx is live (sandbox/production via FEDEX_* env). Royal Mail and Palletways
remain stubs until credentials/integrations are added.
"""

from __future__ import annotations

import logging
from datetime import date

from config import (  # type: ignore
    FEDEX_API_KEY,
    FEDEX_CLIENT_ID,
    FEDEX_CLIENT_SECRET,
    FEDEX_ACCOUNT_NUMBER,
    PALLETWAYS_API_KEY,
    ROYAL_MAIL_API_KEY,
    SHIP_FROM_CITY,
    SHIP_FROM_COUNTRY,
    SHIP_FROM_LINE1,
    SHIP_FROM_LINE2,
    SHIP_FROM_NAME,
    SHIP_FROM_PHONE,
    SHIP_FROM_POSTCODE,
    SHIP_FROM_STATE,
)
from scripts.order_helpers import fetch_order_by_id  # type: ignore

logger = logging.getLogger(__name__)

PALLET_WEIGHT_KG = 50.0

CARRIERS = (
    {"id": "royal_mail", "label": "Royal Mail", "shipment_types": ("parcel",)},
    {"id": "fedex", "label": "FedEx", "shipment_types": ("parcel",)},
    {"id": "palletways", "label": "Palletways", "shipment_types": ("pallet",)},
)


def _royal_mail_configured() -> bool:
    return bool(ROYAL_MAIL_API_KEY)


def _fedex_configured() -> bool:
    try:
        from scripts import fedex_api  # type: ignore
        return fedex_api.configured()
    except Exception:
        return bool(
            (FEDEX_CLIENT_ID or FEDEX_API_KEY)
            and FEDEX_CLIENT_SECRET
            and FEDEX_ACCOUNT_NUMBER
        )


def _palletways_configured() -> bool:
    return bool(PALLETWAYS_API_KEY)


def _ship_from_ready() -> bool:
    return bool((SHIP_FROM_LINE1 or "").strip() and (SHIP_FROM_POSTCODE or "").strip())


def _print_api_configured() -> bool:
    try:
        from scripts import print_client  # type: ignore
        return print_client.configured()
    except Exception:
        return False


def _printer_ready() -> bool:
    try:
        from scripts import print_client  # type: ignore
        return print_client.printer_ready()
    except Exception:
        return False


def shipping_status() -> dict:
    """Provider readiness for the Diary ship modal."""
    fedex_cfg = _fedex_configured()
    carriers = {
        "royal_mail": {
            "label": "Royal Mail",
            "configured": _royal_mail_configured(),
            "ready": False,
        },
        "fedex": {
            "label": "FedEx",
            "configured": fedex_cfg,
            "ready": fedex_cfg and _ship_from_ready(),
        },
        "palletways": {
            "label": "Palletways",
            "configured": _palletways_configured(),
            "ready": False,
        },
    }
    print_api = _print_api_configured()
    printer_ready = _printer_ready() if print_api else False
    return {
        "royal_mail": carriers["royal_mail"]["configured"],
        "fedex": carriers["fedex"]["configured"],
        "palletways": carriers["palletways"]["configured"],
        "carriers": carriers,
        "carrier_labels": [c["label"] for c in CARRIERS],
        "ship_from_ready": _ship_from_ready(),
        "print_server": printer_ready,
        "print_api_configured": print_api,
        "printer_ready": printer_ready,
        "any_carrier_configured": any(c["configured"] for c in carriers.values()),
        "shipstation": False,
    }


def _line_item_id(line: dict) -> str:
    from scripts.office_api import item_key  # type: ignore

    ln = line.get("line_number")
    title = line.get("title") or ""
    if line.get("office_item_id"):
        return str(line["office_item_id"])
    if ln is not None:
        return item_key(int(ln), title)
    return ""


def _filter_ship_items(items: list[dict], item_id: str | None) -> list[dict]:
    target = (item_id or "").strip()
    if not target:
        return items
    for item in items:
        if item.get("item_id") == target:
            return [item]
    from scripts.diary_helpers import item_slug  # type: ignore

    target_slug = item_slug(target)
    if target_slug:
        for item in items:
            if item_slug(item.get("item_id") or "") == target_slug:
                return [item]
    return []


def prepare_shipment(order_id: str | int, *, item_id: str | None = None) -> dict:
    """Load order details for the shipping modal."""
    order = fetch_order_by_id(order_id)
    if not order:
        return {"success": False, "error": "Order not found"}

    ship_to = order.get("shipping_address")
    if not ship_to:
        return {"success": False, "error": "Order has no shipping address"}

    items = [
        {
            "item_id": _line_item_id(li),
            "line_number": li.get("line_number"),
            "title": li.get("title") or "",
            "sku": li.get("sku") or "",
            "quantity": li.get("quantity") or 1,
            "weight_kg": li.get("weight_kg") or 0,
        }
        for li in (order.get("order_items") or [])
        if not li.get("is_fee")
    ]

    if item_id:
        items = _filter_ship_items(items, item_id)
        if not items:
            return {"success": False, "error": "Line item not found on this order"}

    total_weight_kg = sum(
        (li.get("weight_kg") or 0) * max(1, int(li.get("quantity") or 1))
        for li in items
    )
    # Only prefill when Shopify has a real weight — never invent 1 kg.
    known_weight = round(total_weight_kg, 3) if total_weight_kg > 0 else None

    return {
        "success": True,
        "order_id": str(order.get("id") or order_id),
        "order_name": order.get("name") or "",
        "item_id": (item_id or "").strip() or None,
        "company": order.get("company") or "",
        "customer_email": order.get("customer_email") or "",
        "ship_to": ship_to,
        "ship_from": ship_from_address(),
        "items": items,
        "defaults": {
            "weight_kg": known_weight,
            "length_cm": None,
            "width_cm": None,
            "height_cm": None,
            "shipment_type": "parcel",
        },
        "providers": shipping_status(),
    }


def ship_from_address() -> dict:
    """Warehouse / origin address from SHIP_FROM_* env vars."""
    return {
        "name": (SHIP_FROM_NAME or "").strip() or "Warehouse",
        "phone": (SHIP_FROM_PHONE or "").strip() or "0000000000",
        "address1": (SHIP_FROM_LINE1 or "").strip(),
        "address2": (SHIP_FROM_LINE2 or "").strip(),
        "city": (SHIP_FROM_CITY or "").strip(),
        "province": (SHIP_FROM_STATE or "").strip(),
        "zip": (SHIP_FROM_POSTCODE or "").strip(),
        "country_code": ((SHIP_FROM_COUNTRY or "GB").strip().upper() or "GB"),
    }


def _resolve_shipment_type(payload: dict) -> str:
    explicit = (payload.get("shipment_type") or "parcel").strip().lower()
    if explicit == "pallet":
        return "pallet"
    weight = float(payload.get("weight_kg") or 0)
    if weight >= PALLET_WEIGHT_KG:
        return "pallet"
    return "parcel"


def _parse_dim(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        n = float(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_weight_kg(value) -> float | None:
    return _parse_dim(value)


def _weight_from_payload(payload: dict, prep: dict | None = None) -> float | None:
    """Require an explicit positive weight — never invent a default kg."""
    weight = _parse_weight_kg(payload.get("weight_kg"))
    if weight is not None:
        return weight
    if prep:
        return _parse_weight_kg((prep.get("defaults") or {}).get("weight_kg"))
    return None


def _pending_notes_for_others(shipment_type: str, *, fedex_ok: bool) -> list[dict]:
    notes: list[dict] = []
    if shipment_type == "pallet":
        notes.append({
            "carrier": "Palletways",
            "kind": "pending",
            "message": (
                "Palletways direct API not connected yet."
                if not _palletways_configured()
                else "Palletways API key is set, but the integration is not wired yet."
            ),
        })
        return notes

    notes.append({
        "carrier": "Royal Mail",
        "kind": "pending",
        "message": (
            "Royal Mail direct API not connected yet."
            if not _royal_mail_configured()
            else "Royal Mail API key is set, but the integration is not wired yet."
        ),
    })
    if not fedex_ok:
        if not _fedex_configured():
            notes.append({
                "carrier": "FedEx",
                "kind": "pending",
                "message": (
                    "FedEx credentials missing. Set FEDEX_CLIENT_ID, "
                    "FEDEX_CLIENT_SECRET, and FEDEX_ACCOUNT_NUMBER."
                ),
            })
        elif not _ship_from_ready():
            notes.append({
                "carrier": "FedEx",
                "kind": "pending",
                "message": "Set SHIP_FROM_LINE1 and SHIP_FROM_POSTCODE for FedEx quotes.",
            })
    return notes


def quote_shipment(payload: dict) -> dict:
    """Return carrier rates (FedEx live; others pending)."""
    order_id = payload.get("order_id")
    if not order_id:
        return {"success": False, "error": "order_id is required"}

    prep = prepare_shipment(order_id, item_id=payload.get("item_id"))
    if not prep.get("success"):
        return prep

    weight = _weight_from_payload(payload, prep)
    if weight is None:
        return {
            "success": False,
            "error": "Enter the package weight in kg before getting rates.",
        }

    shipment_type = _resolve_shipment_type({**payload, "weight_kg": weight})
    rates: list[dict] = []
    carrier_notes: list[dict] = []
    carriers_queried: list[str] = []
    fedex_ok = False

    if shipment_type == "parcel" and _fedex_configured() and _ship_from_ready():
        carriers_queried.append("FedEx")
        try:
            from scripts import fedex_api  # type: ignore
            from scripts.fedex_api import FedExError  # type: ignore

            rates = fedex_api.get_rates(
                ship_from=prep.get("ship_from") or ship_from_address(),
                ship_to=prep.get("ship_to") or {},
                weight_kg=weight,
                length_cm=_parse_dim(payload.get("length_cm")),
                width_cm=_parse_dim(payload.get("width_cm")),
                height_cm=_parse_dim(payload.get("height_cm")),
            )
            fedex_ok = bool(rates)
            if not rates:
                carrier_notes.append({
                    "carrier": "FedEx",
                    "kind": "no_rates",
                    "message": "FedEx returned no rates for this package/route.",
                })
        except FedExError as exc:
            logger.warning("FedEx quote failed: %s", exc)
            carrier_notes.append({
                "carrier": "FedEx",
                "kind": "error",
                "message": str(exc),
            })
        except Exception as exc:
            logger.warning("FedEx quote failed: %s", exc)
            carrier_notes.append({
                "carrier": "FedEx",
                "kind": "error",
                "message": str(exc),
            })

    carrier_notes.extend(_pending_notes_for_others(shipment_type, fedex_ok=fedex_ok and bool(rates)))
    if shipment_type == "pallet":
        carriers_queried = ["Palletways"]
    else:
        for label in ("Royal Mail", "FedEx"):
            if label not in carriers_queried:
                carriers_queried.append(label)

    result = {
        "success": True,
        "shipment_type": shipment_type,
        "order_name": prep.get("order_name"),
        "item_id": prep.get("item_id"),
        "items": prep.get("items") or [],
        "rates": rates,
        "carriers_queried": carriers_queried,
        "carrier_notes": carrier_notes,
    }
    if not rates:
        result["error_hint"] = (
            carrier_notes[0]["message"]
            if carrier_notes
            else "No carrier rates available yet."
        )
    return result


def ship_order(payload: dict) -> dict:
    """Purchase label via FedEx (or reject for other carriers until wired)."""
    order_id = payload.get("order_id")
    rate_id = (payload.get("rate_id") or "").strip()
    if not order_id:
        return {"success": False, "error": "order_id is required"}
    if not rate_id:
        return {"success": False, "error": "rate_id is required"}

    shipment_type = _resolve_shipment_type(payload)
    if shipment_type == "pallet":
        return {"success": False, "error": "Palletways direct integration is not wired yet"}

    if not rate_id.startswith("fedex:"):
        return {
            "success": False,
            "error": "Only FedEx label purchase is available right now. Royal Mail is not wired yet.",
        }

    if not _fedex_configured():
        return {"success": False, "error": "FedEx is not configured"}
    if not _ship_from_ready():
        return {
            "success": False,
            "error": "Ship-from address missing. Set SHIP_FROM_LINE1 and SHIP_FROM_POSTCODE.",
        }

    prep = prepare_shipment(order_id, item_id=payload.get("item_id"))
    if not prep.get("success"):
        return prep

    weight = _weight_from_payload(payload, prep)
    if weight is None:
        return {
            "success": False,
            "error": "Enter the package weight in kg before creating a label.",
        }

    try:
        from scripts import fedex_api, print_client  # type: ignore
        from scripts.fedex_api import FedExError  # type: ignore

        service_type, packaging = fedex_api.parse_rate_id(rate_id)
        label = fedex_api.create_label(
            ship_from=prep.get("ship_from") or ship_from_address(),
            ship_to=prep.get("ship_to") or {},
            weight_kg=weight,
            service_type=service_type,
            packaging_type=packaging,
            length_cm=_parse_dim(payload.get("length_cm")),
            width_cm=_parse_dim(payload.get("width_cm")),
            height_cm=_parse_dim(payload.get("height_cm")),
            order_name=prep.get("order_name") or "",
            label_format="ZPLII",
        )

        tracking = str(label.get("tracking_number") or "").strip()
        label_id = str(label.get("label_id") or tracking or "").strip()
        service_code = str(label.get("service_code") or service_type)
        # Sandbox sometimes returns a label with no tracking — still stamp the row.
        if not tracking:
            tracking = label_id or f"FEDEX-{service_code}-{date.today().isoformat()}"
        if not label_id:
            label_id = tracking
        label_bytes = label.get("label_bytes") or b""
        label_url = str(label.get("label_url") or "")

        order_name = prep.get("order_name") or ""
        # Prefer the Diary row's item_id so the Ship column updates the same key.
        diary_item_id = (payload.get("item_id") or prep.get("item_id") or "").strip()
        stamp_ids: list[str] = []
        if diary_item_id:
            stamp_ids.append(diary_item_id)
        else:
            for item in prep.get("items") or []:
                item_id = (item.get("item_id") or "").strip()
                if not item_id:
                    ln = item.get("line_number")
                    title = item.get("title") or ""
                    if ln is None:
                        continue
                    from scripts.office_api import item_key  # type: ignore
                    item_id = item_key(int(ln), title)
                if item_id and item_id not in stamp_ids:
                    stamp_ids.append(item_id)

        stamped = 0
        for item_id in stamp_ids:
            saved = save_manual_dispatch(
                order_name=order_name,
                item_id=item_id,
                carrier="fedex",
                tracking_number=tracking,
                service_code=service_code,
                label_id=label_id,
                shipment_type="parcel",
            )
            if not saved.get("success"):
                logger.warning("Diary stamp failed for %s / %s: %s", order_name, item_id, saved)
            else:
                stamped += 1
        if stamped == 0:
            return {
                "success": False,
                "error": (
                    "Label may have been created, but Diary could not be updated "
                    f"(order={order_name!r}, items={len(stamp_ids)}). "
                    "Refresh and check tracking before shipping again."
                ),
                "tracking_number": tracking,
            }

        # Office server is the source of truth for label ZPL (not Render disk).
        from scripts import office_api  # type: ignore
        from scripts.office_api import OfficeApiError  # type: ignore

        label_stored = False
        label_store_meta: dict = {}
        store_errors: list[str] = []
        office_ready = print_client.configured()

        if not label_bytes:
            store_errors.append(
                "FedEx did not return usable ZPL for this label"
                + (f" (url present: {bool(label_url)})" if label_url else "")
                + ". Check FedEx label format is ZPLII, not PDF/PNG."
            )
        elif not office_ready:
            store_errors.append(
                "Office API is not configured (OFFICE_API_URL / OFFICE_API_KEY) — cannot store label."
            )
        else:
            for item_id in stamp_ids:
                try:
                    label_store_meta = office_api.store_label(
                        order_name,
                        item_id,
                        label_bytes,
                        tracking=tracking,
                        carrier="fedex",
                        item_label=item_id,
                    )
                    label_stored = True
                except OfficeApiError as store_exc:
                    logger.warning(
                        "Office label store failed for %s / %s: %s",
                        order_name,
                        item_id,
                        store_exc,
                    )
                    store_errors.append(str(store_exc))
                except Exception as store_exc:
                    logger.warning(
                        "Office label store failed for %s / %s: %s",
                        order_name,
                        item_id,
                        store_exc,
                    )
                    store_errors.append(str(store_exc))

        # Don't pretend ship succeeded if the office copy (source of truth) failed.
        if not label_stored:
            return {
                "success": False,
                "error": (
                    "FedEx label was created"
                    + (f" (tracking {tracking})" if tracking else "")
                    + ", but it was NOT saved on the office server. "
                    + (store_errors[0] if store_errors else "Unknown store error.")
                    + " Fix the error and ship again (creates v2) so Print label can work."
                ),
                "order_name": order_name,
                "item_id": diary_item_id or (stamp_ids[0] if stamp_ids else ""),
                "tracking_number": tracking,
                "label_id": label_id,
                "carrier": "fedex",
                "label_stored": False,
                "label_store_error": store_errors[0] if store_errors else None,
                "has_zpl": bool(label_bytes),
                "label_download_url": label_url or None,
            }

        print_result: dict = {"skipped": True, "reason": "no_label_bytes"}
        if label_bytes:
            try:
                print_result = print_client.send_print_job(
                    profile="parcel-4x6-zpl",
                    label_format="zpl",
                    data=label_bytes,
                    order_name=order_name,
                    tracking_number=tracking,
                    carrier="fedex",
                )
            except Exception as print_exc:
                logger.warning("Label print failed (label still stored): %s", print_exc)
                print_result = {"success": False, "error": str(print_exc)}
        elif not print_client.configured():
            print_result = {
                "success": True,
                "skipped": True,
                "reason": "print_server_not_configured",
            }

        import base64

        return {
            "success": True,
            "order_name": order_name,
            "item_id": diary_item_id or (stamp_ids[0] if stamp_ids else ""),
            "tracking_number": tracking,
            "label_id": label_id,
            "carrier": "fedex",
            "carrier_label": "FedEx",
            "service_code": service_code,
            "print": print_result,
            "label_stored": True,
            "label_filename": label_store_meta.get("filename"),
            "label_version": label_store_meta.get("version"),
            "has_zpl": True,
            "label_download_url": label_url or None,
            "label_zpl_base64": base64.b64encode(label_bytes).decode("ascii") if label_bytes else None,
            "sandbox_note": (
                "Sandbox/virtual response — not a live courier label."
                if fedex_api.is_sandbox()
                else None
            ),
        }
    except FedExError as exc:
        logger.warning("FedEx ship failed: %s", exc)
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("FedEx ship failed: %s", exc)
        return {"success": False, "error": str(exc)}


def save_manual_dispatch(
    *,
    order_name: str,
    item_id: str,
    carrier: str,
    tracking_number: str = "",
    service_code: str = "",
    label_id: str = "",
    shipment_type: str = "parcel",
) -> dict:
    """Stamp diary after a successful label buy."""
    from scripts.Diary import save_diary_entry  # type: ignore

    order_name = (order_name or "").strip()
    item_id = (item_id or "").strip()
    if not order_name or not item_id:
        return {"success": False, "error": "order_name and item_id are required"}

    today_iso = date.today().isoformat()
    result = save_diary_entry({
        "order_name": order_name,
        "item_id": item_id,
        "carrier": (carrier or "").strip(),
        "dispatch_date": today_iso,
        "dispatch_manual": True,
        "tracking_number": (tracking_number or "").strip(),
        "label_id": (label_id or "").strip(),
        "service_code": (service_code or "").strip(),
        "shipment_type": shipment_type or "parcel",
    })
    return result if isinstance(result, dict) else {"success": True}


def labels_status(payload: dict) -> dict:
    """Return which diary lines have a stored office ZPL label."""
    from scripts import office_api  # type: ignore

    items = payload.get("items") or []
    pairs: list[tuple[str, str]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        order = (entry.get("order_name") or entry.get("order") or "").strip()
        item = (entry.get("item_id") or entry.get("item") or "").strip()
        if order and item:
            pairs.append((order, item))

    status = office_api.labels_status(pairs)
    results = []
    for order, item in pairs:
        key = f"{order}\t{item}"
        results.append({
            "order_name": order,
            "item_id": item,
            "has_label": bool(status.get(key)),
        })
    return {"success": True, "results": results}


def reprint_label(payload: dict) -> dict:
    """Fetch latest ZPL from the office server, then POST it to ``/print``."""
    from scripts import office_api, print_client  # type: ignore
    from scripts.office_api import OfficeApiError  # type: ignore
    from scripts.print_client import PrintClientError  # type: ignore

    order_name = (payload.get("order_name") or "").strip()
    item_id = (payload.get("item_id") or "").strip()
    version = payload.get("version")
    if not order_name or not item_id:
        return {"success": False, "error": "order_name and item_id are required"}

    if not print_client.configured():
        return {
            "success": False,
            "error": "Office API is not configured (OFFICE_API_URL / OFFICE_API_KEY).",
        }

    try:
        ver = int(version) if version is not None and str(version).strip() != "" else None
    except (TypeError, ValueError):
        return {"success": False, "error": "Invalid label version"}

    try:
        stored = office_api.get_label(order_name, item_id, version=ver)
    except OfficeApiError as exc:
        return {
            "success": False,
            "error": str(exc) or (
                "No saved ZPL label on the office server for this line. "
                "Ship the line first, then use Print label."
            ),
        }
    except Exception as exc:
        logger.warning("Office get_label failed for %s / %s: %s", order_name, item_id, exc)
        return {"success": False, "error": str(exc)}

    zpl = stored.get("zpl") or ""
    tracking = str(stored.get("tracking") or stored.get("tracking_number") or "").strip()
    label_ref = tracking or str(stored.get("filename") or "")
    carrier = str(stored.get("carrier") or payload.get("carrier") or "fedex").strip().lower()

    try:
        print_result = print_client.send_print_job(
            profile="parcel-4x6-zpl",
            label_format="zpl",
            data=zpl.encode("utf-8") if isinstance(zpl, str) else zpl,
            order_name=order_name,
            tracking_number=label_ref,
            carrier=carrier,
        )
    except PrintClientError as print_exc:
        logger.warning("Label print failed for %s / %s: %s", order_name, item_id, print_exc)
        return {
            "success": False,
            "error": str(print_exc),
            "order_name": order_name,
            "item_id": item_id,
            "tracking_number": tracking,
            "label_filename": stored.get("filename"),
            "label_version": stored.get("version"),
            "has_zpl": True,
        }
    except Exception as print_exc:
        logger.warning("Label print failed for %s / %s: %s", order_name, item_id, print_exc)
        return {
            "success": False,
            "error": str(print_exc),
            "order_name": order_name,
            "item_id": item_id,
            "tracking_number": tracking,
            "has_zpl": True,
        }

    return {
        "success": True,
        "order_name": order_name,
        "item_id": item_id,
        "tracking_number": tracking,
        "label_filename": stored.get("filename"),
        "label_version": stored.get("version"),
        "print": print_result,
        "message": "Sent to printer",
        "has_zpl": True,
    }
