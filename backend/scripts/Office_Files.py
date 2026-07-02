"""Browse artwork and proof files across orders via the Office Order API."""

from __future__ import annotations

from urllib.parse import quote

from scripts.order_helpers import is_fee_item  # type: ignore


def _file_kind(name: str, kind: str | None) -> str:
    if kind in ("artwork", "proof"):
        return kind
    lower = (name or "").lower()
    if lower.startswith("customer-artwork") or "artwork" in lower:
        return "artwork"
    if lower.startswith("proof"):
        return "proof"
    return "other"


def browse_office_files(*, search: str = "", max_orders: int = 150) -> dict:
    """Return a tree of orders → line items → files from the Office API."""
    from scripts.Orders import get_orders_overview  # type: ignore
    from scripts.office_api import get_order, list_files, item_key, OfficeApiError  # type: ignore

    overview = get_orders_overview(max_orders=max(1, min(max_orders, 250)))
    if not overview.get("success"):
        return overview

    needle = (search or "").strip().lower()
    orders_out = []
    total_files = 0

    for order in overview.get("orders") or []:
        order_id = str(order.get("id") or "")
        order_name = order.get("name") or ""
        customer = order.get("customer_name") or ""

        if needle:
            hay = f"{order_name} {customer}".lower()
            if needle not in hay:
                item_hay = " ".join(
                    (li.get("title") or "") for li in (order.get("order_items") or [])
                ).lower()
                if needle not in item_hay:
                    continue

        office_by_item: dict[str, dict] = {}
        try:
            office_order = get_order(order_name)
            if office_order and office_order.get("items"):
                for view in office_order["items"]:
                    key = view.get("item") or ""
                    if key:
                        office_by_item[key] = view
        except OfficeApiError:
            pass

        items_out = []
        for li in order.get("order_items") or []:
            title = li.get("title") or ""
            if is_fee_item(title):
                continue
            ln = li.get("line_number")
            if ln is None:
                continue
            oid = li.get("office_item_id") or item_key(ln, title)
            view = office_by_item.get(oid)
            files = list((view or {}).get("files") or [])

            if not files:
                try:
                    listed = list_files(order_name, oid)
                    files = listed.get("files") or []
                except OfficeApiError:
                    files = []

            if not files:
                continue

            files_out = []
            for f in files:
                fname = f.get("name")
                if not fname:
                    continue
                base = (
                    f"/api/orders/{quote(order_id, safe='')}"
                    f"/items/{quote(oid, safe='')}"
                    f"/files/{quote(fname, safe='')}"
                )
                files_out.append({
                    "name": fname,
                    "kind": _file_kind(fname, f.get("kind")),
                    "version": f.get("version"),
                    "order_id": order_id,
                    "office_item_id": oid,
                    "download_url": base,
                    "view_url": f"{base}?inline=1",
                })

            if not files_out:
                continue

            total_files += len(files_out)
            items_out.append({
                "line_number": ln,
                "title": title,
                "office_item_id": oid,
                "current_stage": (view or {}).get("current_stage") or "",
                "files": files_out,
            })

        if items_out:
            orders_out.append({
                "order_id": order_id,
                "order_name": order_name,
                "customer_name": customer,
                "processed_at": order.get("processed_at") or "",
                "items": items_out,
            })

    return {
        "success": True,
        "orders": orders_out,
        "order_count": len(orders_out),
        "total_files": total_files,
    }
