"""LaTeX compile + page-count verification, plus ACTIVE-TEMPLATE parsing.

The runner compiles and inspects PDFs itself — DeepSeek's text-only API cannot
look at a rendered PDF the way a vision-capable agent loop can. On failure the
caller feeds compile errors + a text preview back to the model and retries.
"""
from __future__ import annotations

import re
import subprocess

from .config import Config
from .io import read_text

ACTIVE_TEMPLATE_RE = re.compile(
    r"<!-- BEGIN ACTIVE-TEMPLATE.*?-->(.*?)<!-- END ACTIVE-TEMPLATE -->", re.DOTALL
)


class TemplateOverride:
    """Resolved ACTIVE-TEMPLATE block (stock defaults when absent)."""

    def __init__(
        self,
        extension: str = ".tex",
        compile_cmd: str | None = None,
        page_limit: int | None = None,
        skeleton: str | None = None,
    ):
        self.extension = extension
        self.compile_cmd = compile_cmd
        self.page_limit = page_limit
        self.skeleton = skeleton

    def engine_args(self, filename: str) -> list[str] | None:
        """Shell command pieces for the output dir, or None for stock defaults."""
        if not self.compile_cmd:
            return None
        return self.compile_cmd.replace("<file>", filename).split()


def resolve_template_override(config: Config, guidance_path: str) -> TemplateOverride:
    """Parse the ACTIVE-TEMPLATE block from 05/06 (stock defaults if absent)."""
    text = read_text(config.repo_root / guidance_path)
    m = ACTIVE_TEMPLATE_RE.search(text)
    if not m:
        return TemplateOverride()
    block = m.group(1)
    ext = re.search(r"\*\*Source extension:\*\*\s*`?([^\s`]+)", block)
    cmd = re.search(r"\*\*Compile command:\*\*\s*`?([^`\n]+)", block)
    pages = re.search(r"\*\*Page limit:\*\*\s*exactly\s*(\d+)", block, re.IGNORECASE)
    skeleton = re.search(r"\*\*Template skeleton:\*\*\s*`?([^`\n]+)", block)
    return TemplateOverride(
        extension=ext.group(1) if ext else ".tex",
        compile_cmd=cmd.group(1).strip() if cmd else None,
        page_limit=int(pages.group(1)) if pages else None,
        skeleton=skeleton.group(1).strip() if skeleton else None,
    )


def compile_tex(
    config: Config, workdir: str, filename: str, engine: str
) -> tuple[bool, str]:
    """Run `engine -interaction=nonstopmode filename` in workdir."""
    cwd = config.repo_root / workdir
    cmd = [engine, "-interaction=nonstopmode", filename]
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=300
        )
    except FileNotFoundError:
        return False, f"{engine} not found on PATH"
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode == 0, log[-4000:]


def compile_custom(
    config: Config, workdir: str, filename: str, compile_cmd: str
) -> tuple[bool, str]:
    """Run a custom template's declared compile command in workdir."""
    cwd = config.repo_root / workdir
    cmd = compile_cmd.replace("<file>", filename)
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=300
        )
    except OSError as e:
        return False, str(e)
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode == 0, log[-4000:]


def page_count(config: Config, pdf_path: str) -> int | None:
    """Count PDF pages via pdfinfo, falling back to pypdf."""
    pdf = config.repo_root / pdf_path
    if not pdf.exists():
        return None
    try:
        proc = subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=30
        )
        m = re.search(r"^Pages:\s+(\d+)", proc.stdout, re.MULTILINE)
        if m:
            return int(m.group(1))
    except FileNotFoundError:
        pass
    try:
        from pypdf import PdfReader  # venv dependency (requirements.txt)

        return len(PdfReader(str(pdf)).pages)
    except Exception:
        return None


def compile_and_check(
    config: Config,
    workdir: str,
    filename: str,
    engine: str,
    target_pages: int | None,
    pdf_path: str | None = None,
    override: TemplateOverride | None = None,
) -> tuple[bool, str, int | None]:
    """Compile and verify page count. Returns (ok, log, pages)."""
    if override and override.compile_cmd:
        ok, log = compile_custom(config, workdir, filename, override.compile_cmd)
    else:
        ok, log = compile_tex(config, workdir, filename, engine)
    if not ok:
        return False, log, None
    if target_pages is None:
        return True, log, None
    pages = page_count(config, pdf_path or f"{workdir}/{filename}".replace(".tex", ".pdf"))
    return pages == target_pages, log, pages
