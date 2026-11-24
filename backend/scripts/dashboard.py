"""Staff home dashboard: one call that gathers the numbers worth seeing first.

Money owed and overdue dispatches are deliberately left out - the office and
Sage handle those (Sage may be linked in later for the accounting side).

Each section is built on its own, so one slow or failing source (e.g. the
office server) leaves the rest of the page working. The whole result is cached
for a couple of minutes - the page is opened a lot, the numbers move slowly.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
_CACHE_TTL = 120
_cache: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()

_SALES_QUERY = """
query Dash($q: String!, $c: String) {
  orders(first: 250, after: $c, query: $q, sortKey: PROCESSED_AT, reverse: true) {
    nodes {
      legacyResourceId name processedAt cancelledAt
      displayFinancialStatus displayFulfillmentStatus
      totalPriceSet { shopMoney { amount } }
      totalTaxSet { shopMoney { amount } }
      customer { displayName companyNameNew: metafield(namespace: "custom_fields", key: "company_name_new") { value } }
      billingAddress { company }
    }
    pageInfo { hasNextPage endCursor }
  }
}"""

_PENDING_CUSTOMERS_QUERY = """
query DashPending {
  customers(first: 50, query: "tag:Pending", sortKey: CREATED_AT, reverse: true) {
    nodes {
      legacyResourceId displayName email createdAt
      companyNameNew: metafield(namespace: "custom_fields", key: "company_name_new") { value }
    }
  }
}"""


def _money(node: dict, field: str) -> float:
    try:
        return float(((node.get(field) or {}).get("shopMoney") or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _company(node: dict) -> str:
    cust = node.get("customer") or {}
    return (((cust.get("companyNameNew") or {}).get("value") or "").strip()
            or ((node.get("billingAddress") or {}).get("company") or "").strip()
            or (cust.get("displayName") or "").strip()
            or "No customer")


def _uk_date(iso: str) -> date | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LONDON).date()
    except (ValueError, AttributeError):
        return None


def _paged(query: str, variables: dict, key: str, limit: int) -> list[dict]:
    from scripts.Orders import _graphql  # type: ignore
    out, cursor = [], None
    while len(out) < limit:
        block = (_graphql(query, {**variables, "c": cursor}) or {}).get(key) or {}
        out += block.get("nodes") or []
        page = block.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    return out[:limit]


def _sales(today: date) -> dict:
    """Takings ex VAT: today, this week, this month vs the same days last month,
    a 30-day daily series, top customers this month and the latest orders."""
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    since = min(last_month_start, today - timedelta(days=29))
    since_utc = datetime.combine(since, datetime.min.time(), LONDON).astimezone(ZoneInfo("UTC"))
    nodes = _paged(_SALES_QUERY, {"q": f"processed_at:>='{since_utc.isoformat()}'"}, "orders", 2000)

    week_start = today - timedelta(days=today.weekday())
    # Same stretch of last month (1st up to today's day number, capped at month end).
    last_month_end = month_start - timedelta(days=1)
    same_point_last_month = last_month_start.replace(day=min(today.day, last_month_end.day))

    def bucket():
        return {"orders": 0, "net": 0.0}

    totals = {"today": bucket(), "week": bucket(), "month": bucket(), "last_month_same_point": bucket(),
              "last_month": bucket()}
    daily = {today - timedelta(days=i): bucket() for i in range(30)}
    companies: dict[str, float] = {}
    recent = []
    for n in nodes:
        if n.get("cancelledAt"):
            continue
        d = _uk_date(n.get("processedAt") or "")
        if not d:
            continue
        net = _money(n, "totalPriceSet") - _money(n, "totalTaxSet")
        hits = []
        if d == today:
            hits.append("today")
        if d >= week_start:
            hits.append("week")
        if d >= month_start:
            hits.append("month")
            companies[_company(n)] = companies.get(_company(n), 0.0) + net
        if last_month_start <= d <= last_month_end:
            hits.append("last_month")
            if d <= same_point_last_month:
                hits.append("last_month_same_point")
        for h in hits:
            totals[h]["orders"] += 1
            totals[h]["net"] += net
        if d in daily:
            daily[d]["orders"] += 1
            daily[d]["net"] += net
        if len(recent) < 8:
            recent.append({
                "id": n.get("legacyResourceId"), "name": n.get("name") or "", "date": d.isoformat(),
                "company": _company(n), "total": _money(n, "totalPriceSet"),
                "financial": (n.get("displayFinancialStatus") or "").replace("_", " ").title(),
                "fulfillment": (n.get("displayFulfillmentStatus") or "").replace("_", " ").title(),
            })
    for b in list(totals.values()) + list(daily.values()):
        b["net"] = round(b["net"], 2)
    return {
        "totals": totals,
        "daily": [{"date": d.isoformat(), **daily[d]} for d in sorted(daily)],
        "top_companies": [{"company": c, "net": round(v, 2)}
                          for c, v in sorted(companies.items(), key=lambda kv: -kv[1])[:5]],
        "recent_orders": recent,
    }


def _pending_customers() -> dict:
    from scripts.Orders import _graphql  # type: ignore
    nodes = ((_graphql(_PENDING_CUSTOMERS_QUERY) or {}).get("customers") or {}).get("nodes") or []
    return {
        "count": len(nodes),
        "latest": [{
            "id": n.get("legacyResourceId"), "name": n.get("displayName") or n.get("email") or "",
            "company": ((n.get("companyNameNew") or {}).get("value") or "").strip(),
            "created": (_uk_date(n.get("createdAt") or "") or date.today()).isoformat(),
        } for n in nodes[:5]],
    }


def _dispatch(today: date) -> dict:
    """Product lines by dispatch date, from the same data as the Diary."""
    from scripts.Diary import get_diary_overview  # type: ignore
    result = get_diary_overview(max_orders=150)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "Diary unavailable")
    week_end = today + timedelta(days=6 - today.weekday() if today.weekday() < 5 else 7 + 4 - today.weekday())
    out = {"today": [], "tomorrow": [], "this_week": 0, "no_date": 0}
    next_day = today + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    for r in result.get("rows") or []:
        if r.get("shipped"):
            continue
        iso = r.get("dispatch_date_iso") or ""
        if not iso:
            out["no_date"] += 1
            continue
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            continue
        line = {k: r.get(k) for k in ("order_id", "order_name", "product_label", "company",
                                       "dispatch_date", "carrier_label")}
        if d == today:
            out["today"].append(line)
        elif d == next_day:
            out["tomorrow"].append(line)
        if today <= d <= week_end:
            out["this_week"] += 1
    return out


def _autoprint() -> dict:
    from scripts import sage_autoprint  # type: ignore
    return sage_autoprint.last_report() or {}


def build(today: date | None = None) -> dict:
    today = today or datetime.now(LONDON).date()
    jobs = {"sales": lambda: _sales(today),
            "pending_customers": _pending_customers, "dispatch": lambda: _dispatch(today),
            "autoprint": _autoprint}
    out: dict = {"success": True, "today": today.isoformat(), "errors": {}}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {k: pool.submit(fn) for k, fn in jobs.items()}
        for k, fut in futures.items():
            try:
                out[k] = fut.result(timeout=60)
            except Exception as exc:
                out[k] = None
                out["errors"][k] = str(exc)[:200]
    out["generated_at"] = datetime.now(LONDON).isoformat(timespec="seconds")
    return out


def get_dashboard(refresh: bool = False) -> dict:
    now = time.time()
    with _lock:
        if not refresh and _cache["data"] and now - _cache["at"] < _CACHE_TTL:
            return _cache["data"]
    data = build()
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data
