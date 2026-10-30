"""Groq (cloud, fast inference, has a free tier). OpenAI wire format: the generic provider with its own name, key
(GROQ_API_KEY) and model (GROQ_MODEL). Data leaves the machine, so config marks it `local: false` and consent applies.
"""
from __future__ import annotations

from app.ai.providers.openai_compat import OpenAICompatProvider


class GroqProvider(OpenAICompatProvider):
    name = "groq"


provider = GroqProvider()
