"""/rank — triage scraped postings into a ranked shortlist.

Port of .claude/commands/rank.md: batch-scores `status:new` postings from
job_scraper/seen_jobs.json against the fit framework (01 + 04), writes the
scores back in place (additive fields), and presents a shortlist.
"""
from __future__ import annotations

from datetime import date

from ..client import DeepSeekClient
from ..config import Config
from ..context import build_context
from ..io import read_json, write_json
from ..manifest import S01, S04
from ..prompts import SECURITY_GUARDRAIL
from ._common import ask, confirm

BATCH = 5


def _load_seen(config: Config) -> list[dict]:
    path = config.repo_root / "job_scraper" / "seen_jobs.json"
    data = read_json(path, [])
    if isinstance(data, dict):
        data = data.get("jobs", [])
    return list(data) if isinstance(data, list) else []


def _score_batch(client: DeepSeekClient, config: Config, batch: list[dict]) -> list[dict]:
    ctx = build_context(config, [S01, S04])
    postings = "\n\n".join(
        f"<POSTING id=\"{p.get('id') or p.get('public_slug') or p.get('url')}\">\n"
        f"Title: {p.get('title')}\nCompany: {p.get('company')}\n"
        f"Location: {p.get('location')}\nDate: {p.get('date')}\n"
        f"URL: {p.get('url')}\nDescription:\n{p.get('description') or ''}\n</POSTING>"
        for p in batch
    )
    user = (
        f"{SECURITY_GUARDRAIL}\n\n"
        "Score each job posting against the candidate profile using the fit "
        "framework. Return a JSON array with ONE object per posting (same "
        "order, same id/slug as the input). Keys: id (the posting id or slug "
        "from input), rank_score (0-100 integer), rank_verdict (one of: Strong "
        "fit / Good fit / Moderate fit / Weak fit / Poor fit), strengths (1-3 "
        "short strings), gaps (1-3 short strings). Base scores on the posting "
        "text only. Return ONLY the JSON array.\n\n"
        f"## Candidate profile + fit framework\n{ctx}\n\n"
        f"## Postings to score\n{postings}"
    )
    data = client.chat_json(
        [{"role": "user", "content": user}], role="reasoning", temperature=0.2
    )
    if isinstance(data, dict):
        data = data.get("scores") or data.get("results") or []
    return list(data) if isinstance(data, list) else []


def run(config: Config, argv: list[str]) -> int:
    all_flag = "--all" in argv
    top = 5
    i = 0
    while i < len(argv):
        if argv[i] == "--top" and i + 1 < len(argv):
            try:
                top = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        i += 1

    seen = _load_seen(config)
    candidates = [j for j in seen if all_flag or j.get("status") == "new"]
    if not candidates:
        print("No `new` postings to rank. Run `scrape` first (or use `--all`).")
        return 0

    print(f"Ranking {len(candidates)} posting(s) against your profile…")
    client = DeepSeekClient(config)

    results = []
    for i in range(0, len(candidates), BATCH):
        batch = candidates[i : i + BATCH]
        scores = _score_batch(client, config, batch)
        by_id = {str(s.get("id")): s for s in scores if isinstance(s, dict)}
        for p in batch:
            ident = str(p.get("id") or p.get("public_slug") or p.get("url"))
            s = by_id.get(ident)
            if s:
                p.update(
                    {
                        "status": "ranked",
                        "rank_score": s.get("rank_score"),
                        "rank_verdict": s.get("rank_verdict"),
                        "rank_date": date.today().isoformat(),
                        "strengths": s.get("strengths", []),
                        "gaps": s.get("gaps", []),
                    }
                )
                results.append(p)
            else:
                # No score returned for this posting — leave as new.
                print(f"  (no score returned for {ident})")

    write_json(config.repo_root / "job_scraper" / "seen_jobs.json", seen)

    ranked = sorted(
        [j for j in results if j.get("rank_score") is not None],
        key=lambda j: (j.get("rank_score") or 0),
        reverse=True,
    )
    if not ranked:
        print("No postings could be scored.")
        return 0

    print(f"\n{'Score':<6} {'Verdict':<14} Company / Role")
    print("-" * 70)
    for j in ranked[:top]:
        score = j.get("rank_score")
        verdict = (j.get("rank_verdict") or "")[:13]
        print(f"{score:<6} {verdict:<14} {j.get('company')} — {j.get('title')}")

    if confirm("Want to apply to any of these? I can run a full fit evaluation "
               "on one (paste/point to it via `apply`).", default=False):
        print("Run: python deepseek_runner.py apply \"<posting URL or text>\"")
    return 0
