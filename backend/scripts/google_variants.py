"""Google & YouTube channel: publish exactly one variant per product.

Every product has a variant per quantity band x customer type. Google Merchant
Center should get one item per product whose price matches what a logged-out
visitor sees on the product page: "FROM <cheapest End Customer price>". So the
variant kept on the Google & YouTube channel is the End Customer variant with
the lowest price (ties -> the higher quantity band); every other variant is
unpublished from that channel. Other channels are not touched.

Variant-level publishing needs Admin API 2026-07 or later, so this module
calls that version directly rather than the app-wide API_VERSION.
"""

from __future__ import annotations

import re
import threading
import time

import requests

from config import STORE_DOMAIN, ACCESS_TOKEN  # type: ignore

API_VERSION = "2026-07"
CHANNEL_NAME = "Google & YouTube"
CUSTOMER_TYPE_OPTION = "customer type"
KEEP_CUSTOMER_TYPE = "end customer"

_PUBLICATION_ID: str | None = None
_RUN_LOCK = threading.Lock()
_LAST_REPORT: dict = {}


def _gql(query: str, variables: dict | None = None) -> dict:
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": ACCESS_TOKEN, "Content-Type": "application/json"}
    for _attempt in range(10):
        resp = requests.post(url, json={"query": query, "variables": variables or {}},
                             headers=headers, timeout=(10, 60))
        if resp.status_code == 429:
            time.sleep(2)
            continue
        resp.raise_for_status()
        payload = resp.json()
        errors = payload.get("errors") or []
        if errors:
            if "THROTTLED" in str(errors).upper():
                time.sleep(2)
                continue
            raise RuntimeError(str(errors)[:500])
        return payload.get("data") or {}
    raise RuntimeError("Shopify GraphQL throttled repeatedly")


def google_publication_id() -> str:
    global _PUBLICATION_ID
    if _PUBLICATION_ID:
        return _PUBLICATION_ID
    data = _gql("{ publications(first: 50) { nodes { id name } } }")
    for node in (data.get("publications") or {}).get("nodes") or []:
        if (node.get("name") or "").strip().lower() == CHANNEL_NAME.lower():
            _PUBLICATION_ID = node["id"]
            return _PUBLICATION_ID
    raise RuntimeError(f"No '{CHANNEL_NAME}' sales channel found")


def _band_start(variant: dict) -> int:
    for opt in variant.get("selectedOptions") or []:
        if (opt.get("name") or "").strip().lower() == "quantity":
            m = re.match(r"\s*(\d+)", opt.get("value") or "")
            if m:
                return int(m.group(1))
    return 0


def _customer_type(variant: dict) -> str:
    for opt in variant.get("selectedOptions") or []:
        if (opt.get("name") or "").strip().lower() == CUSTOMER_TYPE_OPTION:
            return (opt.get("value") or "").strip().lower()
    return ""


def choose_google_variant(variants: list[dict]) -> dict | None:
    """The End Customer variant with the lowest price - the logged-out 'FROM' price."""
    def price(v):
        try:
            return float(v.get("price"))
        except (TypeError, ValueError):
            return None

    candidates = [v for v in variants if _customer_type(v) == KEEP_CUSTOMER_TYPE and price(v)]
    if not candidates:
        # No customer-type option (single-price product): keep the cheapest priced variant.
        has_type = any(_customer_type(v) for v in variants)
        if has_type:
            return None
        candidates = [v for v in variants if price(v)]
    if not candidates:
        return None
    return min(candidates, key=lambda v: (price(v), -_band_start(v)))


_PRODUCT_FIELDS = """
  id handle title status
  onGoogle: publishedOnPublication(publicationId: $pub)
  variants(first: 100) {
    nodes {
      id title price
      selectedOptions { name value }
      onGoogle: publishedOnPublication(publicationId: $pub)
    }
  }
"""


def plan_product(product: dict) -> dict:
    """What would change for one product: {keep, publish: [ids], unpublish: [ids]}."""
    variants = (product.get("variants") or {}).get("nodes") or []
    keep = choose_google_variant(variants)
    plan = {"handle": product.get("handle"), "title": product.get("title"),
            "keep": keep, "publish": [], "unpublish": []}
    if not product.get("onGoogle") or keep is None:
        return plan  # product itself is not on the channel, or nothing sensible to keep
    for v in variants:
        if v["id"] == keep["id"]:
            if not v.get("onGoogle"):
                plan["publish"].append(v["id"])
        elif v.get("onGoogle"):
            plan["unpublish"].append(v["id"])
    return plan


