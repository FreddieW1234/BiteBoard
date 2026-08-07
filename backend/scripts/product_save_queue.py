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
        SAVE_HEARTBEAT_STALE_SEC,
    )
except Exception:
    SAVE_MAX_ATTEMPTS = 3
    SAVE_JOB_TIMEOUT_SEC = 600
    SAVE_JOB_RETENTION_H = 24
    SAVE_HEARTBEAT_STALE_SEC = 180

KIND = "save_job"
# Big/append-heavy fields live in their own items so the polled job list stays
# tiny. The job item holds only summary fields; data (create_product input) and
# logs (streamed output) are fetched on demand.
DATA_KIND = "save_job_data"
LOG_KIND = "save_job_log"
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


def _save_data(job_id: str, data: dict) -> None:
    """Store the create_product input separately from the summary job item."""
    office_api.put_snapshot_item(DATA_KIND, str(job_id), {"data": data}, updated_by="render")


def get_job_data(job_id: str):
    """The create_product input for a job (used by the runner). None if absent."""
    if not _available() or not job_id:
        return None
    try:
        item = office_api.get_snapshot_item(DATA_KIND, str(job_id))
    except Exception:
        item = None
    if isinstance(item, dict) and isinstance(item.get("payload"), dict):
        return item["payload"].get("data")
    # Back-compat: older jobs stored data inline on the job item.
    job = get_job(job_id)
    return (job or {}).get("data")


def _save_logs(job_id: str, logs) -> None:
    """Best-effort store of a job's captured output, separate from the job item."""
    try:
        office_api.put_snapshot_item(LOG_KIND, str(job_id), {"logs": logs or ""}, updated_by="render")
    except Exception:
        pass


def get_logs(job_id: str) -> str:
    """A job's captured output (Logs tab). Empty string if none."""
    if not _available() or not job_id:
        return ""
    try:
        item = office_api.get_snapshot_item(LOG_KIND, str(job_id))
    except Exception:
        item = None
    if isinstance(item, dict) and isinstance(item.get("payload"), dict):
        return item["payload"].get("logs") or ""
    # Back-compat: older jobs stored logs inline on the job item.
    job = get_job(job_id)
    return (job or {}).get("logs") or ""


# --------------------------------------------------------------------------- #
# Queue operations
# --------------------------------------------------------------------------- #
def enqueue(data: dict, product_id=None, title: str = "", locked_ids=None) -> dict:
    """Create a queued save job and return it. Binary media is never stored.

    locked_ids: product ids that this job locks for editing. For a parent save
    this includes the parent plus every child it will propagate to, so children
    cannot be edited while the save is in flight.
    """
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
    # Stamp into the payload the runner uses — job.product_id alone is not enough;
    # create_product() only updates when data["product_id"] is set.
    if pid is not None:
        data["product_id"] = pid
    locked = set()
    if pid is not None:
        locked.add(pid)
    for cid in (locked_ids or []):
        try:
            locked.add(int(cid))
        except (TypeError, ValueError):
            pass
    job = {
        "job_id": uuid.uuid4().hex,
        "product_id": pid,
        "locked_ids": sorted(locked),
        "title": (title or data.get("title") or "").strip() or "Untitled product",
        "status": "queued",
        "attempts": 0,
        "max_attempts": int(SAVE_MAX_ATTEMPTS),
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "worker_id": None,
        "verify": [],
        "error": None,
    }
    # Heavy fields go in their own items so the polled job list stays tiny.
    _save_data(job["job_id"], data)
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


def _yield_to_earlier_runner(job_id, claimed) -> bool:
    """Put a just-claimed job back if another worker started one at the same moment.

    Both sides break the tie on (started_at, worker_id), which is a total order,
    so exactly one of them wins and the other returns its job to the queue.
    """
    try:
        others = [j for j in list_jobs()
                  if j.get("status") == "running" and j.get("job_id") != job_id]
    except Exception:
        return False
    if not others:
        return False

    def rank(j):
        return (j.get("started_at") or "", str(j.get("worker_id") or ""))

    if all(rank(claimed) <= rank(o) for o in others):
        return False  # we got there first

    claimed["status"] = "queued"
    claimed["worker_id"] = None
    claimed["started_at"] = None
    claimed["attempts"] = max(0, int(claimed.get("attempts", 1)) - 1)
    try:
        _save(claimed)
    except Exception:
        pass
    return True


