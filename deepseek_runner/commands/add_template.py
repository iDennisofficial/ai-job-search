"""/add-template — register a custom CV/cover-letter template.

Port of .claude/commands/add-template.md. Activation is deterministic Python:
the managed ACTIVE-TEMPLATE block is built from the template's TEMPLATE.md
manifest and inserted after the H1 of 05 (CV) or 06 (cover letter). The
scaffold path uses DeepSeek to produce the template skeleton + manifest.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..client import DeepSeekClient
from ..config import Config
from ..io import read_text, write_text
from ..manifest import S05, S06
from ..parse_output import extract_files
from ._common import ask, confirm

BLOCK_BEGIN = "<!-- BEGIN ACTIVE-TEMPLATE (managed by /add-template - do not edit by hand) -->"
BLOCK_END = "<!-- END ACTIVE-TEMPLATE -->"
TYPE_DIR = {"CV": "cv", "Cover letter": "cover_letters"}
GUIDANCE = {"CV": S05, "Cover letter": S06}
TYPE_FROM_DIR = {"cv": "CV", "cover_letters": "Cover letter"}


def list_templates(config: Config) -> list[tuple[str, str, str]]:
    out = []
    for tdir in ("cv", "cover_letters"):
        base = config.repo_root / "templates" / tdir
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            mf = d / "TEMPLATE.md"
            if mf.exists():
                text = read_text(mf)
                cmd = _parse_manifest(text).get("compile_command", "?")
                out.append((d.name, TYPE_FROM_DIR[tdir], cmd))
    return out


def _parse_manifest(text: str) -> dict:
    m = {
        "name": "",
        "type": "",
        "extension": "",
        "page_limit": "",
        "fonts": "",
        "class_packages": "",
        "compile_command": "",
    }
    n = re.search(r"^# Template:\s*(.+)$", text, re.MULTILINE)
    if n:
        m["name"] = n.group(1).strip()
    t = re.search(r"-\s*\*\*Type:\*\*\s*(.+)$", text, re.MULTILINE)
    if t:
        m["type"] = t.group(1).strip()
    e = re.search(r"-\s*\*\*Source extension:\*\*\s*`?([^\s`]+)", text)
    if e:
        m["extension"] = e.group(1).strip()
    p = re.search(r"-\s*\*\*Page limit:\*\*\s*([\w\s]+?)$", text, re.MULTILINE)
    if p:
        m["page_limit"] = p.group(1).strip()
    f = re.search(r"-\s*\*\*Fonts:\*\*\s*(.+)$", text, re.MULTILINE)
    if f:
        m["fonts"] = f.group(1).strip()
    c = re.search(r"-\s*\*\*Class/packages:\*\*\s*(.+)$", text, re.MULTILINE)
    if c:
        m["class_packages"] = c.group(1).strip()
    # compile command: indented code block under "## Compile command"
    cm = re.search(r"## Compile command\s*\n+\s*```.*?\n(.*?)\n\s*```", text, re.DOTALL)
    if cm:
        m["compile_command"] = cm.group(1).strip()
    else:
        ci = re.search(r"## Compile command\s*\n+(\s{4}.*(?:\n\s{4}.*)*)", text)
        if ci:
            m["compile_command"] = "\n".join(
                ln.strip() for ln in ci.group(1).splitlines()
            ).strip()
    return m


def build_active_block(mf: dict, tdir: str) -> str:
    name = mf["name"]
    ext = mf["extension"] or ".tex"
    cmd = mf["compile_command"] or f"lualatex -interaction=nonstopmode <file>{ext}"
    pages = mf["page_limit"] or ("2" if tdir == "cv" else "1")
    fonts = mf["fonts"] or "(system font)"
    other = "cover_letters/cover_<company>_<role>" if tdir == "cover_letters" else "cv/main_<company>_<role>"
    return (
        f"{BLOCK_BEGIN}\n"
        f"> **Active template override: `{name}`**\n"
        f">\n"
        f"> A custom template is active. Where this block conflicts with the "
        f"stock guidance below, this block wins. Structural advice below "
        f"(tailoring, page-budget, cutting rules) still applies.\n"
        f">\n"
        f"> - **Template skeleton:** `templates/{tdir}/{name}/template{ext}` — "
        f"use this as the structural reference instead of the stock template\n"
        f"> - **Manifest:** `templates/{tdir}/{name}/TEMPLATE.md` — read this "
        f"for style rules and known pitfalls before drafting\n"
        f"> - **Source extension:** `{ext}` (not `.tex` unless the template's "
        f"own toolchain is LaTeX)\n"
        f"> - **Compile command:** `{cmd}` (not the command named in the stock "
        f"guidance below — /apply's compile step must use this instead)\n"
        f"> - **Fonts:** {fonts}\n"
        f"> - **Page limit:** exactly {pages} page(s)\n"
        f"> - **Output file:** `{other}{ext}`; copy any class/package/font "
        f"files the template needs into the output directory, or reference "
        f"them by relative path\n"
        f"{BLOCK_END}"
    )


def _remove_block(text: str) -> str:
    pattern = re.compile(
        re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), re.DOTALL
    )
    return pattern.sub("", text)


def _insert_after_h1(text: str, block: str) -> str:
    text = _remove_block(text).rstrip("\n")
    lines = text.split("\n")
    idx = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
    return "\n".join(lines[: idx + 1] + [block] + lines[idx + 1 :]) + "\n"


def _activate(config: Config, name: str) -> bool:
    for tdir, type_label in TYPE_DIR.items():
        mf_path = config.repo_root / "templates" / tdir / name / "TEMPLATE.md"
        if mf_path.exists():
            mf = _parse_manifest(read_text(mf_path))
            mf.setdefault("name", name)
            block = build_active_block(mf, TYPE_DIR.get(mf["type"], tdir))
            guidance = GUIDANCE.get(mf["type"], GUIDANCE[TYPE_FROM_DIR[tdir]])
            path = config.repo_root / guidance
            write_text(path, _insert_after_h1(read_text(path), block))
            print(f"Activated template '{name}' in {guidance}")
            return True
    return False


def run(config: Config, argv: list[str]) -> int:
    args = list(argv)

    if "--list" in args:
        items = list_templates(config)
        if not items:
            print("No registered templates.")
        else:
            for name, type_label, cmd in items:
                print(f"  {name:<20} {type_label:<12} {cmd}")
        return 0

    if "--use" in args:
        i = args.index("--use")
        target = args[i + 1] if i + 1 < len(args) else "default"
        if target == "default":
            for guidance in (S05, S06):
                path = config.repo_root / guidance
                cleaned = _remove_block(read_text(path)).rstrip("\n") + "\n"
                write_text(path, cleaned)
            print("Deactivated custom template (stock defaults restored).")
            return 0
        if _activate(config, target):
            return 0
        print(f"No template named '{target}' found under templates/.")
        return 1

    # ---- interactive scaffold -------------------------------------------------
    print("Registering a new template (LLM-assisted).")
    name = ask("Template name (kebab-case, e.g. 'minimal')").strip()
    if not name:
        print("A name is required.")
        return 1
    type_label = ask("Type? (CV / Cover letter)", "CV").strip().lower()
    if type_label.startswith("cover"):
        type_label, tdir = "Cover letter", "cover_letters"
    else:
        type_label, tdir = "CV", "cv"
    src = ask("Path to the existing template source (.tex/.typ/.cls/.sty)?", "").strip()
    if not src or not (config.repo_root / src).exists():
        print(f"Source file not found: {src}")
        return 1

    source_text = read_text(config.repo_root / src)
    client = DeepSeekClient(config)
    user = (
        "A user wants to register this as a custom template. Produce two files "
        "as FILE: fenced blocks:\n"
        f"1) `templates/{tdir}/{name}/template{Path(src).suffix}` — the "
        "template skeleton with `[PLACEHOLDER]` tokens for candidate-specific "
        "values.\n"
        f"2) `templates/{tdir}/{name}/TEMPLATE.md` — a manifest in EXACTLY "
        "this format:\n"
        "```\n# Template: <name>\n\n"
        "- **Type:** {type}\n"
        "- **Source extension:** <ext>\n"
        "- **Engine/toolchain:** <tool>\n"
        "- **Page limit:** <N> page(s)\n"
        "- **Fonts:** <main font> (<bundled in fonts/ | system font - must be "
        "installed>)\n"
        "- **Class/packages:** <documentclass/imports>\n\n"
        "## Compile command\n\n    cd <output dir> && <command>\n\n"
        "## Style rules\n\n- <rule>\n\n## Known pitfalls\n\n- <pitfall>\n"
        "```\n\n"
        f"## Template source\n{source_text}"
    )
    result = client.chat([{"role": "user", "content": user}], role="default", temperature=0.2)
    files = extract_files(result)
    if not files:
        print("Model returned no FILE: blocks.\n" + result[:2000])
        return 1
    for p, content in files:
        if p.startswith(f"templates/{tdir}/") or "TEMPLATE.md" in p:
            write_text(config.repo_root / p, content)
            print(f"  wrote {p}")
    if _activate(config, name):
        print("\nTemplate registered and activated.")
    else:
        print("\nTemplate files written, but activation failed — check the "
              "TEMPLATE.md manifest under templates/.")
    return 0
