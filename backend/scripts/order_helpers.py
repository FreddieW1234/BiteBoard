"""Shared Shopify order formatting for client and staff portals."""

from __future__ import annotations

import re
import time

import requests

from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN  # type: ignore

HEADERS = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": ACCESS_TOKEN,
}

ORDER_UPDATE_MUTATION = """
mutation OrderUpdate($input: OrderInput!) {
  orderUpdate(input: $input) {
    order {
      legacyResourceId
      note
      customAttributes { key value }
    }
    userErrors { field message }
  }
}
"""

ORDER_CUSTOMER_QUERY = """
query OrderCustomer($id: ID!) {
  order(id: $id) {
    legacyResourceId
    customer { legacyResourceId }
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

ORDER_TOTAL_FIELDS = """
          subtotalPriceSet {
            shopMoney { amount currencyCode }
          }
          totalShippingPriceSet {
            shopMoney { amount currencyCode }
          }
          totalTaxSet {
            shopMoney { amount currencyCode }
          }
          totalPriceSet {
            shopMoney { amount currencyCode }
          }
"""

ADDRESS_FIELDS = """
            firstName
            lastName
            name
            company
            address1
            address2
            city
            province
            zip
            country
            countryCodeV2
            phone
"""

ORDER_ADDRESS_PAYMENT_FIELDS = f"""
{ORDER_TOTAL_FIELDS}
          shippingAddress {{
{ADDRESS_FIELDS}
          }}
          billingAddress {{
{ADDRESS_FIELDS}
          }}
          paymentGatewayNames
          paymentTerms {{
            paymentTermsName
            paymentTermsType
            dueInDays
          }}
          transactions {{
            gateway
            formattedGateway
            manualPaymentGateway
            kind
            status
          }}
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


def _is_order_info_section_heading(key: str, inline_value: str = "") -> bool:
    """ALL CAPS label with colon and no value on the same line (e.g. DELIVERY CONTACT:)."""
    k = (key or "").strip().rstrip(":")
    if not k or (inline_value or "").strip():
        return False
    letters = [c for c in k if c.isalpha()]
    return bool(letters) and k.upper() == k


_PRODUCT_PAIR_FIELD_KEYS = frozenset({"name", "address"})


def _order_info_field_full_width(key: str, value: str = "") -> bool:
    k_norm = (key or "").strip().rstrip(":").lower()
    if k_norm in _PRODUCT_PAIR_FIELD_KEYS:
        return False
    if k_norm in _ADDITIONAL_NOTES_HEADINGS:
        return True
    if "\n" in (value or ""):
        return True
    return bool(re.search(r"address|notes|comments|instructions|details", key or "", re.I))


_NOTE_LINE = re.compile(r"^(.+?):\s*(.*)$")

_DELIVERY_DATE_KEY_NAMES = frozenset({"delivery date", "requested delivery date"})
_REQUEST_DELIVERY_DATES_HEADINGS = frozenset({"request delivery dates", "requested delivery dates"})
_ADDITIONAL_NOTES_HEADINGS = frozenset({"additional notes"})


def _section_heading_norm(heading: str | None) -> str:
    return (heading or "").strip().rstrip(":").lower()


def _is_request_delivery_dates_heading(heading: str | None) -> bool:
    return _section_heading_norm(heading) in _REQUEST_DELIVERY_DATES_HEADINGS


def _is_additional_notes_section(heading: str | None) -> bool:
    return _section_heading_norm(heading) in _ADDITIONAL_NOTES_HEADINGS


def _is_po_key(key: str) -> bool:
    return (key or "").upper().startswith("PO NUMBER")


def _is_single_delivery_date_key(key: str) -> bool:
    return (key or "").upper().startswith("REQUESTED DELIVERY DATE")


def _append_note_field_lines(out_lines: list[str], field: dict) -> None:
    key = (field.get("key") or "").strip()
    if key and not key.endswith(":"):
        key += ":"
    value = str(field.get("value") or "").replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in value:
        out_lines.append(key)
        out_lines.extend(value.split("\n"))
    elif value:
        out_lines.append(f"{key} {value}")
    elif key:
        out_lines.append(key)


