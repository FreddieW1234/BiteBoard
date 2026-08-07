# Stock Designs on the Office Server

## Install on the office API

1. Copy `stock_designs_addon.py` next to your office FastAPI app file.
2. Near the bottom of the office API (after `init_snapshots_db()`), add:

```python
from stock_designs_addon import register_stock_design_routes

register_stock_design_routes(
    app,
    db_dir=DB_DIR,
    lock=LOCK,
    require_key_dep=require_key,
    max_upload_bytes=MAX_UPLOAD_BYTES,
    max_upload_mb=MAX_UPLOAD_MB,
)
```

3. Restart the office service.

## Disk layout

```
{DB_DIR}/stock designs/{shopify_product_id}/{Product Name}_{product_id}_v1.zip
{DB_DIR}/stock designs/{shopify_product_id}/{Product Name}_{product_id}_v2.zip
...
```

Example:

```
./data/stock designs/16170516480378/Moustache Chocolate - Lollipop - Movember_16170516480378_v1.zip
```

The Shopify product must exist before upload (so the id is known). Soft-deleted files go to:

```
{DB_DIR}/stock designs/_Archive/{product_id}/...
```
