"""Klaviyo Events API — trigger transactional production-update emails via Flow."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import requests

from config import KLAVIYO_API_KEY, KLAVIYO_API_REVISION, KLAVIYO_METRIC_NAME  # type: ignore

log = logging.getLogger(__name__)

UPDATE_LABELS: dict[str, str] = {
    "proof_uploaded": "Proof ready for review",
    "printing": "Printing",
    "in_production": "In production",
    "shipped": "Shipped",
}

NOTIFY_WORTHY_UPDATE_TYPES = frozenset(UPDATE_LABELS.keys())


class KlaviyoError(Exception):
    pass


def klaviyo_configured() -> bool:
    return bool(KLAVIYO_API_KEY and KLAVIYO_METRIC_NAME)


def send_production_update(
    email: str,
    order_name: str,
    update_type: str,
    *,
    item_title: str = "",
    item_id: str = "",
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

    payload: dict[str, Any] = {
        "data": {
            "type": "event",
            "attributes": {
                "properties": {
                    "order_name": order_name,
                    "update_type": update_type,
                    "stage_label": stage_label,
                    "item_title": item_title or "",
                    "item_id": item_id or "",
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
