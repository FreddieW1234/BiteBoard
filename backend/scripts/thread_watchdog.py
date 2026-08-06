"""Diagnose request-thread exhaustion from inside the process.

The app runs on a single gunicorn worker with a fixed thread pool, so a handful
of slow requests can occupy every thread and leave the site unable to answer
anything — including /healthz, which does no I/O at all. From outside, that is
indistinguishable from a slow dependency: the browser just waits. The only way
to tell which operation is holding the threads is to look at their stacks while
it is happening, so this samples in the background and dumps to stdout (i.e. the
Render logs) when the pool looks saturated.

Note the blind spot: this can only see requests the app has actually been handed.
Requests still waiting in the kernel's accept backlog are invisible, so if the
server is configured to handle very few at once, a total outage can show up here
as an almost idle process. That is exactly what happened while gunicorn was
running its default sync worker — one request at a time, everything else queued
out of sight. The concurrency in gunicorn.conf.py is what makes these numbers
mean anything.

Costs nothing when healthy: two dict operations per request and one wakeup every
WATCHDOG_POLL_SEC that usually does nothing.
"""

import sys
import threading
import time
import traceback
from datetime import datetime, timezone

try:
    from config import (  # type: ignore
        THREAD_WATCHDOG_ENABLED,
        THREAD_WATCHDOG_POLL_SEC,
        THREAD_WATCHDOG_BUSY,
        THREAD_WATCHDOG_SLOW_SEC,
        THREAD_WATCHDOG_COOLDOWN_SEC,
    )
except Exception:  # config not importable (e.g. standalone tooling)
    THREAD_WATCHDOG_ENABLED = True
    THREAD_WATCHDOG_POLL_SEC = 10
    THREAD_WATCHDOG_BUSY = 8
    THREAD_WATCHDOG_SLOW_SEC = 30
    THREAD_WATCHDOG_COOLDOWN_SEC = 120

# thread ident -> {"path", "method", "started"} for requests currently being served.
_inflight = {}
_lock = threading.Lock()
_started = False
_last_dump_at = 0.0


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot():
    """Currently in-flight requests, oldest first. Safe to call from any thread."""
    now = time.time()
    with _lock:
        rows = [
            {
                "thread": tid,
                "path": rec["path"],
                "method": rec["method"],
                "age_s": round(now - rec["started"], 1),
            }
            for tid, rec in _inflight.items()
        ]
    rows.sort(key=lambda r: r["age_s"], reverse=True)
    return rows


def _should_dump(rows):
    """Saturated pool, or one request running far longer than any page should."""
    if len(rows) >= int(THREAD_WATCHDOG_BUSY):
        return f"{len(rows)} requests in flight"
    if rows and rows[0]["age_s"] >= int(THREAD_WATCHDOG_SLOW_SEC):
        r = rows[0]
        return f"{r['method']} {r['path']} running {r['age_s']}s"
    return None


def dump(reason=""):
    """Print every thread's stack, annotated with the request it is serving."""
    rows = snapshot()
    by_thread = {r["thread"]: r for r in rows}
    names = {t.ident: t.name for t in threading.enumerate()}
    frames = sys._current_frames()
    me = threading.get_ident()

    out = [
        "",
        "=" * 78,
        f"THREAD WATCHDOG {_now_iso()} — {reason}",
        f"in-flight requests: {len(rows)}",
    ]
    for r in rows:
        out.append(f"  {r['age_s']:>8.1f}s  {r['method']:<6} {r['path']}")
    out.append("-" * 78)

    for tid, frame in frames.items():
        if tid == me:
            continue  # the watchdog's own stack is noise
        req = by_thread.get(tid)
        label = f"{req['method']} {req['path']} ({req['age_s']}s)" if req else "idle/background"
        out.append(f"\nThread {names.get(tid, '?')} [{tid}] — {label}")
        out.extend("  " + ln.rstrip() for ln in traceback.format_stack(frame))

    out.append("=" * 78)
    print("\n".join(out), flush=True)


def _loop():
    global _last_dump_at
    poll = max(2, int(THREAD_WATCHDOG_POLL_SEC))
    cooldown = int(THREAD_WATCHDOG_COOLDOWN_SEC)
    while True:
        time.sleep(poll)
        try:
            reason = _should_dump(snapshot())
            if not reason:
                continue
            now = time.time()
            if now - _last_dump_at < cooldown:
                continue
            _last_dump_at = now
            dump(reason)
        except Exception as exc:  # a diagnostic must never take the app down
            print(f"⚠️ Thread watchdog error: {exc}", flush=True)


def init_watchdog(app):
    """Record in-flight requests and start the sampler.

    Register this before the maintenance and auth gates so short-circuited
    requests are still accounted for. It never short-circuits itself, so it does
    not disturb the ordering those two rely on.
    """
    global _started

    @app.before_request
    def _watchdog_track():
        from flask import request

        with _lock:
            _inflight[threading.get_ident()] = {
                "path": request.path or "?",
                "method": request.method,
                "started": time.time(),
            }
        return None

    @app.teardown_request
    def _watchdog_untrack(_exc=None):
        with _lock:
            _inflight.pop(threading.get_ident(), None)

    if not THREAD_WATCHDOG_ENABLED or _started:
        return
    _started = True
    threading.Thread(target=_loop, name="thread-watchdog", daemon=True).start()
    print(
        f"🩺 Thread watchdog on — dump at {THREAD_WATCHDOG_BUSY} in-flight "
        f"or a request over {THREAD_WATCHDOG_SLOW_SEC}s",
        flush=True,
    )
