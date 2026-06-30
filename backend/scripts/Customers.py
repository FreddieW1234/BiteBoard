"""Fetch Shopify customers for the Customers page."""

import os
import sys
import time
import requests

PARENT_DIR = os.path.dirname(os.path.dirname(__file__))
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from config import STORE_DOMAIN, API_VERSION, ACCESS_TOKEN  # type: ignore

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
)

CUSTOMERS_GRAPHQL_QUERY = """
query GetCustomersOverview($cursor: String) {
  customers(first: 100, after: $cursor) {
    edges {
      node {
        legacyResourceId
        firstName
        lastName
        email
        phone
        tags
        ordersCount
        amountSpent { amount }
        state
        createdAt
        companyNameNew: metafield(namespace: "custom_fields", key: "company_name_new") { value }
        invoiceAddressNew: metafield(namespace: "custom_fields", key: "invoice_address_new") { value }
        landlinePhoneNumber: metafield(namespace: "custom_fields", key: "landline_phone_number") { value }
        mobileNumber: metafield(namespace: "custom_fields", key: "mobile_number") { value }
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
            timeout=30,
        )
        if resp.status_code == 429:
            time.sleep(2)
            continue
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            err_str = str(data["errors"])
            if "THROTTLED" in err_str.upper():
                time.sleep(2)
                continue
            raise RuntimeError(err_str)
        return data.get("data") or {}


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
}


def _graphql_metafields_set(metafields):
    data = _graphql_request(METAFIELDS_SET_MUTATION, {"metafields": metafields})
    result = (data.get("metafieldsSet") or {})
    errors = result.get("userErrors") or []
    if errors:
        raise RuntimeError("; ".join(e.get("message", "") for e in errors if e.get("message")))
    return result.get("metafields") or []


def _fetch_single_customer(customer_id):
    customer_id = int(customer_id)
    get_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers/{customer_id}.json"
    raw = _safe_request("GET", get_url).json().get("customer") or {}
    mf = _metafields_map_from_rest(_fetch_customer_metafields_rest(customer_id))
    return _format_customer_rest(raw, mf)


def update_customer_details(customer_id, payload):
    """Update customer tags, email, and custom_fields metafields."""
    customer_id = int(customer_id)
    get_url = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/customers/{customer_id}.json"
    raw = _safe_request("GET", get_url).json().get("customer") or {}

    existing_tags = _parse_tags(raw.get("tags"))
    type_tag = payload.get("type_tag")
    if type_tag is not None:
        if type_tag == "":
            type_tag = None
        else:
            key = str(type_tag).strip().lower()
            if key not in CUSTOMER_TYPE_TAGS:
                raise ValueError("Invalid type tag")
            type_tag = key
    new_tags = _apply_type_tag(existing_tags, type_tag)

    customer_body = {"id": customer_id, "tags": ", ".join(new_tags)}
    if "email" in payload:
        customer_body["email"] = str(payload.get("email") or "").strip()
    if "first_name" in payload:
        customer_body["first_name"] = str(payload.get("first_name") or "").strip()
    if "last_name" in payload:
        customer_body["last_name"] = str(payload.get("last_name") or "").strip()

    _safe_request("PUT", get_url, json={"customer": customer_body})

    owner_gid = f"gid://shopify/Customer/{customer_id}"
    metafields_input = []
    for api_key, (shopify_key, field_type) in METAFIELD_PAYLOAD_KEYS.items():
        if api_key not in payload:
            continue
        metafields_input.append({
            "ownerId": owner_gid,
            "namespace": CUSTOMER_METAFIELD_NAMESPACE,
            "key": shopify_key,
            "type": field_type,
            "value": str(payload.get(api_key) or ""),
        })

    if metafields_input:
        _graphql_metafields_set(metafields_input)

    return _fetch_single_customer(customer_id)


def _format_customer_graphql(node):
    first = (node.get("firstName") or "").strip()
    last = (node.get("lastName") or "").strip()
    name = f"{first} {last}".strip() or (node.get("email") or "Unknown")
    tags = _parse_tags(node.get("tags"))
    matched = _matched_type_tags(tags)
    amount_spent = (node.get("amountSpent") or {}).get("amount") or "0.00"
    return {
        "id": node.get("legacyResourceId"),
        "name": name,
        "first_name": first,
        "last_name": last,
        "email": node.get("email") or "",
        "company_name": _metafield_graphql_value(node, "companyNameNew"),
        "invoice_address": _metafield_graphql_value(node, "invoiceAddressNew"),
        "landline_phone": _metafield_graphql_value(node, "landlinePhoneNumber"),
        "mobile_number": _metafield_graphql_value(node, "mobileNumber"),
        "phone": node.get("phone") or "",
        "tags": tags,
        "matched_tags": matched,
        "tag_conflict": len(matched) > 1,
        "orders_count": node.get("ordersCount") or 0,
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
        "phone": raw.get("phone") or (raw.get("default_address") or {}).get("phone") or "",
        "tags": tags,
        "matched_tags": matched,
        "tag_conflict": len(matched) > 1,
        "orders_count": raw.get("orders_count") or 0,
        "total_spent": raw.get("total_spent") or "0.00",
        "state": raw.get("state") or "",
        "created_at": raw.get("created_at") or "",
    }


def _fetch_all_customers_graphql():
    customers = []
    cursor = None
    while True:
        variables = {"cursor": cursor} if cursor else {}
        data = _graphql_request(CUSTOMERS_GRAPHQL_QUERY, variables)
        customers_data = data.get("customers") or {}
        for edge in customers_data.get("edges") or []:
            node = edge.get("node") or {}
            if node:
                customers.append(_format_customer_graphql(node))
        page_info = customers_data.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    return customers


def _fetch_all_customers():
    try:
        return _fetch_all_customers_graphql()
    except Exception:
        raw_customers = _fetch_all_customers_rest()
        customers = []
        for raw in raw_customers:
            mf = _metafields_map_from_rest(_fetch_customer_metafields_rest(raw.get("id")))
            customers.append(_format_customer_rest(raw, mf))
        return customers


def get_customers_overview():
    """Return all Shopify customers as a flat list."""
    customers = _fetch_all_customers()
    conflict_count = sum(1 for c in customers if c["tag_conflict"])
    return {
        "success": True,
        "customers": customers,
        "total": len(customers),
        "conflict_count": conflict_count,
    }
