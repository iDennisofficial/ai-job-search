"""File-system, JSON, and tracker-CSV helpers used across commands."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .config import Config

TRACKER_HEADER = [
    "date",
    "company",
    "sector",
    "role",
    "role_type",
    "channel",
    "status",
    "contact_person",
    "fit_rating",
    "notes",
    "cv_file",
    "cover_letter_file",
    "source",
]


def slugify(text: str) -> str:
    """Lowercase slug: non-alphanumeric runs become a single underscore."""
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s or "untitled"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path, default: str = "") -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return default


def write_text(path: Path, content: str) -> Path:
    path = Path(path)
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
    return path


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def write_json(path: Path, data) -> Path:
    path = Path(path)
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_tracker(config: Config) -> list[dict]:
    p = config.repo_root / "job_search_tracker.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def write_tracker(config: Config, rows: list[dict]) -> None:
    p = config.repo_root / "job_search_tracker.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRACKER_HEADER, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def archive_dir(config: Config, company: str, role: str) -> Path:
    """documents/applications/<company>_<role>/ (lowercase, underscores)."""
    name = f"{slugify(company)}_{slugify(role)}" if role else slugify(company)
    return config.repo_root / "documents" / "applications" / name


def list_open_applications(config: Config) -> list[dict]:
    """Tracker rows whose status is not a final value."""
    final = {"hired", "rejected", "no response", "no_response", "offer declined",
             "offer_declined", "withdrawn"}
    return [r for r in read_tracker(config) if (r.get("status") or "").strip().lower() not in final]