def _order_info_field_meta(key: str, value: str = "") -> dict:
    """Canonical Shopify key + UI label for a parsed note field."""
    k_norm = (key or "").strip().rstrip(":").lower()
    if k_norm in _DELIVERY_DATE_KEY_NAMES:
        return {
            "key": "REQUESTED DELIVERY DATE:",
            "display_label": "Requested delivery date (DD.MM.YYYY ONLY):",
            "full_width": False,
        }
    canonical = key if key.endswith(":") else f"{key}:"
    meta = {
        "key": canonical,
        "display_label": canonical,
        "full_width": _order_info_field_full_width(key, value),
    }
    if k_norm == "address":
        meta["field_role"] = "address"
    return meta


def _finalize_order_note_sections(sections: list[dict]) -> list[dict]:
    """Build PO + delivery dates top row; ensure additional notes have a field."""
    po_field: dict | None = None
    date_fields: list[dict] = []

    si = 0
    while si < len(sections):
        sec = sections[si]
        heading = sec.get("heading")
        fi = 0
        while fi < len(sec.get("fields") or []):
            field = sec["fields"][fi]
            key = field.get("key") or ""
            if _is_po_key(key):
                po_field = sec["fields"].pop(fi)
                continue
            if _is_single_delivery_date_key(key):
                moved = sec["fields"].pop(fi)
                moved["restore_heading"] = None
                moved["field_role"] = "date"
                moved["full_width"] = False
                date_fields.append(moved)
                continue
            if _is_request_delivery_dates_heading(heading):
                moved = sec["fields"].pop(fi)
                moved["restore_heading"] = heading
                moved["field_role"] = "date"
                moved["full_width"] = False
                date_fields.append(moved)
                continue
            fi += 1

        if _is_request_delivery_dates_heading(heading) and not sec.get("fields"):
            sections.pop(si)
            continue

        if _is_additional_notes_section(heading) and not sec.get("fields"):
            sec["fields"] = [{
                "key": "ADDITIONAL NOTES:",
                "display_label": "Additional notes:",
                "full_width": True,
                "value": "",
            }]

        sec.pop("separator_before", None)
        si += 1

    sections[:] = [s for s in sections if s.get("layout") or s.get("heading") or s.get("fields")]

    if po_field or date_fields:
        top_fields: list[dict] = []
        if po_field:
            po_field["field_role"] = "po"
            po_field["full_width"] = False
            top_fields.append(po_field)
        top_fields.extend(date_fields)
        sections.insert(0, {
            "layout": "date_top_row",
            "heading": None,
            "fields": top_fields,
            "field_count": len(top_fields),
            "date_count": len(date_fields),
        })

    return sections


