"""Send ZPL labels to the office Zebra via the Office API ``/print`` endpoint."""

from __future__ import annotations

import logging
import os
import re

from config import OFFICE_API_KEY, OFFICE_API_URL  # type: ignore

logger = logging.getLogger(__name__)

# Office thermal stock: 9.7 cm wide × 14.8 cm tall, portrait (≈ 4×6 in).
_LABEL_WIDTH_MM = float(os.environ.get("LABEL_WIDTH_MM") or "97")
_LABEL_HEIGHT_MM = float(os.environ.get("LABEL_HEIGHT_MM") or "148")
_FEDEX_DPI = int(os.environ.get("LABEL_DPI") or "203")
# Signed horizontal shift: +mm = left, −mm = right (ZPL ``^LS``). Default −3.5 mm right.
_FEDEX_SHIFT_MM = float(os.environ.get("FEDEX_LABEL_SHIFT_MM") or "-3.5")
# Print-time 180° — set FEDEX_LABEL_PRINT_ROTATE_180=0 once FedEx orientation is right.
_FEDEX_ROTATE_180 = os.environ.get("FEDEX_LABEL_PRINT_ROTATE_180", "1").lower() in (
    "1",
    "true",
    "yes",
)
# Uniform content scale (1.0 = none). Default 0.9653 ≈ 3.5% smaller (was 2%, then −1.5% more).
_LABEL_SCALE = float(os.environ.get("FEDEX_LABEL_SCALE") or "0.9653")
_PREPARED_MARKER = "bite-label-adjusted"


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


def _mm_to_dots(mm: float, dpi: int) -> int:
    return max(1, int(round(mm * dpi / 25.4)))


def _scale_dots(value: int, factor: float, *, minimum: int = 0) -> int:
    return max(minimum, int(round(value * factor)))


def scale_zpl_content(zpl: str, *, scale: float = _LABEL_SCALE) -> str:
    """Shrink/grow field positions, fonts, boxes, and barcodes uniformly."""
    if not zpl or abs(scale - 1.0) < 0.0001:
        return zpl

    text = zpl

    def sd(value: int, minimum: int = 0) -> int:
        return _scale_dots(value, scale, minimum=minimum)

    text = re.sub(
        r"\^FO(\d+),(\d+)",
        lambda m: f"^FO{sd(int(m.group(1)))},{sd(int(m.group(2)))}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\^FT(\d+),(\d+)",
        lambda m: f"^FT{sd(int(m.group(1)))},{sd(int(m.group(2)))}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\^GB(\d+),(\d+),(\d+)",
        lambda m: (
            f"^GB{sd(int(m.group(1)), 1)},{sd(int(m.group(2)), 1)},"
            f"{sd(int(m.group(3)), 1)}"
        ),
        text,
        flags=re.IGNORECASE,
    )

    def _scale_by(match: re.Match) -> str:
        w = sd(int(match.group(1)), 1)
        r = match.group(2)
        h = match.group(3)
        out = f"^BY{w}"
        if r is not None:
            out += f",{r}"
            if h is not None:
                out += f",{sd(int(h), 1)}"
        return out

    text = re.sub(
        r"\^BY(\d+)(?:,(\d+))?(?:,(\d+))?",
        _scale_by,
        text,
        flags=re.IGNORECASE,
    )

    def _scale_font(match: re.Match) -> str:
        face = match.group(1)
        height = sd(int(match.group(2)), 1)
        width = match.group(3)
        if width is not None:
            return f"^A{face},{height},{sd(int(width), 1)}"
        return f"^A{face},{height}"

    text = re.sub(
        r"\^A([^,\^]+),(\d+)(?:,(\d+))?",
        _scale_font,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(\^B[A-Z0-9@]+(?:,[A-Z])?),(\d+)",
        lambda m: f"{m.group(1)},{sd(int(m.group(2)), 1)}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\^FB(\d+)",
        lambda m: f"^FB{sd(int(m.group(1)), 1)}",
        text,
        flags=re.IGNORECASE,
    )
    return text


