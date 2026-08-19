"""/reset — wipe candidate profile and/or documents (destructive).

Faithful port of .claude/commands/reset.md. Nothing is deleted until the user
types `RESET`.
"""
from __future__ import annotations

import re
import shutil
import sys

from ..config import Config
from ..io import read_text, write_text
from ._common import ask

S01 = ".claude/skills/job-application-assistant/01-candidate-profile.md"
S02 = ".claude/skills/job-application-assistant/02-behavioral-profile.md"
S05 = ".claude/skills/job-application-assistant/05-cv-templates.md"
S07 = ".claude/skills/job-application-assistant/07-interview-prep.md"

BLANK_01 = """# Candidate Profile

<!-- Run /setup to populate this file -->

## Identity

## Education

## Professional Experience

## Independent Projects

## Technical Skills

## Publications

## Awards

## References
"""

BLANK_02 = """# Behavioral Profile

<!-- Run /setup to populate this file -->

## Overview

## Strongest Behavioral Traits

## How I Work Best

## Growth Areas

## Mapping to Job Posting Language

## Management Style Preferences

## Using This in Applications
"""

PROFILE_STATEMENTS_PLACEHOLDER = (
    "**Profile statement templates:**\n\n"
    "<!-- Run /setup to populate role-specific profile statements -->"
)

STAR_PLACEHOLDER = (
    "## Ready-Made STAR Examples\n\n"
    "<!-- Run /setup to populate STAR examples from your actual experience -->"
)

_SECTION_RE = r"(?=\n##\s|\Z)"


def _reset_profile_statements(text: str) -> str:
    pattern = re.compile(
        r"\*\*Profile statement templates.*?" + _SECTION_RE, re.DOTALL
    )
    if not pattern.search(text):
        return text
    return pattern.sub(PROFILE_STATEMENTS_PLACEHOLDER + "\n", text, count=1)


def _reset_star_sections(text: str) -> str:
    text = re.sub(
        r"## Ready-Made STAR Examples.*?" + _SECTION_RE,
        STAR_PLACEHOLDER + "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"## STAR Candidates \(Complete Manually\).*?" + _SECTION_RE,
        "",
        text,
        count=1,
        flags=re.DOTALL,
    )
    # Tidy: collapse 3+ blank lines left behind.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _has_content(text: str) -> bool:
    # A file "has content" when it carries real section bodies, not just
    # headings + comments.
    stripped = re.sub(r"(?m)^\s*(#.*|<!--.*-->)\s*$", "", text)
    return bool(stripped.strip())


def run(config: Config, argv: list[str]) -> int:
    scope = None
    for token in argv:
        if token in ("profile", "documents", "all"):
            scope = token
            break

    if scope is None:
        print("What would you like to reset?")
        print("  profile   — clears candidate data from skill files (framework preserved)")
        print("  documents — deletes files in documents/ (folder structure preserved)")
        print("  all       — both of the above")
        ans = ask("Reply with profile, documents, or all").strip().lower()
        if ans not in ("profile", "documents", "all"):
            print("Unknown scope. Reset cancelled.")
            return 1
        scope = ans

    do_profile = scope in ("profile", "all")
    do_docs = scope in ("documents", "all")

    # --- Step 1: show exactly what will be cleared -------------------------
    if do_profile:
        s01 = read_text(config.repo_root / S01)
        s02 = read_text(config.repo_root / S02)
        s05 = read_text(config.repo_root / S05)
        s07 = read_text(config.repo_root / S07)
        print("\n## Profile reset will clear:")
        print(
            f"- 01-candidate-profile.md — "
            f"{'has content' if _has_content(s01) else 'already empty'}"
        )
        print("  Full file will be replaced with a blank template.")
        print(
            f"- 02-behavioral-profile.md — "
            f"{'has content' if _has_content(s02) else 'already empty'}"
        )
        print("  Full file will be replaced with a blank template.")
        print(
            f"- 05-cv-templates.md — "
            f"{'has profile statements' if 'Profile statement templates' in s05 else 'already blank'}"
        )
        print("  Profile statement templates will be cleared; framework preserved.")
        print(
            f"- 07-interview-prep.md — "
            f"{'has STAR examples' if 'Ready-Made STAR Examples' in s07 else 'already blank'}"
        )
        print("  STAR sections will be cleared; framework preserved.")
        print("The following files are NOT touched (framework rules only):")
        print("  - 03-writing-style.md\n  - 04-job-evaluation.md\n  - 06-cover-letter-templates.md")

    if do_docs:
        print("\n## Documents reset will delete:")
        total = 0
        for sub in ("cv", "linkedin", "diplomas", "references", "applications"):
            folder = config.repo_root / "documents" / sub
            names = sorted(
                p.name for p in folder.iterdir()
                if folder.is_dir() and not p.name.startswith(".")
            ) if folder.is_dir() else []
            total += len(names)
            print(f"documents/{sub}/")
            for n in names:
                print(f"  - {n}")
            if not names:
                print("  (empty)")
        print("documents/README.md — NOT deleted (instructions file)")
        if total == 0:
            print("All document subfolders are already empty — nothing to delete.")
            do_docs = False

    if not do_profile and not do_docs:
        print("Nothing to reset.")
        return 0

    # --- Step 2: require explicit confirmation -----------------------------
    print("\n> **This cannot be undone.**")
    ans = ask("Type RESET (all caps) to confirm, or anything else to cancel")
    if ans != "RESET":
        print("Reset cancelled. Nothing was changed.")
        return 0

    # --- Step 3: execute -----------------------------------------------------
    cleared, unchanged = [], []
    if do_profile:
        write_text(config.repo_root / S01, BLANK_01)
        cleared.append("01-candidate-profile.md (blank template written)")
        write_text(config.repo_root / S02, BLANK_02)
        cleared.append("02-behavioral-profile.md (blank template written)")
        s05 = _reset_profile_statements(read_text(config.repo_root / S05))
        write_text(config.repo_root / S05, s05)
        cleared.append("05-cv-templates.md (profile statements cleared)")
        s07 = _reset_star_sections(read_text(config.repo_root / S07))
        write_text(config.repo_root / S07, s07)
        cleared.append("07-interview-prep.md (STAR sections cleared)")

    if do_docs:
        for sub in ("cv", "linkedin", "diplomas", "references"):
            folder = config.repo_root / "documents" / sub
            if folder.is_dir():
                for f in folder.iterdir():
                    # Skip hidden files (matches the upstream `rm -f dir/*` glob,
                    # which does not match dotfiles like .gitkeep).
                    if f.is_file() and not f.name.startswith("."):
                        f.unlink()
                        cleared.append(f"documents/{sub}/{f.name}")
        apps = config.repo_root / "documents" / "applications"
        if apps.is_dir():
            for d in apps.iterdir():
                if d.is_dir():
                    shutil.rmtree(d)
                    cleared.append(f"documents/applications/{d.name}/")

    # --- Step 4: report -------------------------------------------------------
    print("\n## Reset complete\n")
    print("### Cleared")
    for c in cleared:
        print(f"- {c}")
    print("\n### Unchanged")
    print("- 03-writing-style.md, 04-job-evaluation.md, 06-cover-letter-templates.md (framework)")
    print("- documents/ folder structure + README.md")

    if do_profile:
        print("\nYour candidate profile is now blank. Run `setup` to repopulate it.")
    if do_docs:
        print("\nThe documents/ folder is now empty. Add career documents, then run `setup`.")
    return 0
