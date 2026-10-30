"""Checks every AI task applies to what a model returns. A fluent invented figure is worse than a plain correct sentence,
so an answer that quotes a number it was not given is rejected and the task's rule-based fallback is used instead."""
from __future__ import annotations

import re

from app.ai import privacy

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def numbers_in(text: str) -> list[float]:
    out = []
    for m in _NUM.findall((text or "").translate(_AR_DIGITS)):
        try:
            out.append(float(m.replace(",", ".")))
        except ValueError:
            pass
    return out


def allowed_numbers(facts) -> list[float]:
    ok = set()
    for f in facts or []:
        if f is None:
            continue
        for scale in (1, 100):
            v = float(f) * scale
            for d in (0, 1, 2):
                ok.add(round(v, d))
            ok.add(round(abs(v), 0))
            ok.add(round(abs(v), 1))
    return sorted(ok)


def check_numbers(text: str, facts) -> bool:
    ok = allowed_numbers(facts)
    for n in numbers_in(text):
        if 1990 <= n <= 2100 or (n.is_integer() and n <= 12):   # years, months and small counts are always fine
            continue
        if not any(abs(n - a) <= max(0.051, abs(a) * 0.005) for a in ok):
            return False
    return True


def clip_list(v, n, width):
    return [privacy.clip(x, width) for x in v if isinstance(x, str) and x.strip()][:n] if isinstance(v, list) else []
