"""Direct FedEx REST API client (sandbox + production).

Auth: OAuth client_credentials
Rates: POST /rate/v1/rates/quotes
Ship:  POST /ship/v1/shipments
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from config import (  # type: ignore
    FEDEX_ACCOUNT_NUMBER,
    FEDEX_API_KEY,
    FEDEX_API_URL,
    FEDEX_CLIENT_ID,
    FEDEX_CLIENT_SECRET,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 45
_token: str | None = None
_token_expires_at: float = 0.0

DEFAULT_SANDBOX_URL = "https://apis-sandbox.fedex.com"
DEFAULT_PROD_URL = "https://apis.fedex.com"


class FedExError(Exception):
    """Raised when FedEx returns an error or is unreachable."""


def _client_id() -> str:
    return (FEDEX_CLIENT_ID or FEDEX_API_KEY or "").strip()


def _client_secret() -> str:
    return (FEDEX_CLIENT_SECRET or "").strip()


def _account_number() -> str:
    return (FEDEX_ACCOUNT_NUMBER or "").strip()


def _base_url() -> str:
    return (FEDEX_API_URL or DEFAULT_SANDBOX_URL).rstrip("/")


def configured() -> bool:
    return bool(_client_id() and _client_secret() and _account_number())


def is_sandbox() -> bool:
    return "sandbox" in _base_url().lower()


def ready() -> bool:
    """Credentials present and we can obtain an OAuth token."""
    if not configured():
        return False
    try:
        get_access_token()
        return True
    except Exception as exc:
        logger.warning("FedEx readiness check failed: %s", exc)
        return False


def get_access_token(*, force: bool = False) -> str:
    global _token, _token_expires_at
    now = time.time()
    if not force and _token and now < (_token_expires_at - 60):
        return _token
    if not configured():
        raise FedExError(
            "FedEx is not configured. Set FEDEX_CLIENT_ID, FEDEX_CLIENT_SECRET, "
            "and FEDEX_ACCOUNT_NUMBER."
        )

    url = f"{_base_url()}/oauth/token"
    try:
        resp = requests.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": _client_id(),
                "client_secret": _client_secret(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("FedEx OAuth request failed: %s", exc)
        raise FedExError("FedEx authentication service unavailable") from exc

    if not resp.ok:
        detail = _error_detail(resp)
        logger.error("FedEx OAuth failed HTTP %s: %s", resp.status_code, detail)
        raise FedExError(detail or f"FedEx authentication failed ({resp.status_code})")

    data = resp.json() if resp.content else {}
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise FedExError("FedEx OAuth response missing access_token")
    expires_in = int(data.get("expires_in") or 3600)
    _token = token
    _token_expires_at = now + max(60, expires_in)
    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
        "X-locale": "en_GB",
    }


def _error_detail(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except Exception:
        return (resp.text or "")[:300]
    errors = body.get("errors") or body.get("errorList") or []
    parts: list[str] = []
    for err in errors if isinstance(errors, list) else [errors]:
        if isinstance(err, dict):
            code = str(err.get("code") or "").strip()
            msg = str(err.get("message") or err.get("error") or "").strip()
            line = f"{code}: {msg}" if code and msg else (msg or code)
        else:
            line = str(err).strip()
        if line:
            parts.append(line)
    if parts:
        return "; ".join(parts[:4])
    return str(body.get("message") or body.get("error") or "")[:300]


def _request(method: str, path: str, *, json: dict | None = None) -> dict:
    if not path.startswith("/"):
        path = "/" + path
    url = f"{_base_url()}{path}"
    try:
        resp = requests.request(
            method,
            url,
            headers=_headers(),
            json=json,
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("FedEx request failed %s %s: %s", method, path, exc)
        raise FedExError("FedEx service unavailable") from exc

    if resp.status_code == 401:
        # Retry once with a fresh token.
        get_access_token(force=True)
        try:
            resp = requests.request(
                method,
                url,
                headers=_headers(),
                json=json,
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise FedExError("FedEx service unavailable") from exc

    if not resp.ok:
        detail = _error_detail(resp)
        logger.error("FedEx HTTP %s %s: %s", resp.status_code, path, detail)
        raise FedExError(detail or f"FedEx request failed ({resp.status_code})")

    if resp.status_code == 204 or not resp.content:
        return {}
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def _normalize_country(code: str) -> str:
    cc = (code or "").strip().upper()
    if cc in ("UK", "GBR", "UNITED KINGDOM", "GREAT BRITAIN"):
        return "GB"
    return cc or "GB"


def _addr_party(addr: dict) -> dict:
    """Map our ship_to / ship_from dict into FedEx address + contact."""
    street = []
    for key in ("address1", "address_line1", "addressLine1", "line1"):
        val = (addr.get(key) or "").strip()
        if val:
            street.append(val)
            break
    for key in ("address2", "address_line2", "addressLine2", "line2"):
        val = (addr.get(key) or "").strip()
        if val:
            street.append(val)
            break
    if not street:
        street = ["Address"]

    city = (
        addr.get("city")
        or addr.get("city_locality")
        or addr.get("cityLocality")
        or ""
    ).strip() or "City"
    postal = (
        addr.get("zip")
        or addr.get("postal_code")
        or addr.get("postalCode")
        or ""
    ).strip()
    state = (
        addr.get("province")
        or addr.get("state")
        or addr.get("state_province")
        or addr.get("stateOrProvinceCode")
        or ""
    ).strip()
    country = _normalize_country(
        addr.get("country_code") or addr.get("countryCode") or "GB"
    )
    name = (addr.get("name") or addr.get("company") or "Contact").strip()
    phone = (addr.get("phone") or "0000000000").strip() or "0000000000"
    company = (addr.get("company") or addr.get("company_name") or "").strip()

    person: dict[str, Any] = {
        "address": {
            "streetLines": street[:3],
            "city": city,
            "postalCode": postal,
            "countryCode": country,
            "residential": bool(addr.get("residential")),
        },
        "contact": {
            "personName": name[:70],
            "phoneNumber": phone[:15],
        },
    }
    if state and country not in ("GB",):
        person["address"]["stateOrProvinceCode"] = state[:2] if len(state) <= 2 else state
    elif state and country == "GB":
        # Optional for UK; some FedEx UK calls accept county in stateOrProvinceCode.
        person["address"]["stateOrProvinceCode"] = state[:2] if len(state) == 2 else ""
        if not person["address"]["stateOrProvinceCode"]:
            person["address"].pop("stateOrProvinceCode", None)
    if company:
        person["contact"]["companyName"] = company[:35]
    return person


def _package_line(
    *,
    weight_kg: float,
    length_cm: float | None,
    width_cm: float | None,
    height_cm: float | None,
) -> dict:
    item: dict[str, Any] = {
        "weight": {
            "units": "KG",
            "value": round(max(0.01, float(weight_kg)), 3),
        },
    }
    if length_cm and width_cm and height_cm:
        dims = sorted([float(length_cm), float(width_cm), float(height_cm)], reverse=True)
        item["dimensions"] = {
            "length": int(max(1, round(dims[0]))),
            "width": int(max(1, round(dims[1]))),
            "height": int(max(1, round(dims[2]))),
            "units": "CM",
        }
    return item


def get_rates(
    *,
    ship_from: dict,
    ship_to: dict,
    weight_kg: float,
    length_cm: float | None = None,
    width_cm: float | None = None,
    height_cm: float | None = None,
) -> list[dict]:
    """Return normalized rate dicts for the UI."""
    shipper = _addr_party(ship_from)
    recipient = _addr_party(ship_to)

    payload = {
        "accountNumber": {"value": _account_number()},
        "requestedShipment": {
            "shipper": {"address": shipper["address"]},
            "recipient": {"address": recipient["address"]},
            "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
            "rateRequestType": ["LIST", "ACCOUNT"],
            "preferredCurrency": "GBP",
            "requestedPackageLineItems": [
                _package_line(
                    weight_kg=weight_kg,
                    length_cm=length_cm,
                    width_cm=width_cm,
                    height_cm=height_cm,
                )
            ],
        },
        "rateRequestControlParameters": {
            "returnTransitTimes": True,
        },
    }

    data = _request("POST", "/rate/v1/rates/quotes", json=payload)
    return _normalize_rates(data)


def _rate_total(detail: dict) -> tuple[float | None, str]:
    currency = "GBP"
    for key in ("totalNetCharge", "totalNetChargeWithDutiesAndTaxes", "totalBaseCharge"):
        block = detail.get(key)
        if isinstance(block, dict) and block.get("amount") is not None:
            try:
                return float(block["amount"]), str(block.get("currency") or currency).upper()
            except (TypeError, ValueError):
                continue
    rated = detail.get("ratedShipmentDetails") or []
    if isinstance(rated, list) and rated:
        first = rated[0] if isinstance(rated[0], dict) else {}
        for key in ("totalNetCharge", "totalNetFedExCharge", "shipmentRateDetails"):
            block = first.get(key)
            if isinstance(block, dict) and block.get("amount") is not None:
                try:
                    return float(block["amount"]), str(block.get("currency") or currency).upper()
                except (TypeError, ValueError):
                    continue
            if key == "shipmentRateDetails" and isinstance(block, dict):
                tnc = block.get("totalNetCharge")
                if isinstance(tnc, dict) and tnc.get("amount") is not None:
                    try:
                        return float(tnc["amount"]), str(tnc.get("currency") or currency).upper()
                    except (TypeError, ValueError):
                        pass
    return None, currency


def _normalize_rates(data: dict) -> list[dict]:
    out: list[dict] = []
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    rate_reply = output.get("rateReplyDetails") or data.get("rateReplyDetails") or []

    for reply in rate_reply if isinstance(rate_reply, list) else []:
        if not isinstance(reply, dict):
            continue
        service_type = str(reply.get("serviceType") or "").strip()
        service_name = str(
            reply.get("serviceName") or reply.get("serviceDescription", {}).get("description")
            or service_type
        ).strip()
        if isinstance(reply.get("serviceDescription"), dict):
            service_name = str(
                reply["serviceDescription"].get("name")
                or reply["serviceDescription"].get("description")
                or service_name
            ).strip()

        # Prefer ACCOUNT rated shipment detail, else first.
        rated_list = reply.get("ratedShipmentDetails") or []
        chosen = None
        for r in rated_list if isinstance(rated_list, list) else []:
            if not isinstance(r, dict):
                continue
            rtype = str(r.get("rateType") or "").upper()
            if "ACCOUNT" in rtype:
                chosen = r
                break
            if chosen is None:
                chosen = r
        if chosen is None and isinstance(rated_list, list) and rated_list:
            chosen = rated_list[0] if isinstance(rated_list[0], dict) else None
        if not isinstance(chosen, dict):
            chosen = reply

        price, currency = _rate_total(chosen)
        if price is None:
            price, currency = _rate_total(reply)
        if price is None or price < 0:
            continue

        commit = reply.get("commit") if isinstance(reply.get("commit"), dict) else {}
        days = commit.get("dateDetail", {}).get("dayOfWeek") if isinstance(commit.get("dateDetail"), dict) else None
        transit_days = None
        for key in ("transitTime", "saturdayDelivery"):
            val = commit.get(key) or reply.get(key)
            if isinstance(val, str) and val.isdigit():
                transit_days = int(val)
                break
        # FedEx often returns transit as enum like TWO_DAYS
        tt = str(commit.get("transitTime") or reply.get("operationalDetail", {}).get("transitTime") or "")
        transit_map = {
            "ONE_DAY": 1, "TWO_DAYS": 2, "THREE_DAYS": 3, "FOUR_DAYS": 4,
            "FIVE_DAYS": 5, "SIX_DAYS": 6, "SEVEN_DAYS": 7,
        }
        if tt in transit_map:
            transit_days = transit_map[tt]

        packaging = str(reply.get("packagingType") or "YOUR_PACKAGING")
        rate_id = f"fedex:{service_type}:{packaging}"

        out.append({
            "rate_id": rate_id,
            "carrier_id": "fedex",
            "carrier_code": "fedex",
            "carrier_friendly_name": "FedEx",
            "service_code": service_type,
            "service_type": service_name or service_type,
            "delivery_days": transit_days,
            "price": round(float(price), 2),
            "currency": currency or "GBP",
            "packaging_type": packaging,
        })

    out.sort(key=lambda x: (x.get("price") is None, x.get("price") or 999999))
    return out


def create_label(
    *,
    ship_from: dict,
    ship_to: dict,
    weight_kg: float,
    service_type: str,
    packaging_type: str = "YOUR_PACKAGING",
    length_cm: float | None = None,
    width_cm: float | None = None,
    height_cm: float | None = None,
    order_name: str = "",
    label_format: str = "ZPLII",
) -> dict:
    """Create a shipment and return tracking + label bytes/url info."""
    service_type = (service_type or "").strip()
    if not service_type:
        raise FedExError("FedEx service_type is required to create a label")

    shipper = _addr_party(ship_from)
    recipient = _addr_party(ship_to)
    label_resp_format = "ZPLII" if label_format.upper().startswith("ZPL") else "PDF"

    payload = {
        "labelResponseOptions": "LABEL",
        "requestedShipment": {
            "shipDatestamp": time.strftime("%Y-%m-%d"),
            "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
            "serviceType": service_type,
            "packagingType": packaging_type or "YOUR_PACKAGING",
            "shipper": shipper,
            "recipients": [recipient],
            "shippingChargesPayment": {
                "paymentType": "SENDER",
                "payor": {
                    "responsibleParty": {
                        "accountNumber": {"value": _account_number()},
                    }
                },
            },
            "labelSpecification": {
                "imageType": label_resp_format,
                "labelStockType": "STOCK_4X6" if label_resp_format == "ZPLII" else "PAPER_4X6",
            },
            "requestedPackageLineItems": [
                _package_line(
                    weight_kg=weight_kg,
                    length_cm=length_cm,
                    width_cm=width_cm,
                    height_cm=height_cm,
                )
            ],
        },
        "accountNumber": {"value": _account_number()},
    }
    if order_name:
        payload["requestedShipment"]["requestedPackageLineItems"][0]["customerReferences"] = [
            {"customerReferenceType": "CUSTOMER_REFERENCE", "value": order_name[:40]}
        ]

    data = _request("POST", "/ship/v1/shipments", json=payload)
    return _normalize_label(data, service_type=service_type)


def _normalize_label(data: dict, *, service_type: str) -> dict:
    output = data.get("output") if isinstance(data.get("output"), dict) else data
    txns = output.get("transactionShipments") or []
    if not txns and isinstance(output.get("shipmentDocuments"), list):
        txns = [output]

    tracking = ""
    label_b64 = ""
    label_url = ""
    master = ""

    for txn in txns if isinstance(txns, list) else []:
        if not isinstance(txn, dict):
            continue
        tracking = str(
            txn.get("masterTrackingNumber")
            or txn.get("trackingNumber")
            or tracking
        )
        master = str(txn.get("masterTrackingNumber") or master)
        piece_responses = txn.get("pieceResponses") or []
        for piece in piece_responses if isinstance(piece_responses, list) else []:
            if not isinstance(piece, dict):
                continue
            tracking = str(piece.get("trackingNumber") or tracking)
            for doc in piece.get("packageDocuments") or []:
                if not isinstance(doc, dict):
                    continue
                if doc.get("url"):
                    label_url = str(doc["url"])
                if doc.get("encodedLabel"):
                    label_b64 = str(doc["encodedLabel"])
                    break
        for doc in txn.get("shipmentDocuments") or []:
            if not isinstance(doc, dict):
                continue
            if doc.get("url") and not label_url:
                label_url = str(doc["url"])
            if doc.get("encodedLabel") and not label_b64:
                label_b64 = str(doc["encodedLabel"])

    label_bytes = b""
    if label_b64:
        import base64
        try:
            label_bytes = base64.b64decode(label_b64)
        except Exception as exc:
            logger.warning("Could not decode FedEx label: %s", exc)

    if not tracking and not label_bytes and not label_url:
        alerts = output.get("alerts") or data.get("alerts") or []
        raise FedExError(
            "FedEx created no tracking/label in the response"
            + (f" ({alerts})" if alerts else "")
        )

    return {
        "tracking_number": tracking or master,
        "label_id": master or tracking,
        "carrier_code": "fedex",
        "carrier_friendly_name": "FedEx",
        "service_code": service_type,
        "label_bytes": label_bytes,
        "label_url": label_url,
        "raw": data,
    }


def parse_rate_id(rate_id: str) -> tuple[str, str]:
    """Parse `fedex:SERVICE:PACKAGING` → (service_type, packaging_type)."""
    text = (rate_id or "").strip()
    parts = text.split(":")
    if len(parts) < 2 or parts[0].lower() != "fedex":
        raise FedExError("Not a FedEx rate_id")
    service = parts[1].strip()
    packaging = parts[2].strip() if len(parts) > 2 else "YOUR_PACKAGING"
    if not service:
        raise FedExError("FedEx rate_id missing service type")
    return service, packaging or "YOUR_PACKAGING"
