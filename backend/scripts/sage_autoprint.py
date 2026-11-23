"""6am auto-print: yesterday's orders' Sage info sheets on the office printer.

Runs Monday-Friday. Each run covers the previous working day's orders by UK
date; Monday's run covers Friday, Saturday and Sunday so nothing ordered over
the weekend is missed. Every order printed is recorded on the office server,
so a retry or a second trigger never prints the same order twice.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from config import ACCESS_TOKEN, API_VERSION, STORE_DOMAIN  # type: ignore

LONDON = ZoneInfo("Europe/London")
PRINT_HOUR = 6
_PRINTED_KIND = "sage_autoprint"
_TEMPLATES = Path(__file__).resolve().parents[1] / "templates"

_RUN_LOCK = threading.Lock()
_LAST_REPORT: dict = {}


def print_window(today: date) -> tuple[datetime, datetime]:
    """UK-midnight bounds: from the previous working day up to today (exclusive)."""
    start = today - timedelta(days=1)
    while start.weekday() >= 5:  # Sat/Sun -> back to Friday
        start -= timedelta(days=1)
    return (datetime.combine(start, datetime.min.time(), LONDON),
            datetime.combine(today, datetime.min.time(), LONDON))


def is_print_time(now: datetime | None = None) -> bool:
    """True at 6am UK time on a weekday (cron fires at 05:00 and 06:00 UTC to cover BST)."""
    now = (now or datetime.now(LONDON)).astimezone(LONDON)
    return now.weekday() < 5 and now.hour == PRINT_HOUR


def orders_between(start: datetime, end: datetime) -> list[dict]:
    """Shopify orders processed in [start, end), oldest first, cancelled ones left out."""
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": ACCESS_TOKEN, "Content-Type": "application/json"}
    search = (f"processed_at:>='{start.astimezone(ZoneInfo('UTC')).isoformat()}' "
              f"processed_at:<'{end.astimezone(ZoneInfo('UTC')).isoformat()}'")
    query = """query($q: String!, $c: String) {
      orders(first: 100, after: $c, query: $q, sortKey: PROCESSED_AT) {
        nodes { legacyResourceId name processedAt cancelledAt }
        pageInfo { hasNextPage endCursor }
      } }"""
    out, cursor = [], None
    while True:
        resp = requests.post(url, headers=headers, timeout=30,
                             json={"query": query, "variables": {"q": search, "c": cursor}})
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(str(body["errors"])[:300])
        conn = (body.get("data") or {}).get("orders") or {}
        out += [n for n in conn.get("nodes") or [] if not n.get("cancelledAt")]
        page = conn.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return out
        cursor = page.get("endCursor")


def render_pdf(info: dict) -> bytes:
    """The same Sage info page staff print by hand, as a PDF."""
    from io import BytesIO
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from xhtml2pdf import pisa

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=select_autoescape(["html"]))
    html = env.get_template("UI/Sage_Info.html").render(info=info, embed=True, auto_print=False)
    buf = BytesIO()
    result = pisa.CreatePDF(html, dest=buf, encoding="utf-8")
    if result.err:
        raise RuntimeError("PDF could not be built")
    return buf.getvalue()


def _already_printed(order_id: str) -> bool:
    from scripts.office_api import get_snapshot_item  # type: ignore
    try:
        return bool(get_snapshot_item(_PRINTED_KIND, order_id))
    except Exception:
        return False


def run(*, today: date | None = None, dry_run: bool = False, reprint: bool = False) -> dict:
    """Print every order in the window. Returns a report (also kept for /status)."""
    from scripts.office_api import print_document, put_snapshot_item  # type: ignore
    from scripts.sage_info import get_sage_info_for_order  # type: ignore

    if not _RUN_LOCK.acquire(blocking=False):
        return {"success": False, "error": "Already running"}
    started = time.time()
    try:
        today = today or datetime.now(LONDON).date()
        start, end = print_window(today)
        report = {"success": True, "dry_run": dry_run, "window": [start.isoformat(), end.isoformat()],
                  "printed": [], "skipped": [], "failed": []}
        for o in orders_between(start, end):
            oid, name = str(o["legacyResourceId"]), o.get("name") or ""
            if not reprint and _already_printed(oid):
                report["skipped"].append(name)
                continue
            if dry_run:
                report["printed"].append(name)
                continue
            try:
                result = get_sage_info_for_order(oid)
                if not result.get("success"):
                    raise RuntimeError(result.get("error") or "order not found")
                print_document(render_pdf(result["info"]), title=f"Sage info {name}")
                put_snapshot_item(_PRINTED_KIND, oid, {"name": name, "printed_at": datetime.now(LONDON).isoformat()},
                                  updated_by="sage-autoprint")
                report["printed"].append(name)
            except Exception as exc:
                report["failed"].append({"order": name, "error": str(exc)[:200]})
        report["success"] = not report["failed"]
        report["seconds"] = round(time.time() - started, 1)
        print(f"[sage-autoprint] {'dry run' if dry_run else 'run'} {start.date()}..{end.date()}: "
              f"printed={len(report['printed'])} skipped={len(report['skipped'])} failed={len(report['failed'])}",
              flush=True)
        _LAST_REPORT.clear()
        _LAST_REPORT.update(report, finished_at=datetime.now(LONDON).isoformat())
        return report
    except Exception as exc:
        print(f"[sage-autoprint] failed: {exc}", flush=True)
        _LAST_REPORT.clear()
        _LAST_REPORT.update({"success": False, "error": str(exc)[:300], "finished_at": datetime.now(LONDON).isoformat()})
        return dict(_LAST_REPORT)
    finally:
        _RUN_LOCK.release()


def print_one(order_name: str) -> dict:
    """Print one order's Sage info now (staff test / reprint), e.g. "#S1099"."""
    from scripts.office_api import print_document  # type: ignore
    from scripts.sage_info import get_sage_info_for_order  # type: ignore

    name = order_name.strip()
    if not name.startswith("#"):
        name = "#" + name
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
    resp = requests.post(url, timeout=30,
                         headers={"X-Shopify-Access-Token": ACCESS_TOKEN, "Content-Type": "application/json"},
                         json={"query": "query($q: String!) { orders(first: 1, query: $q) { nodes { legacyResourceId name } } }",
                               "variables": {"q": f"name:{name}"}})
    nodes = (((resp.json().get("data") or {}).get("orders") or {}).get("nodes")) or []
    if not nodes:
        return {"success": False, "error": f"Order {name} not found"}
    result = get_sage_info_for_order(nodes[0]["legacyResourceId"])
    if not result.get("success"):
        return {"success": False, "error": result.get("error") or "Order not found"}
    printed = print_document(render_pdf(result["info"]), title=f"Sage info {nodes[0]['name']}")
    return {"success": True, "printed": nodes[0]["name"], "printer": printed}


def run_async(**kwargs) -> None:
    threading.Thread(target=run, kwargs=kwargs, name="sage-autoprint", daemon=True).start()


def last_report() -> dict:
    return dict(_LAST_REPORT)
