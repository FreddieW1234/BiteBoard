"""Fetch Shopify orders for the staff Orders page."""

from __future__ import annotations

import time
import requests

from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN  # type: ignore

HEADERS = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": ACCESS_TOKEN,
}

ORDERS_QUERY = """
query StaffOrders($cursor: String) {
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
        customer {
          legacyResourceId
          displayName
          email
        }
        lineItems(first: 20) {
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


def _format_order_node(node: dict) -> dict:
    money = (node.get("totalPriceSet") or {}).get("shopMoney") or {}
    customer = node.get("customer") or {}
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
    return {
        "id": node.get("legacyResourceId"),
        "name": node.get("name") or "",
        "processed_at": node.get("processedAt") or "",
        "financial_status": node.get("displayFinancialStatus") or "",
        "fulfillment_status": node.get("displayFulfillmentStatus") or "",
        "total": money.get("amount") or "0.00",
        "currency": money.get("currencyCode") or "GBP",
        "customer_id": customer.get("legacyResourceId"),
        "customer_name": customer.get("displayName") or "",
        "customer_email": customer.get("email") or "",
        "line_items": line_items,
    }


def get_orders_overview(max_orders: int = 250) -> dict:
    """Return recent store orders for staff (paginated up to max_orders)."""
    orders = []
    cursor = None
    try:
        while len(orders) < max_orders:
            data = _graphql(ORDERS_QUERY, {"cursor": cursor})
            block = data.get("orders") or {}
            edges = block.get("edges") or []
            if not edges:
                break
            for edge in edges:
                node = edge.get("node")
                if node:
                    orders.append(_format_order_node(node))
                if len(orders) >= max_orders:
                    break
            page_info = block.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break
        return {"success": True, "total": len(orders), "orders": orders}
    except Exception as e:
        return {"success": False, "error": str(e), "total": 0, "orders": []}
