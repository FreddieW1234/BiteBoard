"""Klaviyo Events API — trigger transactional production-update emails via Flow."""

from __future__ import annotations

import logging
import uuid
from typing import Any
from urllib.parse import urlencode

import requests

from config import (  # type: ignore
    KLAVIYO_API_KEY,
    KLAVIYO_API_REVISION,
    KLAVIYO_CUSTOMER_REGISTERED_METRIC_NAME,
    KLAVIYO_CUSTOMER_TYPE_METRIC_NAME,
    KLAVIYO_METRIC_NAME,
    KLAVIYO_PROOF_APPROVED_METRIC_NAME,
    PORTAL_PAGE_URL,
    STOREFRONT_URL,
)

log = logging.getLogger(__name__)

UPDATE_LABELS: dict[str, str] = {
    "proof_uploaded": "Proof ready for review",
    "printing": "Printing",
    "in_production": "In production",
    "shipped": "Shipped",
}

CUSTOMER_TYPE_LABELS: dict[str, str] = {
    "trade": "Trade Customer",
    "end-customer": "End Customer",
}

ASSIGNED_CUSTOMER_TYPES = frozenset(CUSTOMER_TYPE_LABELS.keys())

NOTIFY_WORTHY_UPDATE_TYPES = frozenset(UPDATE_LABELS.keys())


class KlaviyoError(Exception):
    pass


def klaviyo_configured() -> bool:
    return bool(KLAVIYO_API_KEY and KLAVIYO_METRIC_NAME)


def klaviyo_customer_type_configured() -> bool:
    return bool(KLAVIYO_API_KEY and KLAVIYO_CUSTOMER_TYPE_METRIC_NAME)


def klaviyo_customer_registered_configured() -> bool:
    return bool(KLAVIYO_API_KEY and KLAVIYO_CUSTOMER_REGISTERED_METRIC_NAME)


def klaviyo_proof_approved_configured() -> bool:
    return bool(KLAVIYO_API_KEY and KLAVIYO_PROOF_APPROVED_METRIC_NAME)


def build_portal_url(
    order_id: str,
    *,
    item_id: str = "",
    proof_filename: str = "",
) -> str:
    """Deep-link URL for the Shopify portal page (order expand + optional proof view)."""
    params: dict[str, str] = {}
    oid = (order_id or "").strip()
    if oid:
        params["order"] = oid
    iid = (item_id or "").strip()
    if iid:
        params["item"] = iid
    proof = (proof_filename or "").strip()
    if proof:
        params["proof"] = proof
    base = PORTAL_PAGE_URL or ""
    if not params:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{urlencode(params)}"


def latest_proof_filename(order_name: str, item_id: str) -> str:
    """Return the newest proof filename for an order line, or empty string."""
    order_name = (order_name or "").strip()
    item_id = (item_id or "").strip()
    if not order_name or not item_id:
        return ""
    try:
        from scripts.office_api import get_item, OfficeApiError  # type: ignore

        office = get_item(order_name, item_id)
    except OfficeApiError:
        return ""
    if not isinstance(office, dict):
        return ""
    proofs: list[dict] = []
    for f in office.get("files") or []:
        if not isinstance(f, dict):
            continue
        kind = (f.get("kind") or "").strip().lower()
        name = (f.get("name") or "").strip()
        if not name:
            continue
        if kind == "proof" or name.lower().startswith("proof"):
            proofs.append(f)
    if not proofs:
        return ""
    best = max(proofs, key=lambda f: int(f.get("version") or 0))
    return (best.get("name") or "").strip()


def _find_line_for_item(order: dict | None, item_id: str) -> dict | None:
    item_id = (item_id or "").strip()
    if not order or not item_id:
        return None
    for line in order.get("order_items") or []:
        if (line.get("office_item_id") or "") == item_id:
            return line
    return None


