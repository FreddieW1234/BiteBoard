#!/usr/bin/env python3
"""Durable product-save queue backed by the office snapshot store.

Each queued save is one office snapshot item under kind ``save_job``. The item
id is the job id (a uuid hex, which matches the office id regex). This gives us a
queue that survives Render restarts and is shared across Render instances without
any new office-side code — it reuses the existing snapshot-item client methods.

Job payload shape::

    {
      job_id, product_id|None, title,
      status: queued|running|done|failed|cancelled,
      attempts, max_attempts,
      created_at, started_at, finished_at, worker_id,
      data,     # create_product() input (media referenced by id, no binary)
      verify,   # list of {field, intended, actual, ok}
      logs,     # captured save output (str)
      error,    # last error message (str|None)
    }
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

# Make ``config`` and sibling scripts importable regardless of entry point.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPTS_DIR)
for _p in (_BACKEND_DIR, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.append(_p)

try:
    from scripts import office_api  # type: ignore
except Exception:  # pragma: no cover
    try:
        import office_api  # type: ignore
    except Exception:
        office_api = None  # type: ignore

try:
    from config import (  # type: ignore
        SAVE_MAX_ATTEMPTS,
        SAVE_JOB_TIMEOUT_SEC,
        SAVE_JOB_RETENTION_H,
    )
except Exception:
    SAVE_MAX_ATTEMPTS = 3
    SAVE_JOB_TIMEOUT_SEC = 600
    SAVE_JOB_RETENTION_H = 24

KIND = "save_job"
TERMINAL = ("done", "failed", "cancelled")
ACTIVE = ("queued", "running")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _available() -> bool:
    return office_api is not None and bool(getattr(office_api, "OFFICE_API_URL", None))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_seconds(iso, now=None):
    """Seconds since an ISO-8601 timestamp, or None if it can't be parsed."""
    if not iso:
        return None
    try:
        s = str(iso).replace("Z", "+00:00")
        ts = datetime.fromisoformat(s).timestamp()
        return (now if now is not None else datetime.now(timezone.utc).timestamp()) - ts
    except Exception:
        return None


def _save(job: dict) -> None:
    office_api.put_snapshot_item(KIND, job["job_id"], job, updated_by="render")


# --------------------------------------------------------------------------- #
# Queue operations
# --------------------------------------------------------------------------- #
def enqueue(data: dict, product_id=None, title: str = "") -> dict:
    """Create a queued save job and return it. Binary media is never stored."""
    if not _available():
        raise RuntimeError("Office snapshot store is not configured")
    data = dict(data or {})
    data["media_files"] = []  # binary is uploaded synchronously before enqueue
    pid = None
    if product_id is not None:
        try:
            pid = int(product_id)
        except (TypeError, ValueError):
            pid = None
    job = {
        "job_id": uuid.uuid4().hex,
        "product_id": pid,
        "title": (title or data.get("title") or "").strip() or "Untitled product",
        "status": "queued",
        "attempts": 0,
        "max_attempts": int(SAVE_MAX_ATTEMPTS),
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "worker_id": None,
        "data": data,
        "verify": [],
        "logs": "",
        "error": None,
    }
    _save(job)
    return job


def list_jobs() -> list:
    """All jobs, oldest first. Empty list if the store is unavailable."""
    if not _available():
        return []
    try:
        items = office_api.get_snapshot_items(KIND, include_payload=True)
    except Exception:
        return []
    jobs = [it.get("payload") for it in items if isinstance(it.get("payload"), dict)]
    jobs.sort(key=lambda j: j.get("created_at") or "")
    return jobs


def get_job(job_id: str):
    """One job payload, or None."""
    if not _available() or not job_id:
        return None
    try:
        item = office_api.get_snapshot_item(KIND, str(job_id))
    except Exception:
        return None
    if isinstance(item, dict) and isinstance(item.get("payload"), dict):
        return item["payload"]
    return None


def claim_next(worker_id: str):
    """Claim the oldest queued job for this worker, or None if none are queued.

    Marks it running (attempts++), then re-reads it to confirm ownership. The
    re-read narrows the window where two Render instances grab the same job
    (last write wins on the office side).
    """
    if not _available():
        return None
    for job in list_jobs():
        if job.get("status") != "queued":
            continue
        job["status"] = "running"
        job["worker_id"] = worker_id
        job["started_at"] = _now_iso()
        job["attempts"] = int(job.get("attempts", 0)) + 1
        try:
            _save(job)
        except Exception:
            continue
        confirm = get_job(job["job_id"])
        if (
            confirm
            and confirm.get("worker_id") == worker_id
            and confirm.get("status") == "running"
        ):
            return confirm
        # Lost the race — someone else owns it now; try the next queued job.
    return None


def complete(job_id: str, status: str, verify=None, logs=None, error=None):
    """Move a job to a terminal state (done|failed|cancelled) with results."""
    job = get_job(job_id)
    if not job:
        return None
    job["status"] = status
    job["finished_at"] = _now_iso()
    if verify is not None:
        job["verify"] = verify
    if logs is not None:
        job["logs"] = logs
    job["error"] = error
    _save(job)
    return job


def requeue(job_id: str, error=None, logs=None, verify=None):
    """Put a running job back in the queue (retry with attempts preserved)."""
    job = get_job(job_id)
    if not job:
        return None
    job["status"] = "queued"
    job["worker_id"] = None
    job["started_at"] = None
    if error:
        job["error"] = error
    if logs is not None:
        job["logs"] = logs
    if verify is not None:
        job["verify"] = verify
    _save(job)
    return job


def cancel(job_id: str):
    """Cancel a job (queued/running/failed). Done jobs are left untouched."""
    job = get_job(job_id)
    if not job:
        return None
    if job.get("status") == "done":
        return job
    job["status"] = "cancelled"
    job["finished_at"] = _now_iso()
    _save(job)
    return job


