#!/usr/bin/env python3
"""
Reconcile Online Store publish state + taxonomy `visible` flags (Phase 7).

Policy:
  - Online-Store-published product count > 0 and indexable → publish + visible
  - Count = 0 → unpublish + visible false
  - indexable false → never publish (unpublish if currently published)

Usage (from repo root):
    python scripts/reconcile_visibility.py
    python scripts/reconcile_visibility.py --write
    python scripts/reconcile_visibility.py --write --force

Dry-run is the default. --force bypasses the 20% unpublish circuit breaker
(manual only — nightly cron must not pass --force).

Local encoding: see scripts/README-PYTHONUTF8.md (reconfigure + PYTHONUTF8).
"""

from __future__ import annotations

import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

import argparse
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
for p in (_BACKEND,):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from shopify_client.bite_shopify import ShopifyError  # noqa: E402
from shopify_client.taxonomy import (  # noqa: E402
    VisibilityCircuitBreaker,
    reconcile_visibility,
)


def _print_table(rows: list[dict]) -> None:
    headers = ("handle", "published_count", "indexable", "online_store", "action")
    data = []
    for r in rows:
        action = str(r.get("action") or "")
        if action == "missing_collection":
            online = "missing"
        elif r.get("is_published"):
            online = "published"
        else:
            online = "unpublished"
        data.append(
            (
                str(r.get("handle") or ""),
                str(r.get("count", "")),
                str(bool(r.get("indexable", True))).lower(),
                online,
                action,
            )
        )
    widths = [len(h) for h in headers]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(row):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    print(fmt(headers))
    print(fmt(tuple("-" * w for w in widths)))
    for row in data:
        print(fmt(row))


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile collection visibility (Phase 7)")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply publish/unpublish + taxonomy visible updates (default: dry-run)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass 20%% unpublish circuit breaker (manual only; never use on cron)",
    )
    args = parser.parse_args()

    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"reconcile_visibility [{mode}] force={bool(args.force)}", flush=True)

    try:
        report = reconcile_visibility(write=bool(args.write), force=bool(args.force))
    except VisibilityCircuitBreaker as e:
        report = e.report or {}
        rows = report.get("rows") or []
        if rows:
            _print_table(rows)
        counts = report.get("counts") or {}
        print(
            f"\n[aborted] circuit breaker  published_now={counts.get('published_now')}  "
            f"planned_unpublished={sum(1 for r in rows if r.get('will_unpublish'))}",
            flush=True,
        )
        print(str(e), flush=True)
        return 2
    except ShopifyError as e:
        print(f"[error] {e}", flush=True)
        return 1
    except Exception as e:
        print(f"[error] {e}", flush=True)
        return 1

    rows = report.get("rows") or []
    _print_table(rows)
    counts = report.get("counts") or {}
    print(
        "\nsummary  "
        f"nodes={counts.get('nodes')}  "
        f"published={counts.get('published')}  "
        f"unpublished={counts.get('unpublished')}  "
        f"noop={counts.get('noop')}  "
        f"skipped_non_indexable={counts.get('skipped_non_indexable')}  "
        f"missing={counts.get('missing_collection')}  "
        f"errors={counts.get('errors')}",
        flush=True,
    )
    if args.write:
        print(
            f"taxonomy_written={report.get('taxonomy_written')}  "
            f"updated_at={report.get('taxonomy_updated_at')}",
            flush=True,
        )

    if not report.get("success", True) or int(counts.get("errors") or 0) > 0:
        if report.get("error"):
            print(f"[error] {report['error']}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
