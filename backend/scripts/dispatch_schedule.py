"""Customer's requested delivery / collection date and ASAP choice, per order line.

The storefront saves these two ways:

* the ``_dispatch_schedule`` order note attribute (JSON) - the main source for
  the ASAP choice and the method. When the note also has a date for a line,
  the note's date wins, because staff correct dates there:
  {"method": "shipping"|"pickup",
   "lines": [{"title", "sku", "variant_id", "requested_date": "YYYY-MM-DD",
              "asap_if_ready_sooner": true|false}]}
* the order note text (older orders, and the fallback):
  REQUEST DELIVERY DATES:            (pickup: REQUEST COLLECTION DATES:)
  Product title (SKU): dd.mm.yyyy
  DISPATCH ASAP IF READY SOONER:     (pickup: EARLY COLLECTION IF READY SOONER:)
  Product title (SKU): Yes|No

``requested_date`` is the date the customer asked to receive / collect the
goods - not the dispatch date. Nothing here may stop an order loading: any
bad or missing data just leaves the fields blank.
"""

from __future__ import annotations

import json
import logging
from datetime import date

log = logging.getLogger(__name__)

ATTRIBUTE_KEY = "_dispatch_schedule"

DELIVERY_DATE_HEADINGS = frozenset({"request delivery dates", "requested delivery dates"})
COLLECTION_DATE_HEADINGS = frozenset({"request collection dates", "requested collection dates"})
DATE_HEADINGS = DELIVERY_DATE_HEADINGS | COLLECTION_DATE_HEADINGS

ASAP_DELIVERY_HEADINGS = frozenset({"dispatch asap if ready sooner"})
ASAP_COLLECTION_HEADINGS = frozenset({"early collection if ready sooner"})
ASAP_HEADINGS = ASAP_DELIVERY_HEADINGS | ASAP_COLLECTION_HEADINGS

# Every heading that belongs to the schedule (never a product's own section).
SCHEDULE_HEADINGS = DATE_HEADINGS | ASAP_HEADINGS

_YES = frozenset({"yes", "y", "true"})
_NO = frozenset({"no", "n", "false"})


def heading_norm(heading: str | None) -> str:
    return (heading or "").strip().rstrip(":").strip().lower()


