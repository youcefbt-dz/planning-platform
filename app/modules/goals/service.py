"""Goals computations: progress, expected progress and status for objectives, key results, indicators.

One pass per organization (a few hundred rows at most for the target segment), so the views never
run N+1 queries. The rules themselves live in app/core/progress.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func

from app.core import progress as P
from app.core.models import CheckIn, Link
from app.extensions import db
from app.core.services import cadence_days, thresholds
from app.modules.goals.models import Indicator, IndicatorValue, KeyResult, Objective


@dataclass
class KRView:
    kr: KeyResult
    progress: float
    status: str
    last_update: datetime | None = None


@dataclass
class ObjView:
    obj: Objective
    progress: float = 0.0
    expected: float = 0.0
    status: str = "not_started"
    krs: list[KRView] = field(default_factory=list)
    children: list["ObjView"] = field(default_factory=list)
    last_update: datetime | None = None
    stale: bool = False
    manual_status: str | None = None


def _dates(o: Objective):
    s = o.start_date or (o.cycle.start_date if o.cycle else None)
    e = o.end_date or (o.cycle.end_date if o.cycle else None)
    return s, e


def compute_objectives(org, today: date | None = None) -> dict[int, ObjView]:
    today = today or date.today()
    th, cadence = thresholds(org), cadence_days(org)
    objs = Objective.query.filter_by(org_id=org.id).all()
    krs = KeyResult.query.filter_by(org_id=org.id).all()

    # latest check-in per entity (any author) and latest manual status per objective
    last_at: dict[tuple, datetime] = {}
    last_manual: dict[int, str] = {}
    rows = (
        CheckIn.query.filter(CheckIn.org_id == org.id, CheckIn.entity_type.in_(("objective", "key_result")))
        .order_by(CheckIn.created_at.asc(), CheckIn.id.asc())
        .all()
    )
    for c in rows:  # ascending: the last write wins
        last_at[(c.entity_type, c.entity_id)] = c.created_at
        if c.entity_type == "objective":
            last_manual[c.entity_id] = c.status

    views = {o.id: ObjView(o) for o in objs}
    kr_by_obj: dict[int, list[KeyResult]] = {}
    for k in krs:
        kr_by_obj.setdefault(k.objective_id, []).append(k)
    for o in objs:
        pv = views[o.id]
        if o.parent_id in views:
            views[o.parent_id].children.append(pv)

    done: set[int] = set()
    visiting: set[int] = set()

    def calc(v: ObjView) -> None:
        if v.obj.id in done or v.obj.id in visiting:  # cycle guard
            return
        visiting.add(v.obj.id)
        o = v.obj
        start, end = _dates(o)
        v.expected = P.expected_progress(start, end, today)
        for k in sorted(kr_by_obj.get(o.id, []), key=lambda k: (k.position or 0, k.id)):
            kp = P.typed_kr_progress(k.kr_type, k.start_value, k.target_value, k.current_value)
            ks = P.derive_status(kp, v.expected, start=start, today=today, state=o.state, thresholds=th)
            v.krs.append(KRView(k, kp, ks, last_at.get(("key_result", k.id))))
        for c in v.children:
            calc(c)
        own = P.weighted_mean((k.progress, k.kr.weight) for k in v.krs)
        kids = P.weighted_mean((c.progress, c.obj.weight) for c in v.children)
        v.progress = P.combine_drivers(own, kids, o.progress_driver)
        stamps = [last_at.get(("objective", o.id))] + [k.last_update for k in v.krs]
        stamps = [s for s in stamps if s]
        v.last_update = max(stamps) if stamps else None
        # a manual status holds only until the progress underneath it is updated again
        own_stamp = last_at.get(("objective", o.id))
        newer_kr = any(k.last_update and own_stamp and k.last_update > own_stamp for k in v.krs)
        v.manual_status = last_manual.get(o.id) if own_stamp and not newer_kr else None
        v.status = P.derive_status(v.progress, v.expected, start=start, today=today, state=o.state, manual=v.manual_status, thresholds=th)
        v.stale = v.status in P.LIVE_STATUSES and (
            P.is_stale(v.last_update, cadence) if v.last_update else (start is not None and (today - start).days > cadence)
        )
        visiting.discard(o.id)
        done.add(o.id)

    for v in views.values():
        calc(v)
    return views


def roots(views: dict[int, ObjView], cycle_id: int | None = None):
    """Top-level objectives (no parent in the same dataset), optionally limited to one cycle."""
    out = [v for v in views.values() if v.obj.parent_id not in views]
    if cycle_id:
        out = [v for v in out if v.obj.cycle_id == cycle_id]
    return sorted(out, key=lambda v: v.obj.id)


def summary(views, subset=None) -> dict:
    vs = list(subset if subset is not None else views.values())
    counts = P.status_counts([v.status for v in vs])
    avg = P.weighted_mean((v.progress, 1.0) for v in vs)
    return {"total": len(vs), "counts": counts, "avg": avg or 0.0}


# -- indicators ----------------------------------------------------------------
@dataclass
class IndView:
    ind: Indicator
    latest: float | None
    latest_date: date | None
    attainment: float | None
    status: str
    series: list[tuple[date, float]]
    previous: float | None = None

    @property
    def delta(self):
        if self.latest is None or self.previous is None:
            return None
        return self.latest - self.previous

    @property
    def delta_good(self):
        d = self.delta
        if d is None or d == 0:
            return None
        return (d > 0) == (self.ind.direction == "higher_better")


def compute_indicators(org) -> list[IndView]:
    inds = Indicator.query.filter_by(org_id=org.id).order_by(Indicator.id).all()
    by_ind: dict[int, list] = {}
    ids = [i.id for i in inds]
    if ids:
        for v in IndicatorValue.query.filter(IndicatorValue.indicator_id.in_(ids)).order_by(IndicatorValue.period_date).all():
            by_ind.setdefault(v.indicator_id, []).append(v)
    out = []
    for i in inds:
        vals = by_ind.get(i.id, [])
        latest = vals[-1] if vals else None
        prev = vals[-2].value if len(vals) > 1 else None
        att = P.indicator_attainment(latest.value if latest else None, i.target_value, i.direction)
        out.append(IndView(i, latest.value if latest else None, latest.period_date if latest else None, att,
                           P.indicator_status(att), [(v.period_date, v.value) for v in vals], prev))
    return out


# -- indicators linked to the data module -------------------------------------------------------------
def indicator_series_id(org_id: int, indicator_id: int) -> int | None:
    """Return the data series currently measuring this indicator, if any."""
    link = Link.query.filter_by(org_id=org_id, source_type="indicator", source_id=indicator_id,
                                target_type="series", kind="measured_by").first()
    return link.target_id if link else None


def _indicator_period(d: date, frequency: str) -> date:
    """Normalize a source observation to the indicator's reporting period."""
    if frequency == "weekly":
        return d - timedelta(days=d.weekday())
    if frequency == "quarterly":
        return date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)
    if frequency == "yearly":
        return date(d.year, 1, 1)
    return date(d.year, d.month, 1)


