"""/outcome — record an application result, archive materials, draft follow-ups.

Port of .claude/commands/outcome.md: update the tracker + per-application
archive (copy, never move) and write/append outcome.md in the documented
format. Follow-ups are drafted only, never sent.
"""
from __future__ import annotations

import shutil
from datetime import date

from ..client import DeepSeekClient
from ..config import Config
from ..context import build_context
from ..io import (
    archive_dir,
    ensure_dir,
    list_open_applications,
    read_tracker,
    read_text,
    slugify,
    write_text,
    write_tracker,
)
from ..manifest import S03
from ._common import ask

STATUSES = ["in_progress", "applied", "interview", "offer", "hired", "rejected",
            "no response", "offer declined", "withdrawn", "interview_only"]
FINAL = {"hired", "rejected", "no response", "no_response", "offer declined",
         "offer_declined", "withdrawn"}

OUTCOME_TPL = """# Outcome: {company} — {role}

**Status:** {status}

{date_line}
## Interview stages reached
- [ ] Phone screen
- [ ] Technical interview
- [ ] Case interview
- [ ] Final round
- [ ] Offer received

## Notes
{notes}
"""


def _copy_application_materials(config: Config, row: dict, company: str, role: str) -> list[str]:
    """Copy (never move) the submitted CV/cover into the archive folder."""
    archive = ensure_dir(archive_dir(config, company, role))
    copied = []
    sources = []
    if row.get("cv_file"):
        sources.append(("cv_file", config.repo_root / row["cv_file"], archive / "cv_draft.tex"))
    if row.get("cover_letter_file"):
        sources.append(("cover_letter_file", config.repo_root / row["cover_letter_file"],
                        archive / "cover_letter.tex"))
    # Fallback to loose files in cv/ and cover_letters/.
    loose_cv = list(config.repo_root.glob(f"cv/main_{slugify(company)}_*.tex"))
    if loose_cv and not any(k == "cv_file" for k, _, _ in sources):
        sources.append(("cv_file", loose_cv[0], archive / "cv_draft.tex"))
    loose_cover = list(config.repo_root.glob(f"cover_letters/cover_{slugify(company)}_*.tex"))
    if loose_cover and not any(k == "cover_letter_file" for k, _, _ in sources):
        sources.append(("cover_letter_file", loose_cover[0], archive / "cover_letter.tex"))

    for kind, src, dst in sources:
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            copied.append(dst.name)
    return copied


def _update_outcome(config: Config, company: str, role: str, status: str,
                    notes: str, resolved: bool) -> Path:
    archive = ensure_dir(archive_dir(config, company, role))
    p = archive / "outcome.md"
    existing = read_text(p)
    if existing.strip():
        # Append dated note; update status/date if resolved.
        if resolved and "**Date resolved:**" not in existing:
            existing = existing.replace("**Status:** ", f"**Date resolved:** {date.today().isoformat()}\n\n**Status:** ")
        existing = existing.replace("**Status:** ", f"**Status:** {status}", 1)
        if notes:
            existing = existing.rstrip() + f"\n\n- {date.today().isoformat()}: {notes}\n"
        write_text(p, existing)
        return p
    write_text(p, OUTCOME_TPL.format(
        company=company, role=role, status=status,
        date_line=(f"**Date resolved:** {date.today().isoformat()}\n" if resolved else ""),
        notes=notes or "(no notes recorded yet)",
    ))
    return p


def _draft_followup(config: Config, row: dict, days: int) -> None:
    company, role = row.get("company", ""), row.get("role", "")
    ctx = build_context(config, [S03])
    client = DeepSeekClient(config)
    user = (
        f"Draft a polite, concise follow-up email (~60-120 words) to {company} "
        f"about my application for {role}, submitted ~{days} days ago. Tone per "
        "the writing-style guide. Do NOT invent new claims beyond what the "
        "submitted materials say. Output only the email body.\n\n"
        f"## Writing style\n{ctx}"
    )
    result = client.chat([{"role": "user", "content": user}], role="default", temperature=0.3)
    out = archive_dir(config, company, role) / f"followup_{date.today().isoformat()}.md"
    write_text(out, f"# Follow-up: {company} — {role} ({days}d)\n\n{result}")
    print(f"\nFollow-up drafted (not sent): {out}")


def run(config: Config, argv: list[str]) -> int:
    tokens = list(argv)
    if not tokens:
        open_apps = list_open_applications(config)
        if not open_apps:
            print("No open applications tracked.")
            return 0
        print("Open applications:")
        for r in open_apps:
            print(f"  {r.get('company')} — {r.get('role')} ({r.get('status')})")
        print("\nUsage: outcome \"<company> <role>\"  |  outcome followup [N]")
        return 0

    # follow-up branch
    if tokens[0].lower() == "followup":
        days = 10
        if len(tokens) > 1:
            try:
                days = int(tokens[1])
            except ValueError:
                days = 10
        rows = read_tracker(config)
        open_apps = list_open_applications(config)
        if not open_apps:
            print("No open applications to follow up on.")
            return 0
        company = tokens[1] if len(tokens) > 2 else ask(
            f"Follow up on which application? {', '.join(r.get('company') for r in open_apps)}"
        ).strip()
        matches = [r for r in open_apps if company.lower() in r.get("company", "").lower()]
        if not matches:
            print(f"No open application matching '{company}'.")
            return 1
        _draft_followup(config, matches[0], days)
        return 0

    company = tokens[0]
    role = tokens[1] if len(tokens) > 1 else ask("Role?").strip()
    if not role:
        role = "unknown"

    rows = read_tracker(config)
    matches = [r for r in rows if r.get("company", "").lower() == company.lower()
               and (not role or role.lower() in r.get("role", "").lower())]
    row = matches[0] if matches else {
        "date": date.today().isoformat(), "company": company, "role": role,
        "status": "applied", "notes": "", "cv_file": "", "cover_letter_file": "",
        "source": "", "sector": "", "role_type": "", "channel": "",
        "contact_person": "", "fit_rating": "",
    }

    default_status = row.get("status") or "in_progress"
    status = ask(f"Status? ({'/'.join(STATUSES)})", default_status).strip().lower()
    resolved = status in FINAL
    notes = ask("Notes / feedback? (Enter to skip)").strip()

    copied = _copy_application_materials(config, row, company, role)
    out = _update_outcome(config, company, role, status, notes, resolved)

    # Update tracker: keep existing row, set status + append dated note.
    today = date.today().isoformat()
    note_fragment = f"{today}: {notes}" if notes else ""
    existing_notes = (row.get("notes") or "").strip()
    if note_fragment:
        row["notes"] = (existing_notes + "\n" if existing_notes else "") + note_fragment
    row["status"] = status
    if not matches:
        row["date"] = today
        rows.append(row)
    write_tracker(config, rows)

    print(f"\nRecorded: {company} — {role} ({status})")
    if copied:
        print(f"Archived: {', '.join(copied)}")
    print(f"Outcome file: {out}")
    if not resolved:
        print(f"\nStill open. Track it: run `outcome followup` after ~10 quiet days "
              "to draft a chase email.")
    return 0
