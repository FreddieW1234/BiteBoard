#!/usr/bin/env python3
"""
Configuration for Shopify App deployment.

Secrets and store details are sourced from environment variables to avoid
committing sensitive data to version control. A local `.env` file can be used
for development and is loaded automatically when present.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


_BASE_DIR = Path(__file__).resolve().parent
_ENV_PATH = _BASE_DIR.parent / ".env"

# Load environment variables from `.env` if available (development convenience)
load_dotenv(_ENV_PATH)

# Shopify Store Configuration
STORE_DOMAIN = os.environ.get("SHOPIFY_STORE_DOMAIN", "")
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2025-07")
ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")

# Staff portal logins (hardcoded - blocks customers from staff area only).
# "dev" can see Files / Dev / Artwork Updater; other staff cannot.
STAFF_ACCOUNTS = {
    "Chocolate1!": "Chocolate2!",
    "dev": "dev",
}
STAFF_DEV_TOOL_USERNAMES = frozenset({"dev"})
# Back-compat aliases (primary Chocolate account)
STAFF_USERNAME = "Chocolate1!"
STAFF_PASSWORD = STAFF_ACCOUNTS[STAFF_USERNAME]
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "biteboard-portal-session-key")
# Set to "false" for local HTTP dev so session cookies work without HTTPS
FLASK_SESSION_SECURE = os.environ.get("FLASK_SESSION_SECURE", "true").lower() in ("1", "true", "yes")
# Customer-facing shop URL (for logout links from the client portal iframe)
STOREFRONT_URL = (os.environ.get("SHOPIFY_STOREFRONT_URL") or "https://bitepromotions.uk").rstrip("/")
# Customer portal page on the Shopify storefront (iframe embed)
PORTAL_PAGE_URL = (os.environ.get("PORTAL_PAGE_URL") or f"{STOREFRONT_URL}/pages/portal").rstrip("/")
# Relative path after Shopify login (used with login_hint)
CUSTOMER_LOGIN_RETURN_TO = (os.environ.get("CUSTOMER_LOGIN_RETURN_TO") or "/pages/portal").strip()
# Optional template override: .../login?login_hint={email}&return_to={return_to}
CUSTOMER_LOGIN_URL = (os.environ.get("CUSTOMER_LOGIN_URL") or "").strip()
# Shopify welcome email only works for legacy accounts; default off for passwordless.
CUSTOMER_SEND_WELCOME_EMAIL = os.environ.get(
    "CUSTOMER_SEND_WELCOME_EMAIL", "false"
).lower() in ("1", "true", "yes")


def build_customer_login_url(email: str) -> str:
    """Shopify native login with email prefilled via login_hint."""
    from urllib.parse import quote

    email_q = quote((email or "").strip().lower())
    return_to_q = quote(CUSTOMER_LOGIN_RETURN_TO or "/pages/portal", safe="")
    if CUSTOMER_LOGIN_URL and "{email}" in CUSTOMER_LOGIN_URL:
        return (
            CUSTOMER_LOGIN_URL.replace("{email}", email_q).replace("{return_to}", return_to_q)
        )
    return (
        f"{STOREFRONT_URL}/customer_authentication/login"
        f"?login_hint={email_q}&return_to={return_to_q}"
    )

# Office Order API (status pipeline + artwork/proof files on office server)
OFFICE_API_URL = (os.environ.get("OFFICE_API_URL") or "").rstrip("/")
OFFICE_API_KEY = os.environ.get("OFFICE_API_KEY") or ""
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
ORDER_ACCESS_CACHE_TTL_SEC = int(os.environ.get("ORDER_ACCESS_CACHE_TTL_SEC", "300"))

# All Products snapshot cache (durable office snapshot + short in-process tier).
# PRODUCTS_SNAPSHOT_TTL: seconds before a served snapshot triggers a background
# Shopify rebuild. PRODUCTS_MEM_TTL: seconds the per-instance memory tier is trusted.
PRODUCTS_SNAPSHOT_TTL = int(os.environ.get("PRODUCTS_SNAPSHOT_TTL", "1800"))
PRODUCTS_MEM_TTL = int(os.environ.get("PRODUCTS_MEM_TTL", "30"))
# Ceiling on the per-instance product-detail cache. Entries are full product
# blobs, so on a 512MB instance an uncapped cache eventually triggers an OOM
# kill. Evicted entries cost one office read to restore.
PRODUCT_DETAIL_CACHE_MAX = int(os.environ.get("PRODUCT_DETAIL_CACHE_MAX", "150"))

# Background product-save queue (write-behind saves + post-save verification).
# SAVE_WORKER_ENABLED: run the in-process worker thread on this instance.
# SAVE_QUEUE_POLL_SEC: worker poll interval. SAVE_MAX_ATTEMPTS: retries before a
# job is marked Failed. SAVE_JOB_TIMEOUT_SEC: a running job older than this is
# reaped/requeued. SAVE_JOB_RETENTION_H: terminal jobs pruned after this many hours.
SAVE_WORKER_ENABLED = os.environ.get("SAVE_WORKER_ENABLED", "true").lower() in ("1", "true", "yes")
SAVE_QUEUE_POLL_SEC = int(os.environ.get("SAVE_QUEUE_POLL_SEC", "2"))
# Poll interval when nothing is queued or running. The worker loop runs forever
# on every instance, so this is the floor on background office traffic.
SAVE_QUEUE_IDLE_POLL_SEC = int(os.environ.get("SAVE_QUEUE_IDLE_POLL_SEC", "15"))
SAVE_MAX_ATTEMPTS = int(os.environ.get("SAVE_MAX_ATTEMPTS", "3"))
SAVE_JOB_TIMEOUT_SEC = int(os.environ.get("SAVE_JOB_TIMEOUT_SEC", "1800"))
# A running job heartbeats while its worker is alive. Saves are serialised across
# instances, so a job abandoned by a dead instance must be reclaimed quickly or
# it holds up the whole queue.
SAVE_HEARTBEAT_STALE_SEC = int(os.environ.get("SAVE_HEARTBEAT_STALE_SEC", "180"))
SAVE_JOB_RETENTION_H = int(os.environ.get("SAVE_JOB_RETENTION_H", "6"))
# SAVE_MIN_FREE_MB: the worker defers claiming a job (leaving it queued) when the
# instance has less available memory than this, so the save subprocess can't push
# a small (e.g. 512MB) instance into an OOM kill that takes the whole site down.
SAVE_MIN_FREE_MB = int(os.environ.get("SAVE_MIN_FREE_MB", "150"))

# Request-thread watchdog. The app runs on one gunicorn worker with a fixed
# thread pool, so a few slow requests can occupy every thread and leave the site
# unable to answer anything at all - even /healthz, which does no I/O. Only a
# stack dump taken from inside the process while it is saturated shows what the
# threads are actually stuck on.
# WATCHDOG_BUSY: in-flight requests that count as saturated. WATCHDOG_SLOW_SEC: a
# single request running longer than this also triggers a dump.
# WATCHDOG_COOLDOWN_SEC: minimum gap between dumps, so logs can't flood.
THREAD_WATCHDOG_ENABLED = os.environ.get("THREAD_WATCHDOG_ENABLED", "true").lower() in ("1", "true", "yes")
THREAD_WATCHDOG_POLL_SEC = int(os.environ.get("THREAD_WATCHDOG_POLL_SEC", "10"))
# Default 5 so dumps can fire on a 6-thread worker (the old default of 8 was
# unreachable and left thread-saturation outages invisible in logs).
THREAD_WATCHDOG_BUSY = int(os.environ.get("THREAD_WATCHDOG_BUSY", "5"))
THREAD_WATCHDOG_SLOW_SEC = int(os.environ.get("THREAD_WATCHDOG_SLOW_SEC", "30"))
THREAD_WATCHDOG_COOLDOWN_SEC = int(os.environ.get("THREAD_WATCHDOG_COOLDOWN_SEC", "120"))

# In-process cache for GET /api/shopify/files (full Shopify Content > Files scan).
# Cold loads paginate hundreds of files and can saturate the gunicorn thread pool
# when several staff open Product Creator at once.
SHOPIFY_FILES_MEM_TTL = int(os.environ.get("SHOPIFY_FILES_MEM_TTL", "120"))

# Klaviyo - production update emails (transactional Flow triggered by Events API)
KLAVIYO_API_KEY = os.environ.get("KLAVIYO_API_KEY") or ""
KLAVIYO_API_REVISION = os.environ.get("KLAVIYO_API_REVISION", "2025-01-15")
KLAVIYO_METRIC_NAME = os.environ.get("KLAVIYO_METRIC_NAME", "Bite Production Update")
KLAVIYO_CUSTOMER_TYPE_METRIC_NAME = os.environ.get(
    "KLAVIYO_CUSTOMER_TYPE_METRIC_NAME", "Bite Customer Type Assigned"
)
KLAVIYO_CUSTOMER_REGISTERED_METRIC_NAME = os.environ.get(
    "KLAVIYO_CUSTOMER_REGISTERED_METRIC_NAME", "Bite Customer Registered"
)
KLAVIYO_PROOF_APPROVED_METRIC_NAME = os.environ.get(
    "KLAVIYO_PROOF_APPROVED_METRIC_NAME", "Bite Proof Approved"
)

# Direct carrier APIs (ShipStation removed)
ROYAL_MAIL_API_KEY = os.environ.get("ROYAL_MAIL_API_KEY") or ""
ROYAL_MAIL_API_URL = (os.environ.get("ROYAL_MAIL_API_URL") or "").rstrip("/")
FEDEX_API_KEY = os.environ.get("FEDEX_API_KEY") or ""
FEDEX_API_URL = (
    os.environ.get("FEDEX_API_URL") or "https://apis-sandbox.fedex.com"
).rstrip("/")
FEDEX_ACCOUNT_NUMBER = os.environ.get("FEDEX_ACCOUNT_NUMBER") or ""
FEDEX_METER_NUMBER = os.environ.get("FEDEX_METER_NUMBER") or ""
# OAuth: Client ID = FedEx "API Key"; Client Secret = FedEx "Secret Key"
FEDEX_CLIENT_ID = os.environ.get("FEDEX_CLIENT_ID") or FEDEX_API_KEY or ""
FEDEX_CLIENT_SECRET = os.environ.get("FEDEX_CLIENT_SECRET") or ""
# Label generation (thermal ZPL). Stock 9.7×14.8 cm portrait ≈ STOCK_4X6 -
# FedEx has no custom-mm enum; closest thermal stock is 4×6.
FEDEX_LABEL_STOCK_TYPE = (os.environ.get("FEDEX_LABEL_STOCK_TYPE") or "STOCK_4X6").strip()
# TOP_EDGE_OF_TEXT_FIRST | BOTTOM_EDGE_OF_TEXT_FIRST
FEDEX_LABEL_PRINTING_ORIENTATION = (
    os.environ.get("FEDEX_LABEL_PRINTING_ORIENTATION") or "TOP_EDGE_OF_TEXT_FIRST"
).strip()
# NONE | LEFT | RIGHT | UPSIDE_DOWN (empty = omit from request)
FEDEX_LABEL_ROTATION = (os.environ.get("FEDEX_LABEL_ROTATION") or "").strip()

# Palletways - pallet consignments
PALLETWAYS_API_KEY = os.environ.get("PALLETWAYS_API_KEY") or ""
PALLETWAYS_API_URL = (os.environ.get("PALLETWAYS_API_URL") or "https://api.palletways.com").rstrip("/")

# Warehouse / ship-from address used by direct carrier integrations
SHIP_FROM_NAME = os.environ.get("SHIP_FROM_NAME") or os.environ.get("SHIPSTATION_ORIGIN_NAME") or ""
SHIP_FROM_PHONE = os.environ.get("SHIP_FROM_PHONE") or os.environ.get("SHIPSTATION_ORIGIN_PHONE") or ""
SHIP_FROM_LINE1 = os.environ.get("SHIP_FROM_LINE1") or os.environ.get("SHIPSTATION_ORIGIN_LINE1") or ""
SHIP_FROM_LINE2 = os.environ.get("SHIP_FROM_LINE2") or os.environ.get("SHIPSTATION_ORIGIN_LINE2") or ""
SHIP_FROM_CITY = os.environ.get("SHIP_FROM_CITY") or os.environ.get("SHIPSTATION_ORIGIN_CITY") or ""
SHIP_FROM_STATE = os.environ.get("SHIP_FROM_STATE") or os.environ.get("SHIPSTATION_ORIGIN_STATE") or ""
SHIP_FROM_POSTCODE = os.environ.get("SHIP_FROM_POSTCODE") or os.environ.get("SHIPSTATION_ORIGIN_POSTCODE") or ""
SHIP_FROM_COUNTRY = os.environ.get("SHIP_FROM_COUNTRY") or os.environ.get("SHIPSTATION_ORIGIN_COUNTRY") or "GB"

# Office LAN print server - receives ZPL/PDF jobs from Render (optional in phase 1)
OFFICE_PRINT_SERVER_URL = (os.environ.get("OFFICE_PRINT_SERVER_URL") or "").rstrip("/")
OFFICE_PRINT_SERVER_KEY = os.environ.get("OFFICE_PRINT_SERVER_KEY") or ""

# Phase 7 — Shopify collection webhooks (HMAC) + nightly reconcile cron
SHOPIFY_WEBHOOK_SECRET = os.environ.get("SHOPIFY_WEBHOOK_SECRET") or ""
CRON_SECRET = os.environ.get("CRON_SECRET") or ""

# Common headers for API requests
SHOPIFY_HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN or "",
}
