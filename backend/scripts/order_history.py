"""Change history per order: who changed what, and when.

Kept on the office server (snapshot items, kind ``order_history``, one item per
order) so it survives redeploys. Writing is done in the background and never
fails or slows the action being logged.
"""

from __future__ import annotations

import difflib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

log = logging.getLogger(__name__)

KIND = "order_history"
MAX_EVENTS = 500

# One gunicorn worker: this lock makes each read-add-write of an order's log atomic.
_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="order-history")

STAGE_LABELS = {
    "received": "Order received",
    "artwork": "Artwork",
    "approved": "Proof approved",
    "printing": "Printing",
    "in_production": "In production",
    "shipped": "Shipped",
}


def _key(order_name: str) -> str:
    return (order_name or "").strip().lstrip("#")


def stage_label(stage: str) -> str:
    stage = (stage or "").strip()
    if stage.startswith("proof_"):
        return f"Proof {stage.split('_', 1)[1]}"
    return STAGE_LABELS.get(stage, stage.replace("_", " ").capitalize())


def current_actor() -> str:
    """Who is making this request: staff username, the customer, or BiteBoard itself.

    Call from the request thread (it reads the session).
    """
    try:
        from portal_auth import get_client_email, get_staff_username, is_staff_authenticated  # type: ignore

        if is_staff_authenticated():
            return get_staff_username() or "Staff"
        email = get_client_email()
        if email:
            return f"Customer ({email})"
    except Exception:
        pass
    return "BiteBoard"


def record(
    order_name: str,
    action: str,
    detail: str = "",
    *,
    item: str = "",
    who: str | None = None,
    wait: bool = False,
) -> None:
    """Add one event to an order's history (in the background unless ``wait``)."""
    key = _key(order_name)
    if not key or not action:
        return
    event = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "who": who if who is not None else current_actor(),
        "action": action,
        "detail": (detail or "").strip()[:2000],
        "item": (item or "").strip(),
    }
    if wait:
        _append(key, event)
    else:
        try:
            _POOL.submit(_append, key, event)
        except RuntimeError:  # interpreter shutting down
            pass


def _append(key: str, event: dict) -> None:
    try:
        from scripts.office_api import get_snapshot_item, put_snapshot_item  # type: ignore

        with _LOCK:
            current = get_snapshot_item(KIND, key) or {}
            events = list((current.get("payload") or {}).get("events") or [])
            events.append(event)
            put_snapshot_item(KIND, key, {"order": f"#{key}", "events": events[-MAX_EVENTS:]},
                              updated_by=event.get("who") or "")
    except Exception as exc:
        log.warning("Order history not saved for #%s (%s): %s", key, event.get("action"), exc)


def get_history(order_name: str) -> list[dict]:
    """Events for one order, newest first."""
    from scripts.office_api import get_snapshot_item  # type: ignore

    current = get_snapshot_item(KIND, _key(order_name)) or {}
    events = list((current.get("payload") or {}).get("events") or [])
    events.sort(key=lambda e: e.get("at") or "", reverse=True)
    return events


def note_changes(old: str, new: str, limit: int = 12) -> str:
    """Readable summary of what changed in the order note ("was" / "now" lines)."""
    a = [l.rstrip() for l in (old or "").replace("\r\n", "\n").split("\n") if l.strip()]
    b = [l.rstrip() for l in (new or "").replace("\r\n", "\n").split("\n") if l.strip()]
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        out += [f"Was: {l}" for l in a[i1:i2]]
        out += [f"Now: {l}" for l in b[j1:j2]]
    if len(out) > limit:
        out = out[:limit] + [f"… and {len(out) - limit} more"]
    return "\n".join(out)
