"""Google Gemini (cloud) through the Generative Language REST API.

Why it is the first cloud provider: strong Arabic, strict JSON output, native function calling for the agent, and a generous free tier on the
Flash family. Data leaves the machine, so config marks it `local: false` and the organization's consent applies.

Configure (no code):   GEMINI_API_KEY=...        GEMINI_MODEL=model-a,model-b
`GEMINI_MODEL` may list several models, best first. Each model has its OWN quota, so when one is rate-limited the next is tried at once — and only
when all of them are exhausted does the hub move on to the next provider (Grok). Prefer a Flash model one step behind the newest: its limits are
looser than the newest model's.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from app.ai.base import AIRequest, Provider, ProviderError, RateLimited, extract_json

_PARK: dict[str, float] = {}      # model -> monotonic time until which it is skipped (it just answered 429/503)


class GeminiProvider(Provider):
    name = "gemini"
    supports_chat = True

    # -- configuration ------------------------------------------------------------------------------------------------------------------
    def _key(self, cfg) -> str:
        return os.environ.get(cfg.get("api_key_env", "GEMINI_API_KEY"), "").strip()

    def _models(self, task_name: str, cfg) -> list[str]:
        env = cfg.get("model_env")
        raw = (os.environ.get(env, "") if env else "").strip()
        if not raw:
            m = cfg.get("models") or {}
            raw = m.get(task_name) or m.get("default") or ""
        return [x.strip() for x in str(raw).replace(";", ",").split(",") if x.strip()]

    def available(self, cfg) -> bool:
        return bool(self._key(cfg)) and bool(self._models("default", cfg))

    def model_for(self, req, cfg):
        return (self._models(req.task.name, cfg) or [""])[0]

    def model_for_name(self, task_name, cfg):
        return (self._models(task_name, cfg) or [""])[0]

    # -- transport -----------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _post(url: str, body: dict, key: str, timeout: int) -> dict:
        http = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                      headers={"content-type": "application/json", "x-goog-api-key": key, "user-agent": "Mozilla/5.0 (compatible; PlanWise/1.0)"})
        with urllib.request.urlopen(http, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _generate(self, models: list[str], body: dict, cfg: dict, timeout: int) -> tuple[dict, str]:
        """Try the models in order; a model that is rate-limited, overloaded or unknown is skipped and parked briefly. Raises RateLimited when every model
        was limited, ProviderError for anything else."""
        base = (cfg.get("base_url") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        key, last, limited, wait = self._key(cfg), None, 0, 60.0
        now = time.monotonic()
        order = [m for m in models if _PARK.get(m, 0) <= now] or models[:1]
        for model in order:
            try:
                return self._post(f"{base}/models/{model}:generateContent", body, key, timeout), model
            except urllib.error.HTTPError as e:
                detail = e.read()[:300].decode("utf-8", "replace")
                if e.code in (429, 503, 500):
                    limited += 1
                    try:
                        wait = float(e.headers.get("retry-after") or 60)
                    except (TypeError, ValueError):
                        wait = 60.0
                    _PARK[model] = time.monotonic() + max(5.0, min(wait, 600.0))
                    last = f"gemini {model} HTTP {e.code}"
                    continue
                if e.code == 404:                                   # a model name this key cannot use: try the next one
                    _PARK[model] = time.monotonic() + 3600
                    last = f"gemini {model} HTTP 404: model not found"
                    continue
                raise ProviderError(f"gemini HTTP {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, OSError):
                last = f"gemini {model} unreachable"
                continue
            except (ValueError, TypeError):
                raise ProviderError("gemini reply is not JSON") from None
        if limited and limited == len(order):
            raise RateLimited(last or "gemini rate limited", wait)
        raise ProviderError(last or "gemini failed")

    @staticmethod
    def _parts(payload: dict) -> list[dict]:
        block = (payload.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise ProviderError(f"gemini blocked the prompt ({block})")
        cands = payload.get("candidates") or []
        if not cands:
            raise ProviderError("gemini returned no candidate")
        c = cands[0]
        parts = ((c.get("content") or {}).get("parts")) or []
        if not parts and c.get("finishReason") not in (None, "STOP"):
            raise ProviderError(f"gemini stopped: {c.get('finishReason')}")
        return [p for p in parts if isinstance(p, dict) and not p.get("thought")]

    # -- one structured answer (every task but the agent) --------------------------------------------------------------------------------
    def complete(self, req: AIRequest, cfg):
        models = self._models(req.task.name, cfg)
        if not models:
            raise ProviderError(f"no model configured ({cfg.get('model_env', 'GEMINI_MODEL')})")
        system = req.system + "\n\nReply with ONE JSON object only (no prose, no code fence) matching this JSON schema:\n" + json.dumps(req.schema, ensure_ascii=False)
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": req.user}]}],
                # thinking models spend part of the output budget on reasoning: leave room so the JSON is never cut off
                "generationConfig": {"temperature": req.temperature, "maxOutputTokens": min(max(req.max_tokens * 3, 2048), 8192),
                                     "responseMimeType": "application/json"}}
        payload, model = self._generate(models, body, cfg, req.timeout)
        text = "".join(p.get("text", "") for p in self._parts(payload))
        if not text.strip():
            raise ProviderError("gemini answered with no text")
        return extract_json(text), model

    # -- a turn of the agent's conversation, with tools ----------------------------------------------------------------------------------
    @staticmethod
    def _response_obj(content: str) -> dict:
        try:
            v = json.loads(content)
        except (TypeError, ValueError):
            return {"result": str(content)}
        return v if isinstance(v, dict) else {"result": v}

    def chat(self, messages, tools, system, cfg, *, task="agent", max_tokens=2000, temperature=0.2, timeout=60):
        models = self._models(task, cfg)
        if not models:
            raise ProviderError(f"no model configured ({cfg.get('model_env', 'GEMINI_MODEL')})")
        contents: list[dict] = []
        for m in messages:
            role = m["role"]
            if role == "assistant":
                parts = []
                if m.get("content"):
                    parts.append({"text": m["content"]})
                for c in m.get("tool_calls") or []:
                    part = {"functionCall": {"name": c["name"], "args": c.get("args") or {}}}
                    if c.get("sig"):
                        part["thoughtSignature"] = c["sig"]       # Gemini 3 requires the signature of its own call to be sent back
                    parts.append(part)
                contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            elif role == "tool":
                part = {"functionResponse": {"name": m.get("name", ""), "response": self._response_obj(m.get("content", ""))}}
                if contents and contents[-1]["role"] == "user" and all("functionResponse" in p for p in contents[-1]["parts"]):
                    contents[-1]["parts"].append(part)           # all results of one round go in ONE user turn
                else:
                    contents.append({"role": "user", "parts": [part]})
            else:
                contents.append({"role": "user", "parts": [{"text": m.get("content") or ""}]})
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "generationConfig": {"temperature": temperature, "maxOutputTokens": min(max(max_tokens * 3, 2048), 8192)}}
        if tools:
            decls = []
            for t in tools:
                d = {"name": t["name"], "description": t["description"]}
                if (t.get("parameters") or {}).get("properties"):
                    d["parametersJsonSchema"] = t["parameters"]
                decls.append(d)
            body["tools"] = [{"functionDeclarations": decls}]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        payload, model = self._generate(models, body, cfg, timeout)
        text, calls = [], []
        for p in self._parts(payload):
            if "functionCall" in p:
                fc = p["functionCall"] or {}
                args = fc.get("args") if isinstance(fc.get("args"), dict) else {}
                calls.append({"id": fc.get("id") or f"call_{len(calls)}", "name": fc.get("name", ""), "args": args,
                              **({"sig": p["thoughtSignature"]} if p.get("thoughtSignature") else {})})
            elif p.get("text"):
                text.append(p["text"])
        return {"text": "".join(text).strip(), "tool_calls": calls, "model": model}


provider = GeminiProvider()
