#!/usr/bin/env python3
"""
migrate_collections.py - execute migration-plan.csv against Shopify.

    python scripts/migrate_collections.py scripts/data/migration-plan.csv
    python scripts/migrate_collections.py scripts/data/migration-plan.csv --action rename --priority Critical --write

Nothing happens without --write. Every executed step is appended to
migration-log.csv, which is also the rollback record.

Unpublish rows: migrate refuses collections that still have products. That is
intentional. The CSV may still list older "unpublish" targets (e.g. Favourites,
New Year) that now stay visible under the Phase 4 rule "every collection with
products is visible". Those rows no-op safely; empty collections still unpublish.
See scripts/data/MIGRATION-NOTES.md.
"""

from __future__ import annotations

import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

import argparse
import csv
import datetime
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from shopify_client.bite_shopify import Shopify, ShopifyError  # noqa: E402

LOG = "migration-log.csv"
LOG_FIELDS = ["timestamp", "action", "collection_title", "collection_id",
              "from", "to", "result", "detail"]


def log(row):
    exists = os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--write", action="store_true", help="actually execute")
    ap.add_argument("--action", choices=["rename", "unpublish"], help="filter by action")
    ap.add_argument("--priority", help="filter by priority, e.g. Critical")
    ap.add_argument("--limit", type=int, help="stop after N rows")
    args = ap.parse_args()

    rows = [r for r in csv.DictReader(open(args.plan, encoding="utf-8"))
            if r["action"] in ("rename", "unpublish")]
    if args.action:
        rows = [r for r in rows if r["action"] == args.action]
    if args.priority:
        rows = [r for r in rows if r["priority"] == args.priority]
    if args.limit:
        rows = rows[:args.limit]

    if not rows:
        print("No rows match those filters.")
        return

    shop = Shopify()
    mode = "WRITE" if args.write else "DRY RUN"
    print(f"=== {mode} - {len(rows)} rows - {shop.domain} ===\n")

    ok = failed = skipped = 0

    for i, row in enumerate(rows, 1):
        title = row["collection_title"]
        current = row["current_handle"].strip()
        target = row["new_handle"].strip()
        action = row["action"]
        prefix = f"[{i:>3}/{len(rows)}] {action:<9} {title[:44]:<44}"

        try:
            col = shop.collection_by_handle(current)
        except ShopifyError as exc:
            print(f"{prefix} LOOKUP FAILED: {exc}")
            failed += 1
            continue

        if col is None:
            if target and shop.collection_by_handle(target):
                print(f"{prefix} already at {target}")
                skipped += 1
            else:
                print(f"{prefix} NOT FOUND: /{current}")
                failed += 1
            continue

        cid = col["id"]
        count = col["productsCount"]["count"]

        if action == "unpublish":
            if count > 0:
                print(f"{prefix} REFUSED - has {count} products")
                skipped += 1
                continue
            if not args.write:
                print(f"{prefix} would unpublish /{current}")
                continue
            try:
                shop.set_published(cid, False)
                print(f"{prefix} unpublished /{current}")
                log(dict(timestamp=datetime.datetime.utcnow().isoformat(), action="unpublish",
                         collection_title=title, collection_id=cid, **{"from": current},
                         to="", result="ok", detail="0 products"))
                ok += 1
            except ShopifyError as exc:
                print(f"{prefix} FAILED: {exc}")
                failed += 1
            continue

        if not target:
            print(f"{prefix} no new_handle - skipped")
            skipped += 1
            continue
        if current == target:
            print(f"{prefix} already correct")
            skipped += 1
            continue

        clash = shop.collection_by_handle(target)
        if clash is not None:
            print(f"{prefix} COLLISION - /{target} is taken by {clash['title']!r}")
            failed += 1
            continue

        seo_t = row.get("seo_title", "").strip() or None
        seo_d = row.get("seo_description", "").strip() or None
        extra = " +seo" if (seo_t or seo_d) else ""

        if not args.write:
            print(f"{prefix} /{current}  ->  /{target}{extra}")
            continue

        try:
            shop.create_redirect(f"/collections/{current}", f"/collections/{target}")
            shop.collection_update(cid, handle=target, seo_title=seo_t, seo_description=seo_d)
            print(f"{prefix} /{current}  ->  /{target}{extra}")
            log(dict(timestamp=datetime.datetime.utcnow().isoformat(), action="rename",
                     collection_title=title, collection_id=cid, **{"from": current},
                     to=target, result="ok", detail=f"{count} products{extra}"))
            ok += 1
        except ShopifyError as exc:
            print(f"{prefix} FAILED: {exc}")
            log(dict(timestamp=datetime.datetime.utcnow().isoformat(), action="rename",
                     collection_title=title, collection_id=cid, **{"from": current},
                     to=target, result="failed", detail=str(exc)))
            failed += 1

    print(f"\n{'executed' if args.write else 'would execute'}: {ok}   skipped: {skipped}   failed: {failed}")
    if not args.write:
        print("Dry run. Add --write to execute.")
    else:
        print(f"Log appended to {LOG}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
