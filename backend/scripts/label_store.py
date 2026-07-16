"""Deprecated local label cache.

Labels are stored on the office server via ``office_api.store_label`` /
``office_api.get_label``. Do not use this module for reprint — Render disk is
ephemeral and is not the source of truth.
"""

from __future__ import annotations

import warnings


def has_label(*_args, **_kwargs) -> bool:
    warnings.warn(
        "label_store is deprecated; use office_api.has_label / list_labels",
        DeprecationWarning,
        stacklevel=2,
    )
    return False


def has_zpl(*_args, **_kwargs) -> bool:
    return has_label()


def save_label(*_args, **_kwargs) -> dict:
    warnings.warn(
        "label_store.save_label is deprecated; use office_api.store_label",
        DeprecationWarning,
        stacklevel=2,
    )
    return {}


def load_label(*_args, **_kwargs) -> dict | None:
    warnings.warn(
        "label_store.load_label is deprecated; use office_api.get_label",
        DeprecationWarning,
        stacklevel=2,
    )
    return None