def retry(job_id: str):
    """Requeue a failed/cancelled job from scratch (attempts reset)."""
    job = get_job(job_id)
    if not job:
        return None
    if job.get("status") not in ("failed", "cancelled"):
        return job
    job["status"] = "queued"
    job["attempts"] = 0
    job["worker_id"] = None
    job["started_at"] = None
    job["finished_at"] = None
    job["error"] = None
    _save(job)
    return job


def reap_stale(timeout=None):
    """Requeue (or fail) running jobs orphaned by a restart/crash mid-run."""
    if not _available():
        return 0
    limit = int(timeout if timeout is not None else SAVE_JOB_TIMEOUT_SEC)
    now = datetime.now(timezone.utc).timestamp()
    reaped = 0
    for job in list_jobs():
        if job.get("status") != "running":
            continue
        age = _age_seconds(job.get("started_at"), now)
        if age is None or age <= limit:
            continue
        if int(job.get("attempts", 0)) < int(job.get("max_attempts", SAVE_MAX_ATTEMPTS)):
            job["status"] = "queued"
            job["worker_id"] = None
            job["started_at"] = None
            job["error"] = "Requeued after stalling (worker restart/timeout)"
        else:
            job["status"] = "failed"
            job["finished_at"] = _now_iso()
            job["error"] = "Timed out with no attempts remaining"
        try:
            _save(job)
            reaped += 1
        except Exception:
            pass
    return reaped


def locked_product_ids() -> list:
    """Product ids with an active (queued/running) save — these are locked."""
    ids = set()
    for job in list_jobs():
        if job.get("status") in ACTIVE and job.get("product_id") is not None:
            try:
                ids.add(int(job["product_id"]))
            except (TypeError, ValueError):
                pass
    return sorted(ids)


def prune(retention_h=None):
    """Delete terminal jobs older than the retention window."""
    if not _available():
        return 0
    hours = float(retention_h if retention_h is not None else SAVE_JOB_RETENTION_H)
    cutoff = hours * 3600.0
    now = datetime.now(timezone.utc).timestamp()
    removed = 0
    for job in list_jobs():
        if job.get("status") not in TERMINAL:
            continue
        age = _age_seconds(job.get("finished_at") or job.get("created_at"), now)
        if age is not None and age > cutoff:
            try:
                if office_api.delete_snapshot_item(KIND, job["job_id"]):
                    removed += 1
            except Exception:
                pass
    return removed


# --------------------------------------------------------------------------- #
# Post-save verification — cross-check what we intended against what Shopify has
# --------------------------------------------------------------------------- #
_PRICE_KEYS = {"pricejsontr", "pricejsoner"}


def _norm(value):
    """Best-effort structural normalisation so equal-but-reformatted JSON matches."""
    if value is None:
        return ""
    s = value if isinstance(value, str) else str(value)
    s = s.strip()
    try:
        import json

        return json.dumps(json.loads(s), sort_keys=True, separators=(",", ":"))
    except Exception:
        return s


def verify_product(intended_data: dict, product_id) -> list:
    """Re-read the product from Shopify and diff it against what was intended.

    Returns a list of ``{field, intended, actual, ok}`` rows. Price metafields
    are checked for presence only (Price Bandit rewrites their exact contents in
    the background, so an exact match would give false failures). Blank intended
    values are skipped because create_product substitutes/deletes them.
    """
    # Read live from Shopify. NOT get_product_detail(refresh=True): that still
    # returns the cached office snapshot and only refreshes in the background, so
    # it would compare against pre-save data and always report a mismatch.
    try:
        from product_creator.Product_Creator import _build_product_detail_from_shopify as _live_detail  # type: ignore
    except Exception:
        from scripts.product_creator.Product_Creator import _build_product_detail_from_shopify as _live_detail  # type: ignore

    detail = _live_detail(product_id)
    if not detail or not detail.get("id"):
        return [{
            "field": "product",
            "intended": "readable",
            "actual": "fetch failed",
            "ok": False,
        }]

    rows = []

    # Title
    want_title = (intended_data.get("title") or "").strip()
    if want_title:
        got_title = (detail.get("title") or "").strip()
        rows.append({
            "field": "title",
            "intended": want_title,
            "actual": got_title,
            "ok": want_title == got_title,
        })

    # Build an actual (namespace, key) -> value map from the live metafields.
    actual_mf = {}
    for mf in (detail.get("metafields") or []):
        ns = (mf.get("namespace") or "custom")
        key = mf.get("key")
        if key:
            actual_mf[(ns, key)] = mf.get("value")

    for mf in (intended_data.get("metafields") or []):
        if not isinstance(mf, dict):
            continue
        key = mf.get("key")
        if not key:
            continue
        ns = (mf.get("namespace") or "custom")
        want = mf.get("value")
        got = actual_mf.get((ns, key))
        if key in _PRICE_KEYS:
            # Only verify prices that were meant to be set; cleared prices are skipped.
            if want is None or str(want).strip() in ("", "[]", "{}"):
                continue
            ok = got is not None and str(got).strip() not in ("", "[]", "{}")
            rows.append({
                "field": f"{ns}.{key}",
                "intended": "present",
                "actual": "present" if ok else "missing",
                "ok": ok,
            })
        else:
            # Skip blank intended values: create_product stores "-" or deletes them,
            # so an exact comparison would give false mismatches.
            if want is None or str(want).strip() == "":
                continue
            ok = _norm(want) == _norm(got)
            rows.append({
                "field": f"{ns}.{key}",
                "intended": want,
                "actual": got,
                "ok": ok,
            })

    return rows