def is_prepared_fedex_zpl(zpl: str) -> bool:
    """True when ZPL was already adjusted before storing on the office server."""
    return _PREPARED_MARKER in (zpl or "")


def prepare_fedex_zpl(
    zpl: str,
    *,
    shift_mm: float = _FEDEX_SHIFT_MM,
    dpi: int = _FEDEX_DPI,
    width_mm: float = _LABEL_WIDTH_MM,
    height_mm: float = _LABEL_HEIGHT_MM,
    rotate_180: bool = _FEDEX_ROTATE_180,
    scale: float = _LABEL_SCALE,
) -> str:
    """Adjust FedEx ZPL once before saving on the office server."""
    return adjust_fedex_zpl(
        zpl,
        shift_mm=shift_mm,
        dpi=dpi,
        width_mm=width_mm,
        height_mm=height_mm,
        rotate_180=rotate_180,
        scale=scale,
        mark_prepared=True,
    )


def adjust_fedex_zpl(
    zpl: str,
    *,
    shift_mm: float = _FEDEX_SHIFT_MM,
    dpi: int = _FEDEX_DPI,
    width_mm: float = _LABEL_WIDTH_MM,
    height_mm: float = _LABEL_HEIGHT_MM,
    rotate_180: bool = _FEDEX_ROTATE_180,
    scale: float = _LABEL_SCALE,
    mark_prepared: bool = False,
) -> str:
    """FedEx ZPL tweaks for 9.7×14.8 cm portrait stock.

    ``shift_mm``: positive = left, negative = right (via ``^LS`` / ``^LS-``).
    ``scale``: uniform shrink/grow of fields (default 0.98 = 2% smaller).
    """
    text = first_zpl_label(zpl)
    if not text:
        return text

    pw = _mm_to_dots(width_mm, dpi)
    ll = _mm_to_dots(height_mm, dpi)
    dots = int(round(shift_mm * dpi / 25.4))

    text = re.sub(r"\^PO[NI]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\^LS-?\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\^LH\d+,\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\^PW\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\^LL\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\^FX[^\r\n]*" + re.escape(_PREPARED_MARKER),
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = scale_zpl_content(text, scale=scale)

    injection = f"^PW{pw}^LL{ll}"
    if abs(scale - 1.0) >= 0.0001:
        lh_x = int(round(pw * (1.0 - scale) / 2.0))
        lh_y = int(round(ll * (1.0 - scale) / 2.0))
        if lh_x or lh_y:
            injection += f"^LH{lh_x},{lh_y}"
    if rotate_180:
        injection += "^POI"
    if dots != 0:
        injection += f"^LS{dots}"
    if mark_prepared:
        injection += f"^FX {_PREPARED_MARKER}"

    match = re.search(r"\^XA", text, flags=re.IGNORECASE)
    if match:
        text = text[: match.end()] + injection + text[match.end() :]
    else:
        text = "^XA" + injection + text

    shift_desc = f"{abs(shift_mm)}mm {'left' if shift_mm > 0 else 'right'}" if shift_mm else "0"
    scale_desc = f"{scale * 100:.1f}%"
    logger.info(
        "FedEx ZPL prepared: size=%s×%smm (%sx%s dots@%sdpi) rotate180=%s shift=%s scale=%s stored=%s",
        width_mm,
        height_mm,
        pw,
        ll,
        dpi,
        rotate_180,
        shift_desc,
        scale_desc,
        mark_prepared,
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
    adjust: bool | None = None,
) -> dict:
    """POST raw ZPL to ``{OFFICE_API_URL}/print``.

    By default prints the ZPL as stored on the office server (no extra tweaks).
    Legacy labels saved before store-time adjustment are auto-adjusted once unless
    ``adjust=False``.
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

    if is_prepared_fedex_zpl(zpl_text):
        zpl_text = first_zpl_label(zpl_text)
    elif adjust is not False and _should_adjust_fedex(carrier, zpl_text):
        # Old labels stored before we adjusted at save time.
        zpl_text = adjust_fedex_zpl(zpl_text, mark_prepared=False)
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
