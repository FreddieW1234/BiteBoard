"""
A4 document printing for the Office Order API
=============================================

The portal (Render) sends finished PDFs here - e.g. the 6am Sage info sheets -
and this prints them on the office A4 printer with SumatraPDF (free, silent
printing). The Zebra label route (/print) is unchanged.

Setup on the office PC
----------------------
1. Install SumatraPDF (https://www.sumatrapdfreader.org) - the normal
   installer, "for all users". Or put SumatraPDF.exe next to app.py.
2. In .env (next to app.py) add the printer's exact Windows name, e.g.
       DOC_PRINTER=Kyocera ECOSYS M5526cdw
   GET /print/document/health lists every printer Windows knows, so you can
   copy the name from there. Optional: SUMATRA_PDF=<full path to the exe>.
3. Register near the bottom of app.py (next to the api keys add-on):
       from print_docs_addon import register_print_docs_routes
       register_print_docs_routes(app, require_key_dep=require_key)
4. Restart the Office Order API service.

The service runs as a Windows service, so the printer must be installed for the
account the service runs as (a printer added "for all users", or a local/TCP
printer, works; a network printer mapped only in someone's login may not).

Endpoints (all require X-API-Key):
    POST /print/document          multipart: file (PDF), title?, copies?
    GET  /print/document/health   printer + SumatraPDF status, installed printers
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from fastapi import Depends, File, Form, HTTPException, UploadFile

_PRINT_LOCK = threading.Lock()  # one job at a time - keeps pages in order
_MAX_PDF_BYTES = 20 * 1024 * 1024


def _printer_name() -> str:
    return (os.environ.get("DOC_PRINTER") or "").strip()


def _sumatra_path() -> str | None:
    candidates = [
        os.environ.get("SUMATRA_PDF", ""),
        str(Path(__file__).with_name("SumatraPDF.exe")),
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "SumatraPDF", "SumatraPDF.exe"),
        shutil.which("SumatraPDF") or "",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _installed_printers() -> list[str]:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=20,
        )
        return [line.strip() for line in (out.stdout or "").splitlines() if line.strip()]
    except Exception:
        return []


def register_print_docs_routes(app, *, require_key_dep) -> None:
    @app.get("/print/document/health", dependencies=[Depends(require_key_dep)])
    def print_document_health():
        printer = _printer_name()
        printers = _installed_printers()
        return {
            "configured": bool(printer and _sumatra_path()),
            "printer": printer or None,
            "printer_found": bool(printer) and printer in printers,
            "sumatra": _sumatra_path(),
            "installed_printers": printers,
        }

    @app.post("/print/document", dependencies=[Depends(require_key_dep)])
    def print_document(
        file: UploadFile = File(...),
        title: str = Form(""),
        copies: int = Form(1),
    ):
        printer = _printer_name()
        if not printer:
            raise HTTPException(500, "DOC_PRINTER is not set in the office server's .env.")
        sumatra = _sumatra_path()
        if not sumatra:
            raise HTTPException(500, "SumatraPDF is not installed on the office PC.")
        data = file.file.read(_MAX_PDF_BYTES + 1)
        if len(data) > _MAX_PDF_BYTES:
            raise HTTPException(413, "PDF is too large.")
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "File is not a PDF.")
        copies = max(1, min(int(copies or 1), 5))

        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(data)
                tmp = f.name
            with _PRINT_LOCK:
                result = subprocess.run(
                    [sumatra, "-print-to", printer, "-print-settings", f"{copies}x,fit",
                     "-silent", "-exit-when-done", tmp],
                    capture_output=True, text=True, timeout=90,
                )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "unknown error").strip()
                raise HTTPException(502, f"Print failed: {detail[:300]}")
            return {"ok": True, "printer": printer, "title": title, "copies": copies, "bytes": len(data)}
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Printer did not finish within 90s.")
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
