"""Send ZPL labels to the office Zebra via the Office API ``/print`` endpoint."""

from __future__ import annotations

import logging
import re

from config import OFFICE_API_KEY, OFFICE_API_URL  # type: ignore

logger = logging.getLogger(__name__)

# FedEx 4x6 ZPL is typically 203 dpi; 2mm ≈ 16 dots.
_FEDEX_SHIFT_MM = 2.0
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


def adjust_fedex_zpl(
    zpl: str,
    *,
    shift_mm: float = _FEDEX_SHIFT_MM,
    dpi: int = _FEDEX_DPI,
) -> str:
    """Print-time FedEx tweaks: rotate 180° and shift left. Does not alter stored ZPL.

    FedEx ZPL usually contains its own ``^LS0`` / ``^PON`` later in the format.
    Those override an inject-after-``^XA``, so we strip every ``^PO``/``^LS`` and
    place ours immediately before ``^XZ`` so they win.
    """
    text = first_zpl_label(zpl)
    if not text:
        return text

    dots = max(0, int(round(shift_mm * dpi / 25.4)))
    # Remove ALL orientation/shift commands FedEx (or we) embedded.
    text = re.sub(r"\^PO[NI]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\^LS-?\d+", "", text, flags=re.IGNORECASE)

    injection = "^POI"
    if dots > 0:
        injection += f"^LS{dots}"

    if re.search(r"\^XZ", text, flags=re.IGNORECASE):
        text = re.sub(
            r"\^XZ",
            injection + "^XZ",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        match = re.search(r"\^XA", text, flags=re.IGNORECASE)
        if match:
            text = text[: match.end()] + injection + text[match.end() :]
        else:
            text = injection + text

    logger.warning(
        "FedEx ZPL adjust applied: rotate=180 shift_left=%smm (%s dots) tail=%r",
        shift_mm,
        dots,
        text[-80:],
    )
    return text


def _should_adjust_fedex(carrier: str, zpl_text: str) -> bool:
    carrier_l = (carrier or "").strip().lower()
    if carrier_l == "fedex":
        return True
    # Reprint paths sometimes omit carrier — detect FedEx ZPL content.
    sample = (zpl_text or "")[:4000].upper()
    return "FEDEX" in sample or "FDX" in sample


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

    if _should_adjust_fedex(carrier, zpl_text):
        zpl_text = adjust_fedex_zpl(zpl_text)
    else:
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
