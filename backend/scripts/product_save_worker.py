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
        SAVE_QUEUE_IDLE_POLL_SEC,
        SAVE_JOB_TIMEOUT_SEC,
        SAVE_MIN_FREE_MB,
    )
except Exception:
    SAVE_WORKER_ENABLED = True
    SAVE_QUEUE_POLL_SEC = 2
    SAVE_QUEUE_IDLE_POLL_SEC = 15
    SAVE_JOB_TIMEOUT_SEC = 1800
    SAVE_MIN_FREE_MB = 150

try:
    import product_save_queue as queue  # type: ignore
except Exception:  # pragma: no cover
    from scripts import product_save_queue as queue  # type: ignore

_RUNNER = os.path.join(_SCRIPTS_DIR, "product_save_runner.py")
_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
_started = False
_started_lock = threading.Lock()
_PRUNE_EVERY_SEC = 3600.0
_LOG_FLUSH_SEC = 3.0        # how often to push partial logs to the job record
_HEARTBEAT_SEC = 30.0       # how often to prove this worker is still alive
_MAX_LOG_CHARS = 200_000    # cap stored log size (keep the most recent output)


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
    env["PYTHONUNBUFFERED"] = "1"  # child flushes stdout promptly so logs stream live
    timeout = int(SAVE_JOB_TIMEOUT_SEC)

    # Stream the runner's output so the Queue → Logs tab shows progress live
    # instead of only at the end. A reader thread appends lines; this loop
    # flushes the accumulated log to the job record every few seconds and
    # enforces the timeout even if the child goes silent.
    proc = subprocess.Popen(
        [sys.executable, _RUNNER, job_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=_BACKEND_DIR,
        env=env,
        bufsize=1,
    )

    lines: list = []
    lines_lock = threading.Lock()

    def _reader():
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                with lines_lock:
                    lines.append(line)
        except Exception:
            pass

    reader = threading.Thread(target=_reader, name=f"save-log-{job_id[:8]}", daemon=True)
    reader.start()

    def _current_logs() -> str:
        with lines_lock:
            text = "".join(lines)
        return text[-_MAX_LOG_CHARS:]

    start = time.time()
    last_flush = 0.0
    last_beat = start
    timed_out = False
    while True:
        finished = proc.poll() is not None and not reader.is_alive()
        now = time.time()
        if not finished and now - start > timeout:
            timed_out = True
            try:
                proc.kill()
            except Exception:
                pass
            break
        if now - last_beat >= _HEARTBEAT_SEC:
            last_beat = now
            queue.heartbeat(job_id)
        if now - last_flush >= _LOG_FLUSH_SEC:
            last_flush = now
            # If the job was cancelled externally, stop the subprocess.
            if not queue.set_progress(job_id, _current_logs()):
                try:
                    proc.kill()
                except Exception:
                    pass
                print(f"[save-worker] job {job_id} no longer running — stopped subprocess", flush=True)
                return
        if finished:
            break
        time.sleep(0.5)

    reader.join(timeout=2)
    logs = _current_logs()
    if timed_out:
        logs += f"\n💥 Runner timed out after {timeout}s"
        result = {"ok": False, "success": False, "verify": [], "error": "timeout"}
    else:
        result = _parse_result(logs)

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


def _available_mb():
    """Available RAM in MB from /proc/meminfo (Linux), or None if unknown."""
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        return None
    return None


def _enough_memory() -> bool:
    """True unless the instance is close to OOM (guards the save subprocess)."""
    avail = _available_mb()
    if avail is None:
        return True  # can't measure (e.g. dev/Windows) — don't block saves
    return avail >= float(SAVE_MIN_FREE_MB)


def _loop() -> None:
    poll = max(1, int(SAVE_QUEUE_POLL_SEC))
    idle_poll = max(poll, int(SAVE_QUEUE_IDLE_POLL_SEC))
    last_prune = 0.0
    last_mem_warn = 0.0
    print(f"[save-worker] started ({_WORKER_ID}), polling every {poll}s (idle {idle_poll}s)", flush=True)
    while True:
        idle = True
        try:
            # One office round-trip per pass, shared by reap/prune/claim. This
            # loop runs forever on every instance, so an extra call here is a
            # permanent tax on the office server that every page read competes
            # with.
            jobs = queue.list_jobs()
            idle = not any(j.get("status") in ("queued", "running") for j in jobs)

            queue.reap_stale(jobs=jobs)
            now = time.time()
            if now - last_prune > _PRUNE_EVERY_SEC:
                queue.prune(jobs=jobs)
                last_prune = now
            # Defer starting a heavy save subprocess when memory is tight, so we
            # never OOM-kill the web process. Jobs stay queued and run later.
            if not _enough_memory():
                if now - last_mem_warn > 30:
                    print(f"[save-worker] low memory (<{SAVE_MIN_FREE_MB}MB free) — deferring saves", flush=True)
                    last_mem_warn = now
                time.sleep(poll)
                continue
            job = queue.claim_next(_WORKER_ID, jobs=jobs)
            if job:
                print(f"[save-worker] claimed job {job['job_id']} ({job.get('title')})", flush=True)
                _run_job(job)
                continue  # drain the queue without waiting a full poll
        except Exception as exc:
            print(f"[save-worker] loop error: {exc}", flush=True)
            idle = True
        time.sleep(idle_poll if idle else poll)


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
