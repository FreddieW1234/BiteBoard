"""Fetch Shopify customers for the Customers page."""

import os
import sys
import time
import requests

PARENT_DIR = os.path.dirname(os.path.dirname(__file__))
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN, CUSTOMER_SEND_WELCOME_EMAIL  # type: ignore

HEADERS = {
    "Content-Type": "application/json",
    "X-Shopify-Access-Token": ACCESS_TOKEN,
}

CUSTOMER_TYPE_TAGS = ("pending", "trade", "end-customer")
TYPE_TAG_LABELS = {
    "trade": "trade",
    "end-customer": "end-customer",
    "pending": "Pending",
}
CUSTOMER_METAFIELD_NAMESPACE = "custom_fields"
CUSTOMER_METAFIELD_KEYS = (
    "company_name_new",
    "invoice_address_new",
    "landline_phone_number",
    "mobile_number",
    "linked_company_id",
)

# One metafields connection per customer is cheaper than five separate metafield
# lookups, and avoids the old ordersCount field that broke on API 2025-07.
CUSTOMERS_GRAPHQL_QUERY = """
query GetCustomersOverview($cursor: String) {
  customers(first: 50, after: $cursor) {
    edges {
      node {
        legacyResourceId
        firstName
        lastName
        email
        phone
        tags
        numberOfOrders
        amountSpent { amount }
        state
        createdAt
        metafields(first: 15, namespace: "custom_fields") {
          edges { node { key value } }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _safe_get(url):
    while True:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 429:
            time.sleep(2)
            continue
        resp.raise_for_status()
        return resp


def _graphql_request(query, variables=None):
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"
    while True:
        resp = requests.post(
            url,
            json={"query": query, "variables": variables or {}},
            headers=HEADERS,
            timeout=60,
        )
        if resp.status_code == 429:
            time.sleep(2)
            continue
        resp.raise_for_status()
        payload = resp.json()
        errors = payload.get("errors") or []
        if errors:
            err_str = str(errors)
            if "THROTTLED" in err_str.upper():
                # Honour Shopify's suggested wait when present.
                wait = 2.0
                try:
                    for err in errors:
                        tw = ((err.get("extensions") or {}).get("cost") or {}).get(
                            "throttleStatus", {}
                        ).get("restoreRate")
                        if tw:
                            wait = max(wait, 1.0)
                except Exception:
                    pass
                time.sleep(wait)
                continue
            # If Shopify still returned a customers page, use it (partial success).
            data = payload.get("data") or {}
            if data.get("customers"):
                print(f"[warn] Customers GraphQL warnings (using data anyway): {err_str[:300]}", flush=True)
                return data
            raise RuntimeError(err_str)
        return payload.get("data") or {}


def _fetch_all_customers_rest():
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers.json?limit=250"
    collected = []
    while url:
        resp = _safe_get(url)
        collected.extend(resp.json().get("customers") or [])
        link_header = resp.headers.get("Link")
        next_url = None
        if link_header:
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    next_url = part[part.find("<") + 1 : part.find(">")]
                    break
        url = next_url
    return collected


def _fetch_customer_metafields_rest(customer_id):
    url = (
        f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers/"
        f"{customer_id}/metafields.json?namespace={CUSTOMER_METAFIELD_NAMESPACE}&limit=50"
    )
    try:
        resp = _safe_get(url)
        return resp.json().get("metafields") or []
    except Exception:
        return []


def _metafields_map_from_rest(metafields):
    by_key = {}
    for mf in metafields:
        key = mf.get("key")
        if key in CUSTOMER_METAFIELD_KEYS:
            by_key[key] = (mf.get("value") or "").strip()
    return by_key


def _metafield_graphql_value(node, alias):
    mf = node.get(alias)
    if not mf or not isinstance(mf, dict):
        return ""
    return (mf.get("value") or "").strip()


def _parse_tags(tags_value):
    if not tags_value:
        return []
    if isinstance(tags_value, list):
        return [str(t).strip() for t in tags_value if str(t).strip()]
    return [t.strip() for t in str(tags_value).split(",") if t.strip()]


def _matched_type_tags(tags):
    normalized = {t.lower(): t for t in tags}
    matched = []
    for key in CUSTOMER_TYPE_TAGS:
        if key in normalized:
            matched.append(normalized[key])
    return matched


def _apply_type_tag(existing_tags, type_tag):
    """Remove type tags and optionally set a single new one."""
    remaining = [t for t in existing_tags if t.lower() not in CUSTOMER_TYPE_TAGS]
    if type_tag:
        key = str(type_tag).strip().lower()
        label = TYPE_TAG_LABELS.get(key)
        if label:
            remaining.append(label)
    return remaining


def _safe_request(method, url, **kwargs):
    while True:
        resp = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)
        if resp.status_code == 429:
            time.sleep(2)
            continue
        resp.raise_for_status()
        return resp


def update_customer_type_tag(customer_id, type_tag):
    """Set a customer's mutually exclusive type tag on Shopify."""
    customer_id = int(customer_id)
    get_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers/{customer_id}.json"
    raw = _safe_request("GET", get_url).json().get("customer") or {}
    existing = _parse_tags(raw.get("tags"))
    new_tags = _apply_type_tag(existing, type_tag)
    tags_str = ", ".join(new_tags)

    put_url = get_url
    updated = _safe_request(
        "PUT",
        put_url,
        json={"customer": {"id": customer_id, "tags": tags_str}},
    ).json().get("customer") or {}

    result_tags = _parse_tags(updated.get("tags", tags_str))
    base = {
        "id": customer_id,
        "name": "",
        "email": updated.get("email") or raw.get("email") or "",
        "tags": result_tags,
        "matched_tags": _matched_type_tags(result_tags),
    }
    base["tag_conflict"] = len(base["matched_tags"]) > 1
    return base


