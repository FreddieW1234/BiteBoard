"""Force UTF-8 on stdout/stderr so Windows cp1252 does not crash on Unicode data."""

from __future__ import annotations

import sys


def configure_stdio_utf8(*, log: bool = False) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    if log:
        out_enc = getattr(sys.stdout, "encoding", None)
        err_enc = getattr(sys.stderr, "encoding", None)
        print(f"[ok] stdio encoding stdout={out_enc!r} stderr={err_enc!r}", flush=True)
