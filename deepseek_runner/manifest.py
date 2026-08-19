"""Command registry: maps CLI command name -> metadata.

Each entry mirrors a `.claude/commands/*.md` prompt file (or, for `scrape` and
`upskill`, the corresponding skill file) plus the list of context files that
must be assembled into the prompt for that command.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SKILL = ".claude/skills/job-application-assistant"
CMD_DIR = ".claude/commands"

S01 = f"{SKILL}/01-candidate-profile.md"
S02 = f"{SKILL}/02-behavioral-profile.md"
S03 = f"{SKILL}/03-writing-style.md"
S04 = f"{SKILL}/04-job-evaluation.md"
S05 = f"{SKILL}/05-cv-templates.md"
S06 = f"{SKILL}/06-cover-letter-templates.md"
S07 = f"{SKILL}/07-interview-prep.md"
S08 = f"{SKILL}/08-application-forms.md"

CLAUDE_MD = "CLAUDE.md"
MAIN_CV = "cv/main_example.tex"
COVER_EXAMPLE = "cover_letters/cover_example.tex"
SEARCH_QUERIES = ".claude/skills/job-scraper/search-queries.md"
JOB_SCRAPER_SKILL = ".claude/skills/job-scraper/SKILL.md"
UPSKILL_SKILL = ".claude/skills/upskill/SKILL.md"

ALL_SKILLS = [S01, S02, S03, S04, S05, S06, S07, S08]


@dataclass
class Command:
    name: str
    prompt_file: str  # repo-relative path to the .md that acts as the instruction prompt
    context_files: list = field(default_factory=list)
    needs_api: bool = True
    help: str = ""


COMMANDS: dict[str, Command] = {
    "apply": Command(
        name="apply",
        prompt_file=f"{CMD_DIR}/apply.md",
        context_files=[S01, S03, S04, S05, S06, MAIN_CV, CLAUDE_MD],
        help="Evaluate a job posting and draft a tailored CV + cover letter.",
    ),
    "setup": Command(
        name="setup",
        prompt_file=f"{CMD_DIR}/setup.md",
        context_files=ALL_SKILLS + [MAIN_CV, CLAUDE_MD, SEARCH_QUERIES],
        help="Profile intake -> populate CLAUDE.md and the skill files.",
    ),
    "scrape": Command(
        name="scrape",
        prompt_file=JOB_SCRAPER_SKILL,
        context_files=[JOB_SCRAPER_SKILL, SEARCH_QUERIES, S01, S04],
        help="Search enabled job portals and store postings in job_scraper/.",
    ),
    "rank": Command(
        name="rank",
        prompt_file=f"{CMD_DIR}/rank.md",
        context_files=[S01, S04],
        help="Score scraped postings against the fit framework into a shortlist.",
    ),
    "interview": Command(
        name="interview",
        prompt_file=f"{CMD_DIR}/interview.md",
        context_files=[S01, S02, S04, S07],
        help="Build a stage-specific interview prep pack.",
    ),
    "outcome": Command(
        name="outcome",
        prompt_file=f"{CMD_DIR}/outcome.md",
        context_files=[S03],
        help="Record an application result, archive materials, draft follow-ups.",
    ),
    "expand": Command(
        name="expand",
        prompt_file=f"{CMD_DIR}/expand.md",
        context_files=[S01, S02],
        help="Discover hidden competencies from documents and web presence.",
    ),
    "upskill": Command(
        name="upskill",
        prompt_file=UPSKILL_SKILL,
        context_files=[UPSKILL_SKILL, S01, S02, S04],
        help="Coaching-style skill-building guidance.",
    ),
    "html-report": Command(
        name="html-report",
        prompt_file=f"{CMD_DIR}/html-report.md",
        context_files=[],
        needs_api=False,
        help="Render the application dashboard HTML (pure Python, no LLM).",
    ),
    "add-template": Command(
        name="add-template",
        prompt_file=f"{CMD_DIR}/add-template.md",
        context_files=[S05, S06],
        help="Register a custom CV/cover-letter template.",
    ),
    "add-portal": Command(
        name="add-portal",
        prompt_file=f"{CMD_DIR}/add-portal.md",
        context_files=[],
        help="Scaffold a job-portal search skill from a URL.",
    ),
    "reset": Command(
        name="reset",
        prompt_file=f"{CMD_DIR}/reset.md",
        context_files=[],
        help="Reset candidate profile and/or documents (destructive).",
    ),
    "notion-sync": Command(
        name="notion-sync",
        prompt_file=f"{CMD_DIR}/notion-sync.md",
        context_files=[],
        help="Push ranked jobs + applications to a Notion database.",
    ),
    "gmail-sync": Command(
        name="gmail-sync",
        prompt_file=f"{CMD_DIR}/gmail-sync.md",
        context_files=[],
        help="Classify Gmail status signals for open applications.",
    ),
}


def command_names() -> list[str]:
    return sorted(COMMANDS)


def is_valid(name: str) -> bool:
    return name in COMMANDS
