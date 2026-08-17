# Pass A -> B smoke checklist

Run **after** Tony seeds with:

```text
python -X utf8 scripts/set_taxonomy_metafield.py scripts/data/taxonomy.json --write --allow-missing-handles --yes
```

Do **not** start Pass B code review as "done in prod" until this passes. (Pass B code is already in the repo; this gate is operational.)

Throwaway name: **`zz-smoke-DELETEME`**, leave **In menu** checked (indexable true is the default). Uncheck only if you deliberately want it out of the mega-menu. It may linger in taxonomy/choices until a delete path exists.

**Visibility policy:** collections with products are `visible`; `indexable: false` is deliberate menu exclusion only — not “was empty historically”.

1. Category Editor banner reads **live** (green), not FALLBACK.
2. Create subcategory `zz-smoke-DELETEME` under any category -> choice added + unpublished collection.
3. Publish -> only if the collection has products; otherwise skip with note (do not false-fail). Prefer tagging one product temporarily.
4. **Product Creator** shows the new choice:
   - After create, **restart the backend process** (preferred) or wait 300s TTL.
   - Real failure only if still missing after a clean restart.
5. Reorder + Save in Category Editor -> persisted on reload.
6. Unpublish throwaway collection if possible; leave `zz-smoke-DELETEME` marked for later delete.

## metafieldDefinitionUpdate / append_choice

When updating a definition that is (or is not) used as a smart-collection
condition, **echo** `capabilities.smartCollectionCondition.enabled` from the
live definition. Omitting it can default the capability off and raise
`CAPABILITY_CANNOT_BE_DISABLED` while collections still reference the field.
Never force `enabled: true` (overflow `subcategory_2` must stay off).

Regression: `python -m unittest shopify_client.test_append_choice -v` (from `backend/`).
