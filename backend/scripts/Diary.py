"""Staff Diary — flat list of order lines with dispatch planning."""

from __future__ import annotations

from scripts.diary_helpers import build_diary_rows, format_iso_date, parse_delivery_date  # type: ignore
from scripts.diary_store import get_all_entries, upsert_entry  # type: ignore
from scripts.Orders import get_orders_overview  # type: ignore


def get_diary_overview(max_orders: int = 250) -> dict:
    orders_result = get_orders_overview(max_orders=max_orders)
    if not orders_result.get("success"):
        return orders_result

    saved = get_all_entries()
    rows = build_diary_rows(orders_result.get("orders") or [], saved)
    return {"success": True, "total": len(rows), "rows": rows}


def save_diary_entry(payload: dict) -> dict:
    order_name = (payload.get("order_name") or "").strip()
    item_id = (payload.get("item_id") or "").strip()
    if not order_name or not item_id:
        return {"success": False, "error": "order_name and item_id are required"}

    dispatch_date = payload.get("dispatch_date")
    dispatch_manual = payload.get("dispatch_manual")
    carrier = payload.get("carrier")

    if dispatch_date is not None:
        parsed = parse_delivery_date(str(dispatch_date))
        if dispatch_date and not parsed:
            return {"success": False, "error": "Invalid dispatch date"}
        dispatch_date = format_iso_date(parsed) if parsed else ""

    try:
        entry = upsert_entry(
            order_name,
            item_id,
            dispatch_date=dispatch_date if dispatch_date is not None else None,
            dispatch_manual=dispatch_manual if dispatch_manual is not None else None,
            carrier=carrier if carrier is not None else None,
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    return {"success": True, "entry": entry}