def claim_next(worker_id: str, jobs=None):
    """Claim the oldest queued job for this worker, or None.

    Saves run one at a time across *every* instance, not just within one worker.
    Each instance runs its own worker, and two saves at once would share the same
    Shopify rate budget and each spawn a subprocess on an already small CPU
    share. The office store is last-write-wins with no compare-and-swap, so
    exclusivity is done in two steps: never claim while something is running,
    then re-read and stand down if another worker claimed at the same moment.

    Pass an already-fetched job list to avoid a second office round-trip.
    """
    if not _available():
        return None
    jobs = jobs if jobs is not None else list_jobs()
    # A stalled job is one reap_stale is about to requeue, so it must not count
    # as the live save that holds everyone else back.
    if any(j.get("status") == "running" and not is_stalled(j) for j in jobs):
        return None

    for job in jobs:
        if job.get("status") != "queued":
            continue
        job_id = job["job_id"]
        job["status"] = "running"
        job["worker_id"] = worker_id
        job["started_at"] = _now_iso()
        job["heartbeat_at"] = _now_iso()
        job["attempts"] = int(job.get("attempts", 0)) + 1
        try:
            _save(job)
        except Exception:
            continue
        confirm = get_job(job_id)
        if not (
            confirm
            and confirm.get("worker_id") == worker_id
            and confirm.get("status") == "running"
        ):
            continue  # lost the race for this job; try the next queued one
        if _yield_to_earlier_runner(job_id, confirm):
            return None
        return confirm
    return None


def heartbeat(job_id: str) -> None:
    """Mark a running job as still alive.

    Because saves are serialised across instances, a job left 'running' by an
    instance that died would otherwise block the whole queue until the full job
    timeout. reap_stale uses this to tell a crashed worker from a slow one.
    """
    job = get_job(job_id)
    if not job or job.get("status") != "running":
        return
    job["heartbeat_at"] = _now_iso()
    try:
        _save(job)
    except Exception:
        pass


def complete(job_id: str, status: str, verify=None, logs=None, error=None):
    """Move a job to a terminal state (done|failed|cancelled) with results."""
    job = get_job(job_id)
    if not job:
        return None
    job["status"] = status
    job["finished_at"] = _now_iso()
    if verify is not None:
        job["verify"] = verify
    job["error"] = error
    job.pop("logs", None)   # logs live in their own item now
    job.pop("data", None)
    _save(job)
    if logs is not None:
        _save_logs(job_id, logs)
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
    if verify is not None:
        job["verify"] = verify
    job.pop("logs", None)
    _save(job)
    if logs is not None:
        _save_logs(job_id, logs)
    return job


def set_progress(job_id: str, logs) -> bool:
    """Stream partial logs for a still-running job so the UI can show them live.

    Only the separate log item is written (the summary job item is left alone) so
    the frequently-polled job list never carries the growing log text. Returns
    False when the job is no longer running (e.g. cancelled) so the worker can
    stop the subprocess.
    """
    job = get_job(job_id)
    if not job:
        return False
    if job.get("status") != "running":
        return False
    _save_logs(job_id, logs)
    return True


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


def is_stalled(job, now=None) -> bool:
    """True when a running job has stopped proving its worker is alive.

    claim_next always stamps a heartbeat, so a running job whose heartbeat — or,
    for one claimed by an older build, whose start time — is older than the
    window has lost its worker. Saves are serialised across instances, so a
    stalled job holds up everything behind it until it is reclaimed.
    """
    if job.get("status") != "running":
        return False
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    silent = _age_seconds(job.get("heartbeat_at") or job.get("started_at"), now)
    if silent is not None and silent > int(SAVE_HEARTBEAT_STALE_SEC):
        return True
    ran_for = _age_seconds(job.get("started_at"), now)
    return ran_for is not None and ran_for > int(SAVE_JOB_TIMEOUT_SEC)


def retry(job_id: str):
    """Requeue a job from scratch (attempts reset).

    Failed and cancelled jobs can always be retried. A *stalled* running job can
    too: that is the manual escape hatch for a worker that died mid-save and is
    now blocking the queue.
    """
    job = get_job(job_id)
    if not job:
        return None
    if job.get("status") not in ("failed", "cancelled") and not is_stalled(job):
        return job
    job["status"] = "queued"
    job["attempts"] = 0
    job["worker_id"] = None
    job["started_at"] = None
    job["heartbeat_at"] = None
    job["finished_at"] = None
    job["error"] = None
    _save(job)
    return job


def reap_stale(jobs=None):
    """Requeue (or fail) running jobs whose worker died mid-run.

    Pass an already-fetched job list to avoid a second office round-trip.
    """
    if not _available():
        return 0
    now = datetime.now(timezone.utc).timestamp()
    reaped = 0
    for job in (jobs if jobs is not None else list_jobs()):
        if not is_stalled(job, now):
            continue
        if int(job.get("attempts", 0)) < int(job.get("max_attempts", SAVE_MAX_ATTEMPTS)):
            job["status"] = "queued"
            job["worker_id"] = None
            job["started_at"] = None
            job["heartbeat_at"] = None
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


