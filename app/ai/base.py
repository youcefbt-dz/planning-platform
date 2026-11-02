"""Contracts of the AI layer. A provider talks to a model; a task knows what to ask and how to check the answer."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


class ProviderError(RuntimeError):
    """A provider could not answer (network, auth, bad status, unparsable reply)."""


class RateLimited(ProviderError):
    """The provider is out of quota or overloaded right now (HTTP 429/503). The hub parks it for `retry_after` seconds and goes straight to the next
    provider, so a limit never makes the person wait or the page stumble."""

    def __init__(self, message: str, retry_after: float = 60.0):
        super().__init__(message)
        self.retry_after = max(5.0, min(float(retry_after or 60.0), 900.0))


@dataclass
class AIRequest:
    task: "Task"
    inputs: dict
    lang: str
    system: str
    user: str
    schema: dict
    model: str = ""
    max_tokens: int = 1500
    temperature: float = 0.0
    timeout: int = 45


class Provider:
    """Subclass, set `name`, drop the file in app/ai/providers/ and expose `provider = YourClass`.

    available(cfg)  -> bool    can this provider be used right now (key / URL configured)?
    complete(req, cfg) -> (data: dict, model: str)   must return the *parsed* JSON object, or raise ProviderError.
    `local` (from config) decides whether data leaves the machine.
    """

    name = ""

    def available(self, cfg: dict) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def complete(self, req: AIRequest, cfg: dict) -> tuple[dict, str]:  # pragma: no cover - interface
        raise NotImplementedError

    def model_for(self, req: AIRequest, cfg: dict) -> str:
        models = cfg.get("models") or {}
        return models.get(req.task.name) or models.get("default") or ""

    # -- conversation with tools (the agent). A provider that can do it sets supports_chat and implements `chat`. -----------------------
    supports_chat = False

    def model_for_name(self, task_name: str, cfg: dict) -> str:
        models = cfg.get("models") or {}
        return models.get(task_name) or models.get("default") or ""

    def chat(self, messages: list[dict], tools: list[dict], system: str, cfg: dict, *, task: str = "agent", max_tokens: int = 2000,
             temperature: float = 0.2, timeout: int = 60) -> dict:  # pragma: no cover - interface
        """One model turn. `messages` use one neutral shape:
             {"role": "user", "content": str}
             {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args": dict}]}
             {"role": "tool", "tool_call_id": str, "name": str, "content": str(JSON)}
           `tools` are {"name", "description", "parameters": JSON schema}. Returns {"text": str, "tool_calls": [...], "model": str}."""
        raise NotImplementedError


class Task:
    """Subclass, set `name` and `schema`, drop the file in app/ai/tasks/ and expose `task = YourClass()`.

    prompt(inputs, lang)       -> (system, user)  exactly what will be sent to a model
    validate(data, inputs)     -> dict            check/repair the model's answer; raise ValueError to reject it
    fallback(inputs, lang)     -> dict            rule-based answer used when no model is available or allowed
    """

    name = ""
    description = ""
    schema: dict = {"type": "object"}

    def prompt(self, inputs: dict, lang: str) -> tuple[str, str]:  # pragma: no cover - interface
        raise NotImplementedError

    def validate(self, data: dict, inputs: dict) -> dict:
        return data

    def fallback(self, inputs: dict, lang: str) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class AIResult:
    data: dict
    provider: str            # which provider answered ("offline" for the rule-based fallback)
    model: str = ""
    external: bool = False   # did data leave the machine?
    fell_back: bool = False  # a better provider was configured but did not answer
    errors: list[str] = field(default_factory=list)
    ms: int = 0

    @property
    def is_model(self) -> bool:
        return self.provider != "offline"


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def extract_json(text: str) -> dict:
    """Tolerant JSON extraction: code fences, prose before/after, trailing commas."""
    text = _FENCE.sub("", (text or "").strip())
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            depth += (c == "{") - (c == "}")
            if depth == 0:
                chunk = re.sub(r",\s*([}\]])", r"\1", text[start : i + 1])
                try:
                    out = json.loads(chunk)
                    if isinstance(out, dict):
                        return out
                except ValueError:
                    pass
                break
        start = text.find("{", start + 1)
    raise ProviderError("the model did not return a JSON object")
