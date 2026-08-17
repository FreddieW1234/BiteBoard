"""Gunicorn settings for the Render web service.

Loaded via ``-c gunicorn.conf.py`` after ``--chdir backend`` (see render.yaml and
the Render dashboard Start Command). Keep this file in ``backend/`` so the
chdir'd process always finds it.
"""

import os

# One worker: each is a full copy of the app and its caches, and the instance is
# memory-constrained. Concurrency comes from threads instead.
workers = 1
worker_class = "gthread"

# 8 threads: enough headroom that Render's 5s /healthz probe still gets a free
# slot when a few Shopify/office calls are in flight. Override with WEB_THREADS.
threads = int(os.environ.get("WEB_THREADS", "8"))

# Deliberately no max_requests: with a single worker, recycling would blip the
# whole site and wipe the in-process caches.
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
            "[warn] Gunicorn is serving ONE request at a time - a single slow request "
            "will hang the whole site. Check the start command in the Render dashboard.",
            flush=True,
        )
