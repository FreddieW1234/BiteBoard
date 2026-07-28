"""Build prefilled production note data for each product line in an order."""

from __future__ import annotations

import re
from datetime import datetime

from scripts.diary_helpers import (  # type: ignore
    collect_delivery_date_fields,
    default_dispatch_date,
    format_display_date,
    parse_delivery_date,
    _match_field_for_line,
)
from scripts.order_helpers import fetch_order_by_id  # type: ignore

DEFAULT_SALES_PERSON = "DAVE"


def _format_order_date(processed_at: str) -> str:
    text = (processed_at or "").strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return ""


def _norm_key(key: str) -> str:
    return (key or "").strip().rstrip(":").lower()


def _field_value(section: dict | None, *keys: str) -> str:
    if not section:
        return ""
    wanted = {_norm_key(k) for k in keys}
    for field in section.get("fields") or []:
        if _norm_key(field.get("key") or "") in wanted:
            return str(field.get("value") or "").strip()
    return ""


def _section_heading_norm(heading: str | None) -> str:
    return (heading or "").strip().rstrip(":").upper()


def _section_matches_line(section: dict, line: dict, product_sections: list[dict], index: int) -> bool:
    heading = _section_heading_norm(section.get("heading"))
    if not heading:
        return False
    sku = (line.get("sku") or "").strip().upper()
    title = (line.get("title") or "").strip().upper()
    if sku and (f"({sku})" in heading or heading.endswith(sku) or sku in heading):
        return True
    if title and title in heading:
        return True
    line_num = line.get("line_number")
    if isinstance(line_num, int) and line_num > 0 and len(product_sections) >= line_num:
        return product_sections[line_num - 1] is section
    return index == 0 and len(product_sections) == 1


def _product_note_sections(order_info: dict) -> list[dict]:
    sections: list[dict] = []
    for sec in order_info.get("note_sections") or []:
        if sec.get("layout") == "date_top_row":
            continue
        heading = _section_heading_norm(sec.get("heading"))
        if not heading:
            continue
        if heading in {
            "REQUEST DELIVERY DATES",
            "REQUESTED DELIVERY DATES",
            "ADDITIONAL NOTES",
            "DELIVERY CONTACT",
        }:
            continue
        fields = sec.get("fields") or []
        if any(_norm_key(f.get("key") or "") in {"name", "address"} for f in fields):
            sections.append(sec)
            continue
        if heading and not _field_value(sec, "po number"):
            sections.append(sec)
    return sections


def _match_product_section(order_info: dict, line: dict) -> dict | None:
    product_sections = _product_note_sections(order_info)
    if not product_sections:
        return None
    for idx, sec in enumerate(product_sections):
        if _section_matches_line(sec, line, product_sections, idx):
            return sec
    line_num = line.get("line_number")
    if isinstance(line_num, int) and line_num > 0 and len(product_sections) >= line_num:
        return product_sections[line_num - 1]
    if len(product_sections) == 1:
        return product_sections[0]
    return None


def _global_note_value(order_info: dict, *keys: str) -> str:
    for sec in order_info.get("note_sections") or []:
        val = _field_value(sec, *keys)
        if val:
            return val
    for sec in order_info.get("sections") or []:
        val = _field_value(sec, *keys)
        if val:
            return val
    return ""


def _origination_for_product(order: dict, line: dict) -> str:
    title = (line.get("title") or "").strip()
    sku = (line.get("sku") or "").strip()
    for group in order.get("fees_by_product") or []:
        product = (group.get("product") or "").strip()
        if not product:
            continue
        if product == title or (sku and sku in product) or title in product:
            for fee in group.get("fees") or []:
                if fee.get("is_origination"):
                    return fee.get("total_display") or fee.get("total") or ""
    for fee in order.get("fees") or []:
        if not fee.get("is_origination"):
            continue
        for_product = (fee.get("for_product") or "").strip()
        if not for_product or for_product == title or (sku and sku in for_product):
            return fee.get("total_display") or fee.get("total") or ""
    return ""


def _delivery_address(order: dict, product_section: dict | None) -> str:
    addr = _field_value(product_section, "address") if product_section else ""
    if addr:
        return addr
    shipping = order.get("shipping_address") or {}
    return (shipping.get("text") or "").strip()


def _client_name(order: dict, product_section: dict | None) -> str:
    name = _field_value(product_section, "name") if product_section else ""
    if name:
        return name
    customer_name = (order.get("customer_name") or "").strip()
    if customer_name:
        return customer_name
    shipping = order.get("shipping_address") or {}
    return (shipping.get("name") or "").strip()


