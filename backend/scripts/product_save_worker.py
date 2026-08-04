#!/usr/bin/env python3
"""Background save worker — one daemon thread per Render instance.

Loop: reap stale jobs, claim the next queued job, run it in a subprocess
(``product_save_runner.py``), capture its stdout as the job log, then either
requeue (attempts remaining) or move the job to a terminal state. A verified
success refreshes the overview/detail/family caches via ``sync_product_snapshot``.

Guarded by ``SAVE_WORKER_ENABLED``. Free-tier Render instances sleep when idle,
which pauses the worker; ``reap_stale`` requeues anything left running when the
instance is woken or restarted.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPTS_DIR)
for _p in (_BACKEND_DIR, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.append(_p)

try:
    from config import (  # type: ignore
        SAVE_WORKER_ENABLED,
        SAVE_QUEUE_POLL_SEC,
        SAVE_JOB_TIMEOUT_SEC,
    )
except Exception:
    SAVE_WORKER_ENABLED = True
    SAVE_QUEUE_POLL_SEC = 2
    SAVE_JOB_TIMEOUT_SEC = 600

try:
    import product_save_queue as queue  # type: ignore
except Exception:  # pragma: no cover
    from scripts import product_save_queue as queue  # type: ignore

_RUNNER = os.path.join(_SCRIPTS_DIR, "product_save_runner.py")
_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
_started = False
_started_lock = threading.Lock()
_PRUNE_EVERY_SEC = 3600.0


def _parse_result(stdout: str) -> dict:
    """Pull the last ``RESULT_JSON:{...}`` line out of the runner output."""
    import json

    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("RESULT_JSON:"):
            try:
                return json.loads(line[len("RESULT_JSON:"):])
            except Exception:
                return {}
    return {}


def _run_job(job: dict) -> None:
    job_id = job["job_id"]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    timeout = int(SAVE_JOB_TIMEOUT_SEC)

    try:
        proc = subprocess.run(
            [sys.executable, _RUNNER, job_id],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=_BACKEND_DIR,
            env=env,
            timeout=timeout,
        )
        logs = (proc.stdout or "")
        if proc.stderr:
            logs += "\n--- stderr ---\n" + proc.stderr
        result = _parse_result(proc.stdout)
    except subprocess.TimeoutExpired as exc:
        logs = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        logs += f"\n💥 Runner timed out after {timeout}s"
        result = {"ok": False, "success": False, "verify": [], "error": "timeout"}

    ok = bool(result.get("ok"))
    verify = result.get("verify") or []
    error = result.get("error")
    product_id = result.get("product_id") or job.get("product_id")

    if ok:
        queue.complete(job_id, "done", verify=verify, logs=logs, error=None)
        _refresh_caches(product_id)
        print(f"[save-worker] job {job_id} done (product {product_id})", flush=True)
        return

    # Not ok — refresh the claimed job to read the incremented attempt count.
    current = queue.get_job(job_id) or job
    attempts = int(current.get("attempts", 0))
    max_attempts = int(current.get("max_attempts", 1))
    if attempts < max_attempts:
        queue.requeue(job_id, error=error, logs=logs, verify=verify)
        print(f"[save-worker] job {job_id} requeued ({attempts}/{max_attempts}): {error}", flush=True)
    else:
        queue.complete(job_id, "failed", verify=verify, logs=logs, error=error)
        print(f"[save-worker] job {job_id} FAILED after {attempts} attempt(s): {error}", flush=True)


def _refresh_caches(product_id) -> None:
    if not product_id:
        return
    try:
        from product_creator.Product_Creator import sync_product_snapshot  # type: ignore
    except Exception:
        try:
            from scripts.product_creator.Product_Creator import sync_product_snapshot  # type: ignore
        except Exception:
            return
    try:
        sync_product_snapshot(product_id)
    except Exception as exc:
        print(f"[save-worker] snapshot refresh skipped for {product_id}: {exc}", flush=True)


def _loop() -> None:
    poll = max(1, int(SAVE_QUEUE_POLL_SEC))
    last_prune = 0.0
    print(f"[save-worker] started ({_WORKER_ID}), polling every {poll}s", flush=True)
    while True:
        try:
            queue.reap_stale()
            now = time.time()
            if now - last_prune > _PRUNE_EVERY_SEC:
                queue.prune()
                last_prune = now
            job = queue.claim_next(_WORKER_ID)
            if job:
                print(f"[save-worker] claimed job {job['job_id']} ({job.get('title')})", flush=True)
                _run_job(job)
                continue  # drain the queue without waiting a full poll
        except Exception as exc:
            print(f"[save-worker] loop error: {exc}", flush=True)
        time.sleep(poll)


def start_worker(app=None) -> None:
    """Start the single background worker thread (idempotent)."""
    global _started
    if not SAVE_WORKER_ENABLED:
        print("[save-worker] disabled via SAVE_WORKER_ENABLED", flush=True)
        return
    with _started_lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_loop, name="product-save-worker", daemon=True)
    t.start()
