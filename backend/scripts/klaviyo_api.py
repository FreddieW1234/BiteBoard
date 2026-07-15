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
    KLAVIYO_CUSTOMER_TYPE_METRIC_NAME,
    KLAVIYO_METRIC_NAME,
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


def send_production_update(
    email: str,
    order_name: str,
    update_type: str,
    *,
    order_id: str = "",
    item_title: str = "",
    item_id: str = "",
    proof_filename: str = "",
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
