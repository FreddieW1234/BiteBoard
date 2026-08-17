#!/usr/bin/env python3
"""
rollback_migration.py - undo what migrate_collections.py did.

    python scripts/rollback_migration.py
    python scripts/rollback_migration.py --write
    python scripts/rollback_migration.py --since 2026-08-12T14:00 --write
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
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from shopify_client.bite_shopify import Shopify, ShopifyError  # noqa: E402

LOG = "migration-log.csv"


def find_redirect(shop, path):
    """Locate a redirect by its path so it can be removed."""
    data = shop.gql("""
      query($q: String!) {
        urlRedirects(first: 10, query: $q) {
          edges { node { id path target } }
        }
      }
    """, {"q": f"path:{path}"})
    for edge in data["urlRedirects"]["edges"]:
        if edge["node"]["path"] == path:
            return edge["node"]
    return None


def delete_redirect(shop, redirect_id):
    result = shop.gql("""
      mutation($id: ID!) {
        urlRedirectDelete(id: $id) {
          deletedUrlRedirectId
          userErrors { field message }
        }
      }
    """, {"id": redirect_id})["urlRedirectDelete"]
    return shop._check(result, "urlRedirectDelete")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=LOG)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--since", help="only reverse rows at or after this ISO timestamp")
    ap.add_argument("--keep-redirects", action="store_true",
                    help="put handles back but leave the redirects in place")
    args = ap.parse_args()

    if not os.path.exists(args.log):
        print(f"No {args.log} - nothing has been executed yet.")
        return

    rows = [r for r in csv.DictReader(open(args.log, encoding="utf-8"))
            if r.get("result") == "ok"]
    if args.since:
        rows = [r for r in rows if r["timestamp"] >= args.since]
    rows.reverse()

    if not rows:
        print("No executed rows to reverse.")
        return

    shop = Shopify()
    mode = "WRITE" if args.write else "DRY RUN"
    print(f"=== ROLLBACK {mode} - {len(rows)} rows - {shop.domain} ===\n")

    ok = failed = skipped = 0

    for i, row in enumerate(rows, 1):
        action = row["action"]
        title = row["collection_title"]
        cid = row["collection_id"]
        old = row["from"]
        new = row["to"]
        prefix = f"[{i:>3}/{len(rows)}] {action:<9} {title[:44]:<44}"

        try:
            if action == "unpublish":
                if not args.write:
                    print(f"{prefix} would republish /{old}")
                    continue
                shop.set_published(cid, True)
                print(f"{prefix} republished /{old}")
                ok += 1
                continue

            if action == "rename":
                current = shop.collection_by_handle(new)
                if current is None:
                    if shop.collection_by_handle(old):
                        print(f"{prefix} already back at /{old}")
                        skipped += 1
                    else:
                        print(f"{prefix} NOT FOUND at /{new} or /{old}")
                        failed += 1
                    continue

                if not args.write:
                    extra = "" if args.keep_redirects else f" + drop redirect /collections/{old}"
                    print(f"{prefix} would revert /{new} -> /{old}{extra}")
                    continue

                if not args.keep_redirects:
                    red = find_redirect(shop, f"/collections/{old}")
                    if red:
                        delete_redirect(shop, red["id"])

                shop.collection_update(cid, handle=old)
                print(f"{prefix} reverted /{new} -> /{old}")
                ok += 1

        except ShopifyError as exc:
            print(f"{prefix} FAILED: {exc}")
            failed += 1

    print(f"\n{'reversed' if args.write else 'would reverse'}: {ok}   skipped: {skipped}   failed: {failed}")
    if not args.write:
        print("Dry run. Add --write to execute.")
    else:
        print("Note: SEO titles/descriptions written during migration are NOT reverted.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
