"""DeepSeek job-application assistant runner.

Replaces the Claude Code layer for the ai-job-search repo: loads the Markdown
command files as instruction prompts, assembles context from the skill/profile
files, calls the DeepSeek API, and executes the file/compile/ATS steps itself.
"""

__version__ = "0.1.0"
