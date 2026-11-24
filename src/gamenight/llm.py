"""Thin async model clients. Game logic only ever asks for text and parses JSON itself."""

from __future__ import annotations

import json
import os
import re
from typing import Protocol


class LLM(Protocol):
    name: str

    async def complete(self, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.8) -> str: ...


class AnthropicLLM:
    def __init__(self, model: str | None = None, client=None):
        if client is None:
            from anthropic import AsyncAnthropic  # optional dependency

            client = AsyncAnthropic()
        self.client = client
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.name = f"Claude ({self.model})"

    async def complete(self, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.8) -> str:
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")


class AzureLLM:
    def __init__(self, deployment: str | None = None, client=None):
        if client is None:
            from openai import AsyncAzureOpenAI  # optional dependency

            client = AsyncAzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            )
        self.client = client
        self.model = deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        self.name = f"Azure AI Foundry ({self.model})"

    async def complete(self, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.8) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""


def get_llm(name: str | None = None) -> LLM | None:
    """LLM_PROVIDER = anthropic | azure | offline (default). None means use the offline game master."""
    name = (name or os.getenv("LLM_PROVIDER") or "offline").lower()
    if name == "anthropic":
        return AnthropicLLM()
    if name in ("azure", "foundry"):
        return AzureLLM()
    return None


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a model reply (tolerates code fences and chatter)."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object in model output")
    return json.loads(match.group(0))
