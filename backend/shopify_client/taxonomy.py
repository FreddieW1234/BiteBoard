#!/usr/bin/env python3
"""
Taxonomy operations via shopify_client.bite_shopify.Shopify.

Shopify shop.custom.taxonomy is the source of truth.

Visibility / publish policy (Phase 7):
  - New subcategories default to indexable=True; start unpublished / visible=false.
  - Online-Store-published product count > 0 and indexable=True -> publish + visible=true.
  - Count = 0 -> unpublish + visible=false.
  - indexable=False -> never publish via reconcile/webhooks (unpublish if published).
  - Mega-menu deliberate exclusion is Liquid `indexable` gate (not a publish side effect).
  - visible stays accurate for info / non-verify paths.

Concurrency: process-level Lock + expected_updated_at (metafield updatedAt).
LKG disk cache is ephemeral on Render (same container only).
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shopify_client.bite_shopify import Shopify, ShopifyError

NAMESPACE = "custom"
TAXONOMY_KEY = "taxonomy"

_TAXONOMY_CACHE: dict[str, Any] = {
    "at": 0.0,
    "value": None,
    "updated_at": None,
    "source": None,  # live | cached | fallback
    "fetched_at": None,
}
_TAXONOMY_TTL = 60.0
_WRITE_LOCK = threading.Lock()

# Ephemeral on Render - backend/data/ is gitignored
_LKG_PATH = Path(__file__).resolve().parent.parent / "data" / "taxonomy-lkg.json"


class TaxonomyConflict(ShopifyError):
    """HTTP 409 - expected_updated_at mismatch."""

    def __init__(self, message: str, *, current_updated_at: str | None = None):
        super().__init__(message)
        self.current_updated_at = current_updated_at


def _shop() -> Shopify:
    return Shopify()


def handleize(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "collection"


def is_handle_locked(node: dict) -> bool:
    """Absent handle_locked means locked."""
    if "handle_locked" not in node:
        return True
    return bool(node.get("handle_locked"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_nodes(tax: list) -> int:
    n = len(tax or [])
    for c in tax or []:
        for s in c.get("subcategories") or []:
            n += 1
            n += len(s.get("children") or [])
    return n


def _read_lkg() -> dict | None:
    try:
        if not _LKG_PATH.is_file():
            return None
        data = json.loads(_LKG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        tax = data.get("taxonomy")
        if not isinstance(tax, list) or not tax:
            return None
        return data
    except Exception as exc:
        print(f"[error] LKG read failed: {exc}", flush=True)
        return None


def write_lkg_from_tax(
    tax: list,
    *,
    updated_at: str | None,
    allow_shrink: bool = False,
) -> bool:
    """
    Persist LKG. Refuses empty taxonomy, or >50% shrink vs current LKG,
    unless allow_shrink=True.
    """
    if not tax:
        print("[error] LKG poison guard: refusing to write empty taxonomy", flush=True)
        return False
    existing = _read_lkg()
    if existing and not allow_shrink:
        old_n = _count_nodes(existing.get("taxonomy") or [])
        new_n = _count_nodes(tax)
        if old_n > 0 and new_n < old_n * 0.5:
            print(
                f"[error] LKG poison guard: refusing shrink {old_n} -> {new_n} nodes "
                f"(>50%). Pass allow_shrink to override.",
                flush=True,
            )
            return False
    try:
        _LKG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": _now_iso(),
            "updated_at": updated_at,
            "taxonomy": tax,
            "note": (
                "Ephemeral on Render: survives process restart in the same container, "
                "not deploys/recycles."
            ),
        }
        _LKG_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return True
    except Exception as exc:
        print(f"[error] LKG write failed: {exc}", flush=True)
        return False


def _set_cache(tax: list, *, updated_at: str | None, source: str) -> None:
    now = time.time()
    _TAXONOMY_CACHE.update(
        {
            "at": now,
            "value": list(tax),
            "updated_at": updated_at,
            "source": source,
            "fetched_at": _now_iso(),
        }
    )


def load_taxonomy_meta(*, force: bool = False, require: bool = True) -> dict:
    """
    Load taxonomy with source metadata.
    Returns {taxonomy, updated_at, source, fetched_at, source_age_sec}.
    """
    now = time.time()
    if (
        not force
        and _TAXONOMY_CACHE["value"] is not None
        and (now - float(_TAXONOMY_CACHE["at"] or 0)) < _TAXONOMY_TTL
    ):
        tax = list(_TAXONOMY_CACHE["value"] or [])
        fetched = _TAXONOMY_CACHE.get("fetched_at")
        age = None
        if fetched:
            try:
                age = max(
                    0,
                    int(
                        (
                            datetime.now(timezone.utc)
                            - datetime.fromisoformat(fetched.replace("Z", "+00:00"))
                        ).total_seconds()
                    ),
                )
            except Exception:
                age = int(now - float(_TAXONOMY_CACHE["at"] or now))
        return {
            "taxonomy": tax,
            "updated_at": _TAXONOMY_CACHE.get("updated_at"),
            "source": _TAXONOMY_CACHE.get("source") or "live",
            "fetched_at": fetched,
            "source_age_sec": age,
        }

    shop = _shop()
    try:
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
    except Exception as exc:
        print(f"[error] taxonomy live fetch failed: {exc}", flush=True)
        mf = None
        live_error = str(exc)
    else:
        live_error = None

    if mf and (mf.get("value") or "").strip():
        raw = mf["value"]
        try:
            tax = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError) as exc:
            raise ShopifyError(f"taxonomy metafield is not valid JSON: {exc}") from exc
        if isinstance(tax, list) and tax:
            updated_at = mf.get("updatedAt")
            _set_cache(tax, updated_at=updated_at, source="live")
            write_lkg_from_tax(tax, updated_at=updated_at)
            return {
                "taxonomy": list(tax),
                "updated_at": updated_at,
                "source": "live",
                "fetched_at": _TAXONOMY_CACHE["fetched_at"],
                "source_age_sec": 0,
            }

    # Live empty or failed - try LKG
    lkg = _read_lkg()
    if lkg:
        tax = list(lkg["taxonomy"])
        updated_at = lkg.get("updated_at")
        fetched_at = lkg.get("fetched_at")
        _set_cache(tax, updated_at=updated_at, source="cached")
        _TAXONOMY_CACHE["fetched_at"] = fetched_at
        age = None
        if fetched_at:
            try:
                age = max(
                    0,
                    int(
                        (
                            datetime.now(timezone.utc)
                            - datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                        ).total_seconds()
                    ),
                )
            except Exception:
                age = None
        print(
            f"[warn] taxonomy serving LKG cache (live empty or failed"
            f"{': ' + live_error if live_error else ''})",
            flush=True,
        )
        return {
            "taxonomy": tax,
            "updated_at": updated_at,
            "source": "cached",
            "fetched_at": fetched_at,
            "source_age_sec": age,
        }

    if require:
        raise ShopifyError(
            "shop.custom.taxonomy is missing or empty - run Phase 1 "
            "(scripts/set_taxonomy_metafield.py --write) before using the Category Editor"
        )

    print(
        "[error] taxonomy FALLBACK - no live metafield and no LKG; "
        "do not edit. Cold start after deploy with Shopify down lands here.",
        flush=True,
    )
    _set_cache([], updated_at=None, source="fallback")
    return {
        "taxonomy": [],
        "updated_at": None,
        "source": "fallback",
        "fetched_at": _TAXONOMY_CACHE["fetched_at"],
        "source_age_sec": 0,
    }


def load_taxonomy(*, force: bool = False, require: bool = True) -> list:
    """Load shop.custom.taxonomy. If require=True, raise when missing/empty."""
    meta = load_taxonomy_meta(force=force, require=require)
    tax = meta["taxonomy"]
    if require and not tax:
        raise ShopifyError(
            "shop.custom.taxonomy is empty - run Phase 1 before creating nodes"
        )
    return list(tax)


def _assert_expected_updated_at(mf, expected_updated_at: str | None) -> None:
    """
    null expected is accepted ONLY when metafield is currently empty.
    Null against a populated metafield -> TaxonomyConflict (409).
    """
    current_at = (mf or {}).get("updatedAt") if mf else None
    has_value = bool(mf and (mf.get("value") or "").strip())
    if expected_updated_at is None:
        if has_value:
            raise TaxonomyConflict(
                "expected_updated_at is required when taxonomy metafield is populated; reload and retry",
                current_updated_at=current_at,
            )
        return
    if not has_value:
        raise TaxonomyConflict(
            "taxonomy metafield is empty but expected_updated_at was provided; reload and retry",
            current_updated_at=None,
        )
    if current_at != expected_updated_at:
        raise TaxonomyConflict(
            f"taxonomy changed since you loaded it (expected {expected_updated_at}, "
            f"current {current_at}); reload and retry",
            current_updated_at=current_at,
        )


def save_taxonomy(
    tax: list,
    *,
    expected_updated_at: str | None = None,
    skip_expected_check: bool = False,
) -> dict:
    """
    Write taxonomy under Lock. Re-reads after write for cache/LKG.
    skip_expected_check: only for internal rollback paths (unused normally).
    """
    with _WRITE_LOCK:
        shop = _shop()
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        if not skip_expected_check:
            _assert_expected_updated_at(mf, expected_updated_at)
        shop.set_shop_metafield(NAMESPACE, TAXONOMY_KEY, tax)
        # Re-read - never trust the payload we sent for LKG
        bust_taxonomy_cache()
        again = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        raw = (again or {}).get("value") or ""
        try:
            stored = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            stored = tax
        if not isinstance(stored, list):
            stored = tax
        updated_at = (again or {}).get("updatedAt")
        _set_cache(stored, updated_at=updated_at, source="live")
        write_lkg_from_tax(stored, updated_at=updated_at)
        return again or {"updatedAt": updated_at, "namespace": NAMESPACE, "key": TAXONOMY_KEY}


def bust_taxonomy_cache() -> None:
    _TAXONOMY_CACHE.update(
        {"at": 0.0, "value": None, "updated_at": None, "source": None, "fetched_at": None}
    )


def taxonomy_to_mapping(tax: list | None = None) -> dict[str, list[str]]:
    tax = tax if tax is not None else load_taxonomy(require=False)
    out: dict[str, list[str]] = {}
    for cat in tax or []:
        name = cat.get("category") or ""
        if not name:
            continue
        out[name] = [s.get("label") for s in (cat.get("subcategories") or []) if s.get("label")]
    return out


def find_category(tax: list, category: str) -> dict | None:
    for cat in tax:
        if (cat.get("category") or "") == category:
            return cat
    return None


def find_sub_by_handle(tax: list, handle: str) -> tuple[dict | None, dict | None]:
    for cat in tax:
        for sub in cat.get("subcategories") or []:
            if (sub.get("handle") or "") == handle:
                return cat, sub
    return None, None


def find_node_by_handle_deep(
    tax: list, handle: str
) -> tuple[str | None, dict | None, dict | None, dict | None]:
    """
    Return (kind, category, subcategory_or_None, node) where kind is
    category | subcategory | sub_subcategory.
    """
    h = (handle or "").strip()
    if not h:
        return None, None, None, None
    for cat in tax or []:
        if (cat.get("handle") or "") == h:
            return "category", cat, None, cat
        for sub in cat.get("subcategories") or []:
            if (sub.get("handle") or "") == h:
                return "subcategory", cat, sub, sub
            for child in sub.get("children") or []:
                if (child.get("handle") or "") == h:
                    return "sub_subcategory", cat, sub, child
    return None, None, None, None


def display_name(node: dict, *, identity_key: str = "label") -> str:
    """Menu text: display_label if set, else identity field."""
    dl = (node.get("display_label") or "").strip()
    if dl:
        return dl
    return str(node.get(identity_key) or node.get("category") or "").strip()


def _pick_subcategory_key(shop: Shopify) -> str:
    primary = shop.metafield_definition("custom", "subcategory")
    if primary is None:
        raise ShopifyError("custom.subcategory definition missing")
    real_primary = [
        c for c in (primary.get("choices") or [])
        if str(c).strip().upper() != "BLANK"
    ]
    if len(real_primary) < 128:
        return "subcategory"
    overflow = shop.metafield_definition("custom", "subcategory_2")
    if overflow is None:
        raise ShopifyError(
            "custom.subcategory is full (128/128) and custom.subcategory_2 does not exist"
        )
    real = [
        c for c in (overflow.get("choices") or [])
        if str(c).strip().upper() != "BLANK"
    ]
    if len(real) >= 128:
        raise ShopifyError("custom.subcategory and subcategory_2 are both full")
    return "subcategory_2"


def ensure_sub_subcategory_definitions(shop: Shopify | None = None) -> dict:
    """Ensure primary sub_subcategory exists with smart-collection on. No BLANK."""
    shop = shop or _shop()
    primary = shop.ensure_list_choice_definition(
        "custom",
        "sub_subcategory",
        name="Sub-subcategory",
        smart_collection_condition=True,
    )
    return {"sub_subcategory": primary}


def _pick_sub_subcategory_key(shop: Shopify) -> str:
    ensure_sub_subcategory_definitions(shop)
    primary = shop.metafield_definition("custom", "sub_subcategory")
    if primary is None:
        raise ShopifyError("custom.sub_subcategory definition missing")
    if len(primary.get("choices") or []) < 128:
        return "sub_subcategory"
    overflow = shop.metafield_definition("custom", "sub_subcategory_2")
    if overflow is None:
        shop.ensure_list_choice_definition(
            "custom",
            "sub_subcategory_2",
            name="Sub-subcategory 2",
            smart_collection_condition=True,
        )
        overflow = shop.metafield_definition("custom", "sub_subcategory_2")
    if overflow is None:
        raise ShopifyError("failed to create custom.sub_subcategory_2")
    if len(overflow.get("choices") or []) >= 128:
        raise ShopifyError("custom.sub_subcategory and sub_subcategory_2 are both full")
    return "sub_subcategory_2"


def strip_subcategory_2_blank() -> dict:
    """Remove BLANK from subcategory_2; echo capability (stays false)."""
    shop = _shop()
    return shop.strip_blank_choices("custom", "subcategory_2")


def _validate_taxonomy_depth(tax_payload: list) -> None:
    """Subs only under categories; children only under subs."""
    if not isinstance(tax_payload, list):
        raise ShopifyError("taxonomy must be a list")
    for cat in tax_payload:
        if not isinstance(cat, dict):
            raise ShopifyError("invalid category node")
        if cat.get("children"):
            raise ShopifyError(
                f"category {cat.get('handle')!r} cannot have children (depth)"
            )
        for sub in cat.get("subcategories") or []:
            if not isinstance(sub, dict):
                raise ShopifyError("invalid subcategory node")
            if sub.get("subcategories"):
                raise ShopifyError(
                    f"subcategory {sub.get('handle')!r} cannot nest subcategories"
                )
            for child in sub.get("children") or []:
                if not isinstance(child, dict):
                    raise ShopifyError("invalid sub_subcategory node")
                if child.get("children") or child.get("subcategories"):
                    raise ShopifyError(
                        f"sub_subcategory {child.get('handle')!r} cannot nest further"
                    )


def _persist_tax(shop: Shopify, tax: list) -> tuple[list, str | None]:
    shop.set_shop_metafield(NAMESPACE, TAXONOMY_KEY, tax)
    again = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
    stored_raw = (again or {}).get("value") or ""
    stored = json.loads(stored_raw) if isinstance(stored_raw, str) else stored_raw
    if not isinstance(stored, list):
        stored = tax
    updated_at = (again or {}).get("updatedAt")
    bust_taxonomy_cache()
    _set_cache(stored, updated_at=updated_at, source="live")
    write_lkg_from_tax(stored, updated_at=updated_at)
    return stored, updated_at


def create_category(
    *,
    category: str,
    handle: str | None = None,
    display_label: str | None = None,
    seo_title: str | None = None,
    seo_description: str | None = None,
    expected_updated_at: str | None = None,
) -> dict:
    """Category choice + unpublished single-rule smart collection + taxonomy node."""
    shop = _shop()
    category = (category or "").strip()
    if not category:
        raise ShopifyError("category is required")
    handle = (handle or "").strip() or handleize(category)
    dl = (display_label or "").strip() or None

    with _WRITE_LOCK:
        meta = load_taxonomy_meta(force=True, require=True)
        tax = meta["taxonomy"]
        exp = expected_updated_at if expected_updated_at is not None else meta["updated_at"]
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf, exp)

        if find_category(tax, category) is not None:
            raise ShopifyError(f"category {category!r} already exists")
        kind, _, _, existing = find_node_by_handle_deep(tax, handle)
        if existing is not None:
            raise ShopifyError(f"handle {handle!r} already exists in taxonomy")
        if not shop.handle_available(handle):
            raise ShopifyError(f"handle {handle!r} is already taken")

        cat_def = shop.metafield_definition("custom", "custom_category")
        if cat_def is None:
            raise ShopifyError("custom.custom_category definition missing")

        created_collection_id = None
        try:
            shop.append_choice("custom", "custom_category", category)
            col = shop.collection_create(
                title=category,
                handle=handle,
                rules=[(cat_def["id"], category)],
                seo_title=seo_title or category,
                seo_description=seo_description or "",
                disjunctive=False,
            )
            created_collection_id = col["id"]

            mf2 = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
            _assert_expected_updated_at(mf2, exp)
            raw = (mf2 or {}).get("value") or ""
            tax = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(tax, list):
                raise ShopifyError("taxonomy metafield corrupt during create")
            next_pos = max([int(c.get("position") or 0) for c in tax] + [0]) + 1
            node = {
                "category": category,
                "handle": handle,
                "position": next_pos,
                "visible": False,
                "handle_locked": True,
                "subcategories": [],
            }
            if dl:
                node["display_label"] = dl
            tax.append(node)
            stored, updated_at = _persist_tax(shop, tax)
            try:
                from scripts.product_creator.categories import refresh_category_choice_cache

                refresh_category_choice_cache()
            except Exception:
                pass
            return {
                "success": True,
                "node": node,
                "collection_id": created_collection_id,
                "taxonomy_updated_at": updated_at,
            }
        except Exception:
            if created_collection_id:
                try:
                    shop.gql(
                        """
                      mutation($id: ID!) {
                        collectionDelete(input: {id: $id}) {
                          deletedCollectionId
                          userErrors { field message }
                        }
                      }
                    """,
                        {"id": created_collection_id},
                    )
                except Exception:
                    pass
            raise


def create_sub_subcategory(
    *,
    category: str,
    parent_label: str,
    label: str,
    handle: str | None = None,
    display_label: str | None = None,
    seo_title: str | None = None,
    seo_description: str | None = None,
    indexable: bool = True,
    expected_updated_at: str | None = None,
) -> dict:
    """Third-level node: three AND rules, unpublished collection."""
    shop = _shop()
    category = (category or "").strip()
    parent_label = (parent_label or "").strip()
    label = (label or "").strip()
    if not category or not parent_label or not label:
        raise ShopifyError("category, parent_label, and label are required")
    handle = (handle or "").strip() or handleize(f"{category}-{parent_label}-{label}")
    dl = (display_label or "").strip() or None

    with _WRITE_LOCK:
        meta = load_taxonomy_meta(force=True, require=True)
        tax = meta["taxonomy"]
        exp = expected_updated_at if expected_updated_at is not None else meta["updated_at"]
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf, exp)

        cat = find_category(tax, category)
        if cat is None:
            raise ShopifyError(f"category {category!r} not in taxonomy")
        parent = None
        for s in cat.get("subcategories") or []:
            if (s.get("label") or "") == parent_label:
                parent = s
                break
        if parent is None:
            raise ShopifyError(
                f"subcategory {parent_label!r} not under category {category!r}"
            )

        if not shop.handle_available(handle):
            raise ShopifyError(f"handle {handle!r} is already taken")
        kind, _, _, existing = find_node_by_handle_deep(tax, handle)
        if existing is not None:
            raise ShopifyError(f"handle {handle!r} already exists in taxonomy")

        cat_def = shop.metafield_definition("custom", "custom_category")
        if cat_def is None:
            raise ShopifyError("custom.custom_category definition missing")
        parent_key = parent.get("metafield_key") or "subcategory"
        parent_def = shop.metafield_definition("custom", parent_key)
        if parent_def is None:
            raise ShopifyError(f"custom.{parent_key} definition missing")

        mf_key = _pick_sub_subcategory_key(shop)
        ss_def = shop.metafield_definition("custom", mf_key)
        if ss_def is None:
            raise ShopifyError(f"custom.{mf_key} definition missing")

        created_collection_id = None
        try:
            shop.append_choice("custom", mf_key, label)
            title = f"{category} - {parent_label} - {label}"
            col = shop.collection_create(
                title=title,
                handle=handle,
                rules=[
                    (cat_def["id"], category),
                    (parent_def["id"], parent_label),
                    (ss_def["id"], label),
                ],
                seo_title=seo_title or title,
                seo_description=seo_description or "",
                disjunctive=False,
            )
            created_collection_id = col["id"]

            mf2 = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
            _assert_expected_updated_at(mf2, exp)
            raw = (mf2 or {}).get("value") or ""
            tax = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(tax, list):
                raise ShopifyError("taxonomy metafield corrupt during create")
            cat = find_category(tax, category)
            parent = None
            for s in cat.get("subcategories") or []:
                if (s.get("label") or "") == parent_label:
                    parent = s
                    break
            if parent is None:
                raise ShopifyError("parent subcategory disappeared during create")
            children = list(parent.get("children") or [])
            next_pos = max([int(c.get("position") or 0) for c in children] + [0]) + 1
            node = {
                "label": label,
                "handle": handle,
                "position": next_pos,
                "indexable": bool(indexable),
                "metafield_key": mf_key,
                "visible": False,
                "handle_locked": True,
            }
            if dl:
                node["display_label"] = dl
            children.append(node)
            parent["children"] = children
            stored, updated_at = _persist_tax(shop, tax)
            return {
                "success": True,
                "node": node,
                "collection_id": created_collection_id,
                "metafield_key": mf_key,
                "taxonomy_updated_at": updated_at,
            }
        except Exception:
            if created_collection_id:
                try:
                    shop.gql(
                        """
                      mutation($id: ID!) {
                        collectionDelete(input: {id: $id}) {
                          deletedCollectionId
                          userErrors { field message }
                        }
                      }
                    """,
                        {"id": created_collection_id},
                    )
                except Exception:
                    pass
            raise


def create_subcategory(
    *,
    category: str,
    label: str,
    handle: str | None = None,
    display_label: str | None = None,
    seo_title: str | None = None,
    seo_description: str | None = None,
    indexable: bool = True,
    expected_updated_at: str | None = None,
) -> dict:
    """
    Create flow (ordered). Rolls back on failure.
    Delete of brand-new collection is allowed only here.
    """
    shop = _shop()
    label = (label or "").strip()
    category = (category or "").strip()
    if not label or not category:
        raise ShopifyError("category and label are required")

    handle = (handle or "").strip() or handleize(f"{category}-{label}")
    dl = (display_label or "").strip() or None

    with _WRITE_LOCK:
        meta = load_taxonomy_meta(force=True, require=True)
        tax = meta["taxonomy"]
        current_at = meta["updated_at"]
        # If client omitted expected, use what we just read (same lock).
        exp = expected_updated_at if expected_updated_at is not None else current_at
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf, exp)

        cat = find_category(tax, category)
        if cat is None:
            raise ShopifyError(f"category {category!r} not in taxonomy")

        if not shop.handle_available(handle):
            raise ShopifyError(f"handle {handle!r} is already taken")
        kind, _, _, existing = find_node_by_handle_deep(tax, handle)
        if existing is not None:
            raise ShopifyError(f"handle {handle!r} already exists in taxonomy")

        cat_def = shop.metafield_definition("custom", "custom_category")
        if cat_def is None:
            raise ShopifyError("custom.custom_category definition missing")

        mf_key = _pick_subcategory_key(shop)
        sub_def = shop.metafield_definition("custom", mf_key)
        if sub_def is None:
            raise ShopifyError(f"custom.{mf_key} definition missing")

        created_choice = False
        created_collection_id = None
        try:
            choice_result = shop.append_choice("custom", mf_key, label)
            created_choice = bool(choice_result.get("added"))

            title = f"{category} - {label}"
            col = shop.collection_create(
                title=title,
                handle=handle,
                rules=[
                    (cat_def["id"], category),
                    (sub_def["id"], label),
                ],
                seo_title=seo_title or title,
                seo_description=seo_description or "",
                disjunctive=False,
            )
            created_collection_id = col["id"]

            # Re-read taxonomy under lock before patching
            mf2 = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
            _assert_expected_updated_at(mf2, exp)
            raw = (mf2 or {}).get("value") or ""
            tax = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(tax, list):
                raise ShopifyError("taxonomy metafield corrupt during create")
            cat = find_category(tax, category)
            if cat is None:
                raise ShopifyError(f"category {category!r} disappeared from taxonomy")
            subs = list(cat.get("subcategories") or [])
            next_pos = max([int(s.get("position") or 0) for s in subs] + [0]) + 1
            node = {
                "label": label,
                "handle": handle,
                "position": next_pos,
                "indexable": bool(indexable),
                "metafield_key": mf_key,
                "visible": False,
                "handle_locked": True,
                "children": [],
            }
            if dl:
                node["display_label"] = dl
            subs.append(node)
            cat["subcategories"] = subs

            stored, updated_at = _persist_tax(shop, tax)

            try:
                from scripts.product_creator.categories import refresh_category_choice_cache

                refresh_category_choice_cache()
            except Exception:
                pass

            return {
                "success": True,
                "node": node,
                "collection_id": created_collection_id,
                "choice_added": created_choice,
                "metafield_key": mf_key,
                "taxonomy_updated_at": updated_at,
                "cache_note": "Choice cache refreshed on this worker; restart other workers if stale.",
            }
        except Exception:
            if created_collection_id:
                try:
                    shop.gql(
                        """
                      mutation($id: ID!) {
                        collectionDelete(input: {id: $id}) {
                          deletedCollectionId
                          userErrors { field message }
                        }
                      }
                    """,
                        {"id": created_collection_id},
                    )
                except Exception:
                    pass
            raise


def _node_identity(kind: str, node: dict) -> str:
    if kind == "category":
        return str(node.get("category") or "").strip()
    return str(node.get("label") or "").strip()


def _node_mf_key(kind: str, node: dict) -> str:
    if kind == "category":
        return "custom_category"
    if kind == "subcategory":
        return node.get("metafield_key") or "subcategory"
    return node.get("metafield_key") or "sub_subcategory"


def _replace_choice_value(shop: Shopify, mf_key: str, old: str, new: str) -> dict:
    """Expand (append new if needed) then drop old from the choices list."""
    definition = shop.metafield_definition("custom", mf_key)
    if definition is None:
        raise ShopifyError(f"custom.{mf_key} definition missing")
    choices = [str(c) for c in (definition.get("choices") or [])]
    old_s = str(old).strip()
    new_s = str(new).strip()
    if new_s not in choices:
        shop.append_choice("custom", mf_key, new_s)
        definition = shop.metafield_definition("custom", mf_key)
        choices = [str(c) for c in (definition.get("choices") or [])]
    if old_s in choices and old_s != new_s:
        choices = [c for c in choices if c != old_s]
        shop.set_definition_choices("custom", mf_key, choices)
    return {"choices_count": len(choices), "metafield_key": mf_key}


def _rules_input_from_detail(detail: dict, *, replace: dict[str, str] | None = None) -> list:
    """
    Build CollectionRuleInput list from collection_detail.
    replace: map of metafield key -> new condition string (e.g. subcategory label).
    """
    replace = replace or {}
    rule_set = (detail or {}).get("ruleSet") or {}
    out = []
    for rule in rule_set.get("rules") or []:
        cond_obj = rule.get("conditionObject") or {}
        mf = cond_obj.get("metafieldDefinition") or {}
        key = mf.get("key") or ""
        def_id = mf.get("id")
        condition = rule.get("condition") or ""
        if key in replace:
            condition = replace[key]
        entry = {
            "column": rule.get("column") or "PRODUCT_METAFIELD_DEFINITION",
            "relation": rule.get("relation") or "EQUALS",
            "condition": condition,
        }
        if def_id:
            entry["conditionObjectId"] = def_id
        out.append(entry)
    return out


def _cascade_child_middle_rules(
    shop: Shopify,
    children: list,
    *,
    parent_mf_key: str,
    old_label: str,
    new_label: str,
    log: list,
) -> None:
    """Rewrite middle (parent subcategory) condition on every child sub-sub collection."""
    for child in children or []:
        ch = (child.get("handle") or "").strip()
        if not ch:
            continue
        col = shop.collection_by_handle(ch)
        if not col:
            log.append({"action": "cascade_missing_collection", "handle": ch})
            continue
        detail = shop.collection_detail(col["id"])
        if not detail:
            log.append({"action": "cascade_no_detail", "handle": ch})
            continue
        rules = _rules_input_from_detail(
            detail, replace={parent_mf_key: new_label}
        )
        applied = bool((detail.get("ruleSet") or {}).get("appliedDisjunctively"))
        shop.set_collection_rules(
            col["id"], applied_disjunctive=applied, rules_input=rules
        )
        # Keep derived title in sync when it embeds the old middle label.
        title = detail.get("title") or ""
        if old_label and old_label in title:
            new_title = title.replace(old_label, new_label, 1)
            shop.collection_update(col["id"], title=new_title)
        log.append(
            {
                "action": "cascade_middle_rule",
                "handle": ch,
                "old": old_label,
                "new": new_label,
                "parent_mf_key": parent_mf_key,
            }
        )


def preview_rename_choice(
    handle: str,
    new_value: str,
    *,
    product_cap: int = 50,
) -> dict:
    """
    Preview identity rename (category/label). Does not mutate.
    Includes cascading child sub-sub collections when renaming a subcategory.
    """
    shop = _shop()
    handle = (handle or "").strip()
    new_value = (new_value or "").strip()
    if not handle or not new_value:
        raise ShopifyError("handle and new_value are required")

    meta = load_taxonomy_meta(force=True, require=True)
    tax = meta["taxonomy"]
    kind, cat, sub, node = find_node_by_handle_deep(tax, handle)
    if node is None or kind is None:
        raise ShopifyError(f"unknown handle {handle!r}")

    old_value = _node_identity(kind, node)
    if not old_value:
        raise ShopifyError("node has empty identity")
    if old_value == new_value:
        raise ShopifyError("new_value equals current identity")

    mf_key = _node_mf_key(kind, node)
    products = shop.products_with_choice_value(
        "custom", mf_key, old_value, limit=max(product_cap, 500)
    )
    total = len(products)
    preview_products = [
        {"id": p["id"], "title": p["title"]} for p in products[:product_cap]
    ]

    col = shop.collection_by_handle(handle)
    collection_info = None
    if col:
        detail = shop.collection_detail(col["id"])
        collection_info = {
            "id": col["id"],
            "handle": handle,
            "title": (detail or {}).get("title"),
            "rules": ((detail or {}).get("ruleSet") or {}).get("rules") or [],
        }

    cascading = []
    if kind == "subcategory":
        for child in node.get("children") or []:
            cascading.append(
                {
                    "handle": child.get("handle"),
                    "label": child.get("label"),
                    "middle_rule_old": old_value,
                    "middle_rule_new": new_value,
                    "parent_mf_key": mf_key,
                }
            )
    elif kind == "category":
        for s in node.get("subcategories") or []:
            cascading.append(
                {
                    "handle": s.get("handle"),
                    "label": s.get("label"),
                    "rule_key": "custom_category",
                    "old": old_value,
                    "new": new_value,
                }
            )
            for child in s.get("children") or []:
                cascading.append(
                    {
                        "handle": child.get("handle"),
                        "label": child.get("label"),
                        "rule_key": "custom_category",
                        "old": old_value,
                        "new": new_value,
                    }
                )

    return {
        "success": True,
        "handle": handle,
        "kind": kind,
        "old_value": old_value,
        "new_value": new_value,
        "metafield_key": mf_key,
        "product_total": total,
        "product_cap": product_cap,
        "products_truncated": total > product_cap,
        "products": preview_products,
        "collection": collection_info,
        "cascading_collections": cascading,
        "requires_explicit_apply": total > 0,
        "taxonomy_updated_at": meta.get("updated_at"),
    }


def apply_rename_choice(
    handle: str,
    new_value: str,
    *,
    expected_updated_at: str | None = None,
    confirm: bool = False,
) -> dict:
    """
    Identity rename: expand choice → migrate products → update this node's rule →
    cascade middle conditions on child sub-subs → remove old choice → taxonomy.
    """
    shop = _shop()
    handle = (handle or "").strip()
    new_value = (new_value or "").strip()
    if not handle or not new_value:
        raise ShopifyError("handle and new_value are required")

    log: list[dict] = []
    with _WRITE_LOCK:
        meta = load_taxonomy_meta(force=True, require=True)
        tax = meta["taxonomy"]
        exp = expected_updated_at if expected_updated_at is not None else meta["updated_at"]
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf, exp)

        kind, cat, sub, node = find_node_by_handle_deep(tax, handle)
        if node is None or kind is None:
            raise ShopifyError(f"unknown handle {handle!r}")

        old_value = _node_identity(kind, node)
        if not old_value:
            raise ShopifyError("node has empty identity")
        if old_value == new_value:
            raise ShopifyError("new_value equals current identity")

        mf_key = _node_mf_key(kind, node)
        products = shop.products_with_choice_value(
            "custom", mf_key, old_value, limit=5000
        )
        if products and not confirm:
            raise ShopifyError(
                f"{len(products)} product(s) use {old_value!r}; "
                "pass confirm=true after preview"
            )

        # Snapshot for best-effort rollback notes
        col = shop.collection_by_handle(handle)
        if not col:
            raise ShopifyError(f"collection not found for handle {handle!r}")
        detail_before = shop.collection_detail(col["id"])

        try:
            # 1) Expand: ensure new choice exists
            shop.append_choice("custom", mf_key, new_value)
            log.append({"action": "append_choice", "key": mf_key, "value": new_value})

            # 2) Migrate products
            for p in products:
                vals = list(p.get("all_values") or [])
                vals = [new_value if v == old_value else v for v in vals]
                # de-dupe preserve order
                seen = set()
                cleaned = []
                for v in vals:
                    if v in seen:
                        continue
                    seen.add(v)
                    cleaned.append(v)
                shop.set_product_metafield_list(
                    p["id"], "custom", mf_key, cleaned, p.get("mf_type")
                )
                log.append(
                    {
                        "action": "migrate_product",
                        "product_id": p["id"],
                        "old": old_value,
                        "new": new_value,
                    }
                )

            # 3) Update this node's collection rule + derived title
            detail = shop.collection_detail(col["id"]) or detail_before
            rules = _rules_input_from_detail(detail, replace={mf_key: new_value})
            applied = bool((detail.get("ruleSet") or {}).get("appliedDisjunctively"))
            shop.set_collection_rules(
                col["id"], applied_disjunctive=applied, rules_input=rules
            )
            log.append(
                {
                    "action": "update_collection_rule",
                    "handle": handle,
                    "old": old_value,
                    "new": new_value,
                }
            )
            title = (detail or {}).get("title") or ""
            if old_value and old_value in title:
                shop.collection_update(
                    col["id"], title=title.replace(old_value, new_value, 1)
                )
                log.append({"action": "update_collection_title", "handle": handle})

            # 4) Cascade: subcategory → child middle rules; category → all
            # descendant collection rules that still store the old category.
            if kind == "subcategory":
                _cascade_child_middle_rules(
                    shop,
                    node.get("children") or [],
                    parent_mf_key=mf_key,
                    old_label=old_value,
                    new_label=new_value,
                    log=log,
                )
            elif kind == "category":
                descendants = []
                for s in node.get("subcategories") or []:
                    descendants.append(s)
                    descendants.extend(s.get("children") or [])
                for dnode in descendants:
                    dh = (dnode.get("handle") or "").strip()
                    if not dh:
                        continue
                    dcol = shop.collection_by_handle(dh)
                    if not dcol:
                        log.append(
                            {"action": "cascade_missing_collection", "handle": dh}
                        )
                        continue
                    ddetail = shop.collection_detail(dcol["id"])
                    if not ddetail:
                        continue
                    drules = _rules_input_from_detail(
                        ddetail, replace={"custom_category": new_value}
                    )
                    dapplied = bool(
                        (ddetail.get("ruleSet") or {}).get("appliedDisjunctively")
                    )
                    shop.set_collection_rules(
                        dcol["id"],
                        applied_disjunctive=dapplied,
                        rules_input=drules,
                    )
                    dtitle = ddetail.get("title") or ""
                    if old_value and old_value in dtitle:
                        shop.collection_update(
                            dcol["id"],
                            title=dtitle.replace(old_value, new_value, 1),
                        )
                    log.append(
                        {
                            "action": "cascade_category_rule",
                            "handle": dh,
                            "old": old_value,
                            "new": new_value,
                        }
                    )

            # 5) Remove old choice
            definition = shop.metafield_definition("custom", mf_key)
            choices = [
                str(c)
                for c in (definition.get("choices") or [])
                if str(c) != old_value
            ]
            shop.set_definition_choices("custom", mf_key, choices)
            log.append(
                {"action": "remove_old_choice", "key": mf_key, "value": old_value}
            )

            # 6) Taxonomy identity
            mf2 = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
            _assert_expected_updated_at(mf2, exp)
            raw = (mf2 or {}).get("value") or ""
            tax = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(tax, list):
                raise ShopifyError("taxonomy metafield corrupt during rename")
            kind2, _, _, node2 = find_node_by_handle_deep(tax, handle)
            if node2 is None:
                raise ShopifyError("node disappeared during rename")
            if kind2 == "category":
                node2["category"] = new_value
            else:
                node2["label"] = new_value
            stored, updated_at = _persist_tax(shop, tax)
            log.append({"action": "taxonomy_identity", "handle": handle})

            try:
                from scripts.product_creator.categories import refresh_category_choice_cache

                refresh_category_choice_cache()
            except Exception:
                pass

            return {
                "success": True,
                "handle": handle,
                "kind": kind,
                "old_value": old_value,
                "new_value": new_value,
                "products_migrated": len(products),
                "log": log,
                "taxonomy_updated_at": updated_at,
            }
        except Exception as exc:
            log.append({"action": "error", "error": str(exc)})
            # Best-effort: do not leave taxonomy half-written; collection/product
            # mutations may already have applied — operator should inspect log.
            raise ShopifyError(
                f"apply_rename_choice failed: {exc}; log={json.dumps(log)[:2000]}"
            ) from exc


def update_node_metadata(
    handle: str,
    *,
    display_label: str | None = None,
    clear_display_label: bool = False,
    collection_title: str | None = None,
    description_html: str | None = None,
    seo_title: str | None = None,
    seo_description: str | None = None,
    indexable: bool | None = None,
    expected_updated_at: str | None = None,
) -> dict:
    """
    Collection SEO/title/description via collection_update.
    Taxonomy only: display_label (+ optional indexable). No SEO on taxonomy nodes.
    """
    shop = _shop()
    handle = (handle or "").strip()
    if not handle:
        raise ShopifyError("handle is required")

    with _WRITE_LOCK:
        meta = load_taxonomy_meta(force=True, require=True)
        tax = meta["taxonomy"]
        exp = expected_updated_at if expected_updated_at is not None else meta["updated_at"]
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf, exp)

        kind, _, _, node = find_node_by_handle_deep(tax, handle)
        if node is None:
            raise ShopifyError(f"unknown handle {handle!r}")

        col = shop.collection_by_handle(handle)
        collection_out = None
        if col and any(
            x is not None
            for x in (
                collection_title,
                description_html,
                seo_title,
                seo_description,
            )
        ):
            collection_out = shop.collection_update(
                col["id"],
                title=collection_title,
                description_html=description_html,
                seo_title=seo_title,
                seo_description=seo_description,
            )

        # Re-read for RMW
        mf2 = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf2, exp)
        raw = (mf2 or {}).get("value") or ""
        tax = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(tax, list):
            raise ShopifyError("taxonomy metafield corrupt")
        kind, _, _, node = find_node_by_handle_deep(tax, handle)
        if node is None:
            raise ShopifyError(f"unknown handle {handle!r}")

        if clear_display_label:
            node.pop("display_label", None)
        elif display_label is not None:
            dl = str(display_label).strip()
            if dl:
                node["display_label"] = dl
            else:
                node.pop("display_label", None)
        if indexable is not None and kind in ("subcategory", "sub_subcategory"):
            node["indexable"] = bool(indexable)

        stored, updated_at = _persist_tax(shop, tax)
        detail = None
        if col:
            detail = shop.collection_detail(col["id"])
        return {
            "success": True,
            "handle": handle,
            "kind": kind,
            "node": node,
            "collection": detail or collection_out,
            "taxonomy_updated_at": updated_at,
        }


def rename_handle(
    handle: str,
    new_handle: str,
    *,
    expected_updated_at: str | None = None,
) -> dict:
    """
    Unlock → redirect /collections/old → /collections/new → update collection +
    taxonomy handle → re-lock. Never derived from display_label.
    """
    shop = _shop()
    handle = (handle or "").strip()
    new_handle = (new_handle or "").strip()
    if not handle or not new_handle:
        raise ShopifyError("handle and new_handle are required")
    if handle == new_handle:
        raise ShopifyError("new_handle equals current handle")
    if handleize(new_handle) != new_handle:
        raise ShopifyError("new_handle must be a valid handle (lowercase, hyphens)")

    with _WRITE_LOCK:
        meta = load_taxonomy_meta(force=True, require=True)
        tax = meta["taxonomy"]
        exp = expected_updated_at if expected_updated_at is not None else meta["updated_at"]
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf, exp)

        kind, _, _, node = find_node_by_handle_deep(tax, handle)
        if node is None:
            raise ShopifyError(f"unknown handle {handle!r}")
        conflict = find_node_by_handle_deep(tax, new_handle)[3]
        if conflict is not None:
            raise ShopifyError(f"handle {new_handle!r} already exists in taxonomy")
        if not shop.handle_available(new_handle):
            raise ShopifyError(f"handle {new_handle!r} is already taken in Shopify")

        col = shop.collection_by_handle(handle)
        if not col:
            raise ShopifyError(f"collection not found for handle {handle!r}")

        # Temporary unlock in taxonomy for the write
        node["handle_locked"] = False
        shop.create_redirect(f"/collections/{handle}", f"/collections/{new_handle}")
        shop.collection_update(col["id"], handle=new_handle)

        mf2 = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf2, exp)
        raw = (mf2 or {}).get("value") or ""
        tax = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(tax, list):
            raise ShopifyError("taxonomy metafield corrupt")
        kind, _, _, node = find_node_by_handle_deep(tax, handle)
        if node is None:
            raise ShopifyError("node disappeared during handle rename")
        node["handle"] = new_handle
        node["handle_locked"] = True
        stored, updated_at = _persist_tax(shop, tax)
        return {
            "success": True,
            "kind": kind,
            "old_handle": handle,
            "new_handle": new_handle,
            "redirect": f"/collections/{handle} → /collections/{new_handle}",
            "taxonomy_updated_at": updated_at,
        }


def get_node_metadata(handle: str) -> dict:
    """Read taxonomy node + collection SEO for the metadata panel."""
    shop = _shop()
    handle = (handle or "").strip()
    if not handle:
        raise ShopifyError("handle is required")
    meta = load_taxonomy_meta(force=False, require=True)
    tax = meta["taxonomy"]
    kind, cat, sub, node = find_node_by_handle_deep(tax, handle)
    if node is None:
        raise ShopifyError(f"unknown handle {handle!r}")
    col = shop.collection_by_handle(handle)
    detail = shop.collection_detail(col["id"]) if col else None
    return {
        "success": True,
        "handle": handle,
        "kind": kind,
        "node": node,
        "parent_category": (cat or {}).get("category") if cat else None,
        "parent_subcategory": (sub or {}).get("label") if sub and kind == "sub_subcategory" else None,
        "collection": detail,
        "taxonomy_updated_at": meta.get("updated_at"),
    }


def publish_now(handle: str, *, expected_updated_at: str | None = None) -> dict:
    """
    Publish collection + set visible=True when it has Online-Store-published products
    and indexable is true. Never publishes indexable=false nodes.
    """
    result = reconcile_handle(
        handle, write=True, expected_updated_at=expected_updated_at
    )
    action = result.get("action")
    if action in ("missing_collection", "unknown_handle"):
        raise ShopifyError(f"cannot publish: {action} for {handle!r}")
    if not result.get("indexable", True) or action == "skipped_non_indexable":
        raise ShopifyError("cannot publish a non-indexable node (deliberate menu exclusion)")
    if int(result.get("count") or 0) <= 0 or action == "unpublished":
        raise ShopifyError(
            "collection has 0 Online-Store-published products - leave unpublished / visible=false"
        )
    if action not in ("published", "noop"):
        raise ShopifyError(f"publish_now unexpected action: {action}")
    return {
        "success": True,
        "handle": handle,
        "products": result.get("count"),
        "visible": True,
        "indexable": result.get("indexable", True),
        "taxonomy_updated_at": result.get("taxonomy_updated_at"),
        "action": action,
    }


def reorder_and_patch(
    tax_payload: list,
    *,
    expected_updated_at: str | None = None,
) -> dict:
    """Replace taxonomy with editor payload. Handles stay locked. Depth validated."""
    _validate_taxonomy_depth(tax_payload)
    with _WRITE_LOCK:
        meta = load_taxonomy_meta(force=True, require=True)
        current = meta["taxonomy"]
        exp = expected_updated_at if expected_updated_at is not None else meta["updated_at"]
        shop = _shop()
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf, exp)

        by_handle = {}
        for cat in current:
            by_handle[cat.get("handle")] = cat
            for sub in cat.get("subcategories") or []:
                by_handle[sub.get("handle")] = sub
                for child in sub.get("children") or []:
                    by_handle[child.get("handle")] = child

        for cat in tax_payload:
            ch = cat.get("handle")
            old = by_handle.get(ch)
            if old and is_handle_locked(old) and (old.get("handle") != cat.get("handle")):
                raise ShopifyError(f"handle locked: {old.get('handle')}")
            for sub in cat.get("subcategories") or []:
                sh = sub.get("handle")
                osub = by_handle.get(sh)
                if osub and is_handle_locked(osub) and osub.get("handle") != sh:
                    raise ShopifyError(f"handle locked: {osub.get('handle')}")
                if osub:
                    sub.setdefault("metafield_key", osub.get("metafield_key") or "subcategory")
                    sub.setdefault("handle_locked", osub.get("handle_locked", True))
                    sub.setdefault("visible", osub.get("visible", False))
                    if "display_label" not in sub and osub.get("display_label"):
                        sub["display_label"] = osub.get("display_label")
                children = []
                for child in sub.get("children") or []:
                    chh = child.get("handle")
                    och = by_handle.get(chh)
                    if och and is_handle_locked(och) and och.get("handle") != chh:
                        raise ShopifyError(f"handle locked: {och.get('handle')}")
                    if och:
                        child.setdefault(
                            "metafield_key",
                            och.get("metafield_key") or "sub_subcategory",
                        )
                        child.setdefault("handle_locked", och.get("handle_locked", True))
                        child.setdefault("visible", och.get("visible", False))
                        if "display_label" not in child and och.get("display_label"):
                            child["display_label"] = och.get("display_label")
                    children.append(child)
                sub["children"] = children
            if old:
                cat.setdefault("handle_locked", old.get("handle_locked", True))
                cat.setdefault("visible", old.get("visible", False))
                if "display_label" not in cat and old.get("display_label"):
                    cat["display_label"] = old.get("display_label")

        stored, updated_at = _persist_tax(shop, tax_payload)
        return {
            "success": True,
            "count": _count_nodes(stored),
            "taxonomy_updated_at": updated_at,
        }


# ---------------------------------------------------------------------------
# Phase 7 — publish / visible reconcile
# ---------------------------------------------------------------------------

UNPUBLISH_CIRCUIT_RATIO = 0.20


class VisibilityCircuitBreaker(ShopifyError):
    """Abort write reconcile when planned unpublishes exceed the safety threshold."""

    def __init__(self, message: str, *, report: dict | None = None):
        super().__init__(message)
        self.report = report or {}


def iter_taxonomy_nodes(tax: list):
    """Yield (kind, parent_category_or_None, node) for every handle-bearing node."""
    for cat in tax or []:
        if cat.get("handle"):
            yield "category", None, cat
        for sub in cat.get("subcategories") or []:
            if sub.get("handle"):
                yield "subcategory", cat, sub
            for child in sub.get("children") or []:
                if child.get("handle"):
                    yield "sub_subcategory", cat, child


def find_node_by_handle(tax: list, handle: str) -> tuple[str | None, dict | None, dict | None]:
    """Return (kind, parent_category_or_None, node) or (None, None, None)."""
    h = (handle or "").strip()
    if not h:
        return None, None, None
    for kind, parent, node in iter_taxonomy_nodes(tax):
        if (node.get("handle") or "") == h:
            return kind, parent, node
    return None, None, None


def apply_visibility_rule(
    node: dict,
    published_count: int,
    *,
    is_published: bool,
) -> dict:
    """
    Decide publish/visible action for one taxonomy node.

    Returns dict with handle, count, indexable, visible (current), is_published,
    desired_visible, desired_published, action, taxonomy_dirty.
    """
    handle = (node.get("handle") or "").strip()
    indexable = bool(node.get("indexable", True))
    visible = bool(node.get("visible", False))
    count = int(published_count or 0)
    published = bool(is_published)

    desired_published = False
    desired_visible = False
    action = "noop"

    if not indexable:
        # Never publish; unpublish if currently on Online Store; visible always false.
        desired_published = False
        desired_visible = False
        if published or visible:
            action = "skipped_non_indexable"
        else:
            action = "noop"
    elif count > 0:
        desired_published = True
        desired_visible = True
        if (not published) or (not visible):
            action = "published"
        else:
            action = "noop"
    else:
        desired_published = False
        desired_visible = False
        if published or visible:
            action = "unpublished"
        else:
            action = "noop"

    taxonomy_dirty = visible != desired_visible
    will_unpublish = published and (not desired_published)

    return {
        "handle": handle,
        "count": count,
        "indexable": indexable,
        "visible": visible,
        "is_published": published,
        "desired_visible": desired_visible,
        "desired_published": desired_published,
        "action": action,
        "taxonomy_dirty": taxonomy_dirty,
        "will_unpublish": will_unpublish,
        "will_publish": (not published) and desired_published,
    }


def _empty_reconcile_report(*, write: bool, force: bool) -> dict:
    return {
        "success": True,
        "write": bool(write),
        "force": bool(force),
        "circuit_breaker_tripped": False,
        "taxonomy_written": False,
        "taxonomy_updated_at": None,
        "rows": [],
        "counts": {
            "nodes": 0,
            "published_now": 0,
            "published": 0,
            "unpublished": 0,
            "noop": 0,
            "skipped_non_indexable": 0,
            "missing_collection": 0,
            "errors": 0,
        },
        "error": None,
    }


def _plan_node_actions(tax: list, shop: Shopify) -> tuple[list[dict], list[str]]:
    """Build per-node plans. Returns (rows, hard_errors)."""
    rows: list[dict] = []
    errors: list[str] = []
    for kind, _parent, node in iter_taxonomy_nodes(tax):
        handle = (node.get("handle") or "").strip()
        if not handle:
            continue
        try:
            col = shop.collection_by_handle(handle)
            if col is None:
                row = {
                    "handle": handle,
                    "kind": kind,
                    "count": 0,
                    "indexable": bool(node.get("indexable", True)),
                    "visible": bool(node.get("visible", False)),
                    "is_published": False,
                    "desired_visible": bool(node.get("visible", False)),
                    "desired_published": False,
                    "action": "missing_collection",
                    "taxonomy_dirty": False,
                    "will_unpublish": False,
                    "will_publish": False,
                }
                rows.append(row)
                continue
            count = shop.published_product_count(col["id"])
            is_pub = bool(col.get("publishedOnPublication"))
            decision = apply_visibility_rule(node, count, is_published=is_pub)
            decision["kind"] = kind
            decision["collection_id"] = col["id"]
            rows.append(decision)
        except Exception as e:
            errors.append(f"{handle}: {e}")
            rows.append(
                {
                    "handle": handle,
                    "kind": kind,
                    "count": 0,
                    "indexable": bool(node.get("indexable", True)),
                    "visible": bool(node.get("visible", False)),
                    "is_published": False,
                    "action": "error",
                    "error": str(e),
                    "taxonomy_dirty": False,
                    "will_unpublish": False,
                    "will_publish": False,
                }
            )
    return rows, errors


def _summarize_rows(rows: list[dict]) -> dict:
    counts = {
        "nodes": len(rows),
        "published_now": sum(1 for r in rows if r.get("is_published")),
        "published": 0,
        "unpublished": 0,
        "noop": 0,
        "skipped_non_indexable": 0,
        "missing_collection": 0,
        "errors": 0,
    }
    for r in rows:
        a = r.get("action")
        if a in counts:
            counts[a] += 1
        elif a == "error":
            counts["errors"] += 1
    return counts


def reconcile_visibility(
    *,
    write: bool = False,
    force: bool = False,
    expected_updated_at: str | None = None,
) -> dict:
    """
    Walk all taxonomy handles and align Online Store publish + visible flags.

    Dry-run by default (write=False). Circuit breaker: when write and not force,
    abort if planned Online-Store unpublishes exceed 20% of currently-published
    taxonomy nodes (no mutations, no taxonomy write).
    """
    shop = _shop()
    report = _empty_reconcile_report(write=write, force=force)

    def _run_locked() -> dict:
        meta = load_taxonomy_meta(force=True, require=True)
        tax = meta["taxonomy"]
        exp = expected_updated_at if expected_updated_at is not None else meta["updated_at"]
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        if write:
            _assert_expected_updated_at(mf, exp)

        rows, hard_errors = _plan_node_actions(tax, shop)
        report["rows"] = rows
        report["counts"] = _summarize_rows(rows)
        if hard_errors:
            report["success"] = False
            report["error"] = "; ".join(hard_errors[:5])
            if len(hard_errors) > 5:
                report["error"] += f" (+{len(hard_errors) - 5} more)"
            return report

        published_now = report["counts"]["published_now"]
        planned_unpublish = sum(1 for r in rows if r.get("will_unpublish"))
        if (
            write
            and not force
            and published_now > 0
            and planned_unpublish > published_now * UNPUBLISH_CIRCUIT_RATIO
        ):
            msg = (
                f"[error] visibility circuit breaker: planned unpublish {planned_unpublish} "
                f"of {published_now} currently published "
                f"(>{UNPUBLISH_CIRCUIT_RATIO:.0%}); aborting with no mutations"
            )
            print(msg, flush=True)
            report["success"] = False
            report["circuit_breaker_tripped"] = True
            report["error"] = msg
            raise VisibilityCircuitBreaker(msg, report=report)

        if not write:
            report["taxonomy_updated_at"] = meta.get("updated_at")
            return report

        # Apply Online Store publish/unpublish first
        for r in rows:
            action = r.get("action")
            cid = r.get("collection_id")
            if not cid:
                continue
            if action == "published" and r.get("will_publish"):
                shop.set_published(cid, True)
            elif action in ("unpublished", "skipped_non_indexable") and r.get("will_unpublish"):
                shop.set_published(cid, False)

        # Patch taxonomy visible flags only when dirty
        dirty_handles = {
            r["handle"]: bool(r.get("desired_visible"))
            for r in rows
            if r.get("taxonomy_dirty") and r.get("handle")
        }
        if not dirty_handles:
            report["taxonomy_written"] = False
            report["taxonomy_updated_at"] = meta.get("updated_at")
            return report

        mf2 = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf2, exp)
        raw = (mf2 or {}).get("value") or ""
        tax2 = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(tax2, list):
            raise ShopifyError("taxonomy metafield corrupt during reconcile")

        changed = False
        for _kind, _parent, node in iter_taxonomy_nodes(tax2):
            h = node.get("handle")
            if h in dirty_handles:
                new_vis = dirty_handles[h]
                if bool(node.get("visible", False)) != new_vis:
                    node["visible"] = new_vis
                    changed = True

        if not changed:
            report["taxonomy_written"] = False
            report["taxonomy_updated_at"] = (mf2 or {}).get("updatedAt")
            return report

        shop.set_shop_metafield(NAMESPACE, TAXONOMY_KEY, tax2)
        again = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        stored_raw = (again or {}).get("value") or ""
        stored = json.loads(stored_raw) if isinstance(stored_raw, str) else stored_raw
        if not isinstance(stored, list):
            stored = tax2
        updated_at = (again or {}).get("updatedAt")
        bust_taxonomy_cache()
        _set_cache(stored, updated_at=updated_at, source="live")
        write_lkg_from_tax(stored, updated_at=updated_at)
        report["taxonomy_written"] = True
        report["taxonomy_updated_at"] = updated_at
        return report

    if write:
        with _WRITE_LOCK:
            return _run_locked()
    return _run_locked()


def reconcile_handle(
    handle: str,
    *,
    write: bool = False,
    expected_updated_at: str | None = None,
) -> dict:
    """
    Single-node reconcile for webhooks / publish_now.

    If the action is noop, returns without taxonomy RMW (no lock write).
    """
    handle = (handle or "").strip()
    if not handle:
        raise ShopifyError("handle is required")

    shop = _shop()
    col = shop.collection_by_handle(handle)
    if col is None:
        return {
            "success": True,
            "handle": handle,
            "action": "missing_collection",
            "count": 0,
            "indexable": None,
            "visible": None,
            "taxonomy_updated_at": None,
            "taxonomy_written": False,
        }

    count = shop.published_product_count(col["id"])
    is_pub = bool(col.get("publishedOnPublication"))

    # Cached taxonomy read is enough to decide noop and avoid lock storms.
    meta = load_taxonomy_meta(force=False, require=True)
    kind, _parent, node = find_node_by_handle(meta["taxonomy"], handle)
    if node is None:
        return {
            "success": True,
            "handle": handle,
            "action": "unknown_handle",
            "count": count,
            "indexable": None,
            "visible": None,
            "is_published": is_pub,
            "taxonomy_updated_at": meta.get("updated_at"),
            "taxonomy_written": False,
        }

    decision = apply_visibility_rule(node, count, is_published=is_pub)
    decision["success"] = True
    decision["kind"] = kind
    decision["collection_id"] = col["id"]
    decision["taxonomy_written"] = False
    decision["taxonomy_updated_at"] = meta.get("updated_at")

    if decision["action"] == "noop" or not write:
        return decision

    with _WRITE_LOCK:
        meta2 = load_taxonomy_meta(force=True, require=True)
        exp = expected_updated_at if expected_updated_at is not None else meta2["updated_at"]
        mf = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf, exp)

        kind2, _p2, node2 = find_node_by_handle(meta2["taxonomy"], handle)
        if node2 is None:
            decision["action"] = "unknown_handle"
            return decision

        # Re-fetch live publish state under lock
        col2 = shop.collection_by_handle(handle)
        if col2 is None:
            decision["action"] = "missing_collection"
            return decision
        count2 = shop.published_product_count(col2["id"])
        is_pub2 = bool(col2.get("publishedOnPublication"))
        decision = apply_visibility_rule(node2, count2, is_published=is_pub2)
        decision["success"] = True
        decision["kind"] = kind2
        decision["collection_id"] = col2["id"]
        decision["taxonomy_written"] = False
        decision["taxonomy_updated_at"] = meta2.get("updated_at")

        if decision["action"] == "noop":
            return decision

        if decision.get("will_publish"):
            shop.set_published(col2["id"], True)
        elif decision.get("will_unpublish"):
            shop.set_published(col2["id"], False)

        if not decision.get("taxonomy_dirty"):
            return decision

        mf2 = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        _assert_expected_updated_at(mf2, exp)
        raw = (mf2 or {}).get("value") or ""
        tax2 = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(tax2, list):
            raise ShopifyError("taxonomy metafield corrupt during reconcile_handle")
        _k, _p, node3 = find_node_by_handle(tax2, handle)
        if node3 is None:
            raise ShopifyError(f"handle {handle!r} disappeared from taxonomy")
        node3["visible"] = bool(decision["desired_visible"])
        shop.set_shop_metafield(NAMESPACE, TAXONOMY_KEY, tax2)
        again = shop.get_shop_metafield(NAMESPACE, TAXONOMY_KEY)
        stored_raw = (again or {}).get("value") or ""
        stored = json.loads(stored_raw) if isinstance(stored_raw, str) else stored_raw
        if not isinstance(stored, list):
            stored = tax2
        updated_at = (again or {}).get("updatedAt")
        bust_taxonomy_cache()
        _set_cache(stored, updated_at=updated_at, source="live")
        write_lkg_from_tax(stored, updated_at=updated_at)
        decision["taxonomy_written"] = True
        decision["taxonomy_updated_at"] = updated_at
        decision["visible"] = bool(decision["desired_visible"])
        return decision
