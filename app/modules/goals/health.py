"""Goal health: where each key result is, where it is expected to END, and whether that is on track.

Two sources, never blended silently:
  * data   — a key result measured by an uploaded series is projected from what comparable periods did in the organization's own history
             (a RANGE: 25th..75th percentile of the change over the remaining time, applied to the latest value). The status says how that range sits
             against the target.
  * manual — otherwise the status comes from elapsed time vs progress (app/core/progress.py), as before.
A committed goal is on track when the likely end reaches ~the target; an aspirational one when it reaches ~70% (the Google/WhatMatters convention:
an aspirational objective scoring 0.7 is a success).
"""
from __future__ import annotations

from datetime import date

from flask import current_app

from app.core import progress as P

HIT = {"committed": 0.95, "aspirational": 0.70}
STALE_DAYS = 62


def projected_status(kind: str | None, start: float, target: float, proj: dict, commitment: str = "committed") -> str:
    """on_track | at_risk | off_track from the projected RANGE: on track when the middle of it reaches the bar, at risk when only its top does."""
    bar = HIT.get(commitment, 0.95)
    prog = lambda v: P.typed_kr_progress(kind, start, target, v)
    vals = sorted(prog(proj[k]) for k in ("low", "mid", "high"))
    best, mid = vals[-1], prog(proj["mid"])
    if mid >= bar:
        return "on_track"
    if best >= bar:
        return "at_risk"
    return "off_track"


def range_bar(start: float, target: float, current: float, proj: dict | None) -> dict:
    """Positions (0..100) of the markers on one axis: the track from start to target, today's value, and the projected range."""
    pts = [start, target, current] + ([proj["low"], proj["mid"], proj["high"]] if proj else [])
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    pos = lambda v: round(100 * (v - lo) / span, 1)
    out = {"start": pos(start), "target": pos(target), "current": pos(current)}
    if proj:
        a, b = sorted((pos(proj["low"]), pos(proj["high"])))
        out.update(low=a, high=b, mid=pos(proj["mid"]))
    return out


def kr_data(kr, end_date):
    """What the data module knows about this key result (None if it is off, or the key result is not measured by a series)."""
    r = current_app.extensions["modules"].query("kr.data", kr, end_date)
    return r[0] if r else None


def row(view, kv, today: date, *, start, end) -> dict:
    """One key result of the health table. `view` is the ObjView, `kv` its KRView."""
    kr, o = kv.kr, view.obj
    data = kr_data(kr, end) if kr.kr_type not in ("binary", "milestone") else None
    proj = data.get("projected") if data else None
    source, status = "manual", kv.status
    if kv.progress >= 0.999:
        status = "completed"
    elif data and proj:
        source, status = "data", projected_status(kr.kr_type, kr.start_value, kr.target_value, proj, o.commitment)
    elif data:
        source = "data_short"
    stale = bool(data and data["age_days"] > STALE_DAYS)
    return {"kr": kr, "obj": o, "progress": kv.progress, "status": status, "source": source, "data": data, "projected": proj,
            "bar": range_bar(kr.start_value, kr.target_value, kr.current_value, proj) if kr.kr_type in ("increase", "decrease") or proj else None,
            "stale": stale, "expected": view.expected, "commitment": o.commitment}


def build(views, org, today: date | None = None, cycle_id: int | None = None) -> dict:
    from app.modules.goals.service import _dates

    today = today or date.today()
    groups, counts = [], {"on_track": 0, "at_risk": 0, "off_track": 0, "completed": 0, "not_started": 0}
    for v in sorted(views.values(), key=lambda v: v.obj.id):
        o = v.obj
        if o.state != "active" or (cycle_id and o.cycle_id != cycle_id) or not v.krs:
            continue
        start, end = _dates(o)
        rows = [row(v, kv, today, start=start, end=end) for kv in v.krs]
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        groups.append({"view": v, "rows": rows})
    return {"groups": groups, "counts": counts, "total": sum(counts.values())}