def _sync_indicator_values(ind: Indicator, source, points: list[tuple[date, float]]) -> None:
    """Replace only values imported from this data integration; leave unrelated manual history intact."""
    marker = f"@data:{source.id}"
    old = (IndicatorValue.query.filter_by(indicator_id=ind.id)
           .filter(IndicatorValue.note.like("@data:%")).all())
    for row in old:
        db.session.delete(row)
    db.session.flush()

    buckets: dict[date, list[float]] = {}
    for period, value in points:
        key = _indicator_period(period, ind.frequency)
        buckets.setdefault(key, []).append(float(value))

    for period, values in sorted(buckets.items()):
        if source.aggregation == "sum":
            value = sum(values)
        elif source.aggregation == "avg":
            value = sum(values) / len(values)
        else:
            value = values[-1]
        row = IndicatorValue.query.filter_by(indicator_id=ind.id, period_date=period).first()
        if row is None:
            db.session.add(IndicatorValue(indicator_id=ind.id, period_date=period, value=value, note=marker))
        else:
            # A linked source is authoritative for its reporting periods.
            row.value, row.note = value, marker


def remove_series_data(series, **_) -> None:
    """Clean indicator links and imported values when a source series is deleted."""
    for source in series:
        links = Link.query.filter_by(org_id=source.org_id, source_type="indicator", target_type="series",
                                     target_id=source.id, kind="measured_by").all()
        for link in links:
            ind = db.session.get(Indicator, link.source_id)
            if ind is not None and ind.org_id == source.org_id:
                IndicatorValue.query.filter_by(indicator_id=ind.id, note=f"@data:{source.id}").delete(synchronize_session=False)
            db.session.delete(link)
    db.session.flush()


# -- data -> key results (the "series.updated" hook) ------------------------------------------------------------------
def sync_from_series(series, user_id=None, **_):
    """New data was confirmed: bring every key result measured by one of these series up to date and leave a check-in that says so.
    Uses only the core Link table, so this module never imports the data module's models."""
    from app.core.models import Link, Organization, User
    from app.core.services import add_checkin
    from app.extensions import db

    user = db.session.get(User, user_id) if user_id else None
    touched: dict[int, int] = {}                                   # objective id -> org id
    for s in series:
        pts = s.pairs()

        # KPIs use the same cross-module relation as key results. Their history is
        # rebuilt from the confirmed source, so revised or removed periods cannot linger.
        indicator_links = Link.query.filter_by(org_id=s.org_id, target_type="series", target_id=s.id,
                                               kind="measured_by", source_type="indicator").all()
        for link in indicator_links:
            ind = db.session.get(Indicator, link.source_id)
            if ind is not None and ind.org_id == s.org_id:
                _sync_indicator_values(ind, s, pts)

        if not pts:
            continue
        links = Link.query.filter_by(org_id=s.org_id, target_type="series", target_id=s.id, kind="measured_by", source_type="key_result").all()
        for l in links:
            kr = db.session.get(KeyResult, l.source_id)
            if kr is None or kr.org_id != s.org_id:
                continue
            o = kr.objective
            if kr.measure == "sum":
                start, end = _dates(o)
                vals = [v for d, v in pts if (not start or d >= start) and (not end or d <= end)]
                value = sum(vals) if vals else None
            else:
                value = pts[-1][1]
            if value is None:
                continue
            if abs(kr.current_value - value) < 1e-9 and kr.data_period == pts[-1][0]:
                continue
            kr.current_value, kr.data_period = value, pts[-1][0]
            add_checkin("key_result", kr.id, value=value, progress=P.typed_kr_progress(kr.kr_type, kr.start_value, kr.target_value, value),
                        comment="@data", org=db.session.get(Organization, s.org_id), user=user)
            touched[o.id] = s.org_id
    db.session.flush()
    for oid, org_id in touched.items():                             # keep the objective's progress line continuous
        org = db.session.get(Organization, org_id)
        v = compute_objectives(org).get(oid)
        if v:
            add_checkin("objective", oid, progress=v.progress, comment="", org=org, user=user)
