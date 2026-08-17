#!/usr/bin/env python3
"""
Rename Phase-6-unpublished collections so their handles match live taxonomy.

Empty collections were unpublished in place (old handles). Taxonomy / SEO
targets still use handles like branded-pretzels. Align Shopify handles +
redirects so Phase 7 reconcile can find them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

from shopify_client.bite_shopify import Shopify, ShopifyError  # noqa: E402
from shopify_client import taxonomy as taxmod  # noqa: E402


def _all_collections(shop: Shopify) -> list[dict]:
    pub = shop.online_store_publication_id()
    out = []
    cursor = None
    while True:
        data = shop.gql(
            """
          query($c: String, $pub: ID!) {
            collections(first: 100, after: $c) {
              pageInfo { hasNextPage endCursor }
              edges {
                node {
                  id handle title
                  publishedOnPublication(publicationId: $pub)
                }
              }
            }
          }
        """,
            {"c": cursor, "pub": pub},
        )
        block = data["collections"]
        for e in block["edges"]:
            out.append(e["node"])
        if not block["pageInfo"]["hasNextPage"]:
            break
        cursor = block["pageInfo"]["endCursor"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    shop = Shopify()
    cols = _all_collections(shop)
    by_handle = {c["handle"]: c for c in cols}
    by_title = {c["title"]: c for c in cols}

    meta = taxmod.load_taxonomy_meta(force=True, require=True)
    plans = []
    for kind, parent, node in taxmod.iter_taxonomy_nodes(meta["taxonomy"]):
        want = (node.get("handle") or "").strip()
        if not want:
            continue
        if want in by_handle:
            continue
        if kind == "subcategory" and parent:
            title = f"{parent.get('category')} - {node.get('label')}"
        else:
            title = node.get("category") or ""
        col = by_title.get(title)
        if not col:
            print(f"[skip] no title match for {want!r} title={title!r}")
            continue
        plans.append((col["handle"], want, col["id"], title))

    print(f"planned renames: {len(plans)}  write={args.write}")
    for old, new, cid, title in plans:
        print(f"  {old} -> {new}  ({title})  {cid}")

    if not args.write:
        return 0

    for old, new, cid, title in plans:
        if new in by_handle:
            raise ShopifyError(f"target handle already taken: {new}")
        shop.collection_update(cid, handle=new)
        shop.create_redirect(f"/collections/{old}", f"/collections/{new}")
        print(f"[ok] renamed {old} -> {new}")
        # refresh occupancy
        by_handle.pop(old, None)
        by_handle[new] = {"handle": new, "id": cid}

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
