"""Staff Diary — flat list of order lines with dispatch planning.

Persistence prefers the Office API (durable) and falls back to a local
SQLite store when the Office API diary endpoints are unavailable. This keeps
local development working and means saved data survives Render redeploys once
the Office API exposes the diary endpoints.
"""

from __future__ import annotations

import logging

from scripts.diary_helpers import build_diary_rows, format_iso_date, parse_delivery_date  # type: ignore
from scripts.diary_store import get_all_entries, upsert_entry  # type: ignore
from scripts.Orders import get_orders_overview  # type: ignore

logger = logging.getLogger(__name__)

try:
    from scripts import office_api  # type: ignore
except Exception:  # pragma: no cover - office api optional
    office_api = None


def _office_diary_available() -> bool:
    return office_api is not None and bool(getattr(office_api, "OFFICE_API_URL", None))


def _load_saved_entries() -> dict[tuple[str, str], dict]:
    """Return saved diary entries keyed by (order_name, item_id).

    Tries the Office API first; on any error (endpoint missing, unreachable),
    falls back to the local SQLite store.
    """
    if _office_diary_available():
        try:
            data = office_api.get_diary_entries()
            entries = (data or {}).get("entries") or []
            out: dict[tuple[str, str], dict] = {}
            for e in entries:
                order = str(e.get("order") or e.get("order_name") or "").strip()
                item = str(e.get("item") or e.get("item_id") or "").strip()
                if not order or not item:
                    continue
                out[(order, item)] = {
                    "dispatch_date": e.get("dispatch_date") or "",
                    "dispatch_manual": bool(e.get("dispatch_manual")),
                    "carrier": e.get("carrier") or "",
                    "updated_at": e.get("updated_at") or "",
                }
            return out
        except Exception as exc:
            logger.warning("Diary: Office API unavailable, using local store (%s)", exc)
    return get_all_entries()


def get_diary_overview(max_orders: int = 250) -> dict:
    orders_result = get_orders_overview(max_orders=max_orders)
    if not orders_result.get("success"):
        return orders_result

    saved = _load_saved_entries()
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

    if carrier is not None:
        carrier = (str(carrier) or "").strip().lower()
        if carrier not in ("", "royal_mail", "fedex", "frenni"):
            return {"success": False, "error": "Invalid carrier"}

    if _office_diary_available():
        try:
            entry = office_api.set_diary_entry(
                order_name,
                item_id,
                dispatch_date=dispatch_date if dispatch_date is not None else None,
                dispatch_manual=dispatch_manual if dispatch_manual is not None else None,
                carrier=carrier if carrier is not None else None,
            )
            return {"success": True, "entry": entry}
        except Exception as exc:
            logger.warning("Diary: Office API save failed, using local store (%s)", exc)

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
