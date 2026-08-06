"""Gunicorn settings, loaded automatically from the working directory.

These live here rather than in the start command because the deployed command is
set in the Render dashboard, which silently overrides render.yaml. The service
ran for a long time on gunicorn's default sync worker — one request at a time
for the entire site — while render.yaml claimed twelve threads. Settings in this
file apply wherever the process is launched from, and the boot log below prints
what is actually in effect so a mismatch can never hide again.
"""

import os

# One worker: each is a full copy of the app and its caches, and the instance is
# memory-constrained. Concurrency comes from threads instead, which is the right
# trade here because requests are spent almost entirely waiting on Shopify and
# the office server rather than using CPU — the GIL is released while waiting.
#
# Set explicitly because gunicorn otherwise takes workers from WEB_CONCURRENCY,
# which Render sets to 1 based on available CPUs.
workers = 1
worker_class = "gthread"

# Threads are the concurrency budget, but each in-flight request also holds its
# working set (parsed Shopify JSON is several times the wire size) in a 512MB
# instance. Twelve was enough to trade the old one-at-a-time stall for memory
# pressure, so this is deliberately more conservative — still a large multiple of
# the single request the sync worker allowed. Raise via WEB_THREADS once the
# memory graph shows headroom.
threads = int(os.environ.get("WEB_THREADS", "6"))

# Deliberately no max_requests: with a single worker, recycling would blip the
# whole site and wipe the in-process caches, forcing a cold rebuild every time.

timeout = 300
graceful_timeout = 30
keepalive = 5


def on_starting(server):
    """Log the concurrency actually in effect, so a silent override is visible."""
    cfg = server.cfg
    klass = getattr(cfg, "worker_class_str", None) or cfg.worker_class
    slots = cfg.workers * (cfg.threads if klass == "gthread" else 1)
    print(
        f"🧵 Gunicorn: worker_class={klass} workers={cfg.workers} threads={cfg.threads} "
        f"-> {slots} concurrent request(s)",
        flush=True,
    )
    if slots < 2:
        print(
            "⚠️ Gunicorn is serving ONE request at a time — a single slow request "
            "will hang the whole site. Check the start command in the Render dashboard.",
            flush=True,
        )
