"""Fetch job-posting content from a URL (the WebFetch equivalent).

Only used for the posting URL the user supplied to /apply — the runner never
follows links found inside a posting body (untrusted input).
"""
from __future__ import annotations

import html
import re

import requests


def extract_readable_text(raw: str) -> str:
    """Crude HTML->text: strip script/style/tags, collapse whitespace."""
    raw = re.sub(r"(?is)<(script|style|noscript|head).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw)
    return raw.strip()


def fetch_url(url: str, timeout: float = 30.0) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ai-job-search-runner/0.1)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if "json" in content_type:
        try:
            return resp.json()
        except ValueError:
            pass
    return extract_readable_text(resp.text)
