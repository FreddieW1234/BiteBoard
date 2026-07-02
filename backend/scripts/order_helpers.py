"""Shared Shopify order formatting for client and staff portals."""

from __future__ import annotations

import re

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


def format_gbp(amount: str | float | int | None) -> str:
    try:
        val = float(str(amount or "").replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        val = 0.0
    return f"£{val:,.2f}"


def format_line_price(unit_price: str | float | int, quantity: int, total: str | float | int) -> str:
    return f"{format_gbp(unit_price)} × {quantity} = {format_gbp(total)}"


def _is_hidden_item_property(key: str) -> bool:
    return (key or "").strip().lower() == "_packing fee pence"


def _parse_attributes(raw: list | None) -> list[dict]:
    out = []
    for attr in raw or []:
        key = (attr.get("key") or "").strip()
        value = (attr.get("value") or "").strip()
        if key:
            out.append({"key": key, "value": value})
    return out


def _merge_property_pairs(properties: list[dict]) -> tuple[list[str], list[dict]]:
    """Merge label + _label Code pairs into 'Label - value:code' strings."""
    if not properties:
        return [], []
    by_key = {p["key"]: p["value"] for p in properties}
    consumed: set[str] = set()
    merged: list[str] = []

    for prop in properties:
        key = prop["key"]
        if key in consumed or key.startswith("_"):
            continue
        code_key = f"_{key} Code"
        if code_key in by_key:
            merged.append(f"{key} - {prop['value']}:{by_key[code_key]}")
            consumed.add(key)
            consumed.add(code_key)
        elif key == "Mailer":
            merged.append(f"{key} - {prop['value']}")
            consumed.add(key)

    remaining = [
        p for p in properties
        if p["key"] not in consumed and not _is_hidden_item_property(p["key"])
    ]
    merged.sort(key=str.lower)
    return merged, remaining


def _build_meta_line(variant_title: str, merged_variants: list[str]) -> str:
    """Colour/variant pairs · qty band / customer type (SKU shown separately)."""
    parts: list[str] = list(merged_variants)
    if variant_title:
        parts.append(variant_title)
    return " · ".join(parts)


def _clean_fee_title(title: str) -> str:
    """Remove trailing variant marker e.g. 'Origination Fee (50)' → 'Origination Fee'."""
    return re.sub(r"\s*\(\d+\)\s*$", "", (title or "").strip()).strip()


def _is_hidden_fee_property(key: str) -> bool:
    k = (key or "").strip()
    return k in ("_for_product", "_pl") or k.startswith("_pl")


def _format_fee_item(item: dict) -> dict:
    """Fees: '{name} - {product}', hide _pl / _for_product and variant suffix."""
    properties = item.get("properties") or []
    by_key = {p["key"]: p["value"] for p in properties}
    fee_name = _clean_fee_title(item.get("title") or "")
    for_product = (by_key.get("_for_product") or "").strip()
    item["title"] = f"{fee_name} - {for_product}" if for_product else fee_name
    item["meta_line"] = ""
    item["variant_title"] = ""
    item["properties"] = [p for p in properties if not _is_hidden_fee_property(p["key"])]
    return item


def format_line_item(li: dict) -> dict:
    li_money = (li.get("originalTotalSet") or {}).get("shopMoney") or {}
    unit_money = (li.get("originalUnitPriceSet") or {}).get("shopMoney") or {}
    title = li.get("title") or ""
    currency = li_money.get("currencyCode") or unit_money.get("currencyCode") or "GBP"
    sku = (li.get("sku") or "").strip()
    variant_title = (li.get("variantTitle") or "").strip()
    properties = _parse_attributes(li.get("customAttributes"))
    merged_variants, remaining = _merge_property_pairs(properties)
    is_fee = is_fee_item(title)
    unit_price = unit_money.get("amount") or "0.00"
    total = li_money.get("amount") or "0.00"
    quantity = li.get("quantity") or 0
    item = {
        "title": title,
        "quantity": quantity,
        "sku": sku,
        "variant_title": variant_title,
        "meta_line": _build_meta_line(variant_title, merged_variants),
        "unit_price": unit_price,
        "total": total,
        "unit_price_display": format_gbp(unit_price),
        "total_display": format_gbp(total),
        "price_display": format_line_price(unit_price, quantity, total),
        "currency": currency,
        "properties": remaining,
        "is_fee": is_fee,
    }
    if is_fee:
        item = _format_fee_item(item)
    return item


def split_line_items(line_items: list[dict]) -> tuple[list[dict], list[dict]]:
    items = sorted(
        [li for li in line_items if not li.get("is_fee")],
        key=lambda li: (li.get("title") or "").lower(),
    )
    fees = sorted(
        [li for li in line_items if li.get("is_fee")],
        key=lambda li: (li.get("title") or "").lower(),
    )
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
    base["order_items"] = items
    base["fees"] = fees
    base["order_info"] = format_order_info(node)
    if "total" in base:
        base["total_display"] = format_gbp(base["total"])
    return base
