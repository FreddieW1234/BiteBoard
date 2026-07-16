"""Build flat Diary rows from Shopify orders (one row per product line)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import logging

from scripts.office_api import item_key  # type: ignore

logger = logging.getLogger(__name__)

# Temporary — remove once diary key matching is confirmed in production logs.
_DEBUG_DIARY_KEYS = True

_DATE_FORMATS = ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y")
_CARRIER_LABELS = {
    "royal_mail": "Royal Mail",
    "fedex": "FedEx",
    "frenni": "Frenni",
    "": "",
}


def parse_delivery_date(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def format_display_date(d: date | None) -> str:
    if not d:
        return ""
    return d.strftime("%d.%m.%Y")


def format_iso_date(d: date | None) -> str:
    if not d:
        return ""
    return d.isoformat()


def default_dispatch_date(requested: date | None) -> date | None:
    if not requested:
        return None
    return requested - timedelta(days=1)


def _is_date_field(field: dict) -> bool:
    if field.get("field_role") == "date":
        return True
    key = (field.get("key") or "").upper()
    return key.startswith("REQUESTED DELIVERY DATE") or bool(re.search(r"\(\s*[A-Z0-9]+\s*\)\s*:?\s*$", key))


def collect_delivery_date_fields(order_info: dict) -> list[dict]:
    fields: list[dict] = []
    for sec in order_info.get("note_sections") or []:
        if sec.get("layout") == "date_top_row":
            for field in sec.get("fields") or []:
                if field.get("field_role") == "po":
                    continue
                if _is_date_field(field):
                    fields.append(field)
        heading = (sec.get("heading") or "").strip().rstrip(":").lower()
        if heading in ("request delivery dates", "requested delivery dates"):
            for field in sec.get("fields") or []:
                fields.append(field)
    return fields


def _field_label(field: dict) -> str:
    return (field.get("display_label") or field.get("key") or "").strip().rstrip(":")


def _match_field_for_line(line: dict, fields: list[dict]) -> dict | None:
    sku = (line.get("sku") or "").strip().upper()
    title = (line.get("title") or "").strip().upper()
    if sku:
        for field in fields:
            label = _field_label(field).upper()
            if f"({sku})" in label or sku in label:
                return field
    if title:
        for field in fields:
            label = _field_label(field).upper()
            if title in label:
                return field
    line_num = line.get("line_number")
    if not isinstance(line_num, int) or line_num <= 0:
        return None

    generic = [
        f for f in fields
        if (f.get("key") or "").upper().startswith("REQUESTED DELIVERY DATE")
    ]
    product_specific = [f for f in fields if f not in generic]
    if not product_specific and len(generic) == 1:
        return generic[0]
    if not product_specific and len(generic) >= line_num:
        return generic[line_num - 1]
    if len(product_specific) >= line_num:
        return product_specific[line_num - 1]
    if len(fields) >= line_num:
        return fields[line_num - 1]
    return None


def item_slug(item_id: str) -> str:
    """Slug portion of an item id, stripping a leading line-number prefix."""
    text = (item_id or "").strip()
    if "-" in text:
        prefix, rest = text.split("-", 1)
        if prefix.isdigit() and rest:
            return rest
    return text


def slug_lookup_key(order_name: str, slug: str) -> tuple[str, str]:
    return ((order_name or "").strip(), f"slug:{slug}")


def enrich_saved_index(out: dict[tuple[str, str], dict]) -> None:
    """Add slug-only alias keys so lookup survives line_number prefix drift."""
    aliases: list[tuple[tuple[str, str], dict]] = []
    for (order, item_id), entry in out.items():
        if str(item_id).startswith("slug:"):
            continue
        slug = item_slug(item_id)
        if not slug:
            continue
        alias = slug_lookup_key(order, slug)
        if alias not in out:
            aliases.append((alias, entry))
    out.update(aliases)


def lookup_saved_entry(
    saved: dict[tuple[str, str], dict],
    order_name: str,
    item_id: str,
) -> tuple[dict, str]:
    """Return (entry, match_kind) where match_kind is 'exact', 'slug', or ''."""
    order_name = (order_name or "").strip()
    item_id = (item_id or "").strip()
    entry = saved.get((order_name, item_id))
    if entry:
        return entry, "exact"
    slug = item_slug(item_id)
    if slug:
        entry = saved.get(slug_lookup_key(order_name, slug))
        if entry:
            return entry, "slug"
    return {}, ""


def product_label(line: dict, matched_field: dict | None) -> str:
    if matched_field:
        label = _field_label(matched_field)
        if label and not label.upper().startswith("REQUESTED DELIVERY DATE"):
            if label.isupper():
                return label.title()
            return label
    title = (line.get("title") or "").strip()
    sku = (line.get("sku") or "").strip()
    if title and sku:
        return f"{title} ({sku})"
    return title or sku or "Product"


def build_diary_rows(orders: list[dict], saved: dict[tuple[str, str], dict]) -> list[dict]:
    rows: list[dict] = []
    for order in orders or []:
        order_name = order.get("name") or ""
        order_id = str(order.get("id") or "")
        order_info = order.get("order_info") or {}
        date_fields = collect_delivery_date_fields(order_info)

        for line in order.get("order_items") or []:
            if line.get("is_fee"):
                continue
            line_number = line.get("line_number")
            if line_number is None:
                continue
            item_id = line.get("office_item_id") or item_key(
                int(line_number), line.get("title") or ""
            )
            matched = _match_field_for_line(line, date_fields)
            requested_raw = (matched.get("value") if matched else "") or ""
            requested_raw = str(requested_raw).strip()
            requested_date = parse_delivery_date(requested_raw)

            key = (order_name, item_id)
            entry, match_kind = lookup_saved_entry(saved, order_name, item_id)
            if _DEBUG_DIARY_KEYS:
                logger.warning(
                    "Diary DEBUG row key=%r line_number=%r title=%r hit=%s match=%s carrier=%r",
                    key,
                    line_number,
                    line.get("title"),
                    bool(entry),
                    match_kind or "none",
                    entry.get("carrier") if entry else None,
                )

            dispatch_manual = bool(entry.get("dispatch_manual"))
            if dispatch_manual:
                dispatch_iso = entry.get("dispatch_date") or ""
            elif requested_date:
                dispatch_iso = format_iso_date(default_dispatch_date(requested_date))
            else:
                dispatch_iso = entry.get("dispatch_date") or ""
            dispatch_date = parse_delivery_date(dispatch_iso) if dispatch_iso else None
            if dispatch_iso and not dispatch_date:
                dispatch_date = parse_delivery_date(dispatch_iso)

            carrier = entry.get("carrier") or ""
            tracking_number = entry.get("tracking_number") or ""
            label_id = entry.get("label_id") or ""
            # Treat label purchase as shipped even if sandbox omitted a tracking number.
            shipped = bool(tracking_number or label_id)
            can_print_label = False
            if shipped:
                try:
                    from scripts import office_api  # type: ignore
                    from config import OFFICE_API_URL, OFFICE_API_KEY  # type: ignore
                    if OFFICE_API_URL and OFFICE_API_KEY:
                        can_print_label = office_api.has_label(order_name, item_id)
                        if _DEBUG_DIARY_KEYS:
                            logger.warning(
                                "Diary DEBUG label probe order=%s item=%s can_print=%s",
                                order_name,
                                item_id,
                                can_print_label,
                            )
                except Exception as exc:
                    logger.warning(
                        "Diary label probe failed for %s / %s: %s",
                        order_name,
                        item_id,
                        exc,
                    )
                    can_print_label = False

            rows.append({
                "order_id": order_id,
                "order_name": order_name,
                "item_id": item_id,
                "line_number": line_number,
                "product_label": product_label(line, matched),
                "company": (order.get("company") or "").strip(),
                "requested_date": format_display_date(requested_date),
                "requested_date_iso": format_iso_date(requested_date),
                "dispatch_date": format_display_date(dispatch_date),
                "dispatch_date_iso": format_iso_date(dispatch_date),
                "dispatch_manual": dispatch_manual,
                "carrier": carrier,
                "carrier_label": _CARRIER_LABELS.get(carrier, carrier),
                "tracking_number": tracking_number or label_id,
                "label_id": label_id,
                "shipped": shipped,
                "can_print_label": can_print_label,
                # Back-compat for older diary.js caches
                "can_reprint": can_print_label,
            })

    def sort_key(row: dict):
        iso = row.get("requested_date_iso") or "9999-99-99"
        return (iso, row.get("order_name") or "", row.get("line_number") or 0)

    rows.sort(key=sort_key)
    return rows
