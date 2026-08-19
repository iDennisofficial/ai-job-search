"""Run the Bun job-portal CLIs and parse their JSON output.

The scraping itself needs no AI — the runner shells out to the portal CLIs
under .agents/skills/*/cli and only hands the JSON listings to DeepSeek for
fit-scoring.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

from .config import Config
from .io import read_text


def portal_skill(config: Config, portal: str) -> str:
    return read_text(config.repo_root / ".agents" / "skills" / portal / "SKILL.md")


def portal_enabled(config: Config, portal: str) -> bool:
    """Respect the `enabled: true` frontmatter flag on each SKILL.md."""
    skill = portal_skill(config, portal)
    return re.search(r"^enabled:\s*true", skill, re.MULTILINE) is not None


def cli_path(config: Config, portal: str):
    return config.repo_root / ".agents" / "skills" / portal / "cli" / "src" / "cli.ts"


def run_portal(
    config: Config, portal: str, args: list[str]
) -> tuple[bool, dict, str]:
    """Run `bun run <cli>/src/cli.ts <args>`; return (ok, json, error)."""
    cli = cli_path(config, portal)
    if not shutil.which(config.portal_bin):
        return False, {}, f"{config.portal_bin} not found on PATH"
    if not cli.exists():
        return False, {}, f"CLI not found: {cli}"
    cmd = [config.portal_bin, "run", str(cli), *args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=150, cwd=config.repo_root
        )
    except OSError as e:
        return False, {}, str(e)
    if proc.returncode != 0:
        raw_err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        try:
            err = json.loads(raw_err or "{}")
        except json.JSONDecodeError:
            err = {"error": raw_err[-500:] or "unknown CLI error"}
        return False, err, raw_err[-500:]
    try:
        data = json.loads(proc.stdout or "{}")
        return True, data, ""
    except json.JSONDecodeError:
        return False, {}, f"CLI returned non-JSON output: {proc.stdout[-300:]}"


def list_enabled_portals(config: Config) -> list[str]:
    """Portals that exist, are enabled in their SKILL.md, AND are listed in
    config.enabled_portals (default: linkedin-search, freehire-search)."""
    root = config.repo_root / ".agents" / "skills"
    if not root.is_dir():
        return []
    allowed = set(config.enabled_portals)
    out = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "cli" / "src" / "cli.ts").exists():
            if child.name in allowed and portal_enabled(config, child.name):
                out.append(child.name)
    return out
