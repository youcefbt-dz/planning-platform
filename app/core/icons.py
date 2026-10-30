"""Inline Tabler icons (MIT). Drop any Tabler outline SVG into app/static/icons/ and use its name."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from markupsafe import Markup

ICON_DIR = Path(__file__).resolve().parents[1] / "static" / "icons"
_BODY = re.compile(r"<svg[^>]*>(.*)</svg>", re.S)
_NOOP_PATH = re.compile(r'<path stroke="none"[^>]*/>')


@lru_cache(maxsize=None)
def _inner(name: str) -> str | None:
    f = ICON_DIR / f"{name}.svg"
    if not f.is_file():
        return None
    m = _BODY.search(f.read_text(encoding="utf-8"))
    if not m:
        return None
    return _NOOP_PATH.sub("", m.group(1)).strip()


def icon(name: str, size: int = 16, cls: str = "", flip: bool = False, title: str | None = None) -> Markup:
    """Render an icon. flip=True mirrors it in RTL (arrows, chevrons)."""
    inner = _inner(name) or _inner("circle")
    classes = f"icon icon-{name}" + (" icon-flip" if flip else "") + (f" {cls}" if cls else "")
    aria = f'role="img" aria-label="{title}"' if title else 'aria-hidden="true"'
    return Markup(
        f'<svg class="{classes}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" {aria}>{inner}</svg>'
    )
