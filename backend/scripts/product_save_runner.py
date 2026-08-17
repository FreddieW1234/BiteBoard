#!/usr/bin/env python3
"""Save runner - applies one queued product save in its own process.

Run as: ``python product_save_runner.py <job_id>``

Running the save in a subprocess gives clean per-job log capture (everything on
stdout becomes the job's log) and crash isolation, mirroring the existing
Price Bandit subprocess pattern. The final stdout line is always::

    RESULT_JSON:{"ok": bool, "success": bool, "verify": [...], "error": str|None}

so the worker can parse the outcome even if the save printed a lot before it.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

# Make ``config`` and sibling scripts importable when run as a bare script.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPTS_DIR)
for _p in (_BACKEND_DIR, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.append(_p)


def _emit(result: dict) -> None:
    # Always the very last line so the worker can find it deterministically.
    print("RESULT_JSON:" + json.dumps(result), flush=True)


def main(argv) -> int:
    if len(argv) < 2:
        _emit({"ok": False, "success": False, "verify": [], "error": "missing job_id"})
        return 2

    job_id = argv[1]

    try:
        import product_save_queue as queue  # type: ignore
    except Exception:
        from scripts import product_save_queue as queue  # type: ignore

    job = queue.get_job(job_id)
    if not job:
        _emit({"ok": False, "success": False, "verify": [], "error": f"job {job_id} not found"})
        return 1

    data = queue.get_job_data(job_id) or {}
    print(f"[run] Running save job {job_id} - {job.get('title')!r} (attempt {job.get('attempts')})", flush=True)

    try:
        from product_creator.Product_Creator import create_product  # type: ignore
    except Exception:
        from scripts.product_creator.Product_Creator import create_product  # type: ignore

    try:
        result = create_product(data)
    except Exception as exc:
        print("[error] create_product raised:", exc, flush=True)
        traceback.print_exc()
        _emit({"ok": False, "success": False, "verify": [], "error": str(exc)})
        return 1

    success = bool(isinstance(result, dict) and result.get("success"))
    product_id = None
    if isinstance(result, dict):
        product_id = (result.get("product") or {}).get("id") or result.get("product_id")
    if not product_id:
        product_id = data.get("product_id")

    error = None
    if not success:
        error = (result or {}).get("error") if isinstance(result, dict) else "create_product failed"
        print(f"[error] Save failed: {error}", flush=True)
        _emit({"ok": False, "success": False, "verify": [], "error": error})
        return 1

    print(f"[ok] Save applied to product {product_id}. Verifying against Shopify...", flush=True)

    verify = []
    try:
        verify = queue.verify_product(data, product_id)
    except Exception as exc:
        print("[warn] Verification raised:", exc, flush=True)
        traceback.print_exc()
        verify = [{"field": "verify", "intended": "runs", "actual": str(exc), "ok": False}]

    ok = success and all(row.get("ok") for row in verify)
    if ok:
        print("[ok] Verification passed - Shopify matches the intended save.", flush=True)
    else:
        bad = [r for r in verify if not r.get("ok")]
        print(f"[warn] Verification mismatch on {len(bad)} field(s) (advisory - save still applied):", flush=True)
        for r in bad:
            print(f"   - {r.get('field')}: intended={r.get('intended')!r} actual={r.get('actual')!r}", flush=True)

    # Collect every product this save wrote (parent + children + family image edits)
    # so the worker can cross-check them into the office DB immediately.
    try:
        from product_creator.Product_Creator import product_ids_from_save_result  # type: ignore
    except Exception:
        from scripts.product_creator.Product_Creator import product_ids_from_save_result  # type: ignore
    cross_check_ids = product_ids_from_save_result(result if isinstance(result, dict) else {}, product_id)

    # Verification is advisory: a successful create_product completes the job.
    # The diff is surfaced in the logs/Queue for inspection, but a mismatch does
    # not fail the save (create_product normalises some values, and the write did
    # reach Shopify). Genuine save errors are handled by the `not success` path above.
    _emit({
        "ok": success,
        "success": success,
        "product_id": product_id,
        "cross_check_ids": cross_check_ids,
        "verify": verify,
        "verify_ok": ok,
        "error": None,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
