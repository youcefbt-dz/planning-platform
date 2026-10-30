"""AI layer. Use from views:   from app import ai;  result = ai.run("map_columns", {...})

Everything pluggable lives in sub-folders — providers/ and tasks/ are auto-discovered, configuration is config/ai.yaml.
See docs/AI.md.
"""
from __future__ import annotations

from flask import current_app, g
from flask_login import current_user

from app.ai.base import AIResult, Provider, ProviderError, Task  # noqa: F401  (public API)


def get_hub():
    return current_app.extensions["ai"]


def org_consent(org) -> bool:
    return bool(org and (org.settings or {}).get("ai_consent"))


def run(task: str, inputs: dict, lang: str | None = None) -> AIResult:
    """Run a task for the current request: language, organization, consent and read-only mode are taken from `g`."""
    org = g.get("org")
    return get_hub().run(
        task, inputs, lang=lang or g.get("lang", "ar"), org=org, user=current_user if current_user.is_authenticated else None,
        consent=org_consent(org), read_only=bool(g.get("read_only")),
    )
