"""Minimal DeepSeek chat-completion client (OpenAI-compatible schema).

Only `message.content` is used for drafts; `reasoning_content` (returned by
deepseek-reasoner) is intentionally ignored so chain-of-thought never leaks
into generated files.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from .config import Config
from .parse_output import extract_json


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/chat/completions"

    def _headers(self) -> dict:
        key = self.config.api_key_resolved
        if not key:
            raise DeepSeekError(
                f"DeepSeek API key not found. Set the {self.config.api_key_env} "
                "environment variable (or api_key in config.json)."
            )
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def chat(
        self,
        messages: list[dict],
        *,
        role: str = "default",
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """Send a chat request; return the assistant message content string."""
        model = self.config.model(role)
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                resp = requests.post(
                    self.endpoint,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.config.timeout,
                )
            except requests.RequestException as e:  # network-level failure
                last_err = e
                time.sleep(self.config.retry_backoff * (attempt + 1))
                continue

            if resp.status_code == 200:
                data = resp.json()
                try:
                    return data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    raise DeepSeekError(
                        f"Unexpected DeepSeek response shape: {data}"
                    ) from e

            if resp.status_code in (408, 429, 500, 502, 503, 504):
                last_err = DeepSeekError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}"
                )
                time.sleep(self.config.retry_backoff * (attempt + 1))
                continue
            raise DeepSeekError(
                f"DeepSeek API error {resp.status_code}: {resp.text[:500]}"
            )
        raise DeepSeekError(
            f"DeepSeek API request failed after retries: {last_err}"
        )

    def chat_json(self, messages: list[dict], **kwargs) -> dict:
        """Like chat() but requires and parses JSON output."""
        text = self.chat(messages, json_mode=True, **kwargs)
        return extract_json(text)
