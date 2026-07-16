"""Deployed git commit info for staff UI (Render + local dev)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_cached: dict | None = None


def get_build_info() -> dict:
    """Return commit metadata for the running deploy."""
    global _cached
    if _cached is not None:
        return dict(_cached)

    commit = (
        os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("COMMIT_SHA")
        or os.environ.get("SOURCE_VERSION")
        or ""
    ).strip()
    branch = (
        os.environ.get("RENDER_GIT_BRANCH")
        or os.environ.get("GIT_BRANCH")
        or ""
    ).strip()
    source = "env"

    if not commit:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if result.returncode == 0:
                commit = (result.stdout or "").strip()
                source = "git"
        except Exception:
            pass

    if not branch and commit:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if result.returncode == 0:
                branch = (result.stdout or "").strip()
        except Exception:
            pass

    commit_short = commit[:7] if len(commit) >= 7 else commit
    if not commit:
        _cached = {
            "commit": "",
            "commit_short": "",
            "branch": branch,
            "source": "unknown",
            "label": "unknown",
        }
        return dict(_cached)

    label = commit_short
    if branch and branch != "HEAD":
        label = f"{commit_short} · {branch}"

    _cached = {
        "commit": commit,
        "commit_short": commit_short,
        "branch": branch,
        "source": source,
        "label": label,
    }
    return dict(_cached)
