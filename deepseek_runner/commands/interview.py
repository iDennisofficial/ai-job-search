"""/interview — build a stage-specific interview prep pack.

Port of .claude/commands/interview.md: load a tracked application's archive,
ask for the stage, and generate a prep pack grounded in the submitted documents
+ the interview-prep framework (07) + the candidate's profile (01/02/04).
"""
from __future__ import annotations

from ..client import DeepSeekClient
from ..config import Config
from ..context import build_context
from ..io import archive_dir, list_open_applications, read_text, read_tracker, slugify, write_text
from ..manifest import S01, S02, S04, S07
from ._common import ask


def _archive_block(config: Config, company: str, role: str) -> str:
    archive = archive_dir(config, company, role)
    parts = []
    for fname in ("job_posting.md", "cv_draft.tex", "cover_letter.tex", "outcome.md"):
        p = archive / fname
        if p.exists():
            parts.append(f"===== {fname} =====\n{read_text(p)}")
    # fallback to loose files
    if not parts:
        for pattern in (f"cv/main_{slugify(company)}*.tex",
                        f"cover_letters/cover_{slugify(company)}*.tex"):
            for p in config.repo_root.glob(pattern):
                parts.append(f"===== {p.relative_to(config.repo_root)} =====\n{read_text(p)}")
    return "\n\n".join(parts)


def run(config: Config, argv: list[str]) -> int:
    target = " ".join(argv).strip()

    rows = read_tracker(config)
    if not rows:
        print("No applications tracked yet. Run `outcome \"<company> <role>\"` first.")
        return 1

    if not target:
        print("Open applications:")
        for r in list_open_applications(config):
            print(f"  {r.get('company')} — {r.get('role')} ({r.get('status')})")
        print("\nPass a company (and role) to prep: "
              "python deepseek_runner.py interview \"<company> <role>\"")
        return 0

    needle = target.lower()
    matches = [
        r for r in rows
        if needle in f"{r.get('company', '')} {r.get('role', '')}".lower()
    ]
    if not matches:
        print(f"No tracked application matching '{target}'. Run `outcome` first.")
        return 1
    row = matches[0]
    company = row.get("company", "")
    role = row.get("role", "")
    print(f"Application: {company} — {role} ({row.get('status')})")

    stage = ask("Interview stage (phone / technical / onsite / final / case)?",
                "technical").strip().lower()
    format_q = ask("Format (video / phone / onsite)?", "video").strip()
    archive_text = _archive_block(config, company, role)
    if not archive_text:
        archive_text = "No archive materials found yet — the prep will rely on the profile and posting summary."

    ctx = build_context(config, [S01, S02, S04, S07])
    client = DeepSeekClient(config)
    user = (
        "Build an interview prep pack for the interview described below. "
        "Include: 1) likely questions (priority: recorded feedback > fit-eval "
        "gaps > posting requirements > stage type), with STAR-style answer "
        "framing grounded in the profile; 2) tough questions and honest bridge "
        "answers for any gaps; 3) questions the candidate should ask; 4) "
        "logistics notes. Keep every claim consistent with the submitted "
        "documents — no claim in the room that isn't on the paper.\n\n"
        f"## Company: {company}\n## Role: {role}\n## Stage: {stage}\n"
        f"## Format: {format_q}\n\n"
        f"## Profile + prep framework\n{ctx}\n\n"
        f"## Submitted application materials\n{archive_text}"
    )
    print("\nGenerating prep pack…")
    result = client.chat(
        [{"role": "system",
          "content": "You are a meticulous interview coach. You ground every "
                     "answer in the candidate's actual profile and submitted "
                     "documents; you never invent experience."},
         {"role": "user", "content": user}],
        role="default", temperature=0.4,
    )

    out = archive_dir(config, company, role) / f"interview_prep_{slugify(stage)}.md"
    write_text(out, result)
    print(f"\nPrep pack written: {out}")
    print("\nWant a mock interview next? I can roleplay the interviewer — just ask.")
    return 0
