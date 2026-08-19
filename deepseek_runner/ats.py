"""ATS text-layer verification (pdftotext, poppler).

ATS parsers read the PDF's embedded text layer, not the rendered page. This
module extracts it and checks what a parser would actually see. `pdftotext` is
an optional dependency — callers should skip gracefully when it is missing.
"""
from __future__ import annotations

import re
import subprocess


def pdftotext_available() -> bool:
    try:
        subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, timeout=15)
        return True
    except (FileNotFoundError, OSError):
        return False


def extract_text(pdf_path: str) -> str | None:
    """Return the layout-preserved text layer, or None if unavailable/failed."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            return proc.stdout
    except (FileNotFoundError, OSError):
        return None
    return None


def parseability_issues(text: str) -> list[str]:
    """Return a list of parseability problems in the extracted text layer."""
    issues = []
    if re.search(r"\(cid:\d+\)", text):
        issues.append("Contains (cid:NNN) glyph markers — invisible to an ATS parser.")
    if "\ufffd" in text:
        issues.append("Contains replacement characters (�) — garbled extraction.")
    return issues


def keyword_coverage(text: str, keywords: list[str]) -> list[dict]:
    """Literal keyword coverage against the extracted text layer."""
    lower = text.lower()
    rows = []
    for kw in keywords:
        rows.append(
            {
                "keyword": kw,
                "status": "covered" if (kw or "").lower() in lower else "missing",
            }
        )
    return rows
