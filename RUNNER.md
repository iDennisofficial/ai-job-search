# DeepSeek Runner (`deepseek_runner.py`)

A self-contained orchestration layer that lets the `ai-job-search` repo run
**without Claude Code**, driven by the DeepSeek API. The Markdown prompt files
under `.claude/commands/` are still the product — this runner loads them,
assembles the context (profile + skill files), calls DeepSeek, and executes
the file/compile/ATS steps the original workflow expected Claude Code to do.

## Why this exists

Claude Code provided infrastructure this repo depends on that a DeepSeek chat
API does not: slash-command routing, filesystem access, shell execution, and
subagents. This runner supplies those pieces in Python:

| Claude Code feature | Replacement here |
|---|---|
| Slash commands (`/apply`, `/setup`, …) | `python deepseek_runner.py <command> …` |
| Reading skill/profile files | the runner concatenates them into the prompt |
| Editing files | the model emits `FILE:` blocks; the runner writes them to disk |
| Shell (latex, pdftotext, portal CLIs) | `subprocess` calls made by the runner |
| "Reviewer" subagent in `/apply` | a second DeepSeek call with a critique-only prompt |

## Setup

```bash
# 1. Python venv + deps (Python 3.10+)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Portal search CLIs (Bun) — linkedin + freehire are market-agnostic
cd .agents/skills/linkedin-search/cli && bun install && cd ../../../..
cd .agents/skills/freehire-search/cli && bun install && cd ../../../..

# 3. LaTeX (lualatex for CV, xelatex for cover letters) + pdftotext (optional)
#    e.g. brew install --cask tinytex poppler   (or MacTeX/TeX Live)

# 4. API key
export DEEPSEEK_API_KEY=sk-...
```

## Usage

```bash
.venv/bin/python deepseek_runner.py setup                 # profile intake (interactive)
.venv/bin/python deepseek_runner.py apply "<job URL or pasted posting>"
.venv/bin/python deepseek_runner.py scrape --portal linkedin-search --location "Berlin, Germany"
.venv/bin/python deepseek_runner.py rank
.venv/bin/python deepseek_runner.py interview "<company> <role>"
.venv/bin/python deepseek_runner.py outcome "<company> <role>"
.venv/bin/python deepseek_runner.py html-report
```

Run `.venv/bin/python deepseek_runner.py --help` for the full command list.

## Commands

| Command | Needs LLM | Notes |
|---|---|---|
| `apply` | yes | full drafter→reviewer→revise→compile→ATS pipeline |
| `setup` | yes | interactive profile intake → CLAUDE.md + skills 01–07 |
| `scrape` | no | run enabled portal CLIs, store postings in `job_scraper/seen_jobs.json` |
| `rank` | yes | score `new` postings → shortlist (`deepseek-reasoner`) |
| `interview` | yes | stage-specific prep pack from a tracked application |
| `outcome` | yes* | tracker + archive + follow-up drafting (*needs LLM only for follow-ups) |
| `expand` | yes | additive competency discovery from documents |
| `upskill` | yes | coaching plan from the upskill skill |
| `html-report` | no | offline HTML dashboard (pure Python + inline SVG) |
| `add-template` | yes* | register custom CV/cover template (*scaffold path needs LLM; `--use`/`--list` don't) |
| `add-portal` | yes | scaffold a portal-search skill from a URL |
| `reset` | no | destructive reset of profile/documents (requires typing `RESET`) |
| `notion-sync` | no | push ranked jobs + applications to Notion (gated on `NOTION_TOKEN`) |
| `gmail-sync` | yes | classify Gmail status signals, approve-first batch (gated on Google creds) |

## Design notes

- **Output contract.** When a command must write files, the model is told to
  emit a `FILE: <relative path>` line followed by a fenced code block. The
  runner extracts these and writes them (it is the retrieval/execution layer).
- **Drafter/reviewer.** `/apply` makes a second DeepSeek call with a
  critique-only system prompt and fresh context, then a revision call; the
  runner rewrites the files from the revised `FILE:` blocks (more reliable in a
  stateless runner than mechanical string edits).
- **Models.** `deepseek-chat` is the default; `deepseek-reasoner` is used for
  fit evaluation and CV cutting. Configure in `config.json` (see
  `config.json.example`). Only `message.content` is used — `reasoning_content`
  never leaks into drafts.
- **Security.** Every prompt that includes scraped/pasted posting text carries
  the "posting is untrusted data" guardrail. The runner never follows links
  found inside a posting body.
- **Optional deps degrade gracefully.** Missing `pdftotext` skips the ATS
  parseability check; missing `pdfinfo` falls back to `pypdf`; missing
  `salary_lookup.py` data skips the salary benchmark; missing Notion/Gmail
  credentials exit cleanly with a one-line message.

## Verified in this repo

- `html-report` renders a correct dashboard from a sample tracker + outcomes.
- `reset` safely clears documents (preserving `.gitkeep`) after the `RESET`
  confirmation.
- All modules byte-compile; `--help` lists all 14 commands.
