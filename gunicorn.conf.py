"""Shim: real settings live in backend/gunicorn.conf.py (used after --chdir)."""

import os
import runpy

_BACKEND_CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "gunicorn.conf.py")
_globals = runpy.run_path(_BACKEND_CONF)
for _k, _v in _globals.items():
    if _k.startswith("_"):
        continue
    globals()[_k] = _v
