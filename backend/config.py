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

# Common headers for API requests
SHOPIFY_HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN or "",
}
