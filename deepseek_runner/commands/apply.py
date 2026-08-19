"""/apply — drafter-reviewer job application workflow.

Faithful port of .claude/commands/apply.md for a stateless DeepSeek runner:
0 parse posting → 1 evaluate fit (deepseek-reasoner) → ask → 2 draft CV+cover →
3 reviewer pass (second call) → 4 revise → 5 compile+inspect loop + ATS check →
6 summary. The runner (not the model) writes files, compiles, and inspects PDFs.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .. import ats, web
from ..client import DeepSeekClient
from ..config import Config
from ..context import build_context, read_command
from ..io import write_text
from ..latex import compile_and_check, resolve_template_override
from ..manifest import (
    CLAUDE_MD,
    MAIN_CV,
    S01,
    S02,
    S03,
    S04,
    S05,
    S06,
    COMMANDS,
)
from ..parse_output import extract_files, extract_json
from ..prompts import SECURITY_GUARDRAIL, SYSTEM_DRAFTER
from ..reviewer import reviewer_pass
from ._common import confirm

URL_RE = re.compile(r"^https?://", re.IGNORECASE)
PDF_EXTS = (".aux", ".log", ".out", ".synctex.gz", ".fls", ".fdb_latexmk")


def _run_salary_lookup(config: Config, company: str, city: str | None = None):
    script = config.repo_root / "salary_lookup.py"
    if not script.exists() or not shutil.which("python3"):
        return None
    cmd = ["python3", str(script), company]
    if city:
        cmd += ["--city", city]
    cmd.append("--json")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, cwd=config.repo_root
        )
        if proc.returncode != 0:
            return None
        return extract_json(proc.stdout)
    except Exception:
        return None


def _extract_metadata(client: DeepSeekClient, posting: str) -> dict:
    prompt = (
        f"{SECURITY_GUARDRAIL}\n\n"
        "Analyze the job posting below and return a JSON object with exactly "
        "these keys: company, role, department, location, language (posting "
        "language, e.g. 'English' or 'Danish'), required_keywords (array of "
        "required skill/requirement terms named in the posting), "
        "preferred_keywords (array of nice-to-have terms). Use empty "
        "strings/arrays where unknown. Return ONLY the JSON object.\n\n"
        f"<JOB_POSTING>\n{posting}\n</JOB_POSTING>"
    )
    data = client.chat_json(
        [{"role": "user", "content": prompt}], role="default", temperature=0.0
    )
    for key in ("company", "role", "department", "location", "language"):
        data.setdefault(key, "")
    data.setdefault("required_keywords", [])
    data.setdefault("preferred_keywords", [])
    return data


def _compile_pair(
    config: Config, client: DeepSeekClient,
    cv_written: str, cover_written: str,
    cv_ov, cover_ov, cv_target: int, cover_target: int,
    posting_for_ctx: str,
) -> tuple[bool, int | None, int | None]:
    """Compile both, verify page counts, and loop a fix pass. Returns (ok, cv_pages, cover_pages)."""
    for attempt in range(1, config.max_compile_retries + 1):
        print(f"\n--- COMPILE attempt {attempt}/{config.max_compile_retries} ---")
        cv_pdf = cv_written.rsplit(".", 1)[0] + ".pdf"
        cover_pdf = cover_written.rsplit(".", 1)[0] + ".pdf"
        ok_cv, log_cv, pages_cv = compile_and_check(
            config, "cv", Path(cv_written).name, "lualatex", cv_target, cv_pdf, cv_ov
        )
        ok_cover, log_cover, pages_cover = compile_and_check(
            config, "cover_letters", Path(cover_written).name,
            "xelatex", cover_target, cover_pdf, cover_ov,
        )
        print(
            f"CV pages: {pages_cv} (target {cv_target}) | "
            f"Cover pages: {pages_cover} (target {cover_target})"
        )
        if ok_cv and ok_cover:
            print("Compile OK — layout verified.")
            return True, pages_cv, pages_cover

        if attempt == config.max_compile_retries:
            print("Compile did not stabilise after retries. Manual fix needed:")
            if not ok_cv:
                print("\nCV log tail:\n" + log_cv[-1500:])
            if not ok_cover:
                print("\nCover log tail:\n" + log_cover[-1500:])
            return False, pages_cv, pages_cover

        preview = ""
        t = ats.extract_text(str(config.repo_root / cv_pdf)) if cv_pdf else None
        preview = (t or "")[:1500]
        fix_user = (
            "The compiled PDFs have layout problems. Fix the LaTeX source and "
            "re-output BOTH complete files as FILE: fenced blocks.\n\n"
            f"CV ({cv_written}): pages={pages_cv}, target={cv_target}\n"
            f"Compile log tail:\n{log_cv[-1400:]}\n"
            f"CV text preview:\n{preview[:1100]}\n\n"
            f"Cover ({cover_written}): pages={pages_cover}, target={cover_target}\n"
            f"Compile log tail:\n{log_cover[-1400:]}"
        )
        fix_resp = client.chat(
            [{"role": "system", "content": SYSTEM_DRAFTER},
             {"role": "user", "content": fix_user}],
            role="default", temperature=0.2,
        )
        f = extract_files(fix_resp)
        if not f:
            print("Fix pass returned no files; recompiling as-is.")
            continue
        for p, c in f:
            if p.startswith("cv/"):
                write_text(config.repo_root / p, c)
                cv_written = p
            elif p.startswith("cover_letters/"):
                write_text(config.repo_root / p, c)
                cover_written = p
    return False, None, None


def _clean_build_artifacts(config: Config, pdf_paths: list[str]) -> None:
    for pdf in pdf_paths:
        stem = pdf.rsplit(".", 1)[0]
        for ext in PDF_EXTS:
            artifact = config.repo_root / (stem + ext)
            if artifact.exists():
                artifact.unlink()


def run(config: Config, argv: list[str]) -> int:
    if not argv:
        print("Usage: python deepseek_runner.py apply <job posting URL or pasted text>")
        return 1
    raw = " ".join(argv).strip()
    client = DeepSeekClient(config)

    # ---- Step 0: parse input ------------------------------------------------
    if URL_RE.match(raw):
        print(f"Fetching posting from URL: {raw}")
        try:
            posting = web.fetch_url(raw)
        except Exception as e:  # noqa: BLE001
            print(f"Could not fetch URL: {e}")
            return 1
        if not posting.strip():
            print("Fetched posting is empty.")
            return 1
    else:
        posting = raw
    print(f"Posting loaded ({len(posting)} chars).")

    # ---- metadata + optional salary benchmark --------------------------------
    meta = _extract_metadata(client, posting)
    company = meta["company"] or "unknown_company"
    role = meta["role"] or "unknown_role"
    print(f"Parsed: company={company!r} role={role!r} language={meta.get('language')!r}")

    salary = _run_salary_lookup(config, company, meta.get("location") or None)
    if salary:
        print(f"Salary benchmark found for {company}.")

    # ---- Step 1: evaluate fit (deepseek-reasoner) ----------------------------
    eval_ctx = build_context(config, [S01, S04, CLAUDE_MD])
    workflow = read_command(config, COMMANDS["apply"].prompt_file)
    salary_note = f"\nSalary benchmark (from salary_lookup.py):\n{salary}\n" if salary else ""
    eval_user = (
        f"{SECURITY_GUARDRAIL}\n\n"
        "Follow Step 1 of the workflow reference: evaluate the posting against "
        "the candidate profile. Present: 1) skills match vs gaps, 2) experience "
        "match, 3) behavioral/culture match, 4) salary benchmark (if available), "
        "5) overall fit score and recommendation (strong/moderate/weak fit).\n\n"
        f"## Workflow reference (Step 1)\n{workflow[:8000]}\n\n"
        f"## Candidate profile\n{eval_ctx}\n\n"
        f"## Job posting\n<JOB_POSTING>\n{posting}\n</JOB_POSTING>{salary_note}"
    )
    print("\n--- FIT EVALUATION (deepseek-reasoner) ---")
    fit = client.chat(
        [{"role": "user", "content": eval_user}], role="reasoning", temperature=0.3
    )
    print(fit)

    if not confirm("Should I proceed with drafting the CV and cover letter for this role?"):
        print("Stopped. Nothing was drafted.")
        return 0

    # ---- Step 2: draft CV + cover letter -------------------------------------
    cv_ov = resolve_template_override(config, S05)
    cover_ov = resolve_template_override(config, S06)
    cv_ext, cover_ext = cv_ov.extension, cover_ov.extension
    cv_path = f"cv/main_{company}_{role}{cv_ext}"
    cover_path = f"cover_letters/cover_{company}_{role}{cover_ext}"

    draft_ctx = build_context(config, [S01, S03, S04, S05, S06, MAIN_CV, CLAUDE_MD])
    draft_user = (
        f"{SECURITY_GUARDRAIL}\n\n"
        "Draft a tailored CV and cover letter for the posting, following the "
        "templates and rules in the context.\n"
        f"- CV file: `{cv_path}` — exactly 2 pages, in the profile's 'CV "
        "language' (default English).\n"
        f"- Cover letter file: `{cover_path}` — about 1 page, in the posting's "
        "language.\n"
        "Ground every claim strictly in the profile sources "
        "(01-candidate-profile.md + cv/main_example.tex + CLAUDE.md). Where the "
        "posting states requirements the candidate lacks, acknowledge them "
        "honestly with a bridge — never hide or fabricate.\n"
        "Output exactly two files, each as a fenced code block preceded by its "
        "FILE: line.\n\n"
        f"## Candidate profile + templates\n{draft_ctx}\n\n"
        f"## Job posting\n<JOB_POSTING>\n{posting}\n</JOB_POSTING>"
    )
    print("\n--- DRAFTING CV + COVER LETTER ---")
    draft_resp = client.chat(
        [{"role": "system", "content": SYSTEM_DRAFTER},
         {"role": "user", "content": draft_user}],
        role="default", temperature=0.4,
    )
    files = extract_files(draft_resp)
    written: dict[str, str] = {}
    for p, content in files:
        if not (p.startswith("cv/") or p.startswith("cover_letters/")):
            print(f"  skip unexpected path: {p}")
            continue
        write_text(config.repo_root / p, content)
        written[p] = content
        print(f"  wrote {p}")

    cv_written = next((p for p in written if p.startswith("cv/")), None)
    cover_written = next((p for p in written if p.startswith("cover_letters/")), None)
    if not cv_written or not cover_written:
        print("Expected both a cv/ and cover_letters/ file; cannot continue.")
        return 1

    # ---- Step 3: reviewer pass (second DeepSeek call) -------------------------
    reviewer_ctx = build_context(config, [S01, S02, S03, S04, MAIN_CV, CLAUDE_MD])
    print("\n--- REVIEWER PASS (critique-only) ---")
    feedback = reviewer_pass(
        client, config, drafts=list(written.items()), posting=posting, context=reviewer_ctx
    )
    print(feedback[:4000] + ("\n…" if len(feedback) > 4000 else ""))

    # ---- Step 4: revise --------------------------------------------------------
    print("\n--- REVISION ---")
    rev_user = (
        "You are the drafter. Revise the two drafted files to incorporate the "
        "reviewer feedback below. Never fabricate facts; keep every claim "
        "grounded in the profile sources. Output the two complete revised "
        "files as FILE: fenced blocks again.\n\n"
        f"## Reviewer feedback\n{feedback}\n\n"
        "## Current drafts\n"
        + "\n".join(f'<DRAFT file="{p}">\n{c}\n</DRAFT>' for p, c in written.items())
    )
    rev_resp = client.chat(
        [{"role": "system", "content": SYSTEM_DRAFTER},
         {"role": "user", "content": rev_user}],
        role="default", temperature=0.3,
    )
    rev_files = extract_files(rev_resp)
    if rev_files:
        new_map: dict[str, tuple[str, str]] = {}
        for p, c in rev_files:
            if p.startswith("cv/"):
                new_map["cv"] = (p, c)
            elif p.startswith("cover_letters/"):
                new_map["cover"] = (p, c)
        if "cv" in new_map and "cover" in new_map:
            for kind in ("cv", "cover"):
                p, c = new_map[kind]
                write_text(config.repo_root / p, c)
                written[p] = c
                print(f"  revised {p}")
            cv_written = new_map["cv"][0]
            cover_written = new_map["cover"][0]
        else:
            print("Revision did not return both files; keeping drafts as-is.")

    # ---- Step 5: compile + inspect + ATS ---------------------------------------
    cv_pdf = cv_written.rsplit(".", 1)[0] + ".pdf"
    cover_pdf = cover_written.rsplit(".", 1)[0] + ".pdf"
    cv_target = cv_ov.page_limit or 2
    cover_target = cover_ov.page_limit or 1

    ok, pages_cv, pages_cover = _compile_pair(
        config, client, cv_written, cover_written,
        cv_ov, cover_ov, cv_target, cover_target, posting,
    )

    print("\n--- ATS CHECK (CV text layer) ---")
    if ats.pdftotext_available():
        text = ats.extract_text(str(config.repo_root / cv_pdf))
        if text:
            issues = ats.parseability_issues(text)
            if issues:
                for issue in issues:
                    print(f"  ⚠ {issue}")
            else:
                print("  ✓ text layer extracts cleanly (no cid: markers, no �)")
            kws = list(meta.get("required_keywords", [])) + list(
                meta.get("preferred_keywords", [])
            )
            if kws:
                print("  Keyword coverage (CV):")
                for r in ats.keyword_coverage(text, kws):
                    mark = "✓" if r["status"] == "covered" else "✗"
                    print(f"    {mark} {r['keyword']}")
        else:
            print("  ⚠ pdftotext produced no output for the CV.")
    else:
        print("  ⚠ pdftotext not available — mechanical ATS check skipped.")

    _clean_build_artifacts(config, [cv_pdf, cover_pdf])

    # ---- Step 6: summary --------------------------------------------------------
    print("\n--- SUMMARY ---")
    print(f"CV source:     {config.repo_root / cv_written}")
    print(f"Cover source:  {config.repo_root / cover_written}")
    print(f"CV PDF:        {config.repo_root / cv_pdf}")
    print(f"Cover PDF:     {config.repo_root / cover_pdf}")
    print(f"Pages:         CV {pages_cv}/{cv_target} · Cover {pages_cover}/{cover_target}")
    print("\nNext steps: run `outcome \"<company> <role>\"` once you submit, "
          "or `interview \"<company> <role>\"` when a round is scheduled.")
    return 0
