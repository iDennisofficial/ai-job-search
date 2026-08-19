"""/setup — profile onboarding.

Interactive intake that populates CLAUDE.md + skill files 01–07 from the user's
real profile (documents folder, pasted CV/LinkedIn, or an interview).
Faithful port of .claude/commands/setup.md: read-before-write, idempotent,
never silently overwrites.
"""
from __future__ import annotations

from pathlib import Path

from ..client import DeepSeekClient
from ..config import Config
from ..context import build_context, read_command
from ..io import read_text, write_text
from ..manifest import (
    ALL_SKILLS,
    CLAUDE_MD,
    MAIN_CV,
    SEARCH_QUERIES,
    Command,
    COMMANDS,
)
from ..parse_output import extract_files
from ._common import ask, confirm

PROFILE_FILES = [
    "CLAUDE.md",
    ".claude/skills/job-application-assistant/01-candidate-profile.md",
    ".claude/skills/job-application-assistant/02-behavioral-profile.md",
    ".claude/skills/job-application-assistant/04-job-evaluation.md",
    ".claude/skills/job-application-assistant/05-cv-templates.md",
    ".claude/skills/job-application-assistant/07-interview-prep.md",
    "cv/main_example.tex",
    ".claude/skills/job-scraper/search-queries.md",
]


def _docs_inventory(config: Config) -> list[Path]:
    files: list[Path] = []
    for sub in ("cv", "linkedin", "diplomas", "references", "applications"):
        folder = config.repo_root / "documents" / sub
        if folder.is_dir():
            for p in sorted(folder.rglob("*")):
                if p.is_file() and p.name != "README.md" and p.suffix.lower() not in (
                    ".pdf",
                ) or (p.is_file() and p.suffix.lower() == ".pdf"):
                    files.append(p)
    return files


def _read_material(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from ..ats import extract_text

            return extract_text(str(path)) or f"[PDF could not be read: {path.name}]"
        except Exception:
            return f"[PDF could not be read: {path.name}]"
    text = read_text(path)
    if not text.strip():
        return f"[Unreadable/empty file: {path.name}]"
    return text


def _collect_via_documents(config: Config) -> str:
    files = _docs_inventory(config)
    if not files:
        return ""
    parts = []
    for p in files:
        parts.append(f"===== {p.relative_to(config.repo_root)} =====\n{_read_material(p)}")
    return "\n\n".join(parts)


def _collect_via_interview() -> str:
    q = {
        "name": "What is your full name?",
        "location": "Where are you located (city, country, commute constraints)?",
        "languages": "Which languages do you speak?",
        "cv_language": "What language should your CV be written in (default English)?",
        "status": "What is your current employment status?",
        "linkedin_headline": "What is your LinkedIn headline?",
        "education": "List your degrees (level, field, years, institution, thesis/topics).",
        "experience": "List your professional roles (title, dates, company, location, "
        "key responsibilities, achievements with numbers).",
        "skills_primary": "Your primary technical skills?",
        "skills_secondary": "Secondary skills / domain expertise / software tools?",
        "certifications": "Certifications (name, hours, date)?",
        "behavioral": "Behavioral profile: traits, strengths, growth areas, ideal environment?",
        "excites": "What excites you professionally?",
        "target_sectors": "Target sectors and example companies?",
        "dealbreakers": "Any deal-breakers for a job?",
        "interviews": "Notable interview experiences and feedback?",
    }
    print("\nI'll ask a few questions to build your profile. Press Enter to skip any.")
    answers = []
    for key, question in q.items():
        ans = ask(question).strip()
        if ans:
            answers.append(f"- **{key.replace('_', ' ').title()}:** {ans}")
    return "\n".join(answers) if answers else ""


def run(config: Config, argv: list[str]) -> int:
    section = None
    for token in argv:
        if token.startswith("--section"):
            section = token.split("=", 1)[-1] if "=" in token else "profile"
    if section:
        print(f"Updating section: {section}")

    # Detect documents folder.
    docs_files = _docs_inventory(config)
    if docs_files:
        print(f"Found {len(docs_files)} file(s) in documents/ — I can build your profile "
              "from these (Path A).")

    print("\nHow would you like to provide your profile data?")
    print("  A) documents/ folder (CV, LinkedIn export, diplomas, references, applications)")
    print("  B) Paste CV / LinkedIn text now")
    print("  C) Interactive interview (I ask, you answer)")
    choice = ask("Choose A, B, or C", "A").strip().lower()

    raw = ""
    if choice == "a":
        raw = _collect_via_documents(config)
        if not raw:
            print("documents/ is empty. Falling back to interview.")
            raw = _collect_via_interview()
    elif choice == "b":
        print("Paste your CV / LinkedIn / interview notes below. End with a line "
              "containing only 'END'.")
        lines = []
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                break
            if line.strip().upper() == "END":
                break
            lines.append(line)
        raw = "\n".join(lines)
    else:
        raw = _collect_via_interview()

    if not raw.strip():
        print("No profile data provided. Aborting.")
        return 1

    cmd: Command = COMMANDS["setup"]
    instructions = read_command(config, cmd.prompt_file)
    context = build_context(config, cmd.context_files)

    print("\nGenerating your profile files with DeepSeek… (this can take a minute)")
    client = DeepSeekClient(config)
    system = (
        "You are populating a job-search profile workspace. Follow the instructions "
        "in the setup procedure below. Output each file as a fenced code block "
        "preceded by a line 'FILE: <relative path>'. Only output the files the "
        "instructions ask for; use the exact relative paths given (CLAUDE.md, "
        ".claude/skills/job-application-assistant/0X-*.md, cv/main_example.tex, "
        ".claude/skills/job-scraper/search-queries.md). Replace every "
        "[YOUR_*] / [PLACEHOLDER] token with real data from the material. Never "
        "invent facts that are not present in the material — leave anything "
        "unknown as an explicit [UNKNOWN] marker for the user to fill in."
    )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"## Setup procedure\n{instructions}\n\n"
                f"## Current profile/context files (read-only reference)\n{context}\n\n"
                f"## Raw profile material\n{raw}"
            ),
        },
    ]
    result = client.chat(messages, role="default")
    files = extract_files(result)
    if not files:
        print("DeepSeek did not return any FILE: blocks. Raw response:\n")
        print(result)
        return 1

    print(f"\nDeepSeek produced {len(files)} file(s). Writing:")
    written = []
    for path, content in files:
        target = (config.repo_root / path).resolve()
        # Only write files the setup procedure is allowed to produce.
        rel = target.relative_to(config.repo_root)
        if str(rel) not in PROFILE_FILES and not str(rel).startswith(
            ".claude/skills/job-application-assistant/"
        ):
            print(f"  skip (not a profile file): {rel}")
            continue
        write_text(target, content)
        written.append(str(rel))
        print(f"  wrote {rel}")

    print("\nReview the generated files before running `apply`.")
    print("Files written: " + ", ".join(written))
    return 0
