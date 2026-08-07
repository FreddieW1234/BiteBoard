"""
Stock Designs storage for the Office Order API
==============================================

MERGE THIS into the office FastAPI app (the file you pasted), or import the
helpers/routes from there.

Disk layout (under DB_DIR, same place as orders.db / companies.db):

    data/stock designs/<product_id>/<Product Name>_v1.zip
    data/stock designs/<product_id>/<Product Name>_v2.zip
    ...

- <product_id> is the Shopify product id (stable, even if the title changes)
- Filename is "{Product Name}_v{N}.zip" where N is 1, 2, 3, ...
- Product Name is sanitised for Windows filenames (invalid chars stripped)

Endpoints (all require X-API-Key):

    GET    /stock-designs
    GET    /stock-designs/{product_id}
    POST   /stock-designs/{product_id}          multipart: file + product_name
    GET    /stock-designs/{product_id}/latest
    GET    /stock-designs/{product_id}/files/{filename}
    DELETE /stock-designs/{product_id}/files/{filename}?permanent=true|false
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

# --------------------------------------------------------------------------- #
# These names must already exist in the main office API module when you merge:
#   DB_DIR, LOCK, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, require_key, iso_now
#   ARCHIVE_DIRNAME (optional — archive soft-deletes under stock designs/_Archive)
# --------------------------------------------------------------------------- #

STOCK_DESIGNS_DIRNAME = "stock designs"
_PRODUCT_ID_RE = re.compile(r"^\d{1,20}$")
_FILENAME_OK = re.compile(r"^[A-Za-z0-9 ._#()-]+$", re.UNICODE)
_VERSION_RE = re.compile(r"^(?P<stem>.+)_v(?P<ver>\d+)(?P<ext>\.[^.]+)?$", re.IGNORECASE)
_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def stock_designs_root(db_dir: Path) -> Path:
    root = (db_dir / STOCK_DESIGNS_DIRNAME).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_product_id(product_id: str) -> str:
    product_id = (product_id or "").strip()
    if not _PRODUCT_ID_RE.match(product_id):
        raise HTTPException(400, "Invalid product_id (numeric Shopify id required).")
    return product_id


def sanitize_product_name(name: str) -> str:
    name = (name or "").strip()
    name = _BAD_NAME_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "product"
    # Keep filenames readable but bounded
    return name[:120]


def product_folder(db_dir: Path, product_id: str, create: bool = False) -> Path:
    folder = stock_designs_root(db_dir) / safe_product_id(product_id)
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def next_stock_design_version(folder: Path) -> int:
    highest = 0
    if folder.exists():
        for p in folder.iterdir():
            if not p.is_file():
                continue
            m = _VERSION_RE.match(p.name)
            if m:
                highest = max(highest, int(m.group("ver")))
    return highest + 1


def list_stock_design_files(db_dir: Path, product_id: str) -> list[dict]:
    folder = product_folder(db_dir, product_id, create=False)
    if not folder.exists():
        return []
    out = []
    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        m = _VERSION_RE.match(p.name)
        version = int(m.group("ver")) if m else None
        stat = p.stat()
        out.append({
            "name": p.name,
            "version": version,
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "download": f"/stock-designs/{safe_product_id(product_id)}/files/{p.name}",
        })
    out.sort(key=lambda r: (r.get("version") or 0, r["name"]), reverse=True)
    return out


def save_stock_design_upload(
    db_dir: Path,
    product_id: str,
    product_name: str,
    upload: UploadFile,
    lock,
    *,
    max_upload_bytes: int,
    max_upload_mb: int,
) -> dict:
    product_id = safe_product_id(product_id)
    safe_name = sanitize_product_name(product_name)
    ext = Path(upload.filename or "designs.zip").suffix.lower() or ".zip"
    if ext != ".zip":
        # Force .zip extension — storefront expects a zip of designs
        ext = ".zip"

    folder = product_folder(db_dir, product_id, create=True)

    with lock:
        version = next_stock_design_version(folder)
        filename = f"{safe_name}_v{version}{ext}"
        final = folder / filename
        # Exclusive create so two concurrent uploads never share a name
        final.open("xb").close()

    size = 0
    try:
        with final.open("wb") as out:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_upload_bytes:
                    raise HTTPException(413, f"File exceeds the {max_upload_mb} MB limit.")
                out.write(chunk)
    except Exception:
        final.unlink(missing_ok=True)
        raise

    return {
        "product_id": product_id,
        "product_name": safe_name,
        "version": version,
        "filename": filename,
        "size_bytes": size,
        "path": f"stock designs/{product_id}/{filename}",
        "download": f"/stock-designs/{product_id}/files/{filename}",
    }


def latest_stock_design(db_dir: Path, product_id: str) -> Path | None:
    files = list_stock_design_files(db_dir, product_id)
    if not files:
        return None
    latest = files[0]  # already sorted newest first
    return product_folder(db_dir, product_id) / latest["name"]


# --------------------------------------------------------------------------- #
# FastAPI route registration helper
# Call register_stock_design_routes(app) near the bottom of the office API.
# --------------------------------------------------------------------------- #
def register_stock_design_routes(
    app,
    *,
    db_dir: Path,
    lock,
    require_key_dep,
    max_upload_bytes: int,
    max_upload_mb: int,
):
    """
    Example at the bottom of the office API:

        from stock_designs_addon import register_stock_design_routes
        register_stock_design_routes(
            app,
            db_dir=DB_DIR,
            lock=LOCK,
            require_key_dep=require_key,
            max_upload_bytes=MAX_UPLOAD_BYTES,
            max_upload_mb=MAX_UPLOAD_MB,
        )
    """

    @app.get("/stock-designs", dependencies=[Depends(require_key_dep)])
    def list_all_stock_design_products():
        root = stock_designs_root(db_dir)
        products = []
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("_"):
                continue
            if not _PRODUCT_ID_RE.match(child.name):
                continue
            files = list_stock_design_files(db_dir, child.name)
            products.append({
                "product_id": child.name,
                "file_count": len(files),
                "latest": files[0] if files else None,
            })
        return {"products": products, "count": len(products)}

    @app.get("/stock-designs/{product_id}", dependencies=[Depends(require_key_dep)])
    def get_product_stock_designs(product_id: str):
        product_id = safe_product_id(product_id)
        files = list_stock_design_files(db_dir, product_id)
        return {
            "product_id": product_id,
            "files": files,
            "latest": files[0] if files else None,
            "count": len(files),
        }

    @app.post("/stock-designs/{product_id}", dependencies=[Depends(require_key_dep)])
    def upload_stock_design(
        product_id: str,
        file: UploadFile = File(...),
        product_name: str = Form(""),
    ):
        if not file or not file.filename:
            raise HTTPException(400, "No file provided.")
        result = save_stock_design_upload(
            db_dir=db_dir,
            product_id=product_id,
            product_name=product_name or file.filename,
            upload=file,
            lock=lock,
            max_upload_bytes=max_upload_bytes,
            max_upload_mb=max_upload_mb,
        )
        return {"ok": True, **result}

    @app.get("/stock-designs/{product_id}/latest", dependencies=[Depends(require_key_dep)])
    def download_latest_stock_design(product_id: str):
        path = latest_stock_design(db_dir, product_id)
        if not path or not path.is_file():
            raise HTTPException(404, "No stock designs for this product.")
        return FileResponse(path, filename=path.name)

    @app.get(
        "/stock-designs/{product_id}/files/{filename}",
        dependencies=[Depends(require_key_dep)],
    )
    def download_stock_design_file(product_id: str, filename: str):
        product_id = safe_product_id(product_id)
        # Allow spaces and common punctuation in the stored filename
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(400, "Invalid filename.")
        path = product_folder(db_dir, product_id) / filename
        if not path.is_file():
            raise HTTPException(404, "File not found.")
        return FileResponse(path, filename=filename)

    @app.delete(
        "/stock-designs/{product_id}/files/{filename}",
        dependencies=[Depends(require_key_dep)],
    )
    def delete_stock_design_file(product_id: str, filename: str, permanent: bool = False):
        product_id = safe_product_id(product_id)
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(400, "Invalid filename.")
        path = product_folder(db_dir, product_id) / filename
        if not path.is_file():
            raise HTTPException(404, "File not found.")

        if permanent:
            path.unlink()
            return {
                "ok": True,
                "product_id": product_id,
                "filename": filename,
                "deleted": "permanent",
            }

        archive = stock_designs_root(db_dir) / "_Archive" / product_id
        archive.mkdir(parents=True, exist_ok=True)
        dest = archive / filename
        with lock:
            if dest.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                dest = archive / f"{path.stem}--{stamp}{path.suffix}"
            path.replace(dest)
        return {
            "ok": True,
            "product_id": product_id,
            "filename": filename,
            "deleted": "archived",
            "archived_as": dest.name,
        }
