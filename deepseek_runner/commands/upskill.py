"""/upskill — coaching-style skill-building guidance.

Runs the upskill skill (a prompt file, not a command) through the generic
LLM dispatcher. Outputs a plan only — no file writes.
"""
from __future__ import annotations

from ..client import DeepSeekClient
from ..config import Config
from ..manifest import COMMANDS
from ._common import generic_llm_command


def run(config: Config, argv: list[str]) -> int:
    focus = " ".join(argv).strip() or "a skill-development plan"
    client = DeepSeekClient(config)
    generic_llm_command(
        client,
        config,
        COMMANDS["upskill"],
        f"Produce {focus}. Use the framework in the instructions. Output a "
        "structured plan (goals, weekly actions, resources, self-assessment).",
    )
    return 0
