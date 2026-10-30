"""Rule-based provider: no key, no network, nothing leaves the machine. Always available, always last in the chain.

It does not "think": it asks the task for its own deterministic `fallback`. Every task must provide one, so
every AI feature keeps working (with plainer answers) when no model is configured, allowed, or reachable.
"""
from __future__ import annotations

from app.ai.base import AIRequest, Provider


class OfflineProvider(Provider):
    name = "offline"

    def available(self, cfg):
        return True

    def complete(self, req: AIRequest, cfg):
        return req.task.fallback(req.inputs, req.lang), "rules"


provider = OfflineProvider()
