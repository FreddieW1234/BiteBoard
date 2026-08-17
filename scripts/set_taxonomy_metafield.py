#!/usr/bin/env python3
"""
Write taxonomy.json into the shop metafield custom.taxonomy.

Usage (from repo root):
    python scripts/set_taxonomy_metafield.py scripts/data/taxonomy.json --allow-missing-handles
    python scripts/set_taxonomy_metafield.py scripts/data/taxonomy.json --write --allow-missing-handles --yes
    python scripts/set_taxonomy_metafield.py --restore scripts/data/backups/<file>.json --yes

Uses shopify_client.bite_shopify.Shopify - no second GraphQL helper.

Local encoding: see scripts/README-PYTHONUTF8.md (reconfigure + PYTHONUTF8).
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
import re
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
for p in (_BACKEND,):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from shopify_client.bite_shopify import Shopify, ShopifyError  # noqa: E402

NAMESPACE = "custom"
KEY = "taxonomy"
BACKUP_DIR = _REPO / "scripts" / "data" / "backups"


def validate(tax):
    """Structural + duplicate label/handle checks."""
    problems = []
    handles = {}
    labels = {}
    if not isinstance(tax, list):
        return ["top level must be a list of category objects"]
    for cat in tax:
        for field in ("category", "handle", "position", "subcategories"):
            if field not in cat:
                problems.append(f"category {cat.get('category', '?')} missing '{field}'")
        cat_name = cat.get("category") or "?"
        for h in [cat.get("handle")] + [s.get("handle") for s in cat.get("subcategories", [])]:
            if not h:
                problems.append(f"blank handle under {cat_name}")
                continue
            if h in handles:
                problems.append(
                    f"duplicate handle '{h}' ({handles[h]} and {cat_name})"
                )
            handles[h] = cat_name
        for sub in cat.get("subcategories", []):
            for field in ("label", "handle", "position", "indexable", "metafield_key"):
                if field not in sub:
                    problems.append(
                        f"{cat_name} > {sub.get('label', '?')} missing '{field}'"
                    )
            if sub.get("metafield_key") not in ("subcategory", "subcategory_2"):
                problems.append(
                    f"{sub.get('label')} has bad metafield_key {sub.get('metafield_key')!r}"
                )
            label = sub.get("label")
            if label:
                key = (cat_name, label)
                if key in labels:
                    problems.append(f"duplicate label {label!r} under {cat_name}")
                labels[key] = True
                # Also flag same label twice under different categories only as info? Keep silent.
    return problems


def _norm_lookalike(s: str) -> str:
    t = (s or "").replace("\u00a0", " ").strip().lower()
    t = t.replace("&", " and ")
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("`", "'")
    t = re.sub(r"\s+", " ", t)
    return t


def _load_definition_status(shop: Shopify, key: str) -> tuple[str, list[str]]:
    """
    Returns (status, choices) where status is:
      MISSING | EMPTY | OK | PLACEHOLDER_ONLY | READ_FAILED

    subcategory_2 may contain only the Shopify creation placeholder BLANK;
    that is stripped from returned choices so it never validates as a real label.
    """
    try:
        d = shop.metafield_definition("custom", key)
    except Exception as exc:
        print(f"[error] custom.{key}: READ_FAILED - {exc}")
        return "READ_FAILED", []
    if d is None:
        print(f"[ok] custom.{key}: MISSING")
        return "MISSING", []
    choices = list(d.get("choices") or [])
    real = [c for c in choices if str(c).strip().upper() != "BLANK"]
    if not choices:
        print(f"[ok] custom.{key}: EMPTY (0 choices, definition exists) {d.get('id')}")
        return "EMPTY", []
    if key == "subcategory_2" and not real:
        print(
            f"[ok] custom.{key}: PLACEHOLDER_ONLY (BLANK only, definition ready) {d.get('id')}"
        )
        return "PLACEHOLDER_ONLY", []
    print(f"[ok] custom.{key}: OK ({len(real)} real choices) {d.get('id')}")
    return "OK", real


def validate_against_choices(tax, cat_choices, sub_choices) -> list[str]:
    problems = []
    cat_set = set(cat_choices)
    sub_set = set(sub_choices)
    cat_fuzzy = {_norm_lookalike(c): c for c in cat_choices}
    sub_fuzzy = {_norm_lookalike(c): c for c in sub_choices}

    json_cats = []
    json_subs = []
    for cat in tax:
        name = cat.get("category")
        if name:
            json_cats.append(name)
            if name not in cat_set:
                fuzzy = cat_fuzzy.get(_norm_lookalike(name))
                if fuzzy:
                    problems.append(
                        f"category exact-mismatch: JSON {name!r} ~ definition {fuzzy!r}"
                    )
                else:
                    problems.append(f"category not in definition choices: {name!r}")
        for sub in cat.get("subcategories") or []:
            label = sub.get("label")
            if not label:
                continue
            json_subs.append(label)
            if label not in sub_set:
                fuzzy = sub_fuzzy.get(_norm_lookalike(label))
                if fuzzy:
                    problems.append(
                        f"subcategory exact-mismatch: JSON {label!r} ~ definition {fuzzy!r}"
                    )
                else:
                    problems.append(f"subcategory not in definition choices: {label!r}")

    unused_cats = sorted(cat_set - set(json_cats))
    unused_subs = sorted(sub_set - set(json_subs))
    if unused_cats:
        print(f"[info] definition categories unused by JSON ({len(unused_cats)}):")
        for c in unused_cats:
            print(f"    - {c}")
    if unused_subs:
        print(f"[info] definition subcategories unused by JSON ({len(unused_subs)}):")
        for c in unused_subs[:30]:
            print(f"    - {c}")
        if len(unused_subs) > 30:
            print(f"    ... and {len(unused_subs) - 30} more")
    return problems


def check_handles(shop: Shopify, tax) -> list[tuple[str, str]]:
    missing = []
    for cat in tax:
        ch = cat.get("handle")
        if ch and shop.collection_by_handle(ch) is None:
            missing.append((ch, f"category {cat.get('category')}"))
        for sub in cat.get("subcategories") or []:
            sh = sub.get("handle")
            if sh and shop.collection_by_handle(sh) is None:
                missing.append(
                    (sh, f"{cat.get('category')} > {sub.get('label')}")
                )
    return missing


def _flatten_handles(tax):
    out = {}
    for cat in tax or []:
        if cat.get("handle"):
            out[cat["handle"]] = ("category", cat.get("category"))
        for sub in cat.get("subcategories") or []:
            if sub.get("handle"):
                out[sub["handle"]] = ("sub", f"{cat.get('category')} > {sub.get('label')}")
    return out


def print_diff(current_tax, new_tax):
    cur_h = _flatten_handles(current_tax if isinstance(current_tax, list) else [])
    new_h = _flatten_handles(new_tax)
    added = sorted(set(new_h) - set(cur_h))
    removed = sorted(set(cur_h) - set(new_h))
    cur_n = sum(len(c.get("subcategories") or []) for c in (current_tax or []) if isinstance(c, dict))
    new_n = sum(len(c.get("subcategories") or []) for c in new_tax)
    print(
        f"[diff] categories {len(current_tax or [])} -> {len(new_tax)}; "
        f"subcategories {cur_n} -> {new_n}"
    )
    print(f"[diff] handles +{len(added)} / -{len(removed)}")
    for h in added[:40]:
        print(f"    + {h} ({new_h[h][1]})")
    if len(added) > 40:
        print(f"    ... +{len(added) - 40} more")
    for h in removed[:40]:
        print(f"    - {h} ({cur_h[h][1]})")
    if len(removed) > 40:
        print(f"    ... -{len(removed) - 40} more")


def backup_current(shop: Shopify, label: str = "pre-write") -> Path | None:
    current = shop.get_shop_metafield(NAMESPACE, KEY)
    if not current or not (current.get("value") or "").strip():
        print("[ok] no existing metafield value to back up")
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"taxonomy-metafield-{ts}.json"
    raw = current["value"]
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        parsed = {"_raw": raw}
    payload = {
        "_backup_meta": {
            "label": label,
            "updatedAt": current.get("updatedAt"),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        },
        "taxonomy": parsed,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] backup written: {path}")
    return path


def _confirm(args, prompt: str) -> bool:
    if args.yes:
        return True
    try:
        ans = input(f"{prompt} Type 'yes' to continue: ").strip().lower()
    except EOFError:
        return False
    return ans == "yes"


def _parse_tax_file(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "taxonomy" in data:
        return data["taxonomy"]
    return data


def cmd_restore(args, shop: Shopify):
    path = Path(args.restore)
    if not path.is_file():
        print(f"[error] restore file not found: {path}")
        sys.exit(1)
    tax = _parse_tax_file(path)
    if not isinstance(tax, list):
        print("[error] restore file must contain a taxonomy list (or {_backup_meta, taxonomy})")
        sys.exit(1)

    current = shop.get_shop_metafield(NAMESPACE, KEY)
    if current and (current.get("value") or "").strip():
        print_diff(_parse_current_list(current), tax)
        if not _confirm(args, "Restore will overwrite the live taxonomy metafield."):
            print("[warn] aborted")
            sys.exit(1)
        backup_current(shop, label="pre-restore")
    else:
        print("[ok] target metafield empty - restore without confirm")

    # Skip live choice-list validation on restore (known-good prior state).
    mf = shop.set_shop_metafield(NAMESPACE, KEY, tax)
    print(f"[ok] Restored. {mf['namespace']}.{mf['key']} at {mf['updatedAt']}")


def _parse_current_list(current) -> list:
    if not current:
        return []
    raw = current.get("value") or ""
    try:
        tax = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    return tax if isinstance(tax, list) else []


def main():
    parser = argparse.ArgumentParser(description="Seed or restore shop.custom.taxonomy")
    parser.add_argument("path", nargs="?", help="Path to taxonomy.json")
    parser.add_argument("--write", action="store_true", help="Write metafield (default: dry-run)")
    parser.add_argument("--yes", action="store_true", help="Skip interactive confirm")
    parser.add_argument(
        "--allow-missing-handles",
        action="store_true",
        help="Allow taxonomy handles that do not exist yet (Phase 6 targets)",
    )
    parser.add_argument(
        "--restore",
        metavar="FILE",
        help="Restore taxonomy from a backup JSON (skips choice validation; still backs up current)",
    )
    args = parser.parse_args()

    print(
        f"[ok] stdio encoding stdout={getattr(sys.stdout, 'encoding', None)!r} "
        f"stderr={getattr(sys.stderr, 'encoding', None)!r}",
        flush=True,
    )

    try:
        shop = Shopify()
    except ShopifyError as exc:
        print(f"[error] Shopify config: {exc}")
        sys.exit(1)

    if args.restore:
        cmd_restore(args, shop)
        return

    if not args.path:
        parser.print_help()
        sys.exit(1)

    tax = _parse_tax_file(Path(args.path))
    problems = validate(tax)
    if problems:
        print("VALIDATION FAILED:")
        for p in problems:
            print("  -", p)
        sys.exit(1)

    # A3: subcategory_2 ternary
    print("\n--- metafield definition status ---")
    cat_status, cat_choices = _load_definition_status(shop, "custom_category")
    sub_status, sub_choices = _load_definition_status(shop, "subcategory")
    sub2_status, sub2_choices = _load_definition_status(shop, "subcategory_2")
    if cat_status == "READ_FAILED" or sub_status == "READ_FAILED":
        print("[error] cannot validate choices after READ_FAILED")
        sys.exit(1)
    if sub2_status == "READ_FAILED":
        print("[error] custom.subcategory_2 READ_FAILED - refusing to treat as empty")
        sys.exit(1)

    merged_subs = list(sub_choices)
    seen = {c.lower() for c in merged_subs}
    for c in sub2_choices:
        if c.lower() not in seen:
            merged_subs.append(c)
            seen.add(c.lower())

    choice_problems = validate_against_choices(tax, cat_choices, merged_subs)
    if choice_problems:
        print("\nCHOICE VALIDATION FAILED:")
        for p in choice_problems:
            print("  -", p)
        sys.exit(1)

    print("\n--- collection handles ---")
    missing = check_handles(shop, tax)
    if missing:
        print(f"[warn] {len(missing)} handle(s) not found in Shopify (target/post-migration handles?):")
        for h, label in missing:
            print(f"    MISSING /{h}  ({label})")
        print(
            "[warn] After seed, mega-menu links 404 until Phase 6 renames land "
            "unless you migrate first."
        )
        if not args.allow_missing_handles:
            print(
                "[error] refusing to continue without --allow-missing-handles "
                "(--yes does not bypass this)"
            )
            sys.exit(1)
        print("[ok] continuing with --allow-missing-handles")
    else:
        print("[ok] all taxonomy handles resolve to existing collections")

    subs = sum(len(c["subcategories"]) for c in tax)
    payload = json.dumps(tax, ensure_ascii=False, separators=(",", ":"))
    print(f"\n[ok] {len(tax)} categories, {subs} subcategories, {len(payload):,} bytes")

    current = shop.get_shop_metafield(NAMESPACE, KEY)
    current_list = _parse_current_list(current)
    if current and (current.get("value") or "").strip():
        print(f"[ok] existing value: {len(current['value']):,} bytes, updated {current['updatedAt']}")
        print_diff(current_list, tax)
    else:
        print("[ok] no existing value (first write)")

    if not args.write:
        print("\nDry run. Re-run with --write to set the metafield.")
        return

    if current and (current.get("value") or "").strip():
        if not _confirm(args, "Overwrite non-empty shop.custom.taxonomy?"):
            print("[warn] aborted")
            sys.exit(1)
        backup_current(shop, label="pre-write")

    mf = shop.set_shop_metafield(NAMESPACE, KEY, tax)
    print(f"\n[ok] Written. {mf['namespace']}.{mf['key']} ({mf['type']}) at {mf['updatedAt']}")
    print("Verify in Liquid:  {{ shop.metafields.custom.taxonomy.value | size }}")


if __name__ == "__main__":
    main()
