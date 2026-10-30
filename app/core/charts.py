"""Server-rendered chart geometry. Templates draw the SVG; no chart library, no client math.

Rules followed (see docs/DESIGN_SYSTEM.md, "Data visualisation"):
  one axis, thin 2px lines, ≥8px markers, recessive grid, the target as a reference line,
  hover layer = tiny JS reading data-* attributes, and every chart has a table twin.
"""
from __future__ import annotations

import math
from datetime import date


def nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi == lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    start = math.floor(lo / step) * step
    end = math.ceil(hi / step) * step
    out, v = [], start
    while v <= end + step * 1e-6:
        out.append(round(v, 10))
        v += step
    return out


def line_chart(points: list[tuple[date, float]], target: float | None = None, *, w: int = 640, h: int = 220,
               pad_l: int = 44, pad_r: int = 12, pad_t: int = 12, pad_b: int = 26) -> dict:
    """points sorted by date. Returns coordinates ready for <svg viewBox="0 0 w h">."""
    if not points:
        return {"empty": True, "w": w, "h": h}
    vals = [v for _, v in points] + ([target] if target is not None else [])
    ticks = nice_ticks(min(vals), max(vals))
    lo, hi = ticks[0], ticks[-1]
    pad_l = max(pad_l, 16 + 7 * max(len(f"{t:,.0f}") for t in ticks))
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b

    def y(v):
        return pad_t + ih - (v - lo) / (hi - lo) * ih

    n = len(points)

    def x(i):
        return pad_l + (iw / 2 if n == 1 else i * iw / (n - 1))

    dots = [{"x": round(x(i), 1), "y": round(y(v), 1), "date": d, "value": v} for i, (d, v) in enumerate(points)]
    path = " ".join(("M" if i == 0 else "L") + f"{p['x']} {p['y']}" for i, p in enumerate(dots))
    area = path + f" L{dots[-1]['x']} {pad_t + ih} L{dots[0]['x']} {pad_t + ih} Z"
    step = max(1, math.ceil(n / 6))
    return {
        "empty": False, "w": w, "h": h, "path": path, "area": area, "dots": dots,
        "target_y": round(y(target), 1) if target is not None else None,
        "y_ticks": [{"y": round(y(t), 1), "v": t} for t in ticks],
        "x_ticks": [dots[i] for i in range(0, n, step)],
        "left": pad_l, "right": w - pad_r, "baseline": pad_t + ih,
    }


def sparkline(values: list[float], w: int = 96, h: int = 28) -> str:
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pts = [(i * (w - 2) / (len(values) - 1) + 1, h - 3 - (v - lo) / span * (h - 6)) for i, v in enumerate(values)]
    return " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))
