#!/usr/bin/env python3
"""
fix_taxonomy_whitespace.py - find and fix whitespace-padded taxonomy values.

Dry-run by default.

Shopify blocks metafieldDefinitionUpdate on definitions used by smart collections.
When padded choice strings must be replaced (trimmed form not yet in the list),
pass --unlock-choices with --write. That:

  1. Snapshots every smart-collection ruleSet to scripts/data/whitespace-rules-backup.json
  2. Temporarily strips custom.subcategory / subcategory_2 rules (keeps other rules)
  3. Rewrites the choice list (padded -> trimmed)
  4. Restores rules with trimmed conditions

Rules whose trimmed value already exists in the choice list (e.g. Retro & Novelty)
are fixed without --unlock-choices.

Usage:
    python scripts/fix_taxonomy_whitespace.py
    python scripts/fix_taxonomy_whitespace.py --write
    python scripts/fix_taxonomy_whitespace.py --write --unlock-choices
"""

from __future__ import annotations

import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

import argparse
import json
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from shopify_client.bite_shopify import Shopify, ShopifyError  # noqa: E402

OWNER = "PRODUCT"
KEYS = ("custom_category", "subcategory", "subcategory_2")
SUB_KEYS = ("subcategory", "subcategory_2")
BACKUP = _REPO / "scripts" / "data" / "whitespace-rules-backup.json"


def _parse_mf_values(raw, mf_type):
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if (mf_type or "").startswith("list.") or (isinstance(raw, str) and raw.startswith("[")):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (TypeError, ValueError):
            pass
    return [str(raw)]


def _choices(shop, key):
    return shop.metafield_definition("custom", key, OWNER)


def _set_choices(shop, key, choices):
    result = shop.gql("""
      mutation($def: MetafieldDefinitionUpdateInput!) {
        metafieldDefinitionUpdate(definition: $def) {
          updatedDefinition { id }
          userErrors { field message code }
        }
      }
    """, {"def": {
        "namespace": "custom",
        "key": key,
        "ownerType": OWNER,
        "validations": [{"name": "choices", "value": json.dumps(choices)}],
    }})["metafieldDefinitionUpdate"]
    shop._check(result, "metafieldDefinitionUpdate")
    shop._cache.pop(("mfdef", "custom", key, OWNER), None)


def _scan_products(shop, key):
    by_value = {}
    cursor = None
    while True:
        data = shop.gql("""
          query($cursor: String, $ns: String!, $key: String!) {
            products(first: 100, after: $cursor) {
              pageInfo { hasNextPage endCursor }
              edges { node {
                id title
                metafield(namespace: $ns, key: $key) { id type value }
              } }
            }
          }
        """, {"cursor": cursor, "ns": "custom", "key": key})
        block = data["products"]
        for edge in block["edges"]:
            node = edge["node"]
            mf = node.get("metafield") or {}
            vals = _parse_mf_values(mf.get("value"), mf.get("type"))
            for v in vals:
                by_value.setdefault(v, []).append({
                    "id": node["id"],
                    "title": node.get("title") or "",
                    "metafield_id": mf.get("id"),
                    "mf_type": mf.get("type") or "",
                    "all_values": vals,
                })
        if not block["pageInfo"]["hasNextPage"]:
            break
        cursor = block["pageInfo"]["endCursor"]
    return by_value


def _rule_condition(rule):
    return rule.get("condition") or ""


def _rule_key(rule):
    md = ((rule.get("conditionObject") or {}) or {}).get("metafieldDefinition") or {}
    return md.get("key")


def _rule_def_id(rule):
    md = ((rule.get("conditionObject") or {}) or {}).get("metafieldDefinition") or {}
    return md.get("id")


def _rules_to_input(rules, condition_rewrite=None):
    """condition_rewrite: dict raw->trimmed applied to matching conditions."""
    condition_rewrite = condition_rewrite or {}
    out = []
    for rule in rules:
        cond = _rule_condition(rule)
        if cond in condition_rewrite:
            cond = condition_rewrite[cond]
        entry = {
            "column": rule.get("column"),
            "relation": rule.get("relation"),
            "condition": cond,
        }
        def_id = _rule_def_id(rule)
        if def_id:
            entry["conditionObjectId"] = def_id
        out.append(entry)
    return out


