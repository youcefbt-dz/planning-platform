from __future__ import annotations

from app.core import progress as P
from app.modules.initiatives.service import compute


def health_loader(org) -> dict:
    views = compute(org)
    live = [v for v in views.values() if v.obj.state in ("active", "planned", "on_hold")]
    counts = P.status_counts([v.status for v in views.values()])
    soon = sorted((v for v in views.values() if v.next_milestone and v.obj.state == "active"), key=lambda v: v.next_milestone.due_date)[:5]
    return {"total": len(views), "live": len(live), "counts": counts, "soon": soon}
