"""Anthropic Claude client — transport, auth, and token usage.

Prompts live in eagleeye/core/prompts/*.yml.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic
import httpx

from eagleeye.core.models import (
    AgentResult,
    BugScanResult,
    ModuleReadResult,
    PRReviewResult,
    RepoEvaluationResult,
    RepoSummaryResult,
)

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Accumulated token counts for one EagleEye command invocation."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def _add(self, usage) -> None:
        self.input_tokens += getattr(usage, "input_tokens", 0)
        self.output_tokens += getattr(usage, "output_tokens", 0)
        self.cache_creation_input_tokens += getattr(usage, "cache_creation_input_tokens", 0)
        self.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0)

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_read_input_tokens / self.total_input if self.total_input else 0.0

    @property
    def uncached_equivalent_input(self) -> int:
        return self.total_input


_PR_REVIEW_SCHEMA = json.dumps(PRReviewResult.model_json_schema(), sort_keys=True)
_REPO_SUMMARY_SCHEMA = json.dumps(RepoSummaryResult.model_json_schema(), sort_keys=True)
_REPO_EVALUATION_SCHEMA = json.dumps(RepoEvaluationResult.model_json_schema(), sort_keys=True)
_MODULE_READ_SCHEMA = json.dumps(ModuleReadResult.model_json_schema(), sort_keys=True)
_BUG_SCAN_SCHEMA = json.dumps(BugScanResult.model_json_schema(), sort_keys=True)
_AGENT_RESULT_SCHEMA = json.dumps(AgentResult.model_json_schema(), sort_keys=True)


class AIClient:
    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 8192,
        auth_mode: str = "direct",
        proxy_client_id: str = "",
        proxy_client_secret: str = "",
        proxy_url: str = "",
        token_url: str = "",
        scope: str = "",
    ):
        self.auth_mode = auth_mode
        self.model = model
        self.max_tokens = max_tokens
        self.total_usage = TokenUsage()

        if auth_mode == "proxy":
            self._proxy_url = proxy_url
            self._proxy_client_id = proxy_client_id
            self._proxy_client_secret = proxy_client_secret
            self._token_url = token_url
            self._scope = scope
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=api_key)
            self._proxy_url = ""

    def _log_usage(self, usage, label: str) -> None:
        self.total_usage._add(usage)
        logger.debug(
            f"[{label}] Cache hit: {getattr(usage, 'cache_read_input_tokens', 0)} | "
            f"Cache write: {getattr(usage, 'cache_creation_input_tokens', 0)} | "
            f"Input: {getattr(usage, 'input_tokens', 0)} | "
            f"Output: {getattr(usage, 'output_tokens', 0)}"
        )

    def _call(
        self,
        system_prompt: str,
        user_content: list[dict],
        max_tokens: Optional[int] = None,
    ) -> str:
        tokens = max_tokens if max_tokens is not None else self.max_tokens
        if self.auth_mode == "proxy":
            return self._call_proxy(system_prompt, user_content, tokens)
        return self._call_direct(system_prompt, user_content, tokens)

    def _call_proxy(self, system_prompt: str, user_content: list[dict], max_tokens: int) -> str:
        from eagleeye.core.config import get_proxy_token
        token = get_proxy_token(
            self._proxy_client_id, self._proxy_client_secret, self._token_url, self._scope
        )
        # Proxy rejects top-level 'system' and cache_control beta —
        # inject system as a primed exchange.
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "user", "content": [{"type": "text", "text": system_prompt}]})
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": "Understood."}],
            })
        clean_content = [
            {"type": b["type"], "text": b["text"]}
            for b in user_content
            if b.get("type") == "text"
        ]
        messages.append({"role": "user", "content": clean_content})

        resp = httpx.post(
            self._proxy_url,
            params={"model": self.model},
            json={"max_tokens": max_tokens, "messages": messages},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=90,
        )
        if not resp.is_success:
            raise RuntimeError(
                f"Proxy {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        return "".join(
            block["text"] for block in data.get("content", []) if block.get("type") == "text"
        )

    def _call_direct(self, system_prompt: str, user_content: list[dict], max_tokens: int) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        self._log_usage(response.usage, self.model)
        return "".join(block.text for block in response.content if block.type == "text")

    def _make_content_block(self, text: str, cache: bool = False) -> dict:
        block: dict = {"type": "text", "text": text}
        if cache:
            block["cache_control"] = {"type": "ephemeral"}
        return block


def _clean_json(text: str) -> str:
    """Strip markdown fences if Claude wraps its JSON response in them."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1
        end = len(lines)
        while end > start and lines[end - 1].strip() in ("```", ""):
            end -= 1
        text = "\n".join(lines[start:end])
    return text.strip()
