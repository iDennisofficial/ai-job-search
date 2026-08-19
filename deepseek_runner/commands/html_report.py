"""/html-report — self-contained offline application dashboard.

Pure rendering (no DeepSeek needed): reads job_search_tracker.csv +
documents/applications/*/outcome.md, computes stats, and writes one
dependency-free HTML file with hand-written inline SVG charts.
"""
from __future__ import annotations

import csv
import html
import math
import re
from datetime import datetime
from pathlib import Path

from ..config import Config
from ..io import slugify

COLORS = {
    "Active": "#3b82f6",
    "Interview": "#f59e0b",
    "Offer": "#8b5cf6",
    "Hired": "#22c55e",
    "Rejected/Closed": "#ef4444",
}

CLOSED_STATUSES = {
    "rejected",
    "no_response",
    "no response",
    "offer_declined",
    "offer declined",
    "interview_only",
    "withdrawn",
}


def esc(value) -> str:
    """HTML-escape any CSV/outcome value (incl. SVG <text> content)."""
    return html.escape(str(value if value is not None else ""), quote=True)


def normalize_status(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in ("applied", "applied (sent)") or s.startswith("applied"):
        return "Active"
    if s == "interview" or s.startswith("interview"):
        return "Interview"
    if s == "offer" or s.startswith("offer"):
        return "Offer"
    if s == "hired":
        return "Hired"
    return "Rejected/Closed"


def channel_bucket(raw: str) -> str:
    s = (raw or "").lower()
    if any(k in s for k in ("referral", "reference", "contact", "network")):
        return "referral"
    if any(k in s for k in ("online", "portal", "site", "linkedin", "job", "web")):
        return "online"
    return "other"


def year_of(date_str: str) -> str:
    m = re.match(r"(\d{4})", (date_str or "").strip())
    return m.group(1) if m else "?"


def read_outcomes(config: Config) -> dict:
    """folder_name -> outcome.md text, keyed by slugified folder name."""
    apps = config.repo_root / "documents" / "applications"
    out = {}
    if apps.is_dir():
        for d in sorted(apps.iterdir()):
            if d.is_dir():
                om = d / "outcome.md"
                if om.exists():
                    try:
                        out[d.name] = om.read_text(encoding="utf-8")
                    except OSError:
                        pass
    return out


def read_rows(config: Config) -> list[dict]:
    p = config.repo_root / "job_search_tracker.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def resolve_archive(outcomes: dict, row: dict) -> str | None:
    key = f"{slugify(row.get('company') or '')}_{slugify(row.get('role') or '')}"
    if key in outcomes:
        return outcomes[key]
    # fall back to any folder matching just the company prefix
    for name in outcomes:
        if name == slugify(row.get("company") or "") or name.startswith(
            slugify(row.get("company") or "") + "_"
        ):
            return outcomes[name]
    return None


# ---------------------------------------------------------------- chart builders

def doughnut_svg(items: list[tuple[str, int, str]]) -> str:
    """items: (label, count, color). Returns an inline <svg>."""
    total = sum(c for _, c, _ in items) or 1
    cx, cy, r, inner = 100, 100, 80, 46
    start = -90.0
    paths = []
    for label, count, color in items:
        if count <= 0:
            continue
        frac = count / total
        end = start + 360 * frac
        large = 1 if (end - start) > 180 else 0
        x1 = cx + r * math.cos(math.radians(start))
        y1 = cy + r * math.sin(math.radians(start))
        x2 = cx + r * math.cos(math.radians(end))
        y2 = cy + r * math.sin(math.radians(end))
        d = (
            f"M {cx} {cy} L {x1:.2f} {y1:.2f} A {r} {r} 0 {large} 1 "
            f"{x2:.2f} {y2:.2f} Z"
        )
        paths.append(f'<path d="{d}" fill="{color}"><title>{esc(label)}: {count}</title></path>')
        start = end
    legend = "".join(
        f'<span class="lg"><i style="background:{color}"></i>{esc(label)} ({count})</span>'
        for label, count, color in items
        if count
    )
    summary = ", ".join(f"{n} {l}" for l, n, _ in items if n)
    return (
        f'<div class="chart-wrap">'
        f'<svg viewBox="0 0 200 200" role="img" aria-label="Status breakdown: {esc(summary)}" '
        f'width="180" height="180">{chr(10)}'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none"/>{"".join(paths)}'
        f'<circle cx="{cx}" cy="{cy}" r="{inner}" fill="white"/>'
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="22" font-weight="700" '
        f'fill="#111827">{total}</text>'
        f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" font-size="10" fill="#6b7280">'
        f'total</text>'
        f'</svg><div class="legend">{legend}</div></div>'
    )


def hbar_svg(items: list[tuple[str, int]], color: str, max_count: int | None = None) -> str:
    """Horizontal bar chart. items: (label, value)."""
    if not items:
        return '<div class="chart-wrap"><p class="muted">No data yet.</p></div>'
    mx = max_count if max_count else max(v for _, v in items) or 1
    rows = []
    for label, value in items:
        w = (value / mx) * 220
        rows.append(
            f'<div class="bar-row">'
            f'<span class="bar-label">{esc(label)}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{w:.1f}px;'
            f'background:{color}"><span class="bar-val">{value}</span></div></div>'
            f'</div>'
        )
    summary = ", ".join(f"{v} {l}" for l, v in items)
    aria = f'aria-label="Bar chart: {esc(summary)}"'
    return f'<div class="chart-wrap" {aria}>{"".join(rows)}</div>'


# ------------------------------------------------------------------ HTML page

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Search Dashboard</title>
<style>
:root {{
  --active:#3b82f6; --interview:#f59e0b; --offer:#8b5cf6;
  --hired:#22c55e; --closed:#ef4444;
  --bg:#f3f4f6; --card:#ffffff; --border:#e5e7eb; --text:#111827; --muted:#6b7280;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  background:var(--bg); color:var(--text); padding:24px; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
.sub {{ color:var(--muted); font-size:13px; margin-bottom:20px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:12px; margin-bottom:20px; }}
.card {{ background:var(--card); border-radius:10px; padding:14px 16px;
  box-shadow:0 1px 2px rgba(0,0,0,.06); border-left:4px solid var(--muted); }}
.card .num {{ font-size:26px; font-weight:700; }}
.card .lbl {{ color:var(--muted); font-size:12px; text-transform:uppercase;
  letter-spacing:.03em; }}
.charts {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:20px; }}
.chart-card {{ background:var(--card); border-radius:10px; padding:16px;
  box-shadow:0 1px 2px rgba(0,0,0,.06); }}
.chart-card h3 {{ margin:0 0 10px; font-size:14px; }}
.chart-wrap {{ display:flex; align-items:center; gap:14px; flex-wrap:wrap; }}
.legend {{ display:flex; flex-direction:column; gap:4px; font-size:12px; }}
.lg i {{ display:inline-block; width:10px; height:10px; border-radius:2px;
  margin-right:6px; }}
.bar-row {{ display:flex; align-items:center; gap:8px; margin:5px 0; }}
.bar-label {{ width:90px; font-size:12px; text-align:right; color:var(--text);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.bar-track {{ flex:1; background:#eef1f5; border-radius:4px; height:18px; }}
.bar-fill {{ height:18px; border-radius:4px; display:flex; align-items:center;
  justify-content:flex-end; padding-right:4px; min-width:0; }}
.bar-val {{ font-size:11px; color:#fff; font-weight:600; }}
.muted {{ color:var(--muted); }}
table {{ width:100%; border-collapse:collapse; background:var(--card);
  border-radius:10px; overflow:hidden; box-shadow:0 1px 2px rgba(0,0,0,.06); }}
th,td {{ padding:8px 10px; text-align:left; font-size:13px; border-bottom:1px solid var(--border); }}
th {{ background:#f9fafb; font-size:12px; text-transform:uppercase; letter-spacing:.03em;
  color:var(--muted); }}
tr:nth-child(even) td {{ background:#fafafa; }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:999px; color:#fff;
  font-size:12px; font-weight:600; }}
.tools {{ display:flex; gap:10px; margin-bottom:10px; flex-wrap:wrap; }}
.tools input,.tools select {{ padding:6px 10px; border:1px solid var(--border);
  border-radius:8px; font-size:13px; background:#fff; }}
.tools input {{ width:220px; }}
footer {{ margin-top:20px; color:var(--muted); font-size:12px; }}
@media (max-width:900px) {{ .charts {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<h1>&#128269; Job Search Dashboard</h1>
<div class="sub">Generated: {generated}</div>

<div class="cards">
  <div class="card" style="border-left-color:#111827"><div class="num">{total}</div>
    <div class="lbl">Total</div></div>
  <div class="card" style="border-left-color:var(--active)"><div class="num">{n_active}</div>
    <div class="lbl">Active</div></div>
  <div class="card" style="border-left-color:var(--interview)"><div class="num">{n_interview}</div>
    <div class="lbl">Interview</div></div>
  <div class="card" style="border-left-color:var(--offer)"><div class="num">{n_offer}</div>
    <div class="lbl">Offer</div></div>
  <div class="card" style="border-left-color:var(--closed)"><div class="num">{n_closed}</div>
    <div class="lbl">Rejected/Closed</div></div>
</div>

<div class="charts">
  <div class="chart-card"><h3>Status breakdown</h3>{doughnut}</div>
  <div class="chart-card"><h3>By sector</h3>{sector_bar}</div>
  <div class="chart-card"><h3>By channel</h3>{channel_bar}</div>
  <div class="chart-card"><h3>Application funnel</h3>{funnel}</div>
</div>

<div class="tools">
  <input type="search" id="q" placeholder="Search company, role, sector&#8230;">
  <select id="f-status"><option value="">All statuses</option>{status_opts}</select>
  <select id="f-sector"><option value="">All sectors</option>{sector_opts}</select>
</div>

<table id="apps">
<thead><tr><th>Date</th><th>Company</th><th>Role</th><th>Sector</th><th>Channel</th>
<th>Status</th><th>Notes</th><th>Source</th></tr></thead>
<tbody>{rows}</tbody>
</table>

<footer>Generated by ai-job-search (DeepSeek runner) · {generated}</footer>

<script>
const colorFor = {{
  'Active':'#3b82f6','Interview':'#f59e0b','Offer':'#8b5cf6',
  'Hired':'#22c55e','Rejected/Closed':'#ef4444'
}};
function applyFilters() {{
  const q = document.getElementById('q').value.toLowerCase();
  const s = document.getElementById('f-status').value;
  const se = document.getElementById('f-sector').value;
  document.querySelectorAll('#apps tbody tr').forEach(tr => {{
    const t = tr.dataset; 
    const ok = (!q || t.search.includes(q)) && (!s || t.status === s) &&
      (!se || t.sector === se);
    tr.style.display = ok ? '' : 'none';
  }});
}}
document.getElementById('q').addEventListener('input', applyFilters);
document.getElementById('f-status').addEventListener('change', applyFilters);
document.getElementById('f-sector').addEventListener('change', applyFilters);
</script>
</body>
</html>
"""


def run(config: Config, argv: list[str]) -> int:
    out_path = config.repo_root / "reports" / "application-dashboard.html"
    for token in argv:
        if token == "--open":
            continue
        if not token.startswith("-"):
            out_path = Path(token).expanduser()

    rows = read_rows(config)
    outcomes = read_outcomes(config)

    # Merge outcome notes into rows + compute archive presence.
    enriched = []
    for row in rows:
        om = resolve_archive(outcomes, row)
        if om and not (row.get("notes") or "").strip():
            row["notes"] = row.get("notes") or ""
        enriched.append((row, normalize_status(row.get("status") or "")))

    total = len(enriched)
    n_active = sum(1 for _, s in enriched if s == "Active")
    n_interview = sum(1 for _, s in enriched if s == "Interview")
    n_offer = sum(1 for _, s in enriched if s == "Offer")
    n_hired = sum(1 for _, s in enriched if s == "Hired")
    n_closed = sum(1 for _, s in enriched if s == "Rejected/Closed")

    # Sector / channel / year stats.
    sectors: dict[str, int] = {}
    channels = {"online": 0, "referral": 0, "other": 0}
    years: dict[str, int] = {}
    for row, _ in enriched:
        sec = (row.get("sector") or "").strip() or "—"
        sectors[sec] = sectors.get(sec, 0) + 1
        ch = channel_bucket(row.get("channel") or "")
        channels[ch] = channels.get(ch, 0) + 1
        y = year_of(row.get("date") or "")
        years[y] = years.get(y, 0) + 1

    funnel_applied = total
    funnel_interview = n_interview + n_offer + n_hired
    funnel_offer = n_offer + n_hired
    funnel_hired = n_hired

    progressed = funnel_interview
    funnel_pct = round(progressed / total * 100) if total else 0
    resolved = total - n_active
    reject_pct = round(n_closed / resolved * 100) if resolved else 0

    # Charts.
    status_items = [
        ("Active", n_active, COLORS["Active"]),
        ("Interview", n_interview, COLORS["Interview"]),
        ("Offer", n_offer, COLORS["Offer"]),
        ("Hired", n_hired, COLORS["Hired"]),
        ("Rejected/Closed", n_closed, COLORS["Rejected/Closed"]),
    ]
    doughnut = doughnut_svg(status_items)
    sector_sorted = sorted(sectors.items(), key=lambda kv: kv[1], reverse=True)
    sector_bar = hbar_svg(sector_sorted, "#6366f1")
    channel_items = [("online", channels["online"]), ("referral", channels["referral"]),
                     ("other", channels["other"])]
    channel_bar = hbar_svg(channel_items, "#0ea5e9")
    funnel_items = [("Applied", funnel_applied), ("Interview", funnel_interview),
                    ("Offer", funnel_offer), ("Hired", funnel_hired)]
    funnel_bar = hbar_svg(funnel_items, "#10b981", max_count=total or 1)

    status_opts = "".join(
        f'<option value="{esc(k)}">{esc(k)}</option>' for k in COLORS
    )
    sector_opts = "".join(
        f'<option value="{esc(s)}">{esc(s)}</option>' for s, _ in sector_sorted
    )

    # Table rows (newest-first by date, then company).
    def sort_key(item):
        row, _ = item
        return (row.get("date") or "", row.get("company") or "")

    sorted_rows = sorted(enriched, key=sort_key, reverse=True)
    tbody = []
    for row, status in sorted_rows:
        color = COLORS.get(status, "#6b7280")
        notes = (row.get("notes") or "").strip() or "—"
        notes_short = notes if len(notes) <= 80 else notes[:80] + "…"
        src = (row.get("source") or "").strip()
        if src.startswith("http"):
            source_cell = f'<a href="{esc(src)}" target="_blank" rel="noopener">{esc(src)}</a>'
        else:
            source_cell = esc(src or "—")
        search = " ".join(
            str(row.get(k) or "") for k in ("company", "role", "sector")
        ).lower()
        tbody.append(
            f'<tr data-search="{esc(search)}" data-status="{esc(status)}" '
            f'data-sector="{esc(row.get("sector") or "—")}">'
            f'<td>{esc(row.get("date") or "—")}</td>'
            f'<td>{esc(row.get("company") or "—")}</td>'
            f'<td>{esc(row.get("role") or "—")}</td>'
            f'<td>{esc(row.get("sector") or "—")}</td>'
            f'<td>{esc(row.get("channel") or "—")}</td>'
            f'<td><span class="pill" style="background:{color}">{esc(status)}</span></td>'
            f'<td title="{esc(notes)}">{esc(notes_short)}</td>'
            f'<td>{source_cell}</td></tr>'
        )
    rows_html = "\n".join(tbody)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    page = PAGE_TEMPLATE.format(
        generated=esc(generated),
        total=total,
        n_active=n_active,
        n_interview=n_interview,
        n_offer=n_offer,
        n_closed=n_closed,
        doughnut=doughnut,
        sector_bar=sector_bar,
        channel_bar=channel_bar,
        funnel=funnel_bar,
        status_opts=status_opts,
        sector_opts=sector_opts,
        rows=rows_html,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")

    print(f"Dashboard generated: {out_path}")
    print("Open it in any browser — no server needed.")
    print("\nSummary:")
    print(f"- Total applications: {total}")
    print(f"- Active: {n_active} · Interview: {n_interview} · Hired: {n_hired} · "
          f"Rejected/Closed: {n_closed}")
    print(f"- Funnel: {funnel_pct}% progressed past resume screen "
          f"({funnel_interview} of {total})")
    print(f"- Rejection rate: {reject_pct}% of resolved applications")
    print(f"- By year: {', '.join(f'{y}: {n}' for y, n in sorted(years.items()))}")
    return 0
