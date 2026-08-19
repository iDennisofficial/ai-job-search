"""/notion-sync — push ranked jobs + applications to a Notion database.

One-way, read-only pipeline view: Notion is a disposable presentation layer;
the repo stays the source of truth. Gated on credentials (NOTION_TOKEN +
parent page id or an existing database id) — without them the command exits
cleanly with a one-line message, exactly as the upstream command does.
"""
from __future__ import annotations

import os

import requests

from ..config import Config
from ..io import read_json, write_json
from ._common import ask, confirm

STATE_PATH = "job_scraper/notion_sync.json"
DB_TITLE = "Job Search Pipeline"


class NotionClient:
    def __init__(self, token: str):
        self.base = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    def create_database(self, parent_page_id: str) -> dict:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": DB_TITLE}}],
            "properties": {
                "Name": {"title": {}},
                "Key": {"rich_text": {}},
                "Company": {"rich_text": {}},
                "Score": {"number": {}},
                "Verdict": {"rich_text": {}},
                "Status": {"rich_text": {}},
                "Fit": {"rich_text": {}},
                "Deadline": {"rich_text": {}},
                "First seen": {"rich_text": {}},
                "Ranked": {"rich_text": {}},
                "Applied on": {"rich_text": {}},
                "Channel": {"rich_text": {}},
                "CV file": {"rich_text": {}},
                "Cover letter": {"rich_text": {}},
                "URL": {"url": {}},
            },
        }
        resp = requests.post(f"{self.base}/databases", headers=self.headers,
                             json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def query(self, database_id: str) -> list[dict]:
        results = []
        cursor = None
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            resp = requests.post(f"{self.base}/databases/{database_id}/query",
                                 headers=self.headers, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("results", []))
            cursor = data.get("next_cursor")
            if not cursor or not data.get("has_more"):
                break
        return results

    def _props(self, database_id: str, values: dict) -> dict:
        # database_id unused here; kept for signature symmetry with real API
        return values

    def upsert(self, database_id: str, key: str, values: dict) -> None:
        for page in self.query(database_id):
            kv = (page.get("properties", {}).get("Key", {})
                  .get("rich_text", []))
            if kv and kv[0].get("plain_text") == key:
                self.update(page["id"], values)
                return
        self.create(database_id, values)

    def create(self, database_id: str, values: dict) -> None:
        body = {"parent": {"database_id": database_id}, "properties": values}
        resp = requests.post(f"{self.base}/pages", headers=self.headers,
                             json=body, timeout=30)
        resp.raise_for_status()

    def update(self, page_id: str, values: dict) -> None:
        body = {"properties": values}
        resp = requests.patch(f"{self.base}/pages/{page_id}", headers=self.headers,
                              json=body, timeout=30)
        resp.raise_for_status()


def _rt(text: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": (text or "")[:2000]}}]}


def run(config: Config, argv: list[str]) -> int:
    token = os.environ.get("NOTION_TOKEN") or config.api_key and ""
    token = os.environ.get("NOTION_TOKEN", "")
    parent_page = os.environ.get("NOTION_PARENT_PAGE_ID", "")
    state = read_json(config.repo_root / STATE_PATH, {})
    database_id = state.get("database_id", "")

    if not token:
        print("Notion not configured (set NOTION_TOKEN). Skipping — nothing synced.")
        return 0
    if not database_id and not parent_page:
        print("Notion not configured (set NOTION_PARENT_PAGE_ID or run once with "
              "an existing database id). Skipping.")
        return 0

    client = NotionClient(token)
    if not database_id:
        try:
            db = client.create_database(parent_page)
            database_id = db["id"]
        except requests.HTTPError as e:
            print(f"Could not create Notion database: {e}")
            return 1

    # Build the sync set.
    jobs = read_json(config.repo_root / "job_scraper" / "seen_jobs.json", [])
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs", [])
    ranked = [j for j in (jobs or []) if isinstance(j, dict)
              and j.get("status") == "ranked"
              and (j.get("rank_score") or 0) >= 60]

    from ..io import read_tracker
    apps = read_tracker(config)

    if not ranked and not apps:
        print("Sync set is empty (no ranked jobs ≥60 and no tracked "
              "applications) — nothing synced.")
        return 0

    print(f"Syncing {len(ranked)} ranked job(s) + {len(apps)} application(s) to Notion…")
    for j in ranked:
        key = str(j.get("id") or j.get("url"))
        name = f"{j.get('title')} — {j.get('company')}"
        values = {
            "Name": {"title": [{"type": "text", "text": {"content": name[:2000]}}]},
            "Key": _rt(key),
            "Company": _rt(j.get("company")),
            "Score": {"number": j.get("rank_score")} if isinstance(j.get("rank_score"), (int, float)) else {"number": 0},
            "Verdict": _rt(j.get("rank_verdict")),
            "Deadline": _rt(j.get("date")),
            "First seen": _rt(j.get("first_seen")),
            "Ranked": _rt(j.get("rank_date")),
            "URL": {"url": j.get("url")} if (j.get("url") or "").startswith("http") else {"url": None},
        }
        client.upsert(database_id, key, values)

    for a in apps:
        key = f"app:{a.get('company')}:{a.get('role')}"
        name = f"{a.get('role')} — {a.get('company')} (application)"
        values = {
            "Name": {"title": [{"type": "text", "text": {"content": name[:2000]}}]},
            "Key": _rt(key),
            "Company": _rt(a.get("company")),
            "Status": _rt(a.get("status")),
            "Channel": _rt(a.get("channel")),
            "CV file": _rt(a.get("cv_file")),
            "Cover letter": _rt(a.get("cover_letter_file")),
        }
        client.upsert(database_id, key, values)

    state.update({"database_id": database_id, "last_sync": __import__("datetime").date.today().isoformat()})
    write_json(config.repo_root / STATE_PATH, state)
    print("Synced. Notion database URL: "
          f"https://www.notion.so/{database_id.replace('-', '')}")
    return 0