def locked_product_ids(jobs=None) -> list:
    """Product ids with an active (queued/running) save — these are locked.

    Includes any child products the job will propagate to (job['locked_ids']).
    Pass an already-fetched job list to avoid a second office round-trip.
    """
    ids = set()
    for job in (jobs if jobs is not None else list_jobs()):
        if job.get("status") not in ACTIVE:
            continue
        locked = job.get("locked_ids")
        if not locked and job.get("product_id") is not None:
            locked = [job["product_id"]]
        for pid in (locked or []):
            try:
                ids.add(int(pid))
            except (TypeError, ValueError):
                pass
    return sorted(ids)


def prune(retention_h=None, jobs=None):
    """Delete terminal jobs older than the retention window."""
    if not _available():
        return 0
    hours = float(retention_h if retention_h is not None else SAVE_JOB_RETENTION_H)
    cutoff = hours * 3600.0
    now = datetime.now(timezone.utc).timestamp()
    removed = 0
    for job in (jobs if jobs is not None else list_jobs()):
        if job.get("status") not in TERMINAL:
            continue
        age = _age_seconds(job.get("finished_at") or job.get("created_at"), now)
        if age is not None and age > cutoff:
            jid = job["job_id"]
            try:
                deleted = office_api.delete_snapshot_item(KIND, jid)
            except Exception:
                deleted = False
            for extra in (DATA_KIND, LOG_KIND):
                try:
                    office_api.delete_snapshot_item(extra, jid)
                except Exception:
                    pass
            if deleted:
                removed += 1
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


def _intended_parent_child_value(intended_data: dict) -> str:
    """Best-effort parent_child value from the save payload."""
    raw = (intended_data or {}).get("parent_child")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    for mf in (intended_data or {}).get("metafields") or []:
        if not isinstance(mf, dict):
            continue
        if (mf.get("namespace") or "custom") != "custom":
            continue
        if mf.get("key") in ("parent_child", "parent_child2"):
            val = mf.get("value")
            if val is None:
                continue
            s = str(val).strip()
            if s.startswith("["):
                try:
                    import json
                    arr = json.loads(s)
                    if isinstance(arr, list) and arr:
                        s = str(arr[0]).strip()
                except Exception:
                    pass
            if s:
                return s
    return ""


def _child_inherited_keys_to_skip(intended_data: dict) -> set:
    """
    Child saves overwrite these from the live parent in create_product.
    Comparing them to form values (often new-product defaults like leadtime 5/10)
    causes false verification mismatches.
    """
    pc = _intended_parent_child_value(intended_data)
    if not pc.lower().startswith("child"):
        return set()
    try:
        from product_creator.Product_Creator import PARENT_TO_CHILD_PROPAGATE_METAFIELD_KEYS  # type: ignore
        return set(PARENT_TO_CHILD_PROPAGATE_METAFIELD_KEYS)
    except Exception:
        try:
            from scripts.product_creator.Product_Creator import PARENT_TO_CHILD_PROPAGATE_METAFIELD_KEYS  # type: ignore
            return set(PARENT_TO_CHILD_PROPAGATE_METAFIELD_KEYS)
        except Exception:
            # Fallback includes the lead-time keys that were mismatching.
            return {
                "leadtime1", "leadtime2", "leadtime3",
                "moq", "origination", "shelf_life", "unit_weight",
                "case_quantity", "case_weight", "product_size",
            }


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
    skip_inherited = _child_inherited_keys_to_skip(intended_data or {})

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
        # Child products inherit these from the parent after save — form values
        # (e.g. default lead times 5/10) are not the source of truth.
        if key in skip_inherited:
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

    # Top-level parent_child is never in the metafields array the client sends —
    # create_product writes it separately. Check it when a value was intended.
    want_pc = _intended_parent_child_value(intended_data or {})
    clear_pc_raw = (intended_data or {}).get("clear_parent_child", False)
    if isinstance(clear_pc_raw, str):
        clear_pc = clear_pc_raw.lower() in ("true", "1", "yes")
    else:
        clear_pc = bool(clear_pc_raw)
    if want_pc or clear_pc:
        got_pc = ""
        for key in ("parent_child", "parent_child2"):
            raw = actual_mf.get(("custom", key))
            if raw is None or str(raw).strip() == "":
                continue
            s = str(raw).strip()
            if s.startswith("["):
                try:
                    import json
                    arr = json.loads(s)
                    if isinstance(arr, list) and arr:
                        s = str(arr[0]).strip()
                except Exception:
                    pass
            if s.lower().startswith("parent") or s.lower().startswith("child"):
                got_pc = s
                break
        if clear_pc and not want_pc:
            rows.append({
                "field": "parent_child",
                "intended": "(cleared)",
                "actual": got_pc or "(empty)",
                "ok": not got_pc,
            })
        elif want_pc:
            rows.append({
                "field": "parent_child",
                "intended": want_pc,
                "actual": got_pc or "(empty)",
                "ok": _norm(want_pc) == _norm(got_pc),
            })

    return rows