def _parse_iso(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except (TypeError, ValueError):
        return None


def _parse_yes_no(value) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in _YES:
        return True
    if text in _NO:
        return False
    return None


def read_attribute(attributes: list[dict] | None) -> dict | None:
    """Parsed ``_dispatch_schedule`` JSON, or None when missing / unreadable."""
    for attr in attributes or []:
        if (attr.get("key") or "").strip() != ATTRIBUTE_KEY:
            continue
        raw = attr.get("value") or ""
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("Unreadable %s attribute: %.200r", ATTRIBUTE_KEY, raw)
            return None
        return data if isinstance(data, dict) else None
    return None


def _attribute_entry_for_line(line: dict, entries: list[dict], used: set[int]) -> dict | None:
    """Match by variant id first, then SKU. Each JSON entry is used once."""
    variant_id = str(line.get("variant_id") or "").strip()
    if variant_id:
        for i, entry in enumerate(entries):
            if i not in used and str(entry.get("variant_id") or "").strip() == variant_id:
                used.add(i)
                return entry
    skus = {
        s.strip().upper()
        for s in (line.get("sku"), line.get("sku_raw"))
        if (s or "").strip()
    }
    if skus:
        for i, entry in enumerate(entries):
            if i not in used and str(entry.get("sku") or "").strip().upper() in skus:
                used.add(i)
                return entry
    return None


def _note_asap_fields(order_info: dict) -> tuple[list[dict], str]:
    """(fields under the ASAP heading, method implied by which heading was used)."""
    for sec in order_info.get("note_sections") or []:
        h = heading_norm(sec.get("heading"))
        if h in ASAP_HEADINGS:
            method = "pickup" if h in ASAP_COLLECTION_HEADINGS else "shipping"
            return list(sec.get("fields") or []), method
    return [], ""


def _note_date_method(order_info: dict) -> str:
    for sec in order_info.get("note_sections") or []:
        headings = [heading_norm(sec.get("heading"))]
        headings += [heading_norm(f.get("restore_heading")) for f in sec.get("fields") or []]
        if any(h in COLLECTION_DATE_HEADINGS for h in headings):
            return "pickup"
        if any(h in DELIVERY_DATE_HEADINGS for h in headings):
            return "shipping"
    return ""


def _field_label(field: dict) -> str:
    return (field.get("display_label") or field.get("key") or "").strip().rstrip(":").upper()


def _note_field_for_line(line: dict, fields: list[dict], product_line_count: int) -> dict | None:
    """Match an ASAP note line ("Title (SKU): Yes") to an order line."""
    sku = (line.get("sku") or "").strip().upper()
    title = (line.get("title") or "").strip().upper()
    if sku:
        for f in fields:
            if f"({sku})" in _field_label(f):
                return f
    if title:
        for f in fields:
            if _field_label(f).startswith(title):
                return f
    # Same number of lines as products: assume the same order.
    n = line.get("line_number")
    if isinstance(n, int) and 0 < n <= len(fields) and len(fields) == product_line_count:
        return fields[n - 1]
    return None


def apply_dispatch_schedule(order: dict, node: dict) -> None:
    """Add the schedule fields to an enriched order (in place).

    Per product line: requested_date (dd.mm.yyyy), requested_date_iso,
    asap_if_ready_sooner (True / False / None = not known), schedule_source
    ("attribute" / "note" / "note+attribute" / "").
    Per order: dispatch_method ("shipping" / "pickup" / "") and
    dispatch_schedule_source ("attribute" / "note" / "").
    """
    try:
        _apply(order, node)
    except Exception:  # never fail an order load over this
        log.exception("Could not read the dispatch schedule for order %s", order.get("name"))
        order.setdefault("dispatch_method", "")
        order.setdefault("dispatch_schedule_source", "")
        for line in order.get("order_items") or []:
            line.setdefault("requested_date", "")
            line.setdefault("requested_date_iso", "")
            line.setdefault("asap_if_ready_sooner", None)
            line.setdefault("schedule_source", "")


def _apply(order: dict, node: dict) -> None:
    from scripts.diary_helpers import (  # type: ignore
        _match_field_for_line,
        collect_delivery_date_fields,
        format_display_date,
        format_iso_date,
        parse_delivery_date,
    )

    order_info = order.get("order_info") or {}
    schedule = read_attribute(node.get("customAttributes"))
    entries = [e for e in (schedule or {}).get("lines") or [] if isinstance(e, dict)]
    method = str((schedule or {}).get("method") or "").strip().lower()
    if method not in ("shipping", "pickup"):
        method = ""
    order_source = "attribute" if schedule is not None else ""

    date_fields = collect_delivery_date_fields(order_info)
    asap_fields, asap_method = _note_asap_fields(order_info)
    if not method:
        method = _note_date_method(order_info) or asap_method
        if method and not order_source:
            order_source = "note"

    products = [li for li in order.get("order_items") or [] if not li.get("is_fee")]
    used: set[int] = set()
    for line in products:
        entry = _attribute_entry_for_line(line, entries, used) if entries else None
        requested: date | None = None
        asap: bool | None = None
        source = ""
        # The date in the note wins: staff can correct it in the Order info
        # panel, while the JSON keeps what the customer first picked.
        matched = _match_field_for_line(line, date_fields)
        requested = parse_delivery_date(str((matched or {}).get("value") or "").strip())
        if requested is not None:
            source = "note"
        if entry is not None:
            if requested is None:
                requested = _parse_iso(entry.get("requested_date"))
            asap = _parse_yes_no(entry.get("asap_if_ready_sooner"))
            source = "note+attribute" if source == "note" else "attribute"
        if asap is None and asap_fields:
            field = _note_field_for_line(line, asap_fields, len(products))
            asap = _parse_yes_no((field or {}).get("value"))
            if asap is not None and not source:
                source = "note"
        if source and not order_source:
            order_source = source
        line["requested_date"] = format_display_date(requested)
        line["requested_date_iso"] = format_iso_date(requested)
        line["asap_if_ready_sooner"] = asap
        line["schedule_source"] = source

    order["dispatch_method"] = method
    order["dispatch_schedule_source"] = order_source


def line_requested_date(order: dict, line: dict) -> date | None:
    """The customer's requested delivery / collection date for one line.

    Uses the value worked out when the order loaded; falls back to the note
    text for any line that never went through ``apply_dispatch_schedule``.
    """
    from scripts.diary_helpers import (  # type: ignore
        _match_field_for_line,
        collect_delivery_date_fields,
        parse_delivery_date,
    )

    if "requested_date_iso" in line:
        return _parse_iso(line.get("requested_date_iso"))
    fields = collect_delivery_date_fields(order.get("order_info") or {})
    matched = _match_field_for_line(line, fields)
    return parse_delivery_date(str((matched or {}).get("value") or "").strip())


def is_pickup(order: dict) -> bool:
    return (order.get("dispatch_method") or "") == "pickup"


def asap_display(value: bool | None) -> str:
    if value is True:
        return "YES"
    if value is False:
        return "NO"
    return ""
