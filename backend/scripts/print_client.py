"""Send ZPL labels to the office Zebra via the Office API ``/print`` endpoint."""

from __future__ import annotations

import logging
import re

from config import OFFICE_API_KEY, OFFICE_API_URL  # type: ignore

logger = logging.getLogger(__name__)

# FedEx 4x6 ZPL is typically 203 dpi; 3mm ≈ 24 dots.
_FEDEX_SHIFT_MM = 3.0
_FEDEX_DPI = 203


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


def shift_zpl_left(zpl: str, *, mm: float = _FEDEX_SHIFT_MM, dpi: int = _FEDEX_DPI) -> str:
    """Shift entire ZPL format left using ``^LS`` (dots). Does not alter stored labels."""
    text = (zpl or "").strip()
    if not text or mm <= 0:
        return text
    dots = int(round(mm * dpi / 25.4))
    if dots <= 0:
        return text
    injection = f"^LS{dots}"
    if re.search(r"\^LS-?\d+", text, flags=re.IGNORECASE):
        return re.sub(r"\^LS-?\d+", injection, text, count=1, flags=re.IGNORECASE)
    match = re.search(r"\^XA", text, flags=re.IGNORECASE)
    if not match:
        return text
    return text[: match.end()] + injection + text[match.end() :]


def send_print_job(
    *,
    profile: str = "parcel-4x6-zpl",
    label_format: str = "zpl",
    data: bytes | str,
    order_name: str = "",
    tracking_number: str = "",
    carrier: str = "",
) -> dict:
    """POST raw ZPL to ``{OFFICE_API_URL}/print``.

    ``profile`` / ``label_format`` are kept for call-site compatibility; the
    office endpoint expects a ``zpl`` string. FedEx labels get a 3mm left shift
    at print time only.
    """
    del profile  # unused — office API only accepts raw ZPL
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

    if (carrier or "").strip().lower() == "fedex":
        zpl_text = shift_zpl_left(zpl_text)
        logger.info(
            "Applied FedEx print shift: %.1fmm left (~%sdpi) for %s",
            _FEDEX_SHIFT_MM,
            _FEDEX_DPI,
            order_name or tracking_number,
        )

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
