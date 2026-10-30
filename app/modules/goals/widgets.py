"""Overview widgets contributed by the goals module."""
from __future__ import annotations

import math
from datetime import date

from app.core.services import current_cycle
from app.modules.goals.service import compute_indicators, compute_objectives, summary


def _scope(org):
    cycle = current_cycle(org)
    views = compute_objectives(org)
    return cycle, views


def gauge(progress: float, time: float | None) -> dict:
    """Two concentric orbits for the overview: the outer is the share of the cycle that has passed, the inner is the average progress.
    Everything the SVG needs (arc lengths and the satellite at each arc's tip) is computed here, in a 240x240 box."""
    def orbit(r, share):
        share = max(0.0, min(1.0, share or 0.0))
        c = 2 * math.pi * r
        a = -math.pi / 2 + share * 2 * math.pi
        return {"r": r, "len": round(share * c, 1), "circ": round(c, 1), "x": round(120 + r * math.cos(a), 1), "y": round(120 + r * math.sin(a), 1), "pct": round(share * 100)}
    return {"outer": orbit(104, time) if time is not None else None, "inner": orbit(76, progress)}


def summary_loader(org) -> dict:
    cycle, views = _scope(org)
    # objectives of the current cycle and its sub-cycles (a quarter inside the year, …)
    ids = {cycle.id, cycle.parent_id} - {None} if cycle else set()
    pool = [v for v in views.values() if v.obj.cycle_id in ids] if cycle else list(views.values())
    top = [v for v in pool if v.obj.parent_id is None]
    stats = summary(views, pool)
    time = None
    if cycle and cycle.start_date and cycle.end_date and cycle.end_date > cycle.start_date:
        time = max(0.0, min(1.0, (date.today() - cycle.start_date).days / (cycle.end_date - cycle.start_date).days))
    exp = sum(v.expected for v in pool) / len(pool) if pool else 0.0
    left = max(0, (cycle.end_date - date.today()).days) if cycle and cycle.end_date else None
    return {"stats": stats, "cycle": cycle, "top": sorted(top, key=lambda v: v.obj.id), "gauge": gauge(stats["avg"], time), "expected": exp, "time": time, "days_left": left,
            "gap": round((stats["avg"] - exp) * 100)}


def attention_loader(org) -> dict:
    _, views = _scope(org)
    rank = {"off_track": 0, "at_risk": 1}
    items = [v for v in views.values() if v.status in rank or v.stale]
    items.sort(key=lambda v: (rank.get(v.status, 2), -v.progress))
    return {"items": items[:6], "total": len(items)}


def indicators_loader(org) -> dict:
    items = compute_indicators(org)
    return {"items": items[:6], "total": len(items)}
