"""Everything staff need to key an order into Sage, on one printable page.

One page per order: customer, PO, payment, both addresses, then each product
(Sage code, name, quantity, unit price) with its fees underneath, any fees not
tied to a product, shipping and the totals.
"""

from __future__ import annotations

from scripts.order_helpers import fetch_order_by_id, format_gbp  # type: ignore
from scripts.Diary import load_saved_entries  # type: ignore
from scripts.production_note import (  # type: ignore
    _format_order_date, _money, _parse_case_quantity, _po_number, _total_cases, build_production_note,
    sage_product_code,
)


def _fee_row(fee: dict) -> dict:
    qty = fee.get("quantity")
    unit = _money(fee.get("unit_price"))
    total = _money(fee.get("total"))
    return {
        "code": (fee.get("sku") or "").strip(),
        "name": (fee.get("fee_label") or fee.get("fee_name") or fee.get("title") or "Fee").strip(),
        "quantity": qty if qty is not None else "",
        "unit_price": format_gbp(unit) if unit is not None else "",
        "total": format_gbp(total) if total is not None else "",
    }


def _fees_for_line(line: dict, fees: list[dict], products: list[dict]) -> list[dict]:
    """Fees the storefront linked to this product line (by title, then price band)."""
    title = (line.get("title") or "").strip()
    variant_id = str(line.get("variant_id") or "")
    same_title = [p for p in products if (p.get("title") or "").strip() == title]
    out = []
    for fee in fees:
        if (fee.get("for_product") or "").strip() != title:
            continue
        pl = str(fee.get("pl_variant_id") or "")
        if len(same_title) > 1 and pl and variant_id and pl != variant_id:
            continue  # same product twice in the order - belongs to the other line
        out.append(fee)
    return out


def build_sage_info(order: dict) -> dict:
    products = [li for li in order.get("order_items") or [] if not li.get("is_fee")]
    fees = list(order.get("fees") or [])
    used: set[int] = set()
    try:
        saved = load_saved_entries()
    except Exception:
        saved = {}

    lines = []
    for line in products:
        unit = _money(line.get("unit_price"))
        total = _money(line.get("total"))
        line_fees = _fees_for_line(line, fees, products)
        case_qty = _parse_case_quantity(line)
        try:  # same expected dispatch date the production note shows
            dispatch = build_production_note(order, line, saved=saved).get("expected_dispatch") or ""
        except Exception:
            dispatch = ""
        used.update(id(f) for f in line_fees)
        lines.append({
            "code": sage_product_code(line),
            "name": (line.get("title") or "").strip(),
            "options": (line.get("meta_line") or "").strip(),
            "quantity": line.get("quantity") if line.get("quantity") is not None else "",
            "unit_price": format_gbp(unit) if unit is not None else "",
            "case_size": case_qty or "",
            "total_cases": _total_cases(line),
            "case_price": format_gbp(unit * case_qty) if (unit is not None and case_qty) else "",
            "total": format_gbp(total) if total is not None else "",
            "dispatch": dispatch,
            "fees": [_fee_row(f) for f in line_fees],
        })

    other_fees = [_fee_row(f) for f in fees if id(f) not in used]

    customer_name = (order.get("customer_name") or "").strip()
    payment = order.get("payment") or {}
    payment_text = (payment.get("label") or "").strip()
    detail = (payment.get("detail") or "").strip()
    if detail and detail.lower() != payment_text.lower():
        payment_text = f"{payment_text} ({detail})" if payment_text else detail

    def _addr(key):
        addr = order.get(key) or {}
        return list(addr.get("lines") or [])

    return {
        "order_name": order.get("name") or "",
        "order_date": _format_order_date(order.get("processed_at") or ""),
        "customer_name": customer_name,
        "company": (order.get("company") or "").strip(),
        "email": (order.get("customer_email") or "").strip(),
        "po_number": _po_number(order.get("order_info") or {}),
        "payment": payment_text or "-",
        "billing_address": _addr("billing_address"),
        "shipping_address": _addr("shipping_address"),
        "lines": lines,
        "other_fees": other_fees,
        "subtotal": order.get("subtotal_display") or "",
        "shipping": order.get("shipping_display") or "",
        "tax": order.get("tax_display") or "",
        "total": order.get("total_display") or "",
    }


def get_sage_info_for_order(order_id: str | int) -> dict:
    order = fetch_order_by_id(order_id)
    if not order:
        return {"success": False, "error": "Order not found"}
    return {"success": True, "info": build_sage_info(order)}
