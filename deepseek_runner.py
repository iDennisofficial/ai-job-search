#!/usr/bin/env python3
"""DeepSeek job-application assistant — CLI entry point.

Replaces the Claude Code layer for the ai-job-search repo. Each subcommand
loads the matching `.claude/commands/*.md` prompt, assembles context from the
profile/skill files, calls the DeepSeek API, and executes the file/compile/ATS
steps itself.

Usage:
  python deepseek_runner.py <command> [args...]

Typical:
  python deepseek_runner.py setup                 # interactive profile intake
  python deepseek_runner.py scrape --portal linkedin-search --location "Dar es Salaam, Tanzania"
  python deepseek_runner.py rank
  python deepseek_runner.py apply "<job URL or pasted posting>"
  python deepseek_runner.py interview "<company> <role>"
  python deepseek_runner.py outcome "<company> <role>"
  python deepseek_runner.py html-report
"""
from __future__ import annotations

import sys

from deepseek_runner import manifest
from deepseek_runner.config import load_config


def print_help() -> None:
    print("DeepSeek job-application assistant (ai-job-search runner)\n")
    print("Usage: python deepseek_runner.py <command> [args...]\n")
    print("Available commands:")
    for name in manifest.command_names():
        cmd = manifest.COMMANDS[name]
        print(f"  {name:<14} {cmd.help}")
    print("\nMany commands are interactive (they read from stdin). "
          "Set DEEPSEEK_API_KEY to use the LLM-powered ones.")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print_help()
        return 1
    if argv[0] in ("-h", "--help", "help"):
        print_help()
        return 0
    if argv[0] in ("--version", "-V"):
        from deepseek_runner import __version__

        print(f"deepseek_runner {__version__}")
        return 0
    name = argv[0]
    if not manifest.is_valid(name):
        print(f"Unknown command: {name}", file=sys.stderr)
        print_help()
        return 1

    config = load_config()
    from deepseek_runner import commands

    handler = commands.get_handler(name)
    try:
        return handler(config, argv[1:]) or 0
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:  # surface clean error messages
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