def _set_rules(shop, collection_id, applied_disjunctive, rules_input):
    result = shop.gql("""
      mutation($input: CollectionInput!) {
        collectionUpdate(input: $input) {
          collection { id }
          userErrors { field message }
        }
      }
    """, {"input": {
        "id": collection_id,
        "ruleSet": {
            "appliedDisjunctively": bool(applied_disjunctive),
            "rules": rules_input,
        },
    }})["collectionUpdate"]
    shop._check(result, "collectionUpdate")


def _collection_detail(shop, handle):
    data = shop.gql("""
      query($h: String!) {
        collectionByHandle(handle: $h) {
          id handle title
          ruleSet { appliedDisjunctively
            rules { column relation condition conditionObject {
              ... on CollectionRuleMetafieldCondition {
                metafieldDefinition { id namespace key }
              } } } }
        }
      }
    """, {"h": handle})
    return data["collectionByHandle"]


def unlock_and_fix_choices(shop, replacements):
    """replacements: list of (key, raw, trimmed)."""
    print("\n--unlock-choices: snapshot + strip subcategory rules...")
    collections = shop.all_collections()
    backup = []
    stripped = 0
    for col in collections:
        rs = col.get("ruleSet")
        if not rs or not rs.get("rules"):
            continue
        detail = _collection_detail(shop, col["handle"])
        if not detail or not detail.get("ruleSet"):
            continue
        rules = detail["ruleSet"]["rules"]
        backup.append({
            "id": detail["id"],
            "handle": detail["handle"],
            "appliedDisjunctively": detail["ruleSet"]["appliedDisjunctively"],
            "rules": rules,
        })
        kept = [r for r in rules if _rule_key(r) not in SUB_KEYS]
        if len(kept) == len(rules):
            continue
        if not kept:
            print(f"  SKIP {detail['handle']}: would leave empty ruleSet")
            continue
        _set_rules(shop, detail["id"], detail["ruleSet"]["appliedDisjunctively"],
                   _rules_to_input(kept))
        stripped += 1
        print(f"  stripped subcategory rules from /{detail['handle']}")

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_text(json.dumps(backup, indent=2), encoding="utf-8")
    print(f"  backup -> {BACKUP} ({len(backup)} collections, stripped {stripped})")

    print("\nUpdating choice lists...")
    by_key = {}
    for key, raw, trimmed in replacements:
        by_key.setdefault(key, []).append((raw, trimmed))
    for key, pairs in by_key.items():
        d = _choices(shop, key)
        if not d:
            print(f"  custom.{key}: MISSING - skip")
            continue
        new_choices = []
        raw_set = {raw for raw, _ in pairs}
        trim_map = {raw: trimmed for raw, trimmed in pairs}
        for c in d["choices"]:
            if c in raw_set:
                t = trim_map[c]
                if t not in new_choices:
                    new_choices.append(t)
            elif c not in new_choices:
                new_choices.append(c)
        for _, trimmed in pairs:
            if trimmed not in new_choices:
                new_choices.append(trimmed)
        _set_choices(shop, key, new_choices)
        print(f"  custom.{key}: choices updated")

    print("\nRestoring rules with trimmed conditions...")
    rewrite = {raw: trimmed for _, raw, trimmed in replacements}
    for row in backup:
        rules = row["rules"]
        # rewrite padded conditions; keep all original rules including subcategory
        _set_rules(shop, row["id"], row["appliedDisjunctively"],
                   _rules_to_input(rules, rewrite))
        print(f"  restored /{row['handle']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--unlock-choices", action="store_true",
                    help="Temporarily strip subcategory smart-collection rules so choice lists can be edited")
    args = ap.parse_args()

    shop = Shopify()
    mode = "WRITE" if args.write else "DRY RUN"
    print(f"=== {mode} whitespace fix - {shop.domain} ===\n")

    print("Choice lists:")
    padded_choices = []
    for key in KEYS:
        d = _choices(shop, key)
        if d is None:
            print(f"  custom.{key}: MISSING")
            continue
        bad = [c for c in d["choices"] if c != c.strip()]
        print(f"  custom.{key}: {len(d['choices'])} choices, {len(bad)} padded")
        for c in bad:
            print(f"    PADDED choice: {c!r}  ->  {c.strip()!r}")
            padded_choices.append((key, c, c.strip()))

    print("\nScanning product metafields...")
    value_index = {}
    for key in KEYS:
        if _choices(shop, key) is None:
            continue
        value_index[key] = _scan_products(shop, key)
        padded_vals = [v for v in value_index[key] if v != v.strip()]
        print(f"  custom.{key}: {len(value_index[key])} distinct values, "
              f"{len(padded_vals)} padded")

    print("\nCollection rules:")
    collections = shop.all_collections()
    padded_rules = []
    for col in collections:
        rs = col.get("ruleSet") or {}
        for rule in (rs.get("rules") or []):
            cond = _rule_condition(rule)
            if not cond or cond == cond.strip():
                continue
            key = _rule_key(rule) or "subcategory"
            count = ((col.get("productsCount") or {}) or {}).get("count")
            padded_rules.append({
                "collection": col,
                "key": key,
                "raw": cond,
                "trimmed": cond.strip(),
                "products_count": count,
            })
            print(f"  {col.get('title')!r} /{col.get('handle')} "
                  f"key={key} condition={cond!r} productsCount={count}")

    print("\nPer-value report:")
    values = []
    seen = set()

    def note(key, raw, trimmed, context=""):
        tup = (key, raw, trimmed)
        if tup in seen:
            return
        seen.add(tup)
        values.append(tup)
        idx = value_index.get(key) or {}
        n = len(idx.get(raw) or [])
        m = len(idx.get(trimmed) or [])
        d = _choices(shop, key)
        trimmed_in_choices = bool(d and trimmed in d["choices"])
        print(f"  {raw!r} | padded_products={n} trimmed_products={m} "
              f"trimmed_in_choices={trimmed_in_choices}"
              f"{('  [' + context + ']') if context else ''}")
        if n == 0 and m == 0:
            print("    -> tagging gap")
        elif not trimmed_in_choices:
            print("    -> needs --unlock-choices to rewrite definition")
        elif n == 0 and m > 0:
            print("    -> rule padding only; safe simple rule trim")

    for item in padded_rules:
        note(item["key"] if item["key"] in KEYS else "subcategory",
             item["raw"], item["trimmed"], item["collection"].get("title") or "")
    for key, raw, trimmed in padded_choices:
        note(key, raw, trimmed, f"choice {key}")

    if not values:
        print("\nNothing to fix.")
        return

    needs_unlock = []
    simple_rules = []
    for key, raw, trimmed in values:
        d = _choices(shop, key)
        if d and trimmed in d["choices"]:
            simple_rules.append((key, raw, trimmed))
        elif d and raw in d["choices"]:
            needs_unlock.append((key, raw, trimmed))
        else:
            # rule-only padding toward a trimmed value already in choices handled above;
            # rule toward unknown trimmed still needs unlock if we must add choice
            if d and trimmed not in d["choices"]:
                needs_unlock.append((key, raw, trimmed))
            else:
                simple_rules.append((key, raw, trimmed))

    if not args.write:
        print(f"\nDry run. simple={len(simple_rules)} unlock={len(needs_unlock)}")
        if needs_unlock:
            print("Re-run with:  --write --unlock-choices")
        elif simple_rules:
            print("Re-run with:  --write")
        return

    # Simple rule trims (trimmed already a valid choice)
    for key, raw, trimmed in simple_rules:
        print(f"\n--- simple rule trim {raw!r} -> {trimmed!r} ---")
        for item in padded_rules:
            if item["raw"] != raw:
                continue
            col = item["collection"]
            detail = _collection_detail(shop, col["handle"])
            if not detail:
                continue
            try:
                _set_rules(
                    shop, detail["id"], detail["ruleSet"]["appliedDisjunctively"],
                    _rules_to_input(detail["ruleSet"]["rules"], {raw: trimmed}),
                )
                print(f"  trimmed /{col.get('handle')}")
                item["raw"] = trimmed
            except ShopifyError as exc:
                print(f"  FAILED /{col.get('handle')}: {exc}")

    if needs_unlock:
        if not args.unlock_choices:
            print("\nRemaining values need choice-list edits. Re-run with --write --unlock-choices")
            for key, raw, trimmed in needs_unlock:
                print(f"  {key}: {raw!r} -> {trimmed!r}")
            return
        unlock_and_fix_choices(shop, needs_unlock)

    print("\nDone. Re-run without --write to confirm clean.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except ShopifyError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
