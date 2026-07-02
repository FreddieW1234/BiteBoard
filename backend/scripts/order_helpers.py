"""Shared Shopify order formatting for client and staff portals."""

from __future__ import annotations

LINE_ITEM_FIELDS = """
              title
              quantity
              sku
              variantTitle
              customAttributes { key value }
              originalUnitPriceSet {
                shopMoney { amount currencyCode }
              }
              originalTotalSet {
                shopMoney { amount currencyCode }
              }
"""

ORDER_EXTRA_FIELDS = """
          note
          customAttributes { key value }
"""


def is_fee_item(title: str) -> bool:
    return "fee" in (title or "").lower()


def _parse_attributes(raw: list | None) -> list[dict]:
    out = []
    for attr in raw or []:
        key = (attr.get("key") or "").strip()
        value = (attr.get("value") or "").strip()
        if key:
            out.append({"key": key, "value": value})
    return out


def format_line_item(li: dict) -> dict:
    li_money = (li.get("originalTotalSet") or {}).get("shopMoney") or {}
    unit_money = (li.get("originalUnitPriceSet") or {}).get("shopMoney") or {}
    title = li.get("title") or ""
    currency = li_money.get("currencyCode") or unit_money.get("currencyCode") or "GBP"
    return {
        "title": title,
        "quantity": li.get("quantity") or 0,
        "sku": li.get("sku") or "",
        "variant_title": li.get("variantTitle") or "",
        "unit_price": unit_money.get("amount") or "0.00",
        "total": li_money.get("amount") or "0.00",
        "currency": currency,
        "properties": _parse_attributes(li.get("customAttributes")),
        "is_fee": is_fee_item(title),
    }


def split_line_items(line_items: list[dict]) -> tuple[list[dict], list[dict]]:
    items = [li for li in line_items if not li.get("is_fee")]
    fees = [li for li in line_items if li.get("is_fee")]
    return items, fees


def format_order_info(node: dict) -> dict:
    note = (node.get("note") or "").strip()
    attributes = _parse_attributes(node.get("customAttributes"))
    return {"note": note, "attributes": attributes}


def parse_order_line_items(node: dict) -> list[dict]:
    line_items = []
    for li_edge in (node.get("lineItems") or {}).get("edges") or []:
        li = li_edge.get("node") or {}
        line_items.append(format_line_item(li))
    return line_items


def enrich_order(node: dict, base: dict) -> dict:
    """Add items/fees split and order_info to a base order dict."""
    line_items = parse_order_line_items(node)
    items, fees = split_line_items(line_items)
    base["line_items"] = line_items
    base["items"] = items
    base["fees"] = fees
    base["order_info"] = format_order_info(node)
    return base
