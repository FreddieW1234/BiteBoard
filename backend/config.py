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

# Staff portal login (hardcoded — blocks customers from staff area only)
STAFF_USERNAME = "Chocolate1!"
STAFF_PASSWORD = "Chocolate2!"
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
# Send Shopify customer welcome email when a customer is created via portal registration
CUSTOMER_SEND_WELCOME_EMAIL = os.environ.get(
    "CUSTOMER_SEND_WELCOME_EMAIL", "true"
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

# Klaviyo — production update emails (transactional Flow triggered by Events API)
KLAVIYO_API_KEY = os.environ.get("KLAVIYO_API_KEY") or ""
KLAVIYO_API_REVISION = os.environ.get("KLAVIYO_API_REVISION", "2025-01-15")
KLAVIYO_METRIC_NAME = os.environ.get("KLAVIYO_METRIC_NAME", "Bite Production Update")
KLAVIYO_CUSTOMER_TYPE_METRIC_NAME = os.environ.get(
    "KLAVIYO_CUSTOMER_TYPE_METRIC_NAME", "Bite Customer Type Assigned"
)

# ShipStation — parcel labels (Royal Mail, FedEx, etc.)
SHIPSTATION_API_KEY = os.environ.get("SHIPSTATION_API_KEY") or ""
SHIPSTATION_API_URL = (os.environ.get("SHIPSTATION_API_URL") or "https://api.shipstation.com").rstrip("/")
# Optional — if unset, the first warehouse from GET /v2/warehouses is used for ship-from
SHIPSTATION_WAREHOUSE_ID = os.environ.get("SHIPSTATION_WAREHOUSE_ID") or ""
# Optional comma-separated carrier_code substrings to limit quotes (empty = all carriers).
SHIPSTATION_CARRIER_CODES = os.environ.get("SHIPSTATION_CARRIER_CODES") or ""
# Optional manual ship-from fallback when no warehouse is configured in ShipStation
SHIPSTATION_ORIGIN_NAME = os.environ.get("SHIPSTATION_ORIGIN_NAME") or ""
SHIPSTATION_ORIGIN_PHONE = os.environ.get("SHIPSTATION_ORIGIN_PHONE") or ""
SHIPSTATION_ORIGIN_LINE1 = os.environ.get("SHIPSTATION_ORIGIN_LINE1") or ""
SHIPSTATION_ORIGIN_LINE2 = os.environ.get("SHIPSTATION_ORIGIN_LINE2") or ""
SHIPSTATION_ORIGIN_CITY = os.environ.get("SHIPSTATION_ORIGIN_CITY") or ""
SHIPSTATION_ORIGIN_STATE = os.environ.get("SHIPSTATION_ORIGIN_STATE") or ""
SHIPSTATION_ORIGIN_POSTCODE = os.environ.get("SHIPSTATION_ORIGIN_POSTCODE") or ""
SHIPSTATION_ORIGIN_COUNTRY = os.environ.get("SHIPSTATION_ORIGIN_COUNTRY") or "GB"

# Palletways — pallet consignments (optional until API key is issued)
PALLETWAYS_API_KEY = os.environ.get("PALLETWAYS_API_KEY") or ""
PALLETWAYS_API_URL = (os.environ.get("PALLETWAYS_API_URL") or "https://api.palletways.com").rstrip("/")

# Office LAN print server — receives ZPL/PDF jobs from Render (optional in phase 1)
OFFICE_PRINT_SERVER_URL = (os.environ.get("OFFICE_PRINT_SERVER_URL") or "").rstrip("/")
OFFICE_PRINT_SERVER_KEY = os.environ.get("OFFICE_PRINT_SERVER_KEY") or ""

# Common headers for API requests
SHOPIFY_HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN or "",
}
