"""Any OpenAI-compatible chat endpoint — Ollama, LM Studio, vLLM, llama.cpp server, or a hosted one.

This is the provider for LOCAL models: set AI_LOCAL_BASE_URL (e.g. http://localhost:11434/v1) and
AI_LOCAL_MODEL, and the product keeps company data on the company's own machine.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from app.ai.base import AIRequest, Provider, ProviderError, extract_json


class OpenAICompatProvider(Provider):
    name = "openai_compat"

    def _base(self, cfg):
        # Only the provider's OWN env var is read: xai/groq must never inherit AI_LOCAL_BASE_URL (that sent Grok's
        # requests to the local model's address).
        env = cfg.get("base_url_env")
        return ((os.environ.get(env, "") if env else "") or cfg.get("base_url") or "").rstrip("/")

    def _key(self, cfg):
        return os.environ.get(cfg.get("api_key_env", "AI_LOCAL_API_KEY"), "").strip()

    def available(self, cfg):
        if cfg.get("key_required") and not self._key(cfg):
            return False
        return bool(self._base(cfg))

    def model_for(self, req, cfg):
        env = cfg.get("model_env")
        return (os.environ.get(env, "").strip() if env else "") or super().model_for(req, cfg)

    @staticmethod
    def _post(url, body, headers, timeout):
        http = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
        with urllib.request.urlopen(http, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def complete(self, req: AIRequest, cfg):
        model = self.model_for(req, cfg)
        if not model:
            raise ProviderError(f"no model configured ({cfg.get('model_env', 'AI_LOCAL_MODEL')})")
        # Local models have no forced tool-calling: put the schema in the instructions.
        system = req.system + "\n\nReply with ONE JSON object only (no prose, no code fence) matching this JSON schema:\n" + json.dumps(req.schema, ensure_ascii=False)
        body = {
            "model": model,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": req.user}],
            "response_format": {"type": "json_object"},
        }
        # A browser-like User-Agent: Cloudflare in front of api.x.ai / api.groq.com answers 403 to Python-urllib's default.
        if "gpt-oss" in model:  # reasoning models: keep the thinking short so the JSON answer is never cut off
            body["reasoning_effort"] = "low"
        headers = {"content-type": "application/json", "accept": "application/json", "user-agent": "Mozilla/5.0 (compatible; Orbit/1.0)"}
        key = self._key(cfg).strip()
        if key:
            headers["authorization"] = "Bearer " + key
        url, data = self._base(cfg) + "/chat/completions", None
        try:
            try:
                payload = self._post(url, body, headers, req.timeout)
            except urllib.error.HTTPError as e:
                if e.code != 400 or not ("response_format" in body or "reasoning_effort" in body):
                    raise
                body.pop("response_format", None)  # some models reject JSON mode: the schema is already in the instructions
                body.pop("reasoning_effort", None)
                payload = self._post(url, body, headers, req.timeout)
            text = payload["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            raise ProviderError(f"{self.name} HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ProviderError(f"{self.name} unreachable: {type(e).__name__}") from None
        except (KeyError, IndexError, ValueError, TypeError):
            raise ProviderError(f"{self.name} reply has an unexpected shape") from None
        return extract_json(text), payload.get("model", model)


provider = OpenAICompatProvider()