METAFIELDS_SET_MUTATION = """
mutation MetafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { key namespace value }
    userErrors { field message }
  }
}
"""

METAFIELD_PAYLOAD_KEYS = {
    "company_name": ("company_name_new", "single_line_text_field"),
    "invoice_address": ("invoice_address_new", "multi_line_text_field"),
    "landline_phone": ("landline_phone_number", "single_line_text_field"),
    "mobile_number": ("mobile_number", "single_line_text_field"),
    "linked_company_id": ("linked_company_id", "single_line_text_field"),
}


METAFIELDS_DELETE_MUTATION = """
mutation MetafieldsDelete($metafields: [MetafieldIdentifierInput!]!) {
  metafieldsDelete(metafields: $metafields) {
    deletedMetafields { key namespace }
    userErrors { field message }
  }
}
"""


def _graphql_metafields_set(metafields):
    data = _graphql_request(METAFIELDS_SET_MUTATION, {"metafields": metafields})
    result = (data.get("metafieldsSet") or {})
    errors = result.get("userErrors") or []
    if errors:
        raise RuntimeError("; ".join(e.get("message", "") for e in errors if e.get("message")))
    return result.get("metafields") or []


def _graphql_metafields_delete(identifiers):
    """Delete metafields by ownerId + namespace + key."""
    if not identifiers:
        return
    data = _graphql_request(METAFIELDS_DELETE_MUTATION, {"metafields": identifiers})
    result = (data.get("metafieldsDelete") or {})
    errors = result.get("userErrors") or []
    if errors:
        raise RuntimeError("; ".join(e.get("message", "") for e in errors if e.get("message")))


def _fetch_single_customer(customer_id):
    customer_id = int(customer_id)
    get_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers/{customer_id}.json"
    raw = _safe_request("GET", get_url).json().get("customer") or {}
    mf = _metafields_map_from_rest(_fetch_customer_metafields_rest(customer_id))
    return _format_customer_rest(raw, mf)


def _request_with_status(method, url, **kwargs):
    """Like _safe_request but returns the response without raising on 4xx."""
    while True:
        resp = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)
        if resp.status_code == 429:
            time.sleep(2)
            continue
        return resp


def customer_exists_by_email(email: str) -> bool:
    """Return True if a Shopify customer with this email already exists."""
    from urllib.parse import quote

    email = (email or "").strip().lower()
    if not email:
        return False
    query = quote(f"email:{email}")
    url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers/search.json?query={query}"
    try:
        resp = _request_with_status("GET", url)
        if resp.status_code != 200:
            return False
        customers = resp.json().get("customers") or []
        return any((c.get("email") or "").strip().lower() == email for c in customers)
    except Exception:
        return False


