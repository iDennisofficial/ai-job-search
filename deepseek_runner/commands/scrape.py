"""/scrape — search enabled job portals and store postings.

Port of the job-scraper skill: runs the Bun portal CLIs (linkedin-search,
freehire-search, …) and merges new postings into job_scraper/seen_jobs.json
with status "new". Fit-scoring happens later in `rank`. The scraping itself
needs no AI.
"""
from __future__ import annotations

from datetime import date

from ..config import Config
from ..io import read_json, write_json
from ..portals import list_enabled_portals, run_portal


def _job_key(r: dict) -> tuple:
    ident = r.get("id") or r.get("public_slug") or r.get("url") or ""
    return (r.get("_portal"), str(ident))


def _load_seen(config: Config) -> list[dict]:
    path = config.repo_root / "job_scraper" / "seen_jobs.json"
    data = read_json(path, [])
    if isinstance(data, dict):
        data = data.get("jobs", [])
    return list(data) if isinstance(data, list) else []


def run(config: Config, argv: list[str]) -> int:
    portal_arg = None
    passthrough = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--portal" and i + 1 < len(argv):
            portal_arg = argv[i + 1]
            i += 2
            continue
        passthrough.append(tok)
        i += 1

    if portal_arg:
        portals = [portal_arg]
    else:
        portals = list_enabled_portals(config)
        if not portals:
            print("No enabled portal CLIs found. Enable one in its SKILL.md "
                  "(`enabled: true`) or run `add-portal`.")
            return 1
        print(f"Enabled portals: {', '.join(portals)}")

    results = []
    for p in portals:
        # The portal CLIs expose a `search` subcommand (and `detail`).
        args = ["search"] + list(passthrough)
        if p == "linkedin-search" and not any(
            a in ("--location", "-l") for a in args
        ):
            print(f"  {p}: linkedin-search requires --location '<place>' (e.g. "
                  "'Berlin, Germany' or 'Remote'). Skipping.")
            continue
        print(f"Searching {p}…")
        ok, data, err = run_portal(config, p, args)
        if not ok:
            print(f"  {p}: {err}")
            continue
        hits = data.get("results", [])
        print(f"  {p}: {len(hits)} result(s)")
        for h in hits:
            if isinstance(h, dict):
                h["_portal"] = p
                results.append(h)

    if not results:
        print("No postings found.")
        return 0

    seen = _load_seen(config)
    seen_by_key = {_job_key(j): j for j in seen}
    added = 0
    today = date.today().isoformat()
    for r in results:
        key = _job_key(r)
        if key in seen_by_key:
            continue
        entry = {
            "_portal": r.get("_portal"),
            "id": r.get("id") or r.get("public_slug"),
            "title": r.get("title"),
            "company": r.get("company"),
            "location": r.get("location"),
            "date": r.get("date"),
            "url": r.get("url"),
            "description": r.get("description"),
            "status": "new",
            "first_seen": today,
        }
        seen.append(entry)
        seen_by_key[key] = entry
        added += 1

    write_json(config.repo_root / "job_scraper" / "seen_jobs.json", seen)
    print(f"\nStored {added} new posting(s) in job_scraper/seen_jobs.json "
          f"({len(seen)} total).")
    print("Run `rank` to score them against your profile.")
    return 0
