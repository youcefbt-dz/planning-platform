"""What may be sent to a model: headers, a few sample rows, short cells — never the whole file."""
from __future__ import annotations

from flask import current_app


def limits() -> dict:
    return current_app.extensions["ai"].privacy


def clip(value, max_chars: int | None = None) -> str:
    n = max_chars or limits()["max_cell_chars"]
    s = "" if value is None else str(value).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def sample_rows(rows: list[list], n: int | None = None) -> list[list[str]]:
    """First, middle and last rows (not just the top) so the model sees the data's real range, each cell clipped."""
    n = n or limits()["sample_rows"]
    if len(rows) <= n:
        pick = rows
    else:
        head = max(1, n // 2)
        tail = max(1, n // 4)
        mid = n - head - tail
        step = max(1, (len(rows) - head - tail) // (mid + 1))
        pick = rows[:head] + [rows[head + step * (i + 1) - 1] for i in range(mid)] + rows[-tail:]
    return [[clip(c) for c in r] for r in pick]
