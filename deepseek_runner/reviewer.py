"""Drafter/Reviewer separation for /apply.

Reproduces the repo's second-agent "reviewer" pass as a second DeepSeek call
with a distinct critique-only system prompt and a fresh context, without
needing real subagents.
"""
from __future__ import annotations

from .client import DeepSeekClient
from .config import Config
from .prompts import SECURITY_GUARDRAIL, SYSTEM_REVIEWER


def reviewer_pass(
    client: DeepSeekClient,
    config: Config,
    *,
    drafts: list[tuple[str, str]],  # [(path, content), ...]
    posting: str,
    context: str,
) -> str:
    """Run the critique-only reviewer over the drafts; return its feedback."""
    draft_blocks = "\n\n".join(
        f"<DRAFT file=\"{path}\">\n{content}\n</DRAFT>" for path, content in drafts
    )
    body = (
        f"{SECURITY_GUARDRAIL}\n\n"
        f"## Reference materials (grounding sources)\n{context}\n\n"
        f"## Job posting\n<JOB_POSTING>\n{posting}\n</JOB_POSTING>\n\n"
        f"## Drafts to review\n{draft_blocks}\n\n"
        "Produce your feedback as Part A (JSON array of edits "
        "[{file, old_string, new_string, reason}]) plus Part B (narrative "
        "suggestions grouped by category). Address every category."
    )
    messages = [
        {"role": "system", "content": SYSTEM_REVIEWER},
        {"role": "user", "content": body},
    ]
    return client.chat(messages, role="default", temperature=0.2)
