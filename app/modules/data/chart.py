"""Geometry of the reality-check chart (server side; the template only draws).

One axis. History as a line; from today to the end date: the range of what the history shows was achievable (a soft band,
low..high), the typical path, the path the target demands (dashed), and the target itself as a marker.
"""
from __future__ import annotations

from datetime import date

from app.core.charts import nice_ticks

LEVEL_TONE = {"realistic": "on_track", "ambitious": "completed", "stretch": "at_risk", "unrealistic": "off_track", "insufficient": "not_started"}
LEVEL_ICON = {"realistic": "circle-check", "ambitious": "trending-up", "stretch": "alert-triangle", "unrealistic": "circle-x", "insufficient": "help-circle"}


def reality_chart(points: list[tuple[date, float]], verdict: dict, *, start: float, target: float, as_of: date, end_date: date,
                  w: int = 640, h: int = 260, pad_l: int = 48, pad_r: int = 16, pad_t: int = 14, pad_b: int = 28) -> dict:
    if not points:
        return {"empty": True, "w": w, "h": h}
    rng = verdict.get("range") or {}
    xs0 = min(points[0][0], as_of)
    x1 = max(end_date, as_of)
    span = max(1, (x1 - xs0).days)
    vals = [v for _, v in points] + [start, target] + [rng[k] for k in ("low", "typical", "high") if rng.get(k) is not None]
    ticks = nice_ticks(min(vals), max(vals))
    lo, hi = ticks[0], ticks[-1]
    pad_l = max(pad_l, 16 + 7 * max(len(f"{t:,.0f}") for t in ticks))      # room for long numbers such as 10,000,000
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b

    def X(d: date) -> float:
        return round(pad_l + (d - xs0).days / span * iw, 1)

    def Y(v: float) -> float:
        return round(pad_t + ih - (v - lo) / (hi - lo) * ih, 1)

    hist = [{"x": X(d), "y": Y(v), "date": d, "value": v} for d, v in points]
    out = {"empty": False, "w": w, "h": h, "left": pad_l, "right": w - pad_r, "baseline": pad_t + ih, "top": pad_t,
           "hist_path": " ".join(("M" if i == 0 else "L") + f"{p['x']} {p['y']}" for i, p in enumerate(hist)),
           "dots": hist if len(hist) <= 60 else hist[-60:],
           "y_ticks": [{"y": Y(t), "v": t} for t in ticks],
           "now_x": X(as_of), "end_x": X(end_date), "start": {"x": X(as_of), "y": Y(start)}, "target": {"x": X(end_date), "y": Y(target), "v": target}}
    # x ticks: first, last history point, and the end date
    out["x_ticks"] = [{"x": X(points[0][0]), "date": points[0][0], "anchor": "start"}, {"x": X(end_date), "date": end_date, "anchor": "end"}]
    out["required_path"] = f"M{X(as_of)} {Y(start)} L{X(end_date)} {Y(target)}"
    if verdict.get("level") != "insufficient" and rng.get("low") is not None:
        ex, sx, sy = X(end_date), X(as_of), Y(start)
        ys = sorted([Y(rng["low"]), Y(rng["high"])])
        out["cone"] = f"M{sx} {sy} L{ex} {ys[0]} L{ex} {ys[1]} Z"
        out["typical_path"] = f"M{sx} {sy} L{ex} {Y(rng['typical'])}"
        out["cone_ends"] = {"low": Y(rng["low"]), "high": Y(rng["high"])}
    return out


def quality_chart(raw, after, flagged=(), w: int = 320, h: int = 84) -> dict:
    """A small before/after picture of one series: the line as uploaded (grey) and as it will be used (blue), with the flagged periods marked."""
    from datetime import date as _d

    both = [p for p in (raw or [])] + [p for p in (after or [])]
    if len(both) < 2:
        return {}
    xs = sorted({d for d, _ in both})
    ys = [v for _, v in both]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    pad = 6
    pos = {d: pad + (w - 2 * pad) * (i / max(1, len(xs) - 1)) for i, d in enumerate(xs)}
    yy = lambda v: round(h - pad - (h - 2 * pad) * (v - lo) / span, 1)

    def path(pts):
        pts = sorted(pts)
        segs, pen = [], False
        for d, v in pts:                       # a missing period breaks the line instead of being bridged
            segs.append(f"{'L' if pen else 'M'}{pos[d]:.1f},{yy(v)}")
            pen = True
        return " ".join(segs)

    rawd, aftd = dict(raw or []), dict(after or [])
    marks = [{"x": round(pos[_d.fromisoformat(f)], 1), "y": yy(rawd[_d.fromisoformat(f)]) if _d.fromisoformat(f) in rawd else h - pad} for f in flagged if _d.fromisoformat(f) in pos]
    return {"w": w, "h": h, "raw": path(raw or []), "after": path(after or []) if aftd != rawd else "", "marks": marks}
