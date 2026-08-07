"""
Apply these changes on the OFFICE Windows server app.py, then RESTART the service.

Why the folder was missing
--------------------------
STOCK_DESIGNS_DIR is only created inside stock_folder(..., create=True), which runs
on a successful POST /stock-designs/{id}. If the portal never delivered a ZIP
(empty body / failed proxy / service not restarted), the folder never appears.

Change 1 — create the root at startup (next to your other mkdir calls)
---------------------------------------------------------------------
After:

    DB_DIR.mkdir(parents=True, exist_ok=True)
    ORDERS_DIR.mkdir(parents=True, exist_ok=True)

add (or move STOCK_DESIGNS_DIR definition earlier if needed):

    # Stock designs root — create even before the first upload so staff can see it.
    STOCK_DESIGNS_DIR.mkdir(parents=True, exist_ok=True)

If STOCK_DESIGNS_DIR is defined later in the file, either move those two lines
up next to DB_DIR, or duplicate:

    (DB_DIR / "stock designs").mkdir(parents=True, exist_ok=True)

Change 2 — optional: put product id in the filename
---------------------------------------------------
In save_stock_upload(), replace:

    final = folder / f"{base}_v{version}.zip"

with:

    final = folder / f"{base}_{pid}_v{version}.zip"

(and the --stamp fallback the same way). Folder is already keyed by product id.

Change 3 — health check shows where files land
----------------------------------------------
In the health() handler, include:

    "db_dir": str(DB_DIR),
    "stock_designs_dir": str(DB_DIR / "stock designs"),

so you can hit GET / and confirm you're looking at the same path the service uses.
DB_DIR comes from the .env (default ./data relative to the *service working directory*,
not necessarily the folder that contains app.py).

Restart
-------
After editing app.py, restart the Office Order API Windows service / uvicorn process.
Until it reloads, POST /stock-designs/... may 404 and the portal will show a 502.
"""
