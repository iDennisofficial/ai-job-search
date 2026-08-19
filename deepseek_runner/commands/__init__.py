"""Command handlers. Each module exposes `run(config, argv) -> int`."""
from __future__ import annotations

from . import (
    add_portal,
    add_template,
    apply,
    expand,
    gmail_sync,
    html_report,
    interview,
    notion_sync,
    outcome,
    rank,
    reset,
    scrape,
    setup,
    upskill,
)

_HANDLERS = {
    "apply": apply.run,
    "setup": setup.run,
    "scrape": scrape.run,
    "rank": rank.run,
    "interview": interview.run,
    "outcome": outcome.run,
    "expand": expand.run,
    "upskill": upskill.run,
    "html-report": html_report.run,
    "add-template": add_template.run,
    "add-portal": add_portal.run,
    "reset": reset.run,
    "notion-sync": notion_sync.run,
    "gmail-sync": gmail_sync.run,
}


def get_handler(name: str):
    return _HANDLERS[name]
