"""Fetch orders for a single Shopify customer (client portal)."""

from __future__ import annotations

import time
import requests

from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN  # type: ignore

HEADERS = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": ACCESS_TOKEN,
}

from scripts.order_helpers import LINE_ITEM_FIELDS, ORDER_EXTRA_FIELDS, ORDER_ADDRESS_PAYMENT_FIELDS, enrich_order  # type: ignore

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
    try:
        import os
        import sys
        scripts_dir = os.path.dirname(__file__)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from Customers import _fetch_single_customer  # type: ignore
        profile = _fetch_single_customer(cid)
        return {
            "success": True,
            "profile": {
                "id": profile.get("id"),
                "name": profile.get("name") or "",
                "first_name": profile.get("first_name") or "",
                "last_name": profile.get("last_name") or "",
                "email": profile.get("email") or "",
                "company_name": profile.get("company_name") or "",
                "invoice_address": profile.get("invoice_address") or "",
                "landline_phone": profile.get("landline_phone") or "",
                "mobile_number": profile.get("mobile_number") or "",
            },
        }
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
    from Customers import update_customer_details  # type: ignore

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
    update_customer_details(customer_id, safe)
    return get_customer_profile(customer_id)


def get_customer_orders(customer_id: str | int, fetch_all: bool = True) -> dict:
    """Return orders for one customer (paginated when fetch_all=True)."""
    cid = str(customer_id).strip()
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

        return {
            "success": True,
            "customer": customer_info or {},
            "orders": orders,
            "total": len(orders),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "orders": [], "total": 0}