def _extract_po_number(order_info: dict | None) -> str:
    if not order_info:
        return ""
    for sec in order_info.get("note_sections") or []:
        for field in sec.get("fields") or []:
            key = (field.get("key") or "").upper()
            if key.startswith("PO NUMBER"):
                return str(field.get("value") or "").strip()
    return ""


def production_update_extra_properties(
    order_name: str,
    order_id: str,
    item_id: str,
    *,
    order: dict | None = None,
) -> dict[str, str]:
    """Diary dispatch date, PO number, and raw order note for Klaviyo templates."""
    props = {"dispatch_date": "", "po_number": "", "order_note": ""}
    order_name = (order_name or "").strip()
    item_id = (item_id or "").strip()

    if order is None and (order_id or "").strip():
        try:
            from scripts.order_helpers import fetch_order_by_id  # type: ignore

            order = fetch_order_by_id(order_id)
        except Exception:
            order = None

    if not order:
        return props

    order_info = order.get("order_info") or {}
    props["order_note"] = (order_info.get("note") or order.get("note") or "").strip()
    props["po_number"] = _extract_po_number(order_info)

    line = _find_line_for_item(order, item_id)
    if not line or not order_name:
        return props

    try:
        from scripts.diary_helpers import (  # type: ignore
            collect_delivery_date_fields,
            dispatch_display_for_line,
            parse_delivery_date,
            _match_field_for_line,
        )
        from scripts.Diary import load_saved_entries  # type: ignore

        date_fields = collect_delivery_date_fields(order_info)
        matched_date = _match_field_for_line(line, date_fields)
        delivery_raw = (matched_date.get("value") if matched_date else "") or ""
        requested_date = parse_delivery_date(str(delivery_raw).strip())
        props["dispatch_date"] = dispatch_display_for_line(
            order_name,
            line,
            load_saved_entries(),
            requested_date=requested_date,
        )
    except Exception as exc:
        log.warning("Could not resolve dispatch date for Klaviyo event: %s", exc)

    return props


