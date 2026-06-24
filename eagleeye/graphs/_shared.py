"""Shared infrastructure for EagleEye LangGraph workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..integrations.anthropic.client import TokenUsage
from ..core.config import (
    get_proxy_token,
)

logger = logging.getLogger(__name__)



@dataclass
class _ProxyResponse:
    """Duck-type response matching what graph nodes expect from llm.invoke()."""
    content: str
    response_metadata: dict = field(default_factory=dict)


class _ProxyChatModel:
    """Thin httpx wrapper for an OAuth2 Claude proxy, compatible with llm.invoke() call sites."""

    def __init__(self, proxy_client_id: str, proxy_client_secret: str, token_url: str,
                 scope: str, proxy_url: str, model: str, max_tokens: int):
        self._proxy_client_id = proxy_client_id
        self._proxy_client_secret = proxy_client_secret
        self._token_url = token_url
        self._scope = scope
        self._proxy_url = proxy_url
        self.model = model
        self.max_tokens = max_tokens

    def invoke(self, messages: list) -> _ProxyResponse:
        token = get_proxy_token(
            self._proxy_client_id, self._proxy_client_secret, self._token_url, self._scope
        )

        # Proxy does not accept top-level 'system' field — inject SystemMessage as user/assistant exchange
        proxy_messages: list[dict] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_text = _extract_text(msg.content)
                if system_text:
                    proxy_messages.append({"role": "user", "content": [{"type": "text", "text": system_text}]})
                    proxy_messages.append({"role": "assistant", "content": [{"type": "text", "text": "Understood."}]})
            elif isinstance(msg, HumanMessage):
                proxy_messages.append({"role": "user", "content": _normalise_content(msg.content)})
            elif isinstance(msg, AIMessage):
                proxy_messages.append({"role": "assistant", "content": _normalise_content(msg.content)})

        resp = httpx.post(
            self._proxy_url,
            params={"model": self.model},
            json={"max_tokens": self.max_tokens, "messages": proxy_messages},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=120,
        )
        if not resp.is_success:
            raise RuntimeError(f"Proxy {resp.status_code}: {resp.text[:400]}")

        data = resp.json()
        text = "".join(
            block["text"] for block in data.get("content", []) if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        return _ProxyResponse(
            content=text,
            response_metadata={"usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            }},
        )


def _extract_text(content: Any) -> str:
    """Extract plain text from a message content (str or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _normalise_content(content: Any) -> list[dict]:
    """Convert LangChain message content to proxy-compatible content blocks (no cache_control)."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        blocks = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                blocks.append({"type": "text", "text": block["text"]})
            elif isinstance(block, str):
                blocks.append({"type": "text", "text": block})
        return blocks
    return [{"type": "text", "text": str(content)}]


def make_llm(state: dict) -> ChatAnthropic | _ProxyChatModel:
    """Create an LLM client from graph state.

    Supports two auth modes:
      direct — ChatAnthropic against api.anthropic.com
      proxy  — _ProxyChatModel using direct httpx to the SN Claude proxy
    """
    model = state["model"]
    max_tokens = state["max_tokens"]

    if state.get("auth_mode") == "proxy":
        return _ProxyChatModel(
            proxy_client_id=state["proxy_client_id"],
            proxy_client_secret=state["proxy_client_secret"],
            token_url=state.get("token_url") or "",
            scope=state.get("scope") or _DEFAULT_SCOPE,
            proxy_url=state.get("proxy_url") or "",
            model=model,
            max_tokens=max_tokens,
        )

    return ChatAnthropic(
        api_key=state["api_key"],
        model=model,
        max_tokens=max_tokens,
    )


def make_cached_system_message(system_text: str) -> SystemMessage:
    return SystemMessage(
        content=[
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )


def make_content_block(text: str, cache: bool = False) -> dict:
    block: dict = {"type": "text", "text": text}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return block


def accumulate_usage(usage: TokenUsage, response_metadata: dict) -> None:
    u = response_metadata.get("usage", {})
    usage.input_tokens += u.get("input_tokens", 0)
    usage.output_tokens += u.get("output_tokens", 0)
    usage.cache_creation_input_tokens += u.get("cache_creation_input_tokens", 0)
    usage.cache_read_input_tokens += u.get("cache_read_input_tokens", 0)
    logger.debug(
        "Cache hit: %d | Cache write: %d | Input: %d | Output: %d",
        u.get("cache_read_input_tokens", 0),
        u.get("cache_creation_input_tokens", 0),
        u.get("input_tokens", 0),
        u.get("output_tokens", 0),
    )
