"""Contracts of the AI layer. A provider talks to a model; a task knows what to ask and how to check the answer."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


class ProviderError(RuntimeError):
    """A provider could not answer (network, auth, bad status, unparsable reply)."""


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