def _apply(plan: dict, pub: str) -> None:
    ops = ([("publishablePublish", vid) for vid in plan["publish"]]
           + [("publishableUnpublish", vid) for vid in plan["unpublish"]])
    # A handful of aliased mutations per request keeps query cost low.
    for i in range(0, len(ops), 10):
        chunk = ops[i:i + 10]
        body = "\n".join(
            f'm{n}: {mut}(id: "{vid}", input: [{{publicationId: "{pub}"}}]) '
            "{ userErrors { field message } }"
            for n, (mut, vid) in enumerate(chunk)
        )
        data = _gql("mutation {\n" + body + "\n}")
        errs = [e for r in data.values() for e in ((r or {}).get("userErrors") or [])]
        if errs:
            raise RuntimeError(f"{plan['handle']}: {errs[:3]}")


def sync_product(product_id, *, write: bool = True) -> dict:
    """Fix one product (e.g. right after it is created or repriced)."""
    pub = google_publication_id()
    gid = product_id if str(product_id).startswith("gid://") else f"gid://shopify/Product/{product_id}"
    data = _gql(f"query($id: ID!, $pub: ID!) {{ product(id: $id) {{ {_PRODUCT_FIELDS} }} }}",
                {"id": gid, "pub": pub})
    product = data.get("product")
    if not product:
        return {"success": False, "error": "Product not found"}
    plan = plan_product(product)
    if write and (plan["publish"] or plan["unpublish"]):
        _apply(plan, pub)
    return {"success": True, "changed": bool(plan["publish"] or plan["unpublish"]), **_summary(plan)}


def _summary(plan: dict) -> dict:
    keep = plan.get("keep") or {}
    return {"handle": plan["handle"], "keep": keep.get("title"), "keep_price": keep.get("price"),
            "published": len(plan["publish"]), "unpublished": len(plan["unpublish"])}


def sync_all(*, write: bool = True) -> dict:
    """Every active product. Returns counts and the products changed."""
    if not _RUN_LOCK.acquire(blocking=False):
        return {"success": False, "error": "Already running"}
    try:
        started = time.time()
        pub = google_publication_id()
        query = ("query($c: String, $pub: ID!) { products(first: 20, after: $c, query: \"status:active\") "
                 "{ pageInfo { hasNextPage endCursor } nodes { " + _PRODUCT_FIELDS + " } } }")
        cursor = None
        counts = {"products": 0, "on_google": 0, "already_correct": 0, "changed": 0,
                  "no_end_customer_variant": 0, "variants_published": 0, "variants_unpublished": 0}
        changed, problems = [], []
        while True:
            data = _gql(query, {"c": cursor, "pub": pub})
            conn = data.get("products") or {}
            for product in conn.get("nodes") or []:
                counts["products"] += 1
                if not product.get("onGoogle"):
                    continue
                counts["on_google"] += 1
                plan = plan_product(product)
                if plan["keep"] is None:
                    counts["no_end_customer_variant"] += 1
                    problems.append(product.get("handle"))
                    continue
                if not (plan["publish"] or plan["unpublish"]):
                    counts["already_correct"] += 1
                    continue
                counts["changed"] += 1
                counts["variants_published"] += len(plan["publish"])
                counts["variants_unpublished"] += len(plan["unpublish"])
                changed.append(_summary(plan))
                if write:
                    try:
                        _apply(plan, pub)
                    except Exception as exc:  # keep going; report at the end
                        problems.append(f"{plan['handle']}: {exc}")
            page = conn.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")
        report = {"success": not any(":" in p for p in problems), "write": write, "counts": counts,
                  "changed": changed, "problems": problems,
                  "seconds": round(time.time() - started, 1)}
        _LAST_REPORT.clear()
        _LAST_REPORT.update(report)
        print(f"[google-variants] {'applied' if write else 'dry run'}: {counts}", flush=True)
        return report
    finally:
        _RUN_LOCK.release()


def sync_all_async() -> bool:
    """Start sync_all(write=True) in the background. False if one is running."""
    if _RUN_LOCK.locked():
        return False
    threading.Thread(target=sync_all, kwargs={"write": True}, name="google-variants", daemon=True).start()
    return True


def last_report() -> dict:
    return dict(_LAST_REPORT)