def create_customer(payload: dict) -> dict:
    """Create a Shopify customer tagged Pending with custom_fields metafields."""
    import re

    first_name = str(payload.get("first_name") or "").strip()
    last_name = str(payload.get("last_name") or "").strip()
    email = str(payload.get("email") or "").strip()
    if not first_name:
        raise ValueError("First name is required.")
    if not email:
        raise ValueError("Email is required.")
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        raise ValueError("Please enter a valid email address.")

    customer_body: dict = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "tags": TYPE_TAG_LABELS["pending"],
    }
    if CUSTOMER_SEND_WELCOME_EMAIL:
        customer_body["send_email_welcome"] = True

    create_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers.json"
    resp = _request_with_status(
        "POST",
        create_url,
        json={"customer": customer_body},
    )
    if resp.status_code == 422:
        detail = resp.text or ""
        if "email" in detail.lower() and ("taken" in detail.lower() or "already" in detail.lower()):
            raise ValueError("An account with this email already exists.")
        try:
            errors = resp.json().get("errors") or {}
            email_errors = errors.get("email") if isinstance(errors, dict) else None
            if email_errors:
                raise ValueError("An account with this email already exists.")
        except ValueError:
            raise
        except Exception:
            pass
        raise ValueError("Could not create account. Please check your details and try again.")
    resp.raise_for_status()

    created = resp.json().get("customer") or {}
    customer_id = created.get("id")
    if not customer_id:
        raise RuntimeError("Shopify did not return a customer id.")

    metafield_payload = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
    }
    for key in METAFIELD_PAYLOAD_KEYS:
        if key in payload:
            metafield_payload[key] = payload.get(key)

    customer = update_customer_details(customer_id, metafield_payload)
    return customer


def _customer_company_locked(mf: dict) -> bool:
    return bool((mf.get("linked_company_id") or "").strip())


def set_customer_company_link(customer_id: str | int, company_id: str, company_name: str) -> dict:
    """Assign customer to a company - overwrite company name and store company id on Shopify."""
    payload = {
        "company_name": (company_name or "").strip(),
        "linked_company_id": str(company_id or "").strip(),
    }
    return update_customer_details(customer_id, payload, allow_company_override=True)


def clear_customer_company_link(customer_id: str | int) -> dict:
    """Remove company assignment from a customer."""
    customer_id = int(customer_id)
    owner_gid = f"gid://shopify/Customer/{customer_id}"
    _graphql_metafields_delete([{
        "ownerId": owner_gid,
        "namespace": CUSTOMER_METAFIELD_NAMESPACE,
        "key": "linked_company_id",
    }])
    return _fetch_single_customer(customer_id)


def update_customer_details(customer_id, payload, *, allow_company_override: bool = False):
    """Update customer tags, email, and custom_fields metafields."""
    customer_id = int(customer_id)
    get_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers/{customer_id}.json"
    raw = _safe_request("GET", get_url).json().get("customer") or {}

    existing_tags = _parse_tags(raw.get("tags"))
    if "type_tag" in payload:
        type_tag = payload.get("type_tag")
        if type_tag == "":
            type_tag = None
        else:
            key = str(type_tag).strip().lower()
            if key not in CUSTOMER_TYPE_TAGS:
                raise ValueError("Invalid type tag")
            type_tag = key
        new_tags = _apply_type_tag(existing_tags, type_tag)
    else:
        new_tags = existing_tags

    customer_body = {"id": customer_id, "tags": ", ".join(new_tags)}
    if "email" in payload:
        customer_body["email"] = str(payload.get("email") or "").strip()
    if "first_name" in payload:
        customer_body["first_name"] = str(payload.get("first_name") or "").strip()
    if "last_name" in payload:
        customer_body["last_name"] = str(payload.get("last_name") or "").strip()

    _safe_request("PUT", get_url, json={"customer": customer_body})

    owner_gid = f"gid://shopify/Customer/{customer_id}"
    existing_mf = _fetch_customer_metafields_rest(customer_id)
    existing_by_key = {mf.get("key"): mf for mf in existing_mf if mf.get("key")}
    mf_map = _metafields_map_from_rest(existing_mf)

    if not allow_company_override and _customer_company_locked(mf_map) and "company_name" in payload:
        payload = dict(payload)
        payload.pop("company_name", None)

    metafields_to_set = []
    metafields_to_delete = []
    for api_key, (shopify_key, field_type) in METAFIELD_PAYLOAD_KEYS.items():
        if api_key not in payload:
            continue
        value = str(payload.get(api_key) or "").strip()
        if value:
            metafields_to_set.append({
                "ownerId": owner_gid,
                "namespace": CUSTOMER_METAFIELD_NAMESPACE,
                "key": shopify_key,
                "type": field_type,
                "value": value,
            })
        elif shopify_key in existing_by_key:
            # Cleared field - remove metafield (Shopify rejects blank values on set)
            metafields_to_delete.append({
                "ownerId": owner_gid,
                "namespace": CUSTOMER_METAFIELD_NAMESPACE,
                "key": shopify_key,
            })

    if metafields_to_set:
        _graphql_metafields_set(metafields_to_set)
    if metafields_to_delete:
        _graphql_metafields_delete(metafields_to_delete)

    return _fetch_single_customer(customer_id)


