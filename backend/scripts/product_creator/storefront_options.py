"""
Storefront product option metafields written on BiteBoard product save.

Colour fields: comma-separated Name:Code pairs (single_line_text_field).
Fee toggles: full choice lists (list.single_line_text_field) - prices live on fee products.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

COLOUR_METAFIELD_KEYS = (
    "product_colours",
    "packaging_colours",
    "foil_colours",
    "bag_colours",
)

CUSTOM_OPTION_SLOTS = (1, 2, 3)
CUSTOM_OPTION_METAFIELD_KEYS = tuple(
    key
    for n in CUSTOM_OPTION_SLOTS
    for key in (f"customoption{n}name", f"customoption{n}options")
)

STOREFRONT_OPTION_KEYS = ("print", "foil", "mailer", "mailerpacking")

STOREFRONT_OPTION_CHOICES: Dict[str, List[str]] = {
    "print": ["Outside Only", "Outside + Inside"],
    "foil": ["Yes", "No"],
    "mailer": ["Yes", "No"],
    "mailerpacking": ["Yes", "No"],
}

CALENDAR_METAFIELD_KEY = "calendar"

RETIRED_METAFIELD_KEYS = ("packingfee",)


def _truthy(val: Any) -> bool:
    if val is True:
        return True
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def parse_storefront_options(raw: Any) -> Dict[str, List[str]]:
    """Return enabled options mapped to their validated choice lists."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for key in STOREFRONT_OPTION_KEYS:
        if not _truthy(raw.get(key)):
            continue
        choices = STOREFRONT_OPTION_CHOICES.get(key)
        if choices:
            out[key] = list(choices)
    return out


def validate_storefront_options(raw: Any) -> Optional[str]:
    """Return an error message if storefront_options payload is invalid."""
    if raw is None:
        return None
    if isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            return "storefront_options must be an object"
    if not isinstance(raw, dict):
        return "storefront_options must be an object"
    for key, enabled in raw.items():
        if key not in STOREFRONT_OPTION_KEYS:
            continue
        if not isinstance(enabled, (bool, str, int)) and enabled is not None:
            return f"Invalid storefront option flag for {key}"
    return None


def resolve_storefront_options(storefront_options: Any, is_calendar: Any) -> Dict[str, bool]:
    """Calendar products always expose print/mailer toggles; foil is optional."""
    if _truthy(is_calendar):
        opts = storefront_options if isinstance(storefront_options, dict) else {}
        return {
            "print": True,
            "foil": _truthy(opts.get("foil")),
            "mailer": True,
            "mailerpacking": True,
        }
    if not isinstance(storefront_options, dict):
        return {}
    return {key: _truthy(storefront_options.get(key)) for key in STOREFRONT_OPTION_KEYS if key in storefront_options}


def build_calendar_metafield_entry(is_calendar: Any) -> dict:
    return {
        "namespace": "custom",
        "key": CALENDAR_METAFIELD_KEY,
        "value": "true" if _truthy(is_calendar) else "",
        "type": "boolean",
    }


def build_colour_metafield_entries(
    product_data: dict,
    *,
    is_child: bool,
) -> List[dict]:
    """Build colour metafield payloads; empty value deletes the metafield on save."""
    if is_child:
        return []
    entries: List[dict] = []
    for colour_key in COLOUR_METAFIELD_KEYS:
        if colour_key not in product_data:
            continue
        colour_val = str(product_data.get(colour_key) or "").strip()
        entries.append({
            "namespace": "custom",
            "key": colour_key,
            "value": colour_val,
            "type": "single_line_text_field",
        })
    return entries


def build_custom_option_metafield_entries(
    product_data: dict,
    *,
    is_child: bool,
) -> List[dict]:
    """Build customoptionNname / customoptionNoptions payloads (max 3 slots)."""
    if is_child:
        return []
    entries: List[dict] = []
    any_present = any(
        f"customoption{n}name" in product_data or f"customoption{n}options" in product_data
        for n in CUSTOM_OPTION_SLOTS
    )
    if not any_present:
        return []
    for n in CUSTOM_OPTION_SLOTS:
        name_key = f"customoption{n}name"
        opts_key = f"customoption{n}options"
        name_val = str(product_data.get(name_key) or "").strip()
        opts_val = str(product_data.get(opts_key) or "").strip()
        if not name_val:
            name_val = ""
            opts_val = ""
        entries.append({
            "namespace": "custom",
            "key": name_key,
            "value": name_val,
            "type": "single_line_text_field",
        })
        entries.append({
            "namespace": "custom",
            "key": opts_key,
            "value": opts_val,
            "type": "single_line_text_field",
        })
    return entries


def build_storefront_option_metafield_entries(storefront_options: Any) -> List[dict]:
    """
    Enabled options get the full choice list. Disabled options send empty values
    so create_metafields deletes them (storefront hides the group).
    """
    if not isinstance(storefront_options, dict):
        return []
    entries: List[dict] = []
    for key in STOREFRONT_OPTION_KEYS:
        if key not in storefront_options:
            continue
        if _truthy(storefront_options.get(key)):
            entries.append({
                "namespace": "custom",
                "key": key,
                "value": json.dumps(STOREFRONT_OPTION_CHOICES[key]),
                "type": "list.single_line_text_field",
            })
        else:
            entries.append({
                "namespace": "custom",
                "key": key,
                "value": "",
                "type": "list.single_line_text_field",
            })
    return entries


def retired_metafield_clear_entries() -> List[dict]:
    """Queue deletion of retired metafields (e.g. custom.packingfee)."""
    return [
        {
            "namespace": "custom",
            "key": key,
            "value": "",
            "type": "single_line_text_field",
        }
        for key in RETIRED_METAFIELD_KEYS
    ]


def storefront_clearable_keys() -> set:
    return (
        set(COLOUR_METAFIELD_KEYS)
        | set(CUSTOM_OPTION_METAFIELD_KEYS)
        | set(STOREFRONT_OPTION_KEYS)
        | set(RETIRED_METAFIELD_KEYS)
        | {CALENDAR_METAFIELD_KEY}
    )
