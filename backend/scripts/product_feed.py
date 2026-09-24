"""Customer product feed: nightly catalogue snapshot, filtered per pricing tag.

One Admin API pass builds the snapshot (both price lists attached); each feed
request only filters it to the caller's price list. Memory is the source of
truth - the disk copy is a warm-start cache that Render wipes on every deploy
and idle spin-down, so nothing may assume it exists.

Pricing rules (these are the reason the feed exists at all):
  - A caller sees exactly one price list: trade -> custom.pricejsontr,
    end-customer -> custom.pricejsoner. Never both.
  - A product with no positive price for that list is omitted, not zeroed.
  - Only products published to the Online Store (onlineStoreUrl is set).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN  # type: ignore

_BASE_DIR = Path(__file__).resolve().parent.parent
_CACHE_PATH = _BASE_DIR / "data" / "feed_snapshot.json"
_DISK_MAX_AGE_SECONDS = 26 * 3600
_CUSTOMER_TAG_TTL = 300

PRICE_KEY_BY_TYPE = {"trade": "pricejsontr", "end-customer": "pricejsoner"}

_LOCK = threading.Lock()
_BUILD_LOCK = threading.Lock()
_SNAPSHOT: dict | None = None
_VIEWS: dict[tuple[str, str], dict] = {}   # (generated_at, customer_type) -> rendered body
_LAST_BUILD_ERROR: str | None = None
_BUILD_STARTED_AT: float | None = None
_CUSTOMER_TYPES: dict[str, tuple[float, str | None]] = {}

# Aliased single-metafield lookups are cheap in query cost and are never
# truncated the way a metafields(first: N) page can be.
_METAFIELD_ALIASES = {
    "mf_pricejsontr": "pricejsontr",
    "mf_pricejsoner": "pricejsoner",
    "mf_sku": "sku",
    "mf_description": "description",
    "mf_custom_category": "custom_category",
    "mf_subcategory": "subcategory",
    "mf_subcategory_2": "subcategory_2",
    "mf_sub_subcategory": "sub_subcategory",
    "mf_sub_subcategory_2": "sub_subcategory_2",
    "mf_moq": "moq",
    "mf_case_quantity": "case_quantity",
    "mf_leadtime1": "leadtime1",
    "mf_leadtime2": "leadtime2",
    "mf_unit_weight": "unit_weight",
    "mf_product_size": "product_size",
    "mf_origination": "origination",
    "mf_product_colours": "product_colours",
    "mf_packaging_colours": "packaging_colours",
    "mf_foil_colours": "foil_colours",
    "mf_bag_colours": "bag_colours",
    "mf_customoption1name": "customoption1name",
    "mf_customoption1options": "customoption1options",
    "mf_customoption2name": "customoption2name",
    "mf_customoption2options": "customoption2options",
    "mf_customoption3name": "customoption3name",
    "mf_customoption3options": "customoption3options",
}

_PAGE_SIZE = 25
_PRODUCTS_QUERY = """
query FeedProducts($cursor: String) {
  products(first: %d, after: $cursor, query: "status:active") {
    edges {
      node {
        legacyResourceId
        handle
        title
        description
        productType
        onlineStoreUrl
        images(first: 10) { edges { node { url } } }
        %s
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
""" % (
    _PAGE_SIZE,
    "\n        ".join(
        f'{alias}: metafield(namespace: "custom", key: "{key}") {{ value }}'
        for alias, key in _METAFIELD_ALIASES.items()
    ),
)

_CUSTOMER_TAGS_QUERY = """
query FeedCustomerTags($id: ID!) { customer(id: $id) { tags } }
"""


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _graphql(query: str, variables: dict | None = None) -> dict:
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": ACCESS_TOKEN, "Content-Type": "application/json"}
    for _attempt in range(8):
        resp = requests.post(url, json={"query": query, "variables": variables or {}},
                             headers=headers, timeout=60)
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


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #

def _num(value):
    """int/float from a metafield string; None if blank or not numeric."""
    if value is None:
        return None
    s = str(value).strip().replace("£", "").replace(",", "")
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _text(value):
    s = (value or "").strip() if isinstance(value, str) else value
    return None if s in (None, "", "-") else s


def _text_list(*raws) -> list[str]:
    """Taxonomy metafields are list types (``["Events"]``); merge primary + overflow."""
    out: list[str] = []
    for raw in raws:
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            data = [raw]
        for item in data if isinstance(data, list) else [data]:
            s = str(item).strip()
            if s and s not in out:
                out.append(s)
    return out


def parse_price_breaks(raw) -> list[dict]:
    """Price-table JSON -> [{min, max, price}] with positive prices only, sorted."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for band in data:
        if not isinstance(band, dict):
            continue
        lo, hi, price = _num(band.get("min")), _num(band.get("max")), _num(band.get("price"))
        if lo is None or price is None or price <= 0:
            continue
        out.append({"min": lo, "max": hi, "price": round(float(price), 4)})
    out.sort(key=lambda b: b["min"])
    return out


def _parse_colours(raw) -> list[dict]:
    """``Name:Code, Name:Code`` -> [{name, code}]."""
    out = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, _, code = part.partition(":")
        if name.strip():
            out.append({"name": name.strip(), "code": code.strip() or None})
    return out


def _parse_choices(raw) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except (TypeError, ValueError):
        pass
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def _options(mf: dict) -> dict:
    colours = {}
    for key in ("product_colours", "packaging_colours", "foil_colours", "bag_colours"):
        parsed = _parse_colours(mf.get(key))
        if parsed:
            colours[key.replace("_colours", "")] = parsed
    custom = []
    for n in (1, 2, 3):
        name = _text(mf.get(f"customoption{n}name"))
        choices = _parse_choices(mf.get(f"customoption{n}options"))
        if name and choices:
            custom.append({"name": name, "choices": choices})
    return {"colours": colours, "custom": custom}


def _product_from_node(node: dict) -> dict:
    mf = {key: ((node.get(alias) or {}).get("value")) for alias, key in _METAFIELD_ALIASES.items()}
    images = [
        (e.get("node") or {}).get("url")
        for e in ((node.get("images") or {}).get("edges") or [])
    ]
    lead_times = []
    for key, lo, hi in (("leadtime1", 1, 4999), ("leadtime2", 5000, 10000)):
        raw = _text(mf.get(key))
        if raw:
            lead_times.append({"min_qty": lo, "max_qty": hi,
                               "working_days": _num(raw) if _num(raw) is not None else raw})
    return {
        "id": str(node.get("legacyResourceId") or ""),
        "handle": node.get("handle"),
        "sku": _text(mf.get("sku")),
        "title": node.get("title"),
        "description": _text(mf.get("description")) or _text(node.get("description")),
        "product_type": _text(node.get("productType")),
        "url": node.get("onlineStoreUrl"),
        "categories": _text_list(mf.get("custom_category")),
        "subcategories": _text_list(mf.get("subcategory"), mf.get("subcategory_2")),
        "sub_subcategories": _text_list(mf.get("sub_subcategory"), mf.get("sub_subcategory_2")),
        "images": [u for u in images if u],
        "moq": _num(mf.get("moq")),
        "case_quantity": _num(mf.get("case_quantity")),
        "lead_times": lead_times,
        "unit_weight_g": _num(mf.get("unit_weight")),
        "product_size": _text(mf.get("product_size")),
        "origination": _num(mf.get("origination")),
        "options": _options(mf),
        # Both lists live only in the snapshot; views expose exactly one.
        "_prices": {
            "trade": parse_price_breaks(mf.get("pricejsontr")),
            "end-customer": parse_price_breaks(mf.get("pricejsoner")),
        },
    }


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #

def build_catalogue_snapshot() -> dict:
    """One Admin API pass over every active product published to the Online Store."""
    started = time.time()
    products = []
    cursor = None
    while True:
        data = _graphql(_PRODUCTS_QUERY, {"cursor": cursor})
        conn = data.get("products") or {}
        for edge in conn.get("edges") or []:
            node = edge.get("node") or {}
            if not node.get("onlineStoreUrl"):
                continue  # not published to the Online Store
            products.append(_product_from_node(node))
        page = conn.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    products.sort(key=lambda p: (p.get("sku") or "", p.get("title") or ""))
    snapshot = {"generated_at": _iso_now(), "currency": "GBP", "products": products}
    print(f"[feed] snapshot built: {len(products)} products in {time.time() - started:.1f}s", flush=True)
    return snapshot


def _install(snapshot: dict) -> None:
    global _SNAPSHOT
    with _LOCK:
        _SNAPSHOT = snapshot
        _VIEWS.clear()


def _write_disk_cache(snapshot: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot), encoding="utf-8")
        os.replace(tmp, _CACHE_PATH)
    except Exception as exc:
        print(f"[warn] feed: disk cache write failed: {exc}", flush=True)


def _load_disk_cache() -> dict | None:
    try:
        if not _CACHE_PATH.is_file():
            return None
        if time.time() - _CACHE_PATH.stat().st_mtime > _DISK_MAX_AGE_SECONDS:
            return None
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("products"), list):
            return data
    except Exception as exc:
        print(f"[warn] feed: disk cache unreadable: {exc}", flush=True)
    return None


def rebuild_snapshot() -> tuple[bool, str]:
    """Build and install a fresh snapshot. Returns (built, message). Never overlaps."""
    global _LAST_BUILD_ERROR, _BUILD_STARTED_AT
    if not _BUILD_LOCK.acquire(blocking=False):
        return False, "A snapshot build is already running"
    try:
        _BUILD_STARTED_AT = time.time()
        snapshot = build_catalogue_snapshot()
        _install(snapshot)
        _LAST_BUILD_ERROR = None
        _write_disk_cache(snapshot)
        return True, f"{len(snapshot['products'])} products"
    except Exception as exc:
        _LAST_BUILD_ERROR = f"{_iso_now()} {exc}"
        print(f"[error] feed: snapshot build failed: {exc}", flush=True)
        return False, str(exc)
    finally:
        _BUILD_STARTED_AT = None
        _BUILD_LOCK.release()


def rebuild_snapshot_async() -> None:
    threading.Thread(target=rebuild_snapshot, name="feed-snapshot", daemon=True).start()


def warm_on_boot() -> None:
    """Disk copy if this container still has one, else a background rebuild."""
    cached = _load_disk_cache()
    if cached is not None:
        _install(cached)
        print(f"[feed] snapshot restored from disk ({cached.get('generated_at')})", flush=True)
        return
    rebuild_snapshot_async()


def snapshot_status() -> dict:
    with _LOCK:
        snap = _SNAPSHOT
    return {
        "generated_at": snap.get("generated_at") if snap else None,
        "product_count": len(snap.get("products") or []) if snap else 0,
        "building": _BUILD_STARTED_AT is not None,
        "last_error": _LAST_BUILD_ERROR,
    }


def get_snapshot_generated_at() -> str | None:
    with _LOCK:
        return _SNAPSHOT.get("generated_at") if _SNAPSHOT else None


# --------------------------------------------------------------------------- #
# Per-caller view
# --------------------------------------------------------------------------- #

def render_view(customer_type: str) -> dict | None:
    """Body (+gzip, ETag) for one price list. None if no snapshot is loaded yet."""
    if customer_type not in PRICE_KEY_BY_TYPE:
        raise ValueError(f"Unknown customer type {customer_type!r}")
    with _LOCK:
        snap = _SNAPSHOT
        if snap is None:
            return None
        cache_key = (snap["generated_at"], customer_type)
        cached = _VIEWS.get(cache_key)
    if cached is not None:
        return cached

    products = []
    for p in snap["products"]:
        breaks = p["_prices"].get(customer_type) or []
        if not breaks:
            continue  # omit, never zero
        out = {k: v for k, v in p.items() if not k.startswith("_")}
        out["prices_include_vat"] = False
        out["price_breaks"] = breaks
        products.append(out)
    body = json.dumps(
        {
            "generated_at": snap["generated_at"],
            "currency": snap.get("currency", "GBP"),
            # All prices are ex-VAT. Shown as inc-VAT they would undercharge by 20%.
            "prices_include_vat": False,
            "product_count": len(products),
            "products": products,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    view = {
        "body": body,
        "gzip": gzip.compress(body, compresslevel=6),
        "etag": '"' + hashlib.sha256(body).hexdigest()[:32] + '"',
        "product_count": len(products),
        "generated_at": snap["generated_at"],
    }
    with _LOCK:
        if _SNAPSHOT is snap:
            _VIEWS[cache_key] = view
    return view


def resolve_customer_type(customer_id: str) -> str | None:
    """'trade' / 'end-customer' from the customer's CURRENT Shopify tags.

    None for pending, untagged, both-tagged or missing customers. Cached briefly
    so a customer cron does not cost an Admin API call on every request.
    """
    cid = str(customer_id or "").strip()
    if not cid.isdigit():
        return None
    now = time.time()
    cached = _CUSTOMER_TYPES.get(cid)
    if cached and now - cached[0] < _CUSTOMER_TAG_TTL:
        return cached[1]
    data = _graphql(_CUSTOMER_TAGS_QUERY, {"id": f"gid://shopify/Customer/{cid}"})
    customer = data.get("customer")
    tags = {str(t).strip().lower() for t in ((customer or {}).get("tags") or [])}
    matched = [t for t in PRICE_KEY_BY_TYPE if t in tags]
    ctype = matched[0] if len(matched) == 1 else None
    if customer is not None and len(matched) > 1:
        print(f"[warn] feed: customer {cid} has both trade and end-customer tags - refusing", flush=True)
    _CUSTOMER_TYPES[cid] = (now, ctype)
    return ctype