def _pack_size(line: dict) -> str:
    variant = (line.get("variant_title") or "").strip()
    if variant:
        return variant
    for prop in line.get("properties") or []:
        key = _norm_key(prop.get("key") or "")
        if "pack" in key or key in {"size", "product size"}:
            return str(prop.get("value") or "").strip()
    return ""


def _parse_case_quantity(line: dict) -> int | None:
    for prop in line.get("properties") or []:
        key = _norm_key(prop.get("key") or "")
        if key in {"case quantity", "case_quantity", "units per case", "pack size"}:
            try:
                val = int(float(str(prop.get("value") or "").strip()))
                if val > 0:
                    return val
            except (TypeError, ValueError):
                continue
    variant = (line.get("variant_title") or "")
    m = re.search(r"(?:case\s*of|x)\s*(\d+)", variant, re.I)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _total_cases(line: dict) -> str:
    qty = line.get("quantity")
    case_qty = _parse_case_quantity(line)
    if isinstance(qty, int) and qty > 0 and case_qty and case_qty > 0:
        if qty % case_qty == 0:
            return str(qty // case_qty)
        return f"{qty / case_qty:.2f}".rstrip("0").rstrip(".")
    return ""


def build_production_note(order: dict, line: dict) -> dict:
    """Return prefilled field values for one product line item."""
    order_info = order.get("order_info") or {}
    product_section = _match_product_section(order_info, line)
    date_fields = collect_delivery_date_fields(order_info)
    matched_date = _match_field_for_line(line, date_fields)
    delivery_raw = (matched_date.get("value") if matched_date else "") or ""
    delivery_date = parse_delivery_date(str(delivery_raw).strip())
    dispatch_date = default_dispatch_date(delivery_date) if delivery_date else None

    quantity = line.get("quantity")
    qty_text = str(quantity) if quantity is not None else ""

    return {
        "order_name": order.get("name") or "",
        "line_number": line.get("line_number"),
        "product_title": (line.get("title") or "").strip(),
        "double_checked_by": "",
        "date_of_order": _format_order_date(order.get("processed_at") or ""),
        "company_name": (order.get("company") or "").strip(),
        "product_code": (line.get("sku") or "").strip(),
        "total_units_ordered": qty_text,
        "pack_size": _pack_size(line),
        "origination_charge": _origination_for_product(order, line),
        "dispatch_date": format_display_date(dispatch_date),
        "delivery_address_confirmed": _delivery_address(order, product_section),
        "approved_to_print": "",
        "sales_person": DEFAULT_SALES_PERSON,
        "client_name_logo": _client_name(order, product_section),
        "product": (line.get("title") or "").strip(),
        "total_cases_ordered": _total_cases(line),
        "case_price": line.get("unit_price_display") or line.get("unit_price") or "",
        "email_address": (order.get("customer_email") or "").strip(),
        "delivery_date": format_display_date(delivery_date),
        "use_customers_delivery_note": _global_note_value(
            order_info,
            "use customer's delivery note",
            "use customers delivery note",
            "delivery note",
        ),
        "sample_to_customer": _global_note_value(order_info, "sample to customer"),
        "proforma_emailed_person": "",
        "proforma_emailed_date": "",
        "proforma_phoned_person": "",
        "proforma_phoned_date": "",
        "paid_by": "",
        "paid_date": "",
        "no_of_shippers": "",
        "no_of_pallets": "",
        "wip_on": "",
        "wip_dispatch_date": format_display_date(dispatch_date),
    }


def build_production_notes(order: dict, *, line_number: int | None = None) -> list[dict]:
    notes: list[dict] = []
    for line in order.get("order_items") or []:
        if line.get("is_fee"):
            continue
        ln = line.get("line_number")
        if line_number is not None and ln != line_number:
            continue
        notes.append(build_production_note(order, line))
    return notes


def get_production_notes_for_order(order_id: str | int, *, line_number: int | None = None) -> dict:
    order = fetch_order_by_id(order_id)
    if not order:
        return {"success": False, "error": "Order not found"}
    notes = build_production_notes(order, line_number=line_number)
    if line_number is not None and not notes:
        return {"success": False, "error": "Line item not found"}
    return {
        "success": True,
        "order_id": str(order.get("id") or order_id),
        "order_name": order.get("name") or "",
        "notes": notes,
    }
