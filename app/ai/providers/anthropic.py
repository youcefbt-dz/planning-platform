"""Anthropic Messages API (cloud). Dependency-free (urllib) so it can be tested against a fake server.

Structured output is forced with a single tool whose input_schema is the task schema.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from app.ai.base import AIRequest, Provider, ProviderError


class AnthropicProvider(Provider):
    name = "anthropic"

    def _key(self, cfg):
        return os.environ.get(cfg.get("api_key_env", "ANTHROPIC_API_KEY"), "")

    def available(self, cfg):
        return bool(self._key(cfg))

    def complete(self, req: AIRequest, cfg):
        model = self.model_for(req, cfg)
        if not model:
            raise ProviderError("no model configured")
        body = {
            "model": model,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "system": req.system,
            "messages": [{"role": "user", "content": req.user}],
            "tools": [{"name": "respond", "description": req.task.description or req.task.name, "input_schema": req.schema}],
            "tool_choice": {"type": "tool", "name": "respond"},
        }
        url = cfg.get("base_url", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        http = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"content-type": "application/json", "x-api-key": self._key(cfg), "anthropic-version": cfg.get("version", "2023-06-01")},
        )
        try:
            with urllib.request.urlopen(http, timeout=req.timeout) as r:
                payload = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ProviderError(f"anthropic HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise ProviderError(f"anthropic unreachable: {type(e).__name__}") from None
        for block in payload.get("content", []):
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                return block["input"], payload.get("model", model)
        raise ProviderError("anthropic reply had no tool_use block")


provider = AnthropicProvider()