def parse_order_note(note: str) -> list[dict]:
    """Parse Shopify order note text into titled sections and labelled fields."""
    text = (note or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    sections: list[dict] = []
    current: dict | None = None
    i = 0
    n = len(lines)

    def ensure_section() -> dict:
        nonlocal current
        if current is None:
            current = {"heading": None, "fields": []}
            sections.append(current)
        return current

    def next_meaningful(start: int) -> tuple[int | None, str | None]:
        j = start
        while j < n:
            s = lines[j].strip()
            if s:
                return j, s
            j += 1
        return None, None

    while i < n:
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        m = _NOTE_LINE.match(stripped)
        if not m:
            if current and _is_additional_notes_section(current.get("heading")):
                if not current.get("fields"):
                    current["fields"].append({
                        "key": "ADDITIONAL NOTES:",
                        "display_label": "Additional notes:",
                        "full_width": True,
                        "value": "",
                    })
                notes_field = current["fields"][-1]
                if not stripped:
                    if notes_field["value"]:
                        notes_field["value"] += "\n"
                else:
                    notes_field["value"] = (
                        f"{notes_field['value']}\n{stripped}" if notes_field["value"] else stripped
                    )
                i += 1
                continue
            i += 1
            continue

        key_raw = m.group(1).strip()
        inline_val = m.group(2)
        key = key_raw if key_raw.endswith(":") else f"{key_raw}:"

        if _is_order_info_section_heading(key_raw, inline_val):
            current = {"heading": key, "fields": []}
            sections.append(current)
            i += 1
            continue

        if inline_val.strip() and key_raw.upper() == key_raw and re.search(r"[A-Z]", key_raw):
            if current and current.get("fields"):
                current = None

        if inline_val.strip():
            value = inline_val
            i += 1
        else:
            i += 1
            val_lines: list[str] = []
            while i < n:
                s = lines[i].strip()
                if not s:
                    _, ns = next_meaningful(i + 1)
                    if ns and _NOTE_LINE.match(ns):
                        break
                    if ns is None:
                        break
                    val_lines.append("")
                    i += 1
                    continue
                if _NOTE_LINE.match(s):
                    break
                val_lines.append(lines[i].rstrip("\n"))
                i += 1
            value = "\n".join(val_lines)

        sec = ensure_section()
        meta = _order_info_field_meta(key, value)
        sec["fields"].append({**meta, "value": value})

    return _finalize_order_note_sections(sections)


def serialize_order_note(sections: list[dict]) -> str:
    """Rebuild Shopify order note text from structured sections."""
    out_lines: list[str] = []
    for si, sec in enumerate(sections or []):
        if sec.get("layout") == "date_top_row":
            if si > 0 and out_lines and out_lines[-1] != "":
                out_lines.append("")
            grouped: dict[str | None, list[dict]] = {}
            for field in sec.get("fields") or []:
                rh = field.get("restore_heading")
                grouped.setdefault(rh, []).append(field)
            for field in grouped.get(None, []):
                _append_note_field_lines(out_lines, field)
            for rh, fields in grouped.items():
                if rh is None:
                    continue
                if out_lines and out_lines[-1] != "":
                    out_lines.append("")
                heading = rh if rh.endswith(":") else f"{rh}:"
                out_lines.append(heading)
                for field in fields:
                    _append_note_field_lines(out_lines, field)
            continue

        if si > 0 and out_lines and out_lines[-1] != "":
            out_lines.append("")
        heading = (sec.get("heading") or "").strip()
        if heading:
            if not heading.endswith(":"):
                heading += ":"
            out_lines.append(heading)
        for field in sec.get("fields") or []:
            _append_note_field_lines(out_lines, field)
    return "\n".join(out_lines).strip()


def group_order_info_attributes(attributes: list[dict]) -> list[dict]:
    """Group flat customAttributes into titled sections for display."""
    sections: list[dict] = []
    current: dict | None = None

    for attr in attributes or []:
        key = (attr.get("key") or "").strip()
        value = attr.get("value") or ""
        if _is_order_info_section_heading(key, value):
            current = {"heading": key if key.endswith(":") else f"{key}:", "heading_value": value, "fields": []}
            sections.append(current)
            continue
        if current is None:
            current = {"heading": None, "heading_value": "", "fields": []}
            sections.append(current)
        current["fields"].append({
            "key": key if key.endswith(":") else f"{key}:",
            "value": value,
            "full_width": _order_info_field_full_width(key, value),
        })

    return sections


def format_order_info(node: dict) -> dict:
    note = (node.get("note") or "").strip()
    attributes = _parse_attributes(node.get("customAttributes"))
    note_sections = parse_order_note(note)
    return {
        "note": note,
        "attributes": attributes,
        "note_sections": note_sections,
        "sections": group_order_info_attributes(attributes),
        "structured": bool(note_sections) or bool(attributes),
    }


def parse_order_line_items(node: dict) -> list[dict]:
    line_items = []
    product_line_num = 0
    for li_edge in (node.get("lineItems") or {}).get("edges") or []:
        li = li_edge.get("node") or {}
        item = format_line_item(li)
        if not item.get("is_fee"):
            product_line_num += 1
            item["line_number"] = product_line_num
        line_items.append(item)
    return line_items


def format_mailing_address(addr: dict | None) -> dict | None:
    """Format a Shopify MailingAddress into display lines."""
    if not addr:
        return None
    parts: list[str] = []
    name = (addr.get("name") or "").strip()
    if not name:
        first = (addr.get("firstName") or "").strip()
        last = (addr.get("lastName") or "").strip()
        name = " ".join(x for x in (first, last) if x)
    if name:
        parts.append(name)
    company = (addr.get("company") or "").strip()
    if company:
        parts.append(company)
    for key in ("address1", "address2"):
        val = (addr.get(key) or "").strip()
        if val:
            parts.append(val)
    city = (addr.get("city") or "").strip()
    province = (addr.get("province") or "").strip()
    zip_code = (addr.get("zip") or "").strip()
    city_line = ", ".join(x for x in (city, province, zip_code) if x)
    if city_line:
        parts.append(city_line)
    country = (addr.get("country") or "").strip()
    if country:
        parts.append(country)
    phone = (addr.get("phone") or "").strip()
    if phone:
        parts.append(phone)
    if not parts:
        return None
    country_code = (addr.get("countryCodeV2") or "").strip().upper()
    if not country_code and country:
        country_code = _guess_country_code(country)
    return {
        "lines": parts,
        "text": "\n".join(parts),
        "name": name,
        "company": company,
        "address1": (addr.get("address1") or "").strip(),
        "address2": (addr.get("address2") or "").strip(),
        "city": city,
        "province": province,
        "zip": zip_code,
        "country": country,
        "country_code": country_code or "GB",
        "phone": phone,
    }


def _guess_country_code(country: str) -> str:
    c = (country or "").strip().lower()
    if c in ("united kingdom", "uk", "great britain", "gb"):
        return "GB"
    if c in ("ireland", "republic of ireland"):
        return "IE"
    if len(c) == 2:
        return c.upper()
    return ""


_ON_ACCOUNT_GATEWAY_HINTS = (
    "account", "invoice", "manual", "bank", "deferred", "cod", "cheque", "check", "transfer",
)


def _is_on_account_phrase(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return False
    if normalized in ("on account", "pay on account"):
        return True
    return "pay" in normalized and "account" in normalized and len(normalized.split()) <= 4


def _payment_display_detail(label: str, detail: str) -> str:
    """Drop gateway detail when it repeats the payment label (e.g. 'On account' ×3)."""
    detail = (detail or "").strip()
    if not detail:
        return ""
    label_l = label.lower().strip()
    parts = [p.strip() for p in re.split(r",\s*", detail) if p.strip()]
    if label_l == "on account" and parts and all(_is_on_account_phrase(p) for p in parts):
        return ""
    if label_l == "card" and len(parts) == 1 and parts[0].lower() in ("card", "card payment"):
        return ""
    if detail.lower().strip(".") == label_l:
        return ""
    return detail


def format_payment_method(node: dict) -> dict:
    """Classify payment as Card or On account using Shopify gateway / terms data."""
    payment_terms = node.get("paymentTerms") or {}
    terms_name = (payment_terms.get("paymentTermsName") or "").strip()
    if terms_name:
        label = "On account"
        detail = "" if _is_on_account_phrase(terms_name) else terms_name
        return {"method": "on_account", "label": label, "detail": detail}

    gateways: set[str] = set()
    has_card = False
    has_manual = False

    for txn in node.get("transactions") or []:
        status = (txn.get("status") or "").upper()
        kind = (txn.get("kind") or "").upper()
        if kind in ("REFUND", "VOID", "CHANGE"):
            continue
        if status and status not in ("SUCCESS", "PENDING", "AUTHORIZATION", "AWAITING_RESPONSE"):
            continue
        gw = (txn.get("formattedGateway") or txn.get("gateway") or "").strip()
        if gw:
            gateways.add(gw)
        if txn.get("manualPaymentGateway"):
            has_manual = True
        else:
            has_card = True

    for gw in node.get("paymentGatewayNames") or []:
        gw = (gw or "").strip()
        if not gw:
            continue
        gateways.add(gw)
        gw_lower = gw.lower()
        if any(hint in gw_lower for hint in _ON_ACCOUNT_GATEWAY_HINTS):
            has_manual = True
        elif "shopify payments" in gw_lower or "credit" in gw_lower or "debit" in gw_lower:
            has_card = True

    detail = ", ".join(sorted(gateways)) if gateways else ""

    if has_manual and not has_card:
        return {
            "method": "on_account",
            "label": "On account",
            "detail": _payment_display_detail("On account", detail or "Manual / invoice payment"),
        }
    if has_card:
        return {
            "method": "card",
            "label": "Card",
            "detail": _payment_display_detail("Card", detail or "Card payment"),
        }

    if detail:
        gw_lower = detail.lower()
        if any(hint in gw_lower for hint in _ON_ACCOUNT_GATEWAY_HINTS):
            return {
                "method": "on_account",
                "label": "On account",
                "detail": _payment_display_detail("On account", detail),
            }
        return {
            "method": "card",
            "label": "Card",
            "detail": _payment_display_detail("Card", detail),
        }

    financial = (node.get("displayFinancialStatus") or "").replace("_", " ").strip()
    if financial:
        financial_title = financial.title()
        return {"method": "unknown", "label": financial_title, "detail": ""}
    return {"method": "unknown", "label": "—", "detail": ""}


def _shop_money(node: dict, field: str) -> tuple[str, str]:
    money = (node.get(field) or {}).get("shopMoney") or {}
    return money.get("amount") or "0.00", money.get("currencyCode") or "GBP"


def format_order_totals(node: dict) -> dict:
    """Extract subtotal, shipping, tax, and total from a Shopify order node."""
    subtotal, _ = _shop_money(node, "subtotalPriceSet")
    shipping, _ = _shop_money(node, "totalShippingPriceSet")
    tax, _ = _shop_money(node, "totalTaxSet")
    total, currency = _shop_money(node, "totalPriceSet")
    return {
        "subtotal": subtotal,
        "subtotal_display": format_gbp(subtotal),
        "shipping": shipping,
        "shipping_display": format_gbp(shipping),
        "tax": tax,
        "tax_display": format_gbp(tax),
        "total": total,
        "total_display": format_gbp(total),
        "currency": currency,
    }


def enrich_order(node: dict, base: dict) -> dict:
    """Add items/fees split, addresses, payment, and order_info to a base order dict."""
    line_items = parse_order_line_items(node)
    items, fees = split_line_items(line_items)
    base["line_items"] = line_items
    base["order_items"] = items
    base["fees"] = fees
    base["shipping_address"] = format_mailing_address(node.get("shippingAddress"))
    base["billing_address"] = format_mailing_address(node.get("billingAddress"))
    base["payment"] = format_payment_method(node)
    base["order_info"] = format_order_info(node)
    base.update(format_order_totals(node))
    return base


ORDER_BY_ID_QUERY = (
    """
query OrderById($id: ID!) {
  order(id: $id) {
    legacyResourceId
    name
    processedAt
    customer {
      legacyResourceId
      email
    }
"""
    + ORDER_EXTRA_FIELDS
    + ORDER_ADDRESS_PAYMENT_FIELDS
    + """
    lineItems(first: 50) {
      edges {
        node {
"""
    + LINE_ITEM_FIELDS
    + """
        }
      }
    }
  }
}
"""
)


def fetch_order_by_id(order_id: str | int) -> dict | None:
    """Fetch a single order from Shopify and enrich it."""
    gid = f"gid://shopify/Order/{order_id}"
    data = _graphql(ORDER_BY_ID_QUERY, {"id": gid})
    node = data.get("order")
    if not node:
        return None
    customer = node.get("customer") or {}
    base = {
        "id": node.get("legacyResourceId"),
        "name": node.get("name") or "",
        "processed_at": node.get("processedAt") or "",
        "customer_id": customer.get("legacyResourceId"),
        "customer_email": (customer.get("email") or "").strip(),
    }
    return enrich_order(node, base)


_order_access_cache: dict[str, tuple[float, dict]] = {}


def _build_access_entry(order: dict) -> dict:
    from scripts.office_api import item_key  # type: ignore

    line_items = []
    for item in order.get("order_items") or []:
        ln = item.get("line_number")
        title = item.get("title") or ""
        if ln is None:
            continue
        oid = item_key(ln, title)
        item["office_item_id"] = oid
        line_items.append({
            "line_number": ln,
            "title": title,
            "office_item_id": oid,
        })
    cid = order.get("customer_id")
    return {
        "order_id": str(order.get("id")),
        "name": order.get("name") or "",
        "customer_id": str(cid) if cid else None,
        "line_items": line_items,
        "order": order,
    }


def resolve_order_access(
    order_id: str | int,
    *,
    refresh: bool = False,
    client_customer_id: str | None = None,
) -> dict | None:
    """Return cached order name, customer, and line items for auth; None if denied."""
    from config import ORDER_ACCESS_CACHE_TTL_SEC  # type: ignore

    oid = str(order_id).strip()
    now = time.time()
    if not refresh:
        cached = _order_access_cache.get(oid)
        if cached and cached[0] > now:
            entry = cached[1]
            if client_customer_id is not None:
                owner = entry.get("customer_id")
                if not owner or str(owner) != str(client_customer_id):
                    return None
            return entry

    order = fetch_order_by_id(order_id)
    if not order:
        return None
    entry = _build_access_entry(order)
    if client_customer_id is not None:
        owner = entry.get("customer_id")
        if not owner or str(owner) != str(client_customer_id):
            return None
    _order_access_cache[oid] = (now + ORDER_ACCESS_CACHE_TTL_SEC, entry)
    return entry


def validate_office_item(entry: dict, item: str) -> bool:
    return any(li.get("office_item_id") == item for li in (entry.get("line_items") or []))


def attach_office_tracking(order: dict, *, seed: bool = True) -> dict:
    """Attach Office API status views to each product line item."""
    import logging

    from scripts.office_api import ensure_item, item_key, OfficeApiError  # type: ignore

    log = logging.getLogger(__name__)
    order_name = order.get("name") or ""
    for item in order.get("order_items") or []:
        ln = item.get("line_number")
        if ln is None:
            continue
        if not item.get("office_item_id"):
            item["office_item_id"] = item_key(ln, item.get("title") or "")
        if seed:
            try:
                item["office"] = ensure_item(
                    order_name,
                    item["office_item_id"],
                    item.get("title") or "",
                )
            except OfficeApiError as exc:
                log.warning("Office ensure_item failed for %s: %s", item["office_item_id"], exc)
                item["office"] = None
    return order


def get_order_customer_id(order_id: str | int) -> str | None:
    gid = f"gid://shopify/Order/{order_id}"
    data = _graphql(ORDER_CUSTOMER_QUERY, {"id": gid})
    order = data.get("order")
    if not order:
        return None
    customer = order.get("customer") or {}
    cid = customer.get("legacyResourceId")
    return str(cid) if cid else None


def update_order_info(
    order_id: str | int,
    note: str,
    attributes: list[dict],
    note_sections: list[dict] | None = None,
) -> dict:
    """Update order note and customAttributes (full attribute list required by Shopify)."""
    if note_sections is not None:
        note = serialize_order_note(note_sections)
    gid = f"gid://shopify/Order/{order_id}"
    custom_attributes = [
        {"key": str(a.get("key") or "").strip(), "value": str(a.get("value") or "").strip()}
        for a in (attributes or [])
        if str(a.get("key") or "").strip()
    ]
    data = _graphql(ORDER_UPDATE_MUTATION, {
        "input": {
            "id": gid,
            "note": str(note or "").strip(),
            "customAttributes": custom_attributes,
        },
    })
    result = data.get("orderUpdate") or {}
    errors = result.get("userErrors") or []
    if errors:
        msg = "; ".join(
            (e.get("message") or "Unknown error") for e in errors if e.get("message")
        )
        raise RuntimeError(msg or "Order update failed")
    order = result.get("order") or {}
    return {
        "success": True,
        "order_info": format_order_info(order),
    }
