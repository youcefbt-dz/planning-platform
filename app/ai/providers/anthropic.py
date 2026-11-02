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
    supports_chat = True

    def _key(self, cfg):
        return os.environ.get(cfg.get("api_key_env", "ANTHROPIC_API_KEY"), "")

    def available(self, cfg):
        return bool(self._key(cfg))

    def chat(self, messages, tools, system, cfg, *, task="agent", max_tokens=2000, temperature=0.2, timeout=60):
        model = self.model_for_name(task, cfg)
        if not model:
            raise ProviderError("no model configured")
        wire: list[dict] = []
        for m in messages:
            if m["role"] == "assistant":
                blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c.get("args") or {}} for c in m.get("tool_calls") or []]
                wire.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "…"}]})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if wire and wire[-1]["role"] == "user" and isinstance(wire[-1]["content"], list):
                    wire[-1]["content"].append(block)           # results of one turn go in ONE user message
                else:
                    wire.append({"role": "user", "content": [block]})
            else:
                wire.append({"role": "user", "content": m.get("content") or ""})
        body = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system, "messages": wire}
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
        url = cfg.get("base_url", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        http = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                      headers={"content-type": "application/json", "x-api-key": self._key(cfg), "anthropic-version": cfg.get("version", "2023-06-01")})
        try:
            with urllib.request.urlopen(http, timeout=timeout) as r:
                payload = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ProviderError(f"anthropic HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ProviderError("anthropic unreachable") from None
        text, calls = [], []
        for b in payload.get("content", []):
            if b.get("type") == "text":
                text.append(b.get("text", ""))
            elif b.get("type") == "tool_use":
                calls.append({"id": b.get("id", f"call_{len(calls)}"), "name": b.get("name", ""), "args": b.get("input") if isinstance(b.get("input"), dict) else {}})
        return {"text": "\n".join(text).strip(), "tool_calls": calls, "model": payload.get("model", model)}

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