def _metafields_map_from_graphql_node(node):
    """Map custom_fields keys from either aliased metafields or a metafields connection."""
    by_key = {}
    # Legacy aliased shape (companyNameNew: metafield(...))
    alias_to_key = {
        "companyNameNew": "company_name_new",
        "invoiceAddressNew": "invoice_address_new",
        "landlinePhoneNumber": "landline_phone_number",
        "mobileNumber": "mobile_number",
        "linkedCompanyId": "linked_company_id",
    }
    for alias, key in alias_to_key.items():
        val = _metafield_graphql_value(node, alias)
        if val:
            by_key[key] = val
    edges = ((node.get("metafields") or {}).get("edges")) or []
    for edge in edges:
        mf = (edge or {}).get("node") or {}
        key = mf.get("key")
        if key in CUSTOMER_METAFIELD_KEYS:
            by_key[key] = (mf.get("value") or "").strip()
    return by_key


def _format_customer_graphql(node):
    first = (node.get("firstName") or "").strip()
    last = (node.get("lastName") or "").strip()
    name = f"{first} {last}".strip() or (node.get("email") or "Unknown")
    tags = _parse_tags(node.get("tags"))
    matched = _matched_type_tags(tags)
    amount_spent = (node.get("amountSpent") or {}).get("amount") or "0.00"
    mf = _metafields_map_from_graphql_node(node)
    linked = mf.get("linked_company_id", "")
    return {
        "id": node.get("legacyResourceId"),
        "name": name,
        "first_name": first,
        "last_name": last,
        "email": node.get("email") or "",
        "company_name": mf.get("company_name_new", ""),
        "invoice_address": mf.get("invoice_address_new", ""),
        "landline_phone": mf.get("landline_phone_number", ""),
        "mobile_number": mf.get("mobile_number", ""),
        "linked_company_id": linked,
        "company_locked": bool(linked),
        "phone": node.get("phone") or "",
        "tags": tags,
        "matched_tags": matched,
        "tag_conflict": len(matched) > 1,
        # Shopify renamed ordersCount -> numberOfOrders (API 2022+); accept either.
        "orders_count": node.get("numberOfOrders") or node.get("ordersCount") or 0,
        "total_spent": amount_spent,
        "state": node.get("state") or "",
        "created_at": node.get("createdAt") or "",
    }


def _format_customer_rest(raw, metafields_by_key=None):
    first = (raw.get("first_name") or "").strip()
    last = (raw.get("last_name") or "").strip()
    name = f"{first} {last}".strip() or (raw.get("email") or "Unknown")
    tags = _parse_tags(raw.get("tags"))
    matched = _matched_type_tags(tags)
    mf = metafields_by_key or {}
    return {
        "id": raw.get("id"),
        "name": name,
        "first_name": first,
        "last_name": last,
        "email": raw.get("email") or "",
        "company_name": mf.get("company_name_new", ""),
        "invoice_address": mf.get("invoice_address_new", ""),
        "landline_phone": mf.get("landline_phone_number", ""),
        "mobile_number": mf.get("mobile_number", ""),
        "linked_company_id": mf.get("linked_company_id", ""),
        "company_locked": _customer_company_locked(mf),
        "phone": raw.get("phone") or (raw.get("default_address") or {}).get("phone") or "",
        "tags": tags,
        "matched_tags": matched,
        "tag_conflict": len(matched) > 1,
        "orders_count": raw.get("orders_count") or 0,
        "total_spent": raw.get("total_spent") or "0.00",
        "state": raw.get("state") or "",
        "created_at": raw.get("created_at") or "",
    }


def _publish_customers_partial(customers, *, building: bool, error=None):
    """Publish overview state so the UI can show rows while Shopify pages load."""
    global _CUSTOMERS_CACHE, _CUSTOMERS_CACHE_AT, _CUSTOMERS_LAST_ERROR
    conflict_count = sum(1 for c in customers if c.get("tag_conflict"))
    result = {
        "success": error is None,
        "customers": list(customers),
        "total": len(customers),
        "conflict_count": conflict_count,
        "building": building,
    }
    if error:
        result["error"] = str(error)
        _CUSTOMERS_LAST_ERROR = str(error)
    elif not building:
        _CUSTOMERS_LAST_ERROR = None
    _CUSTOMERS_CACHE = result
    # Only treat a finished successful build as "fresh" for the TTL window.
    if not building and error is None:
        _CUSTOMERS_CACHE_AT = time.time()
    return result


