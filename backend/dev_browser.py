"""Read-only Dev file browser for the running Render instance.

Lets staff inspect the code that is actually deployed, rather than what is in
git. Rooted at the project directory and read-only: no writes, no deletes, no
path escapes above the root.

Note this shows the *Render* filesystem. The Office Order API runs on a
separate machine and is not reachable from here.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, render_template, request

# backend/dev_browser.py -> backend -> project root
ROOT = Path(__file__).resolve().parent.parent

# Noise that would swamp the tree or blow up the response.
SKIP_NAMES = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache", ".mypy_cache"}

MAX_TEXT_BYTES = 2 * 1024 * 1024  # 2 MB cap — the instance only has 512 MB


def _resolve(rel: str) -> Path:
    """Resolve a relative path inside ROOT, refusing anything that escapes it."""
    cleaned = (rel or "").strip().lstrip("/\\")
    target = (ROOT / cleaned).resolve() if cleaned else ROOT
    if target != ROOT and ROOT not in target.parents:
        raise ValueError("Path is outside the project root")
    return target


def _rel(path: Path) -> str:
    return "" if path == ROOT else path.relative_to(ROOT).as_posix()


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%d %b %Y %H:%M")
    except OSError:
        return ""


def _looks_binary(blob: bytes) -> bool:
    return b"\x00" in blob[:4096]


def _dev_page():
    return render_template("UI/Dev_Files.html")


def _dev_tree():
    try:
        target = _resolve(request.args.get("path", ""))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    if not target.is_dir():
        return jsonify({"success": False, "error": "Not a directory"}), 404

    dirs, files = [], []
    try:
        for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if entry.name in SKIP_NAMES:
                continue
            try:
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": _rel(entry), "type": "dir", "modified": _mtime(entry)})
                else:
                    files.append({
                        "name": entry.name,
                        "path": _rel(entry),
                        "type": "file",
                        "size": entry.stat().st_size,
                        "modified": _mtime(entry),
                    })
            except OSError:
                continue
    except OSError as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

    rel = _rel(target)
    crumbs, walked = [{"name": "project", "path": ""}], ""
    for part in (rel.split("/") if rel else []):
        walked = f"{walked}/{part}" if walked else part
        crumbs.append({"name": part, "path": walked})

    parent = "" if target == ROOT else _rel(target.parent)
    return jsonify({
        "success": True,
        "path": rel,
        "parent": parent,
        "at_root": target == ROOT,
        "crumbs": crumbs,
        "entries": dirs + files,
    })


def _dev_file():
    try:
        target = _resolve(request.args.get("path", ""))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    if not target.is_file():
        return jsonify({"success": False, "error": "Not a file"}), 404

    size = target.stat().st_size
    if size > MAX_TEXT_BYTES:
        return jsonify({
            "success": True, "path": _rel(target), "size": size, "truncated": True, "binary": False,
            "content": f"File is {size:,} bytes — too large to display (limit {MAX_TEXT_BYTES:,}).",
        })

    try:
        blob = target.read_bytes()
    except OSError as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

    if _looks_binary(blob):
        return jsonify({
            "success": True, "path": _rel(target), "size": size, "truncated": False, "binary": True,
            "content": f"Binary file — {size:,} bytes.",
        })

    return jsonify({
        "success": True,
        "path": _rel(target),
        "size": size,
        "truncated": False,
        "binary": False,
        "modified": _mtime(target),
        "content": blob.decode("utf-8", errors="replace"),
    })


def init_dev_browser(app):
    """Register the Dev browser page and its two read-only JSON endpoints.

    All three sit behind portal_auth_gate, so staff login is required.
    """
    app.add_url_rule("/app/Dev", "dev_files_page", _dev_page, methods=["GET"])
    app.add_url_rule("/api/dev/tree", "dev_files_tree", _dev_tree, methods=["GET"])
    app.add_url_rule("/api/dev/file", "dev_files_file", _dev_file, methods=["GET"])
