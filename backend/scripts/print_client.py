"""Send ZPL labels to the office Zebra via the Office API ``/print`` endpoint."""

from __future__ import annotations

import logging
import re

from config import OFFICE_API_KEY, OFFICE_API_URL  # type: ignore

logger = logging.getLogger(__name__)


class PrintClientError(Exception):
    pass


def configured() -> bool:
    """True when Office API credentials exist (printer may still be offline)."""
    return bool(OFFICE_API_URL and OFFICE_API_KEY)


def printer_ready() -> bool:
    """True when Office API reports the Zebra print path is configured."""
    if not configured():
        return False
    try:
        from scripts import office_api  # type: ignore
        health = office_api.print_health()
        return bool(health.get("configured"))
    except Exception as exc:
        logger.warning("Office print health check failed: %s", exc)
        return False


def first_zpl_label(zpl: str) -> str:
    """Keep only the first ``^XA…^XZ`` block.

    FedEx often returns two formats in one payload (e.g. label + extra doc),
    which makes the Zebra print twice.
    """
    text = (zpl or "").strip()
    if not text:
        return text
    matches = list(re.finditer(r"\^XA[\s\S]*?\^XZ", text, flags=re.IGNORECASE))
    if len(matches) <= 1:
        return text
    logger.info("ZPL contained %s label blocks — sending only the first", len(matches))
    return matches[0].group(0)


def send_print_job(
    *,
    profile: str = "parcel-4x6-zpl",
    label_format: str = "zpl",
    data: bytes | str,
    order_name: str = "",
    tracking_number: str = "",
    carrier: str = "",
) -> dict:
    """POST raw ZPL to ``{OFFICE_API_URL}/print``."""
    del profile  # unused — office API only accepts raw ZPL
    del carrier  # reserved for future carrier-specific print tweaks
    if not configured():
        logger.info(
            "Office API not configured — skipping print for %s (%s)",
            order_name,
            tracking_number,
        )
        return {"success": True, "skipped": True, "reason": "print_server_not_configured"}

    if not data:
        return {"success": False, "error": "No label data to print"}

    if (label_format or "zpl").lower().find("zpl") < 0:
        return {
            "success": False,
            "error": f"Office printer only accepts ZPL (got {label_format!r})",
        }

    try:
        from scripts import office_api  # type: ignore
        from scripts.office_api import OfficeApiError  # type: ignore
    except Exception as exc:
        raise PrintClientError("Office API client unavailable") from exc

    if isinstance(data, bytes):
        zpl_text = data.decode("utf-8", errors="replace")
    else:
        zpl_text = str(data)

    zpl_text = first_zpl_label(zpl_text)

    try:
        result = office_api.print_label(
            zpl_text,
            order=order_name or None,
            label_ref=tracking_number or None,
        )
    except OfficeApiError as exc:
        raise PrintClientError(str(exc)) from exc

    return {
        "success": True,
        "ok": bool(result.get("ok", True)),
        "printer": result.get("printer"),
        "bytes": result.get("bytes"),
        "raw": result,
    }
