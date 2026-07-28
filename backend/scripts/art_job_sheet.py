"""Build prefilled personalised art job sheet data for each product line."""

from __future__ import annotations

from scripts.diary_helpers import (  # type: ignore
    collect_delivery_date_fields,
    dispatch_display_for_line,
    parse_delivery_date,
    _match_field_for_line,
)
from scripts.Diary import load_saved_entries  # type: ignore
from scripts.order_helpers import fetch_order_by_id  # type: ignore
from scripts.production_note import (  # type: ignore
    _client_name,
    _format_order_date,
    _match_product_section,
)


def build_art_job_sheet(
    order: dict,
    line: dict,
    saved: dict[tuple[str, str], dict] | None = None,
) -> dict:
    """Return prefilled field values for one product line item."""
    order_info = order.get("order_info") or {}
    product_section = _match_product_section(order_info, line)
    date_fields = collect_delivery_date_fields(order_info)
    matched_date = _match_field_for_line(line, date_fields)
    delivery_raw = (matched_date.get("value") if matched_date else "") or ""
    delivery_date = parse_delivery_date(str(delivery_raw).strip())
    saved_entries = saved or {}
    dispatch_date = dispatch_display_for_line(
        order.get("name") or "",
        line,
        saved_entries,
        requested_date=delivery_date,
    )

    quantity = line.get("quantity")
    qty_text = str(quantity) if quantity is not None else ""

    return {
        "order_name": order.get("name") or "",
        "line_number": line.get("line_number"),
        "designer_name": "",
        "product": (line.get("title") or "").strip(),
        "name_on_product": _client_name(order, product_section),
        "date_order_received": _format_order_date(order.get("processed_at") or ""),
        "customer_supplier": (order.get("company") or "").strip(),
        "unit_quantity": qty_text,
        "dispatch_date": dispatch_date,
        "initial_proof_date": "",
        "additional_info": "",
        "rm_number": (line.get("sku") or "").strip(),
        "units_per_sheet": "",
        "sheets_printed": "",
        "total_units_printed": "",
        "date_printed": "",
    }


def build_art_job_sheets(
    order: dict,
    *,
    line_number: int | None = None,
    saved: dict[tuple[str, str], dict] | None = None,
) -> list[dict]:
    sheets: list[dict] = []
    for line in order.get("order_items") or []:
        if line.get("is_fee"):
            continue
        ln = line.get("line_number")
        if line_number is not None and ln != line_number:
            continue
        sheets.append(build_art_job_sheet(order, line, saved=saved))
    return sheets


def get_art_job_sheets_for_order(order_id: str | int, *, line_number: int | None = None) -> dict:
    order = fetch_order_by_id(order_id)
    if not order:
        return {"success": False, "error": "Order not found"}
    saved = load_saved_entries()
    sheets = build_art_job_sheets(order, line_number=line_number, saved=saved)
    if line_number is not None and not sheets:
        return {"success": False, "error": "Line item not found"}
    return {
        "success": True,
        "order_id": str(order.get("id") or order_id),
        "order_name": order.get("name") or "",
        "sheets": sheets,
    }
