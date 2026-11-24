"""Fetch orders for a single Shopify customer (client portal)."""

from __future__ import annotations

import threading
import time
import requests

from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN  # type: ignore

HEADERS = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": ACCESS_TOKEN,
}

from scripts.order_helpers import LINE_ITEM_FIELDS, ORDER_EXTRA_FIELDS, ORDER_ADDRESS_PAYMENT_FIELDS, attach_dispatch_displays, enrich_order  # type: ignore

_CUSTOMER_CACHE_TTL_SEC = 90
_customer_cache: dict[str, tuple[float, dict]] = {}
_customer_cache_lock = threading.Lock()

CUSTOMER_ORDERS_QUERY = f"""
query CustomerOrders($id: ID!, $cursor: String) {{
  customer(id: $id) {{
    legacyResourceId
    email
    firstName
    lastName
    orders(first: 50, after: $cursor, sortKey: PROCESSED_AT, reverse: true) {{
      edges {{
        node {{
          legacyResourceId
          name
          processedAt
          orderOwner: customer {{ legacyResourceId }}
          displayFinancialStatus
          displayFulfillmentStatus
{ORDER_EXTRA_FIELDS}
{ORDER_ADDRESS_PAYMENT_FIELDS}
          lineItems(first: 50) {{
            edges {{
              node {{
{LINE_ITEM_FIELDS}
              }}
            }}
          }}
        }}
      }}
      pageInfo {{ hasNextPage endCursor }}
    }}
  }}
}}
"""


def _graphql(query: str, variables: dict | None = None) -> dict:
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
    while True:
        resp = requests.post(
            url,
            json={"query": query, "variables": variables or {}},
            headers=HEADERS,
            timeout=30,
        )
        if resp.status_code == 429:
            time.sleep(2)
            continue
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(str(payload["errors"]))
        return payload.get("data") or {}


def verify_customer(customer_id: str | int, email: str) -> bool:
    """Confirm customer id and email match in Shopify."""
    cid = str(customer_id).strip()
    expected_email = (email or "").strip().lower()
    if not cid or not expected_email:
        return False
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers/{cid}.json"
    while True:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 429:
            time.sleep(2)
            continue
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        break
    customer = resp.json().get("customer") or {}
    shopify_email = (customer.get("email") or "").strip().lower()
    return shopify_email == expected_email


def get_customer_profile(customer_id: str | int) -> dict:
    """Return profile fields for one customer (same data as staff Customers expand panel)."""
    cid = str(customer_id).strip()
    cache_key = f"profile:{cid}"
    now = time.time()
    with _customer_cache_lock:
        cached = _customer_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]
    try:
        import os
        import sys
        scripts_dir = os.path.dirname(__file__)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from Customers import _fetch_single_customer  # type: ignore
        profile = _fetch_single_customer(cid)
        result = {
            "success": True,
            "profile": {
                "id": profile.get("id"),
                "name": profile.get("name") or "",
                "first_name": profile.get("first_name") or "",
                "last_name": profile.get("last_name") or "",
                "email": profile.get("email") or "",
                "company_name": profile.get("company_name") or "",
                "company_locked": bool(profile.get("company_locked")),
                "invoice_address": profile.get("invoice_address") or "",
                "landline_phone": profile.get("landline_phone") or "",
                "mobile_number": profile.get("mobile_number") or "",
            },
        }
        with _customer_cache_lock:
            _customer_cache[cache_key] = (now + _CUSTOMER_CACHE_TTL_SEC, result)
        return result
    except Exception as e:
        return {"success": False, "error": str(e), "profile": None}


CLIENT_PROFILE_KEYS = (
    "first_name",
    "last_name",
    "email",
    "company_name",
    "invoice_address",
    "landline_phone",
    "mobile_number",
)