def _fetch_all_customers_graphql(on_page=None):
    """Paginate customers from Shopify GraphQL. on_page(customers_so_far) optional."""
    customers = []
    cursor = None
    page = 0
    while True:
        page += 1
        variables = {"cursor": cursor} if cursor else {}
        data = _graphql_request(CUSTOMERS_GRAPHQL_QUERY, variables)
        customers_data = data.get("customers") or {}
        for edge in customers_data.get("edges") or []:
            node = edge.get("node") or {}
            if node:
                customers.append(_format_customer_graphql(node))
        print(f"[recv] Customers GraphQL page {page}: {len(customers)} so far", flush=True)
        if on_page is not None:
            on_page(customers)
        page_info = customers_data.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    return customers


def _fetch_all_customers(on_page=None):
    """GraphQL only for the overview list.

    The old REST fallback fetched metafields per customer and could take many
    minutes, which looked like a permanent spinner. Fail fast instead.
    """
    return _fetch_all_customers_graphql(on_page=on_page)


_CUSTOMERS_CACHE: dict | None = None
_CUSTOMERS_CACHE_AT = 0.0
_CUSTOMERS_CACHE_TTL = 90  # seconds - avoids repeated full Shopify pulls on tab switches
_CUSTOMERS_REFRESH_LOCK = None  # lazy threading.Lock
_CUSTOMERS_REFRESHING = False
_CUSTOMERS_LAST_ERROR = None


def _customers_refresh_lock():
    global _CUSTOMERS_REFRESH_LOCK
    if _CUSTOMERS_REFRESH_LOCK is None:
        import threading
        _CUSTOMERS_REFRESH_LOCK = threading.Lock()
    return _CUSTOMERS_REFRESH_LOCK


def invalidate_customers_cache() -> None:
    global _CUSTOMERS_CACHE, _CUSTOMERS_CACHE_AT
    _CUSTOMERS_CACHE = None
    _CUSTOMERS_CACHE_AT = 0.0


def _refresh_customers_overview_bg():
    """Background rebuild; publishes partial pages so the UI is not stuck empty."""
    global _CUSTOMERS_REFRESHING
    try:
        def _on_page(partial):
            _publish_customers_partial(partial, building=True)

        customers = _fetch_all_customers(on_page=_on_page)
        _publish_customers_partial(customers, building=False)
        print(f"[ok] Customers overview refreshed ({len(customers)} customers)", flush=True)
    except Exception as exc:
        print(f"[warn] Customers background refresh failed: {exc}", flush=True)
        existing = (_CUSTOMERS_CACHE or {}).get("customers") or []
        _publish_customers_partial(existing, building=False, error=exc)
    finally:
        with _customers_refresh_lock():
            _CUSTOMERS_REFRESHING = False


def _kick_customers_refresh():
    global _CUSTOMERS_REFRESHING
    import threading
    with _customers_refresh_lock():
        if _CUSTOMERS_REFRESHING:
            return
        _CUSTOMERS_REFRESHING = True
    threading.Thread(target=_refresh_customers_overview_bg, daemon=True).start()


def get_customers_overview(*, refresh: bool = False):
    """Return all Shopify customers as a flat list (stale-while-revalidate).

    Never runs the full Shopify scan on a gunicorn request thread - that is what
    saturates the pool and makes Render's 5s /healthz check time out. Fresh cache
    is returned immediately; stale/cold/refresh always rebuild in a background
    thread and return whatever we have now (possibly empty with building=True).
    """
    now = time.time()
    cached = _CUSTOMERS_CACHE
    if (
        not refresh
        and cached is not None
        and not cached.get("building")
        and cached.get("success") is not False
        and (now - _CUSTOMERS_CACHE_AT) < _CUSTOMERS_CACHE_TTL
    ):
        return cached

    # Already building - just return the latest partial/empty snapshot.
    with _customers_refresh_lock():
        already = _CUSTOMERS_REFRESHING
    if already and cached is not None:
        return cached
    if already and cached is None:
        return {
            "success": True,
            "customers": [],
            "total": 0,
            "conflict_count": 0,
            "building": True,
        }

    _kick_customers_refresh()
    if cached is not None:
        out = dict(cached)
        out["building"] = True
        return out
    return {
        "success": True,
        "customers": [],
        "total": 0,
        "conflict_count": 0,
        "building": True,
    }


def warm_customers_cache_async():
    """Kick a background customers rebuild (call once at process start)."""
    _kick_customers_refresh()


def get_customers_id_map(*, refresh: bool = False) -> dict[str, dict]:
    """Customer id (str) -> customer dict, from the in-memory overview cache."""
    overview = get_customers_overview(refresh=refresh)
    return {
        str(c.get("id")): c
        for c in (overview.get("customers") or [])
        if c.get("id") is not None
    }
