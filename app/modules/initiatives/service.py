"""Initiative progress and health."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.core import progress as P
from app.core.models import CheckIn
from app.core.services import cadence_days, thresholds
from app.modules.initiatives.models import Initiative


@dataclass
class InitView:
    obj: Initiative
    progress: float
    expected: float
    status: str
    done: int = 0
    total: int = 0
    next_milestone: object | None = None
    overdue: int = 0
    last_update: datetime | None = None
    stale: bool = False
    manual_status: str | None = None


def compute(org, today: date | None = None) -> dict[int, InitView]:
    today = today or date.today()
    th, cadence = thresholds(org), cadence_days(org)
    items = Initiative.query.filter_by(org_id=org.id).all()
    last_at, last_manual = {}, {}
    for c in CheckIn.query.filter_by(org_id=org.id, entity_type="initiative").order_by(CheckIn.created_at, CheckIn.id).all():
        last_at[c.entity_id] = c.created_at
        last_manual[c.entity_id] = c.status
    out = {}
    for it in items:
        ms = it.milestones
        if ms:
            prog = P.weighted_mean((1.0 if m.done else 0.0, m.weight or 1.0) for m in ms) or 0.0
        else:
            prog = it.manual_progress or 0.0
        exp = P.expected_progress(it.start_date, it.end_date, today)
        if it.state == "completed":
            status = "completed"
        elif it.state in ("on_hold", "cancelled"):
            status = it.state
        elif it.state == "planned":
            status = "not_started"
        else:
            status = P.derive_status(prog, exp, start=it.start_date, today=today, manual=last_manual.get(it.id), thresholds=th)
        open_ms = [m for m in ms if not m.done and m.due_date]
        nxt = min(open_ms, key=lambda m: m.due_date) if open_ms else None
        v = InitView(it, prog, exp, status, sum(m.done for m in ms), len(ms), nxt,
                     sum(1 for m in open_ms if m.due_date < today), last_at.get(it.id), manual_status=last_manual.get(it.id))
        v.stale = it.state == "active" and (P.is_stale(v.last_update, cadence) if v.last_update else False)
        out[it.id] = v
    return out
