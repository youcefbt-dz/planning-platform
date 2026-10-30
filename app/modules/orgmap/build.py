"""The map as plain data (no HTML): used by the page, the SVG export and the report."""
from __future__ import annotations

from datetime import date

from flask import current_app

from app.core.models import Cycle
from app.core.profile import profile as get_profile
from app.core.services import current_cycle
from app.modules.goals import health as H
from app.modules.goals.service import _dates, compute_objectives

BAD = ("off_track", "at_risk")


def build(org, today: date | None = None) -> dict:
    today = today or date.today()
    views = compute_objectives(org)
    cur = current_cycle(org)
    scope = None
    if cur:
        scope = {cur.id} | {c.id for c in Cycle.query.filter_by(org_id=org.id).all() if c.parent_id == cur.id or c.id == cur.parent_id}
    mods = current_app.extensions["modules"]
    goals, counts = [], {"on_track": 0, "at_risk": 0, "off_track": 0, "completed": 0, "not_started": 0}
    for v in sorted(views.values(), key=lambda v: v.obj.id):
        o = v.obj
        if o.state != "active" or (scope and o.cycle_id not in scope):
            continue
        _, end = _dates(o)
        krs = []
        for kv in v.krs:
            k = kv.kr
            row = H.row(v, kv, today, start=_dates(o)[0], end=end) if end else None
            status = row["status"] if row else kv.status
            counts[status] = counts.get(status, 0) + 1
            br = mods.query("kr.branches", k) if row and row["data"] else []
            parts = []
            if br:
                for p in br[0]["rows"]:
                    parts.append({"name": p["name"], "text": p["text"], "tone": p["tone"], "delta": p["delta"]})
            gap = None
            if row and row["projected"]:
                gap = k.target_value - row["projected"]["mid"]
            krs.append({"kr": k, "status": status, "row": row, "gap": gap, "branches": parts, "progress": kv.progress,
                        "levers": [{"title": f.title, "effect": f.effect, "status": f.status, "certainty": f.certainty} for f in k.factors]})
        goals.append({"obj": o, "view": v, "status": v.status, "krs": krs, "attention": any(x["status"] in BAD for x in krs) or v.status in BAD})
    prof = get_profile(org)
    return {"org": org, "profile": prof, "goals": goals, "counts": counts, "total": sum(counts.values()), "today": today}
