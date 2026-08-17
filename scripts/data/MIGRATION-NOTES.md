# Migration plan vs visibility policy

`migration-plan.csv` unpublish rows were drafted against older taxonomy flags
(some product-bearing collections marked hidden / indexable false).

**Current policy (Phase 7)**

- Online-Store-**published** product count > 0 and `indexable: true` → publish
  collection + `visible: true`.
- Count = 0 → unpublish + `visible: false`.
- `indexable: false` → never publish via reconcile/webhooks; mega-menu
  exclusion is the Liquid **`indexable` gate** (not a side effect of unpublish).
- New subcategories default to `indexable: true`; create starts unpublished /
  `visible: false`.

**What `--action unpublish` does**

`migrate_collections.py` **refuses** unpublish when `productsCount > 0`. So rows
such as Favourites, New Year, Crackers & Savoury Biscuits, Snack Pots & Dippers,
Soup, and Desserts are protected even if still listed as `unpublish` in the CSV.
Genuinely empty collections still unpublish — that remains correct.

No CSV rewrite required before a careful unpublish dry-run; expect REFUSED lines
for product-bearing rows.

**Handle alignment (post Phase 6)**

Empty collections were unpublished **in place** (old handles kept) while
taxonomy already pointed at SEO handles (`branded-pretzels`,
`promotional-gifts-for-retail`, …). Run
`python scripts/align_unpublished_handles.py` (then `--write`) to rename those
Shopify collections to match taxonomy and add redirects. After alignment,
reconcile resolves them as unpublished / 0 products — not `missing_collection`.