def update_client_profile(customer_id: str | int, payload: dict) -> dict:
    """Update allowed profile fields for the logged-in customer (no type tag changes)."""
    import os
    import sys
    import re
    scripts_dir = os.path.dirname(__file__)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from Customers import update_customer_details, _fetch_single_customer  # type: ignore

    first_name = str(payload.get("first_name") or "").strip()
    email = str(payload.get("email") or "").strip()
    if not first_name:
        return {"success": False, "error": "First name is required."}
    if not email:
        return {"success": False, "error": "Email is required."}
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return {"success": False, "error": "Please enter a valid email address."}

    safe = {k: payload[k] for k in CLIENT_PROFILE_KEYS if k in payload}
    safe["first_name"] = first_name
    safe["email"] = email
    try:
        existing = _fetch_single_customer(customer_id)
        if existing.get("company_locked") and "company_name" in safe:
            safe.pop("company_name", None)
    except Exception:
        pass
    update_customer_details(customer_id, safe)
    with _customer_cache_lock:
        _customer_cache.pop(f"profile:{str(customer_id).strip()}", None)
    return get_customer_profile(customer_id)


def check_client_email(payload: dict) -> dict:
    """Check whether an email is already registered; return login URL if so."""
    import re

    if (payload.get("website") or "").strip():
        return {"success": True, "exists": False}

    email = str(payload.get("email") or "").strip().lower()
    if not email:
        return {"success": False, "error": "Email is required."}
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return {"success": False, "error": "Please enter a valid email address."}

    import os
    import sys
    scripts_dir = os.path.dirname(__file__)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from Customers import customer_exists_by_email  # type: ignore
    from config import build_customer_login_url  # type: ignore

    exists = customer_exists_by_email(email)
    result = {"success": True, "exists": exists, "email": email}
    if exists:
        result["login_url"] = build_customer_login_url(email)
    return result


def register_client_customer(payload: dict) -> dict:
    """Create a new Shopify customer from the public registration form."""
    import os
    import sys
    scripts_dir = os.path.dirname(__file__)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    if (payload.get("website") or "").strip():
        return {
            "success": True,
            "message": "Thanks for registering. We've received your details and will review your account shortly.",
        }

    from Customers import create_customer  # type: ignore

    first_name = str(payload.get("first_name") or "").strip()
    email = str(payload.get("email") or "").strip()
    company_name = str(payload.get("company_name") or "").strip()
    if not first_name:
        return {"success": False, "error": "First name is required."}
    if not email:
        return {"success": False, "error": "Email is required."}
    if not company_name:
        return {"success": False, "error": "Company is required."}

    safe = {k: payload[k] for k in CLIENT_PROFILE_KEYS if k in payload}
    safe["first_name"] = first_name
    safe["email"] = email
    safe["company_name"] = company_name

    try:
        customer = create_customer(safe)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    try:
        from config import build_customer_login_url  # type: ignore
        from scripts.klaviyo_api import (  # type: ignore
            KlaviyoError,
            klaviyo_customer_registered_configured,
            send_customer_registered,
        )

        if klaviyo_customer_registered_configured():
            send_customer_registered(
                email,
                customer_id=str(customer.get("id") or ""),
                first_name=safe.get("first_name") or first_name,
                last_name=safe.get("last_name") or "",
                company_name=safe.get("company_name") or "",
                login_url=build_customer_login_url(email),
            )
    except KlaviyoError as exc:
        import logging
        logging.getLogger(__name__).warning("Klaviyo registration email not sent: %s", exc)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Klaviyo registration email failed: %s", exc)

    return {
        "success": True,
        "customer_id": customer.get("id"),
        "message": "Thanks for registering. We've received your details and will review your account shortly.",
    }


def invalidate_customer_orders(customer_id: str | int) -> None:
    """Forget a customer's cached order list (after an order moves to/from them)."""
    prefix = f"orders:{str(customer_id).strip()}:"
    with _customer_cache_lock:
        for key in [k for k in _customer_cache if k.startswith(prefix)]:
            _customer_cache.pop(key, None)


