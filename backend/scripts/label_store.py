"""Persist purchased shipping labels for reprint (local files, not Office API)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent
_LABELS_DIR = _BASE_DIR / "data" / "shipping_labels"


def _safe_token(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return (text[:48] or "x").strip("_") or "x"


def _key(order_name: str, item_id: str) -> str:
    raw = f"{(order_name or '').strip()}\0{(item_id or '').strip()}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:24]
    return f"{_safe_token(order_name)}__{_safe_token(item_id)}__{digest}"


def _paths(order_name: str, item_id: str) -> tuple[Path, Path]:
    key = _key(order_name, item_id)
    return _LABELS_DIR / f"{key}.bin", _LABELS_DIR / f"{key}.json"


def has_label(order_name: str, item_id: str) -> bool:
    _, meta_path = _paths(order_name, item_id)
    if not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    bin_path, _ = _paths(order_name, item_id)
    if bin_path.is_file() and bin_path.stat().st_size > 0:
        return True
    return bool((meta.get("label_url") or "").strip())


def has_zpl(order_name: str, item_id: str) -> bool:
    """True when stored label bytes exist (required for office Zebra print)."""
    bin_path, meta_path = _paths(order_name, item_id)
    if not bin_path.is_file() or bin_path.stat().st_size <= 0:
        return False
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fmt = str(meta.get("label_format") or "zpl").lower()
            if fmt and "zpl" not in fmt and fmt != "url":
                return False
        except Exception:
            pass
    return True


def save_label(
    *,
    order_name: str,
    item_id: str,
    label_bytes: bytes = b"",
    label_url: str = "",
    label_format: str = "zpl",
    tracking_number: str = "",
    label_id: str = "",
    carrier: str = "",
    service_code: str = "",
) -> dict:
    order_name = (order_name or "").strip()
    item_id = (item_id or "").strip()
    if not order_name or not item_id:
        raise ValueError("order_name and item_id are required")

    _LABELS_DIR.mkdir(parents=True, exist_ok=True)
    bin_path, meta_path = _paths(order_name, item_id)

    data = label_bytes or b""
    if data:
        bin_path.write_bytes(data)
    elif bin_path.exists() and not data:
        # Keep existing binary if a later save only updates metadata.
        pass
    else:
        if bin_path.exists():
            bin_path.unlink(missing_ok=True)

    meta = {
        "order_name": order_name,
        "item_id": item_id,
        "tracking_number": (tracking_number or "").strip(),
        "label_id": (label_id or "").strip(),
        "carrier": (carrier or "").strip(),
        "service_code": (service_code or "").strip(),
        "label_format": (label_format or "zpl").strip().lower() or "zpl",
        "label_url": (label_url or "").strip(),
        "has_bytes": bool(data) or (bin_path.is_file() and bin_path.stat().st_size > 0),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def load_label(order_name: str, item_id: str) -> dict | None:
    order_name = (order_name or "").strip()
    item_id = (item_id or "").strip()
    if not order_name or not item_id:
        return None

    bin_path, meta_path = _paths(order_name, item_id)
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read label meta for %s / %s: %s", order_name, item_id, exc)
        return None

    label_bytes = b""
    if bin_path.is_file():
        try:
            label_bytes = bin_path.read_bytes()
        except Exception as exc:
            logger.warning("Could not read label bytes for %s / %s: %s", order_name, item_id, exc)

    if not label_bytes and not (meta.get("label_url") or "").strip():
        return None

    return {
        **meta,
        "label_bytes": label_bytes,
        "has_bytes": bool(label_bytes),
    }
