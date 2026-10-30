"""The drawing kit shared by every map family: a canvas of timed groups, and small helpers that return SVG text.

A family decides WHERE things go (families/*.py); this file only knows HOW to draw a ring, a pill, an icon, a wrapped label.
Everything is drawn with presentation attributes (no CSS needed), so the same SVG works in the page, in a downloaded file and in a printed report;
the page adds a little CSS that hides each group until its step and animates it in.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

from app.core.icons import _inner

FONT = "IBM Plex Sans Arabic, Noto Sans Arabic, Tahoma, Arial, sans-serif"
INK, BODY, MUTED, LINE, TINT, PRIMARY = "#162447", "#5B657E", "#8A93A8", "#D7DCEC", "#F3F5FF", "#5864FF"
LINE_COLORS = ("#5864FF", "#0E8F9B", "#7A4DD8", "#C23B8A", "#162447", "#5B657E")        # route colours: never the status colours (those only mean status)
STATUS = {                                   # status -> (icon, foreground, soft background): reserved, always shown with an icon and a word
    "on_track": ("circle-check", "#11713f", "#e2f5ea"), "completed": ("circle-check", "#11713f", "#e2f5ea"),
    "at_risk": ("alert-triangle", "#8a5a00", "#fff1cf"), "off_track": ("circle-x", "#b4231f", "#fde7e6"),
    "not_started": ("hourglass-empty", "#5B657E", "#eef0f6"), "on_hold": ("minus", "#5B657E", "#eef0f6"), "cancelled": ("minus", "#5B657E", "#eef0f6"),
}
TONE = {"good": ("#11713f", "#e2f5ea"), "bad": ("#b4231f", "#fde7e6"), "flat": ("#5B657E", "#eef0f6")}


def esc(s) -> str:
    return escape(str(s if s is not None else ""), {'"': "&quot;"})


def clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: max(1, n - 1)].rstrip() + "…"


def wrap(s: str, width: int, lines: int = 2) -> list[str]:
    """Greedy word wrap by character count (Arabic has no fixed width, so this is an estimate that errs on the short side); the last line is clipped."""
    words, out, cur = (s or "").split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = clip(out[-1] + "…", width)
    return [clip(x, width) for x in out] or [""]


def text(x, y, s, *, size=13, weight=400, fill=INK, anchor="middle", extra="") -> str:
    return f'<text x="{x:g}" y="{y:g}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" font-family="{FONT}" style="unicode-bidi:plaintext" {extra}>{esc(s)}</text>'


def lines_block(x, y, lines: list[str], *, size=13, weight=600, fill=INK, anchor="middle", lh=None) -> str:
    lh = lh or round(size * 1.45)
    return "".join(text(x, y + i * lh, ln, size=size, weight=weight, fill=fill, anchor=anchor) for i, ln in enumerate(lines))


def icon(name: str, x, y, size=16, color=INK, width=2) -> str:
    inner = _inner(name) or _inner("circle") or ""
    k = size / 24
    return (f'<g transform="translate({x - size / 2:g} {y - size / 2:g}) scale({k:g})" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round">{inner}</g>')


def ring(cx, cy, r, pct, color, *, track="#E3E7F5", width=4.5, draw=True) -> str:
    """A progress ring that starts at 12 o'clock and runs clockwise; `draw` makes the arc animate in when its group appears."""
    circ = 6.2832 * r
    done = max(0.0, min(1.0, pct / 100)) * circ
    arc = (f'<circle class="j-arc" cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
           f'stroke-dasharray="{done:.1f} {circ:.1f}" transform="rotate(-90 {cx:g} {cy:g})" style="--len:{done:.1f}px"/>') if pct > 0 else ""
    return f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="none" stroke="{track}" stroke-width="{width}"/>{arc}'


def pill(cx, cy, s, *, fg=INK, bg=TINT, size=11.5, weight=600, h=22, ic: str | None = None, anchor="middle", stroke: str | None = None) -> tuple[str, float]:
    """A rounded label. Returns (svg, width). `cx` is the centre, or the right edge when anchor == 'end'."""
    w = len(s) * size * 0.56 + 20 + (16 if ic else 0)
    x0 = cx - w / 2 if anchor == "middle" else (cx - w if anchor == "end" else cx)
    out = f'<rect x="{x0:g}" y="{cy - h / 2:g}" width="{w:g}" height="{h}" rx="{h / 2:g}" fill="{bg}"' + (f' stroke="{stroke}"' if stroke else "") + "/>"
    tx = x0 + w / 2 + (7 if ic else 0)
    if ic:
        out += icon(ic, x0 + w - 13, cy, 13, fg, 2.2)
    out += text(tx - (8 if ic else 0), cy + size * 0.35, s, size=size, weight=weight, fill=fg)
    return out, w


class Canvas:
    """Groups of SVG keyed by the step that reveals them. Order inside a step is the order of `add` (later = on top)."""

    def __init__(self, w: float, h: float):
        self.w, self.h = w, h
        self.items: list[tuple[int, str, str, float, float]] = []   # step, kind, svg, ox, oy

    def add(self, step: int, svg: str, *, kind: str = "pop", ox: float = 0, oy: float = 0) -> None:
        if svg:
            self.items.append((step, kind, svg, ox, oy))

    def render(self, *, title: str = "", steps_total: int = 1, standalone: bool = False, background: bool = True) -> str:
        parts = []
        for step, kind, svg, ox, oy in self.items:
            style = f' style="--ox:{ox:g}px;--oy:{oy:g}px"' if kind == "pop" else ""
            parts.append(f'<g class="j j-{kind}" data-s="{step}"{style}>{svg}</g>')
        bg = (f'<rect width="100%" height="100%" fill="#fff"/><rect width="100%" height="100%" fill="url(#dots)"/>') if background else ""
        defs = (f'<defs><pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="#DDE1F0"/></pattern></defs>')
        ns = ' xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"' if standalone else ""
        head = '<?xml version="1.0" encoding="UTF-8"?>' if standalone else ""
        return (f'{head}<svg{ns} viewBox="0 0 {self.w:g} {self.h:g}" width="{self.w:g}" height="{self.h:g}" role="img" aria-label="{esc(title)}" '
                f'font-family="{FONT}" direction="ltr" style="direction:ltr" data-steps="{steps_total}">{defs}{bg}{"".join(parts)}</svg>')
