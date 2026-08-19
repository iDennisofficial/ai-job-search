"""Parsing helpers for DeepSeek responses."""
from __future__ import annotations

import json
import re

# "FILE: <path>" followed by a fenced code block with an optional language tag.
FILE_BLOCK_RE = re.compile(
    r"FILE:\s*([^\n`]+?)\s*\n\s*```[a-zA-Z0-9_+-]*\n(.*?)\n\s*```",
    re.DOTALL,
)


def extract_files(text: str) -> list[tuple[str, str]]:
    """Return [(path, content)] for every 'FILE: <path>' + fenced block."""
    out: list[tuple[str, str]] = []
    for m in FILE_BLOCK_RE.finditer(text):
        path = m.group(1).strip().strip("`").strip()
        if path:
            out.append((path, m.group(2).strip("\n")))
    return out


def extract_json(text: str):
    """Best-effort JSON parse; tolerates ```json fences, prose, objects, arrays."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_+-]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        end = t.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("Could not parse JSON from model output")
