"""Fetch orders for a single Shopify customer (client portal)."""

from __future__ import annotations

import time
import requests

from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN  # type: ignore

HEADERS = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": ACCESS_TOKEN,
}

CUSTOMER_ORDERS_QUERY = """
query CustomerOrders($id: ID!, $cursor: String) {
  customer(id: $id) {
    legacyResourceId
    email
    firstName
    lastName
    orders(first: 50, after: $cursor, sortKey: PROCESSED_AT, reverse: true) {
      edges {
        node {
          legacyResourceId
          name
          processedAt
          displayFinancialStatus
          displayFulfillmentStatus
          totalPriceSet {
            shopMoney { amount currencyCode }
          }
          lineItems(first: 25) {
            edges {
              node {
                title
                quantity
                originalTotalSet {
                  shopMoney { amount currencyCode }
                }
              }
            }
          }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
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


def get_customer_orders(customer_id: str | int) -> dict:
    """Return orders for one customer only."""
    cid = str(customer_id).strip()
    gid = f"gid://shopify/Customer/{cid}"
    data = _graphql(CUSTOMER_ORDERS_QUERY, {"id": gid, "cursor": None})
    customer = data.get("customer")
    if not customer:
        return {"success": False, "error": "Customer not found", "orders": []}

    orders = []
    for edge in (customer.get("orders") or {}).get("edges") or []:
        node = edge.get("node") or {}
        money = (node.get("totalPriceSet") or {}).get("shopMoney") or {}
        line_items = []
        for li_edge in (node.get("lineItems") or {}).get("edges") or []:
            li = li_edge.get("node") or {}
            li_money = (li.get("originalTotalSet") or {}).get("shopMoney") or {}
            line_items.append({
                "title": li.get("title") or "",
                "quantity": li.get("quantity") or 0,
                "total": li_money.get("amount") or "0.00",
                "currency": li_money.get("currencyCode") or "GBP",
            })
        orders.append({
            "id": node.get("legacyResourceId"),
            "name": node.get("name") or "",
            "processed_at": node.get("processedAt") or "",
            "financial_status": node.get("displayFinancialStatus") or "",
            "fulfillment_status": node.get("displayFulfillmentStatus") or "",
            "total": money.get("amount") or "0.00",
            "currency": money.get("currencyCode") or "GBP",
            "line_items": line_items,
        })

    return {
        "success": True,
        "customer": {
            "id": customer.get("legacyResourceId"),
            "email": customer.get("email") or "",
            "first_name": customer.get("firstName") or "",
            "last_name": customer.get("lastName") or "",
        },
        "orders": orders,
    }
