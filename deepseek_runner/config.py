"""Configuration for the DeepSeek runner.

Loads config.json from the repo root (optional, git-ignored) merged over
defaults, and resolves the API key from the environment. Environment variables
always win over config.json for the API key.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_models() -> dict:
    return {
        "default": "deepseek-chat",
        "reasoning": "deepseek-reasoner",
    }


@dataclass
class Config:
    repo_root: Path = REPO_ROOT
    api_key_env: str = "DEEPSEEK_API_KEY"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    models: dict = field(default_factory=_default_models)
    enabled_portals: list = field(
        default_factory=lambda: ["linkedin-search", "freehire-search"]
    )
    timeout: float = 180.0
    max_retries: int = 3
    retry_backoff: float = 2.0
    max_compile_retries: int = 3
    portal_bin: str = "bun"

    @property
    def api_key_resolved(self) -> str:
        return self.api_key or os.environ.get(self.api_key_env, "")

    def model(self, role: str = "default") -> str:
        return self.models.get(role, self.models.get("default", "deepseek-chat"))


def load_config(config_path: Path | None = None) -> Config:
    cfg = Config()
    path = config_path or (REPO_ROOT / "config.json")
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for key in (
            "api_key_env",
            "api_key",
            "base_url",
            "models",
            "enabled_portals",
            "timeout",
            "max_retries",
            "retry_backoff",
            "max_compile_retries",
            "portal_bin",
        ):
            if key in data:
                setattr(cfg, key, data[key])
    # Environment always wins for the secret.
    if os.environ.get(cfg.api_key_env):
        cfg.api_key = os.environ[cfg.api_key_env]
    return cfg
