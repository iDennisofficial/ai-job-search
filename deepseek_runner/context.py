"""Context assembly.

DeepSeek has no filesystem access — the runner is the retrieval layer, so it
concatenates every file a command needs into a single context string that is
fed to the model alongside the command's own prompt text.
"""
from __future__ import annotations

from .config import Config
from .io import read_text


def build_context(config: Config, files: list[str]) -> str:
    """Concatenate the given repo-relative files with clear separators."""
    parts = []
    for rel in files:
        text = read_text(config.repo_root / rel)
        if text.strip():
            parts.append(f"===== FILE: {rel} =====\n{text.rstrip()}")
    return "\n\n".join(parts)


def read_command(config: Config, rel_path: str) -> str:
    """Read a command/skill prompt file verbatim."""
    return read_text(config.repo_root / rel_path)
