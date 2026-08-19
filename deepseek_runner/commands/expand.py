"""/expand — additive discovery of hidden competencies.

Port of .claude/commands/expand.md: scans the documents folder + profile,
proposes ADD-ONLY additions to 01-candidate-profile.md and
02-behavioral-profile.md (inferred behavioral items labelled), and only writes
after the user confirms.
"""
from __future__ import annotations

from ..client import DeepSeekClient
from ..config import Config
from ..context import build_context
from ..io import read_text, write_text
from ..manifest import S01, S02
from ..parse_output import extract_files
from ._common import ask, confirm


def _scan_documents(config: Config) -> str:
    parts = []
    for sub in ("cv", "linkedin", "diplomas", "references"):
        folder = config.repo_root / "documents" / sub
        if folder.is_dir():
            for p in sorted(folder.iterdir()):
                if p.is_file() and p.suffix.lower() in (".md", ".txt", ".tex", ".pdf"):
                    text = read_text(p)
                    parts.append(f"===== {p.relative_to(config.repo_root)} =====\n"
                                 f"{text[:6000] if text else '[empty]'}")
    return "\n\n".join(parts)


def run(config: Config, argv: list[str]) -> int:
    documents = _scan_documents(config)
    profile = build_context(config, [S01, S02])
    client = DeepSeekClient(config)

    user = (
        "Discover hidden or under-represented competencies for this candidate. "
        "Compare the documents folder material + web/GitHub signals against the "
        "existing profile (01/02).\n"
        "1) First print a concise '## Proposed additions' summary (grouped: "
        "Technical Skills / Domain Knowledge / Behavioral).\n"
        "2) Then output the FULL updated 01-candidate-profile.md and "
        "02-behavioral-profile.md as FILE: fenced blocks, containing ONLY "
        "additive changes on top of the existing content. Mark inferred "
        "behavioral items with '*[Inferred from …; review before relying on "
        "this]*'. Never remove or rewrite existing profile content.\n\n"
        f"## Existing profile\n{profile}\n\n"
        f"## Documents material\n{documents or '(none found)'}"
    )
    print("Scanning documents and proposing additions…")
    result = client.chat(
        [{"role": "system",
          "content": "You are a meticulous career-coach analyst. Additions must "
                     "be grounded in real material; behavioral inferences are "
                     "explicitly labelled as inferred. Never fabricate."},
         {"role": "user", "content": user}],
        role="default", temperature=0.3,
    )
    files = extract_files(result)
    print(result if not files else result[:3000] + ("\n…" if len(result) > 3000 else ""))

    if not files:
        print("\nNo file blocks returned — nothing written.")
        return 0

    if not confirm("\nApply these additive changes to 01 and 02?"):
        print("Skipped — nothing written.")
        return 0

    for p, content in files:
        if p in (S01, S02):
            write_text(config.repo_root / p, content)
            print(f"  updated {p}")
        else:
            print(f"  skip (not a profile file): {p}")
    print("\nDone. Run `/setup` style review if you want to adjust later.")
    return 0
