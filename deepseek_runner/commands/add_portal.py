"""/add-portal — scaffold a job-portal search skill.

Port of .claude/commands/add-portal.md. Uses the canonical linkedin-search
skill (zero-dependency CLI) as the structural reference and DeepSeek to
generate the new portal's SKILL.md, url-reference.md and cli/ files. The
runner writes the files and attempts a bun install/typecheck.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..client import DeepSeekClient
from ..config import Config
from ..io import read_text, write_text
from ..parse_output import extract_files
from ._common import ask

CANONICAL = ".agents/skills/linkedin-search"
REFERENCE_FILES = [
    f"{CANONICAL}/SKILL.md",
    f"{CANONICAL}/url-reference.md",
    f"{CANONICAL}/cli/package.json",
    f"{CANONICAL}/cli/tsconfig.json",
    f"{CANONICAL}/cli/src/cli.ts",
    f"{CANONICAL}/cli/src/helpers.ts",
    f"{CANONICAL}/cli/src/commands/search.ts",
    f"{CANONICAL}/cli/src/commands/detail.ts",
    ".agents/skills/jobindex-search/cli/tests/helpers.ts",
]


def _reference_context(config: Config) -> str:
    parts = []
    for rel in REFERENCE_FILES:
        text = read_text(config.repo_root / rel)
        if text.strip():
            parts.append(f"===== {rel} =====\n{text}")
    return "\n\n".join(parts)


def _list_portals(config: Config) -> None:
    root = config.repo_root / ".agents" / "skills"
    if not root.is_dir():
        print("No portal skills found.")
        return
    for d in sorted(root.iterdir()):
        skill = read_text(d / "SKILL.md")
        name = d.name
        desc = ""
        m = re.search(r"^description:\s*(.+)$", skill, re.MULTILINE)
        if m:
            desc = m.group(1).strip()[:80]
        enabled = "enabled" if re.search(r"^enabled:\s*true", skill, re.MULTILINE) else "disabled"
        print(f"  {name:<18} [{enabled:<8}] {desc}")


def run(config: Config, argv: list[str]) -> int:
    if "--list" in argv:
        _list_portals(config)
        return 0

    print("Scaffolding a new job-portal search skill (LLM-assisted).")
    portal_url = ask("Portal search URL (e.g. https://example.com/jobs?q=)").strip()
    if not portal_url.startswith(("http://", "https://")):
        print("A valid portal URL is required.")
        return 1
    name = ask("Skill name (kebab-case with -search suffix, e.g. 'myboard-search')").strip()
    if not name.endswith("-search"):
        name = f"{name}-search"
    market = ask("Market / language (e.g. 'Germany / German')").strip()
    test_query = ask("A test query (e.g. 'software engineer')").strip()

    client = DeepSeekClient(config)
    user = (
        f"Scaffold a new job-portal search skill for the portal at {portal_url} "
        f"(market: {market}). Follow the canonical linkedin-search structure "
        "provided below EXACTLY (portal-skill contract): commands `search` and "
        "`detail <id|url>`; flags --query/-q, --jobage, --page, --limit, "
        "--format json|table|plain (default json); JSON shape "
        '{"meta":{"count","page"},"results":[...]} with missing values null; '
        "errors to stderr {\"error\",\"code\"} exit 1; zero runtime deps; "
        "fetch with a UA and backoff.\n"
        f"Output these files as FILE: fenced blocks under "
        f".agents/skills/{name}/:\n"
        f"- SKILL.md (frontmatter: name {name}, version 1.0.0, description EN + "
        f"market-language triggers, context: fork, allowed-tools Bash(bun run "
        f"skills/{name}/cli/src/cli.ts *), enabled: true)\n"
        f"- url-reference.md (endpoints/params/field anchors for {portal_url})\n"
        f"- cli/package.json (name {name}-cli, type module, scripts start/test/"
        "typecheck)\n"
        f"- cli/tsconfig.json\n- cli/README.md\n- cli/src/cli.ts\n"
        f"- cli/src/helpers.ts\n- cli/src/commands/search.ts\n"
        f"- cli/src/commands/detail.ts\n- cli/tests/helpers.ts\n\n"
        f"Adapt the search URL pattern to {portal_url} and make the field "
        "mapping match the portal's actual HTML/JSON where inferable.\n\n"
        f"## Reference structure\n{_reference_context(config)}"
    )
    print("Generating portal skill files…")
    result = client.chat(
        [{"role": "system",
          "content": "You scaffold job-portal search CLI skills. You follow the "
                     "canonical structure precisely and only write the files "
                     "requested, as FILE: blocks."},
         {"role": "user", "content": user}],
        role="default", temperature=0.2,
    )
    files = extract_files(result)
    if not files:
        print("Model returned no FILE: blocks.\n" + result[:2000])
        return 1
    cli_written = False
    for p, content in files:
        if p.startswith(f".agents/skills/{name}/"):
            write_text(config.repo_root / p, content)
            print(f"  wrote {p}")
            if p.endswith("cli.ts"):
                cli_written = True

    if not cli_written:
        print("Warning: no cli/src/cli.ts was generated — the skill may not run.")
    if shutil.which("bun"):
        cli_dir = config.repo_root / ".agents" / "skills" / name / "cli"
        if cli_dir.exists():
            print("\nInstalling + typechecking…")
            subprocess.run(["bun", "install"], cwd=cli_dir, capture_output=True, timeout=180)
            tc = subprocess.run(["bun", "run", "typecheck"], cwd=cli_dir,
                                capture_output=True, text=True, timeout=180)
            if tc.returncode == 0:
                print("  typecheck OK")
            else:
                print("  typecheck had issues (see output):")
                print((tc.stdout + tc.stderr)[-1500:])
    print("\nPortal skill scaffolded. It will be auto-discovered by `scrape`.")
    print(f"Test it: python deepseek_runner.py scrape --portal {name} "
          f"--query '{test_query}' --format json")
    return 0
