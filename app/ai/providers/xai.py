"""xAI Grok (cloud). The xAI API speaks the OpenAI wire format, so this is the generic provider with its own name,
its own key (XAI_API_KEY) and its own model (XAI_MODEL). Data leaves the machine, so config marks it `local: false`.
"""
from __future__ import annotations

from app.ai.providers.openai_compat import OpenAICompatProvider


class XAIProvider(OpenAICompatProvider):
    name = "xai"


provider = XAIProvider()
