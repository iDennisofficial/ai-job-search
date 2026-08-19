"""/gmail-sync — classify Gmail status signals for open applications.

Port of .claude/commands/gmail-sync.md. Gated on Google API credentials —
without them the command exits cleanly. Every proposed tracker/outcome change
is presented as a batch and only written after explicit user approval; the
classifier never proposes `hired`/`offer declined` on its own.
"""
from __future__ import annotations

import os
from datetime import date, datetime

from ..client import DeepSeekClient
from ..config import Config
from ..io import (
    archive_dir,
    ensure_dir,
    list_open_applications,
    read_json,
    read_tracker,
    write_json,
    write_tracker,
)
from ..prompts import SECURITY_GUARDRAIL
from ._common import ask, confirm

STATE_PATH = "gmail_sync/state.json"
SENDER_DOMAINS = (
    "greenhouse.io lever.co myworkday.com ashbyhq.com smartrecruiters.com "
    "icims.com bamboohr.com"
)


def _build_service(config: Config):
    """Return a Gmail service, or raise a helpful error."""
    creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH") or (config.repo_root / "gmail_sync" / "credentials.json")
    token_path = os.environ.get("GMAIL_TOKEN_PATH") or (config.repo_root / "gmail_sync" / "token.json")
    try:
        from google.auth.transport.requests import Request  # type: ignore[import-not-found]
        from google.oauth2.credentials import Credentials  # type: ignore[import-not-found]
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-not-found]
        from googleapiclient.discovery import build  # type: ignore[import-not-found]
    except ImportError:
        raise RuntimeError(
            "Google libraries not installed. Run: "
            ".venv/bin/pip install google-api-python-client "
            "google-auth-oauthlib google-auth-httplib2"
        ) from None
    import pathlib

    creds = None
    if pathlib.Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(str(token_path), ["https://www.googleapis.com/auth/gmail.readonly"])
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not pathlib.Path(creds_path).exists():
                raise RuntimeError(
                    f"Gmail not configured: no credentials.json at {creds_path}. "
                    "See https://developers.google.com/gmail/api/quickstart/python"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(creds_path),
                ["https://www.googleapis.com/auth/gmail.readonly"],
            )
            creds = flow.run_local_server(port=0)
        pathlib.Path(token_path).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(token_path).write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _classify(client: DeepSeekClient, company: str, subject: str, body: str) -> str:
    prompt = (
        f"{SECURITY_GUARDRAIL}\n\n"
        f"Classify this email about a job application at {company}. Return one "
        "JSON object: {\"signal\": \"ack\" | \"interview\" | \"offer\" | "
        "\"rejection\" | \"other\", \"stage\": \"\" | \"phone\" | \"technical\" "
        "| \"case\" | \"final\" | \"offer\", \"summary\": \"<one line>\"}. "
        "Classify from the full body only. Never return hired/offer_declined.\n\n"
        f"Subject: {subject}\n\nBody:\n{body[:4000]}"
    )
    data = client.chat_json([{"role": "user", "content": prompt}], role="default", temperature=0.0)
    return data.get("signal", "other"), data.get("stage", ""), data.get("summary", "")


def run(config: Config, argv: list[str]) -> int:
    rows = read_tracker(config)
    open_apps = list_open_applications(config)
    if not rows:
        print("No tracker yet — run `outcome \"<company> <role>\"` first. Skipping.")
        return 0
    if not open_apps:
        print("No open applications — nothing to sync.")
        return 0

    state = read_json(config.repo_root / STATE_PATH, {})
    processed = set(state.get("processed_message_ids", []))
    last_sync = state.get("last_sync")

    try:
        service = _build_service(config)
    except RuntimeError as e:
        print(f"{e} — skipping.")
        return 0

    company_or = " OR ".join(f'"{a["company"]}"' for a in open_apps[:10])
    query = f'in:inbox ({" ".join(open_apps[0:1] and ["{" + company_or + "}"])})'
    query = f'in:inbox ({"{" + company_or + "}"}) ({{from:{" ".join(SENDER_DOMAINS.split())}}})'

    try:
        results = service.users().messages().list(
            userId="me", q=query, maxResults=50
        ).execute()
    except Exception as e:  # noqa: BLE001
        print(f"Gmail query failed: {e}")
        return 1

    messages = results.get("messages", [])
    if not messages:
        print("No candidate emails found.")
        return 0

    print(f"Checking {len(messages)} thread(s)…")
    client = DeepSeekClient(config)
    proposals = []
    for m in messages:
        mid = m["id"]
        if mid in processed:
            continue
        try:
            full = service.users().messages().get(
                userId="me", id=mid, format="full"
            ).execute()
        except Exception:  # noqa: BLE001
            continue
        headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
        subject = headers.get("subject", "")
        sender = headers.get("from", "")
        body_parts = []
        payload = full.get("payload", {})
        if payload.get("body", {}).get("data"):
            import base64
            body_parts.append(base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore"))
        for part in payload.get("parts", []):
            if part.get("mimeType", "").startswith("text/plain") and part.get("body", {}).get("data"):
                import base64
                body_parts.append(base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "ignore"))
        body = "\n".join(body_parts)

        matched = next((a for a in open_apps if a["company"].lower() in (subject + " " + body).lower()), None)
        if not matched:
            continue
        signal, stage, summary = _classify(client, matched["company"], subject, body)
        if signal in ("interview", "offer", "rejection"):
            proposals.append((matched, signal, stage, summary, subject, sender, mid))
        processed.add(mid)

    if not proposals:
        print("No new status-changing signals found.")
        _save_state(config, processed)
        return 0

    print("\nProposed tracker updates (nothing written yet):")
    for matched, signal, stage, summary, subject, sender, mid in proposals:
        print(f"  • {matched['company']} — {matched['role']}: "
              f"{signal.upper()} ({summary})  <{subject}>")

    if not confirm("\nApprove these changes?"):
        print("Skipped — nothing written.")
        _save_state(config, processed)
        return 0

    for matched, signal, stage, summary, subject, sender, mid in proposals:
        for r in rows:
            if r["company"].lower() == matched["company"].lower():
                if signal == "interview":
                    r["status"] = "interview"
                elif signal == "offer":
                    r["status"] = "offer"
                elif signal == "rejection":
                    r["status"] = "rejected"
                note = f"{date.today().isoformat()} gmail-sync: {signal} ({summary})"
                r["notes"] = (r["notes"] + "\n" if r.get("notes") else "") + note
                # minimal outcome.md update
                archive = ensure_dir(archive_dir(config, matched["company"], matched["role"]))
                om = archive / "outcome.md"
                if not om.exists():
                    om.write_text(
                        f"# Outcome: {matched['company']} — {matched['role']}\n\n"
                        f"**Status:** {r['status']}\n\n## Notes\n{note}\n",
                        encoding="utf-8",
                    )
    write_tracker(config, rows)
    _save_state(config, processed)
    print("Tracker + outcome files updated.")
    return 0


def _save_state(config: Config, processed: set) -> None:
    write_json(
        config.repo_root / STATE_PATH,
        {
            "processed_message_ids": sorted(processed),
            "last_sync": datetime.now().isoformat(timespec="seconds"),
        },
    )