def get_customer_orders(customer_id: str | int, fetch_all: bool = True) -> dict:
    """Return orders for one customer (paginated when fetch_all=True)."""
    cid = str(customer_id).strip()
    cache_key = f"orders:{cid}:{fetch_all}"
    now = time.time()
    with _customer_cache_lock:
        cached = _customer_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]
    gid = f"gid://shopify/Customer/{cid}"
    orders = []
    cursor = None
    customer_info = None

    try:
        while True:
            data = _graphql(CUSTOMER_ORDERS_QUERY, {"id": gid, "cursor": cursor})
            customer = data.get("customer")
            if not customer:
                if not orders:
                    return {"success": False, "error": "Customer not found", "orders": []}
                break

            if customer_info is None:
                customer_info = {
                    "id": customer.get("legacyResourceId"),
                    "email": customer.get("email") or "",
                    "first_name": customer.get("firstName") or "",
                    "last_name": customer.get("lastName") or "",
                }

            block = customer.get("orders") or {}
            for edge in block.get("edges") or []:
                node = edge.get("node") or {}
                # An order moved to another customer can linger in this list
                # while Shopify catches up - only show orders they own now.
                owner = str(((node.get("orderOwner") or {}).get("legacyResourceId")) or "")
                if owner and owner != cid:
                    continue
                base = {
                    "id": node.get("legacyResourceId"),
                    "name": node.get("name") or "",
                    "processed_at": node.get("processedAt") or "",
                    "financial_status": node.get("displayFinancialStatus") or "",
                    "fulfillment_status": node.get("displayFulfillmentStatus") or "",
                }
                orders.append(enrich_order(node, base))

            page_info = block.get("pageInfo") or {}
            if not fetch_all or not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break

        attach_dispatch_displays(orders)
        result = {
            "success": True,
            "customer": customer_info or {},
            "orders": orders,
            "total": len(orders),
        }
        with _customer_cache_lock:
            _customer_cache[cache_key] = (now + _CUSTOMER_CACHE_TTL_SEC, result)
        return result
    except Exception as e:
        return {"success": False, "error": str(e), "orders": [], "total": 0}


# --------------------------------------------------------------------------- #
# Company view: a customer can see every order placed by people in the same
# company (Customers > Companies in BiteBoard). Membership is cached briefly.
# --------------------------------------------------------------------------- #
_COMPANY_TTL_SEC = 300
_company_cache: dict[str, tuple[float, dict]] = {}


def client_company(customer_id: str | int) -> dict:
    """{"company_id", "company_name", "member_ids"} for this customer.

    Not in a company -> company_id None and member_ids == [customer_id].
    Lookup failures fail closed (just the customer themself).
    """
    cid = str(customer_id or "").strip()
    now = time.time()
    with _customer_cache_lock:
        hit = _company_cache.get(cid)
    if hit and hit[0] > now:
        return hit[1]
    result = {"company_id": None, "company_name": None, "member_ids": [cid]}
    try:
        from scripts.office_api import get_customer_company, get_company  # type: ignore
        link = get_customer_company(cid) or {}
        company_id = link.get("company_id")
        if company_id:
            company = get_company(str(company_id)) or {}
            if isinstance(company.get("company"), dict):
                company = company["company"]
            members = [str(m.get("customer_id") or "").strip() for m in company.get("members") or []]
            members = [m for m in members if m]
            if cid not in members:
                members.append(cid)
            result = {"company_id": str(company_id), "company_name": link.get("company_name") or company.get("name"),
                      "member_ids": members}
    except Exception:
        return result  # don't cache a failed lookup
    with _customer_cache_lock:
        _company_cache[cid] = (now + _COMPANY_TTL_SEC, result)
    return result


def client_can_see_owner(client_customer_id: str | int, owner_customer_id: str | int | None) -> bool:
    """A client sees their own orders, plus orders of anyone in their company."""
    client = str(client_customer_id or "").strip()
    owner = str(owner_customer_id or "").strip()
    if not client or not owner:
        return False
    if client == owner:
        return True
    return owner in client_company(client)["member_ids"]


def get_company_orders(customer_id: str | int) -> dict:
    """Every order placed by anyone in this customer's company, newest first,
    each tagged with who placed it."""
    from concurrent.futures import ThreadPoolExecutor

    company = client_company(customer_id)
    members = company["member_ids"]
    with ThreadPoolExecutor(max_workers=min(6, len(members) or 1)) as pool:
        results = list(pool.map(get_customer_orders, members))
    orders = []
    for member, res in zip(members, results):
        if not res.get("success"):
            continue
        who = res.get("customer") or {}
        placed_by = f"{who.get('first_name') or ''} {who.get('last_name') or ''}".strip() or who.get("email") or ""
        for o in res.get("orders") or []:
            orders.append({**o, "placed_by": placed_by, "placed_by_id": member})
    orders.sort(key=lambda o: o.get("processed_at") or "", reverse=True)
    return {"success": True, "orders": orders, "total": len(orders), "company": company}
