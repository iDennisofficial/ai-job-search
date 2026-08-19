"""Smoke tests for the DeepSeek runner's pure-Python components.

These tests run without a network connection or API key — they validate the
parts of the runner that don't call DeepSeek (config, parsing, ATS helpers,
IO, manifest, html-report logic).
"""
import json
from pathlib import Path

from deepseek_runner import ats, io, manifest
from deepseek_runner.config import load_config
from deepseek_runner.parse_output import extract_files, extract_json
from deepseek_runner.latex import TemplateOverride, resolve_template_override

REPO = Path(__file__).resolve().parent.parent


def test_config_defaults():
    cfg = load_config()
    assert cfg.model("default") == "deepseek-chat"
    assert cfg.model("reasoning") == "deepseek-reasoner"
    assert cfg.api_key_env == "DEEPSEEK_API_KEY"


def test_manifest_has_all_commands():
    names = manifest.command_names()
    for expected in (
        "apply", "setup", "scrape", "rank", "interview", "outcome", "expand",
        "upskill", "html-report", "add-template", "add-portal", "reset",
        "notion-sync", "gmail-sync",
    ):
        assert expected in names, expected
    assert manifest.is_valid("apply")
    assert not manifest.is_valid("nope")


def test_extract_files():
    text = (
        "FILE: cv/main_acme_mle.tex\n"
        "```latex\n\\documentclass{moderncv}\n\\end{document}\n```\n"
        "FILE: cover_letters/cover_acme_mle.tex\n"
        "```tex\n\\documentclass{cover}\n```\n"
    )
    files = extract_files(text)
    assert len(files) == 2
    assert files[0][0] == "cv/main_acme_mle.tex"
    assert "\\documentclass{moderncv}" in files[0][1]
    assert files[1][0] == "cover_letters/cover_acme_mle.tex"


def test_extract_json_object_and_array():
    assert extract_json('blah {"a": 1} blah') == {"a": 1}
    arr = extract_json('```json\n[{"id": "x", "s": 80}]\n```')
    assert isinstance(arr, list) and arr[0]["id"] == "x"


def test_ats_keyword_coverage():
    text = "Machine Learning Engineer with PyTorch and Kubernetes experience."
    rows = ats.keyword_coverage(text, ["PyTorch", "Kubernetes", "Rust"])
    status = {r["keyword"]: r["status"] for r in rows}
    assert status["PyTorch"] == "covered"
    assert status["Kubernetes"] == "covered"
    assert status["Rust"] == "missing"


def test_ats_parseability():
    assert ats.parseability_issues("clean text") == []
    assert ats.parseability_issues("(cid:12) glyph") != []
    assert ats.parseability_issues("bad \ufffd char") != []


def test_io_slugify_and_archive():
    assert io.slugify("Acme Corp") == "acme_corp"
    assert io.slugify("  Senior ML Engineer!! ") == "senior_ml_engineer"
    cfg = load_config()
    d = io.archive_dir(cfg, "Acme Corp", "Senior ML Engineer")
    assert str(d).endswith("applications/acme_corp_senior_ml_engineer")


def test_template_override_defaults(tmp_path, monkeypatch):
    # No ACTIVE-TEMPLATE block -> stock defaults.
    p = tmp_path / "05.md"
    p.write_text("# Title\n\nSome stock guidance.\n", encoding="utf-8")
    cfg = load_config()
    monkeypatch.setattr(cfg, "repo_root", tmp_path)
    ov = resolve_template_override(cfg, p.name)
    assert isinstance(ov, TemplateOverride)
    assert ov.extension == ".tex"
    assert ov.compile_cmd is None
    assert ov.page_limit is None


def test_template_override_active(tmp_path, monkeypatch):
    cfg = load_config()
    monkeypatch.setattr(cfg, "repo_root", tmp_path)
    p = tmp_path / "05.md"
    p.write_text(
        "# Title\n\n"
        "<!-- BEGIN ACTIVE-TEMPLATE (managed by /add-template - do not edit by hand) -->\n"
        "> - **Source extension:** `.typ`\n"
        "> - **Compile command:** `typst compile <file>.typ <file>.pdf`\n"
        "> - **Page limit:** exactly 1 page(s)\n"
        "<!-- END ACTIVE-TEMPLATE -->\n\nRest.\n",
        encoding="utf-8",
    )
    ov = resolve_template_override(cfg, p.name)
    assert ov.extension == ".typ"
    assert "typst compile" in (ov.compile_cmd or "")
    assert ov.page_limit == 1


def test_html_report_normalize_and_rows(tmp_path, monkeypatch):
    from deepseek_runner.commands import html_report

    cfg = load_config()
    monkeypatch.setattr(cfg, "repo_root", tmp_path)
    assert html_report.normalize_status("applied") == "Active"
    assert html_report.normalize_status("interview") == "Interview"
    assert html_report.normalize_status("offer") == "Offer"
    assert html_report.normalize_status("hired") == "Hired"
    assert html_report.normalize_status("rejected") == "Rejected/Closed"
    assert html_report.normalize_status("no response") == "Rejected/Closed"
    assert html_report.channel_bucket("online") == "online"
    assert html_report.channel_bucket("referral") == "referral"
    assert html_report.channel_bucket("linkedin") == "online"


def test_html_report_end_to_end(tmp_path, monkeypatch):
    from deepseek_runner.commands import html_report

    cfg = load_config()
    monkeypatch.setattr(cfg, "repo_root", tmp_path)
    (tmp_path / "reports").mkdir(parents=True)
    (tmp_path / "job_search_tracker.csv").write_text(
        "date,company,sector,role,role_type,channel,status,contact_person,"
        "fit_rating,notes,cv_file,cover_letter_file,source\n"
        "2026-06-01,Acme Corp,AI,MLE,full-time,online,applied,,85,notes,"
        "cv/a.tex,cover/a.tex,https://acme.example/1\n"
        "2026-06-10,Globex,AI,DS,full-time,referral,hired,,70,,,,\n",
        encoding="utf-8",
    )
    rc = html_report.run(cfg, [])
    assert rc == 0
    out = tmp_path / "reports" / "application-dashboard.html"
    assert out.exists()
    page = out.read_text(encoding="utf-8")
    assert "Acme Corp" in page
    assert "Rejected/Closed" in page  # palette present
    assert "https://acme.example/1" in page  # source link
    assert "Generated by Claude Code" in page