def send_production_update(
    email: str,
    order_name: str,
    update_type: str,
    *,
    order_id: str = "",
    item_title: str = "",
    item_id: str = "",
    proof_filename: str = "",
    order: dict | None = None,
) -> None:
    """Fire a Klaviyo metric event that triggers a transactional Flow."""
    if not klaviyo_configured():
        raise KlaviyoError("Klaviyo is not configured (KLAVIYO_API_KEY / KLAVIYO_METRIC_NAME)")
    update_type = (update_type or "").strip()
    if update_type not in NOTIFY_WORTHY_UPDATE_TYPES:
        raise KlaviyoError(f"Unknown update type: {update_type}")

    email = (email or "").strip()
    if not email:
        raise KlaviyoError("Email address is required")

    stage_label = UPDATE_LABELS.get(update_type, update_type)
    unique_id = f"{order_name}-{item_id}-{update_type}-{uuid.uuid4().hex}"

    proof = (proof_filename or "").strip()
    if update_type == "proof_uploaded" and not proof and order_name and item_id:
        proof = latest_proof_filename(order_name, item_id)

    portal_url = build_portal_url(order_id, item_id=item_id, proof_filename=proof)
    extra = production_update_extra_properties(
        order_name, order_id, item_id, order=order
    )

    payload: dict[str, Any] = {
        "data": {
            "type": "event",
            "attributes": {
                "properties": {
                    "order_name": order_name,
                    "order_id": (order_id or "").strip(),
                    "update_type": update_type,
                    "stage_label": stage_label,
                    "item_title": item_title or "",
                    "item_id": item_id or "",
                    "proof_filename": proof,
                    "portal_url": portal_url,
                    "dispatch_date": extra["dispatch_date"],
                    "po_number": extra["po_number"],
                    "order_note": extra["order_note"],
                },
                "metric": {
                    "data": {
                        "type": "metric",
                        "attributes": {"name": KLAVIYO_METRIC_NAME},
                    }
                },
                "profile": {
                    "data": {
                        "type": "profile",
                        "attributes": {"email": email},
                    }
                },
                "unique_id": unique_id,
            },
        }
    }

    url = "https://a.klaviyo.com/api/events"
    headers = {
        "Authorization": f"Klaviyo-API-Key {KLAVIYO_API_KEY}",
        "accept": "application/json",
        "content-type": "application/json",
        "revision": KLAVIYO_API_REVISION,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise KlaviyoError(f"Could not reach Klaviyo: {exc}") from exc

    if resp.status_code not in (200, 202):
        detail = resp.text[:500] if resp.text else resp.reason
        log.warning("Klaviyo event failed (%s): %s", resp.status_code, detail)
        raise KlaviyoError(f"Klaviyo returned {resp.status_code}")


def send_proof_approved(
    order_name: str,
    *,
    order_id: str = "",
    item_title: str = "",
    item_id: str = "",
    approved_by: str = "",
) -> None:
    """Fire staff-only Klaviyo metric when proof is approved. Recipients are configured in Klaviyo."""
    if not klaviyo_proof_approved_configured():
        raise KlaviyoError(
            "Klaviyo is not configured (KLAVIYO_API_KEY / KLAVIYO_PROOF_APPROVED_METRIC_NAME)"
        )

    order_name = (order_name or "").strip()
    if not order_name:
        raise KlaviyoError("Order name is required")

    unique_id = f"proof-approved-{order_name}-{item_id}-{uuid.uuid4().hex}"
    portal_url = build_portal_url(order_id, item_id=item_id)
    profile_key = (order_id or order_name).strip()

    payload: dict[str, Any] = {
        "data": {
            "type": "event",
            "attributes": {
                "properties": {
                    "order_name": order_name,
                    "order_id": (order_id or "").strip(),
                    "item_title": (item_title or "").strip(),
                    "item_id": (item_id or "").strip(),
                    "approved_by": (approved_by or "").strip(),
                    "portal_url": portal_url,
                },
                "metric": {
                    "data": {
                        "type": "metric",
                        "attributes": {"name": KLAVIYO_PROOF_APPROVED_METRIC_NAME},
                    }
                },
                "profile": {
                    "data": {
                        "type": "profile",
                        "attributes": {"external_id": f"bite-order-{profile_key}"},
                    }
                },
                "unique_id": unique_id,
            },
        }
    }

    url = "https://a.klaviyo.com/api/events"
    headers = {
        "Authorization": f"Klaviyo-API-Key {KLAVIYO_API_KEY}",
        "accept": "application/json",
        "content-type": "application/json",
        "revision": KLAVIYO_API_REVISION,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise KlaviyoError(f"Could not reach Klaviyo: {exc}") from exc

    if resp.status_code not in (200, 202):
        detail = resp.text[:500] if resp.text else resp.reason
        log.warning("Klaviyo proof approved event failed (%s): %s", resp.status_code, detail)
        raise KlaviyoError(f"Klaviyo returned {resp.status_code}")


def send_customer_type_assigned(
    email: str,
    customer_name: str,
    customer_type: str,
    *,
    customer_id: str = "",
) -> None:
    """Fire a Klaviyo metric when a customer is assigned trade or end-customer."""
    if not klaviyo_customer_type_configured():
        raise KlaviyoError(
            "Klaviyo is not configured (KLAVIYO_API_KEY / KLAVIYO_CUSTOMER_TYPE_METRIC_NAME)"
        )
    customer_type = (customer_type or "").strip().lower()
    if customer_type not in ASSIGNED_CUSTOMER_TYPES:
        raise KlaviyoError(f"Invalid customer type: {customer_type}")

    email = (email or "").strip()
    if not email:
        raise KlaviyoError("Email address is required")

    type_label = CUSTOMER_TYPE_LABELS.get(customer_type, customer_type)
    unique_id = f"customer-type-{customer_id or email}-{customer_type}-{uuid.uuid4().hex}"

    payload: dict[str, Any] = {
        "data": {
            "type": "event",
            "attributes": {
                "properties": {
                    "customer_id": str(customer_id or "").strip(),
                    "customer_name": (customer_name or "").strip(),
                    "customer_type": customer_type,
                    "customer_type_label": type_label,
                    "portal_url": (PORTAL_PAGE_URL or "").strip(),
                    "storefront_url": (STOREFRONT_URL or "").strip(),
                },
                "metric": {
                    "data": {
                        "type": "metric",
                        "attributes": {"name": KLAVIYO_CUSTOMER_TYPE_METRIC_NAME},
                    }
                },
                "profile": {
                    "data": {
                        "type": "profile",
                        "attributes": {"email": email},
                    }
                },
                "unique_id": unique_id,
            },
        }
    }

    url = "https://a.klaviyo.com/api/events"
    headers = {
        "Authorization": f"Klaviyo-API-Key {KLAVIYO_API_KEY}",
        "accept": "application/json",
        "content-type": "application/json",
        "revision": KLAVIYO_API_REVISION,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise KlaviyoError(f"Could not reach Klaviyo: {exc}") from exc

    if resp.status_code not in (200, 202):
        detail = resp.text[:500] if resp.text else resp.reason
        log.warning("Klaviyo customer type event failed (%s): %s", resp.status_code, detail)
        raise KlaviyoError(f"Klaviyo returned {resp.status_code}")


def send_customer_registered(
    email: str,
    *,
    customer_id: str = "",
    first_name: str = "",
    last_name: str = "",
    company_name: str = "",
    login_url: str = "",
) -> None:
    """Fire a Klaviyo metric when a new customer registers via the portal."""
    if not klaviyo_customer_registered_configured():
        raise KlaviyoError(
            "Klaviyo is not configured (KLAVIYO_API_KEY / KLAVIYO_CUSTOMER_REGISTERED_METRIC_NAME)"
        )

    email = (email or "").strip()
    if not email:
        raise KlaviyoError("Email address is required")

    first = (first_name or "").strip()
    last = (last_name or "").strip()
    customer_name = f"{first} {last}".strip() or email
    unique_id = f"customer-registered-{customer_id or email}-{uuid.uuid4().hex}"

    profile_attrs: dict[str, str] = {"email": email}
    if first:
        profile_attrs["first_name"] = first
    if last:
        profile_attrs["last_name"] = last

    payload: dict[str, Any] = {
        "data": {
            "type": "event",
            "attributes": {
                "properties": {
                    "customer_id": str(customer_id or "").strip(),
                    "customer_name": customer_name,
                    "first_name": first,
                    "last_name": last,
                    "company_name": (company_name or "").strip(),
                    "portal_url": (PORTAL_PAGE_URL or "").strip(),
                    "storefront_url": (STOREFRONT_URL or "").strip(),
                    "login_url": (login_url or "").strip(),
                },
                "metric": {
                    "data": {
                        "type": "metric",
                        "attributes": {"name": KLAVIYO_CUSTOMER_REGISTERED_METRIC_NAME},
                    }
                },
                "profile": {
                    "data": {
                        "type": "profile",
                        "attributes": profile_attrs,
                    }
                },
                "unique_id": unique_id,
            },
        }
    }

    url = "https://a.klaviyo.com/api/events"
    headers = {
        "Authorization": f"Klaviyo-API-Key {KLAVIYO_API_KEY}",
        "accept": "application/json",
        "content-type": "application/json",
        "revision": KLAVIYO_API_REVISION,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise KlaviyoError(f"Could not reach Klaviyo: {exc}") from exc

    if resp.status_code not in (200, 202):
        detail = resp.text[:500] if resp.text else resp.reason
        log.warning("Klaviyo customer registered event failed (%s): %s", resp.status_code, detail)
        raise KlaviyoError(f"Klaviyo returned {resp.status_code}")
