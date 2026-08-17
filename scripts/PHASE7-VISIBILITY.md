# Phase 7 — publish state + visibility reconcile

## Policy

| Condition | Online Store | `visible` |
|-----------|--------------|-----------|
| Published-product count **> 0** and `indexable: true` | **publish** | `true` |
| Count **= 0** | **unpublish** | `false` |
| `indexable: false` | **never publish** (unpublish if currently published) | `false` |

**Published-product count** means products in the collection that are published
to the Online Store (`productsCount` query with
`collection_id:{id} AND published_status:published`). Raw
`Collection.productsCount` includes drafts/unpublished products and must **not**
drive publish decisions — a collection whose only products are unpublished
counts as **0**.

Handle lookup uses this GraphQL (not `collectionByHandle`):

```graphql
query($q: String!) {
  collections(first: 1, query: $q) {
    edges { node { id handle title productsCount { count } } }
  }
}
```

with `q = "handle:<handle>"`. Publication state is read separately via
`publishedOnPublication`. Genuinely missing handles report
`missing_collection` with `online_store=missing`; unpublished-but-present
nodes show `online_store=unpublished` and a normal action.

**Handle alignment:** Phase 6 unpublished empty collections **in place** on
pre-migration handles while taxonomy already used SEO handles
(`branded-pretzels`, etc.). `scripts/align_unpublished_handles.py` renames
those Shopify collections to match taxonomy (with redirects). After that,
reconcile finds them.

**Menu exclusion is not a publish side effect.** Deliberate hides use the
Liquid `indexable` gate in `theme/snippets/bite-mega-menu.liquid` (verify
branch). If someone republishes a non-indexable collection in Admin, verify
mode still skips it. `visible` stays accurate for non-verify / info paths.

New subcategories start **unpublished** with `visible: false`; Phase 7
(webhook or reconcile) flips them when Online-Store-published count > 0.

## Shared core

`backend/shopify_client/taxonomy.py`:

- `apply_visibility_rule(node, published_count, is_published=...)`
- `reconcile_visibility(write=..., force=...)`
- `reconcile_handle(handle, write=...)` — webhook / `publish_now` path

Concurrency: process-level Lock + metafield `updatedAt` (409 on mismatch).

## Circuit breaker

When `write=True` and `force=False`, if planned Online-Store **unpublishes**
exceed **20%** of taxonomy nodes that are currently published, reconcile
**aborts**: no publish/unpublish mutations and no taxonomy write. Logs
`[error]`. Same spirit as the LKG poison guard.

`--force` / `force=True` bypasses the breaker (**manual only**). Nightly cron
must **not** pass force.

## CLI

```bash
python scripts/reconcile_visibility.py              # dry-run
python scripts/reconcile_visibility.py --write
python scripts/reconcile_visibility.py --write --force   # break glass
```

Prints: handle, published_count, indexable, action. Exit non-zero on hard
failures or circuit-breaker abort.

## Webhooks

- `POST /webhooks/shopify/collections`
- Topics: `collections/create`, `collections/update` (`X-Shopify-Topic`)
- HMAC: raw body + `SHOPIFY_WEBHOOK_SECRET` → SHA256 base64 vs
  `X-Shopify-Hmac-Sha256` (401 on failure)
- Public path (no staff login); secret required
- **Noop short-circuit:** action `noop` → 200 **without** taxonomy metafield
  RMW (avoids lock storms on bulk `collections/update` bursts)

Tony registers the webhooks in Shopify Admin and sets `SHOPIFY_WEBHOOK_SECRET`
(same value in Render env / `render.yaml`).

## Nightly backstop

- `POST /api/cron/reconcile-visibility`
- Header: `Authorization: Bearer <CRON_SECRET>` (401 without)
- Calls `reconcile_visibility(write=True, force=False)` — breaker stays on
- Render Cron Job: `0 3 * * *` **UTC** (= **04:00 BST** in summer). UK clocks
  will look “an hour ahead”; that is expected.

Env: `CRON_SECRET` on web + cron; `RECONCILE_VISIBILITY_URL` on cron pointing at
`https://<service>/api/cron/reconcile-visibility`.

## Ops checklist

1. Dry-run: expected publishes listed; breaker would trip on mass unpublish.
2. `--write`: product-bearing indexable collections published; empty stay unpublished.
3. Collection with only unpublished products → count 0 → stays unpublished.
4. Invalid HMAC → 401; noop webhook → 200, no metafield write.
5. `indexable: false` hidden in menu even if manually published (Liquid gate).
6. Cron without secret → 401; with secret → 200 + summary (breaker intact).
