"""How the data module plugs into goals WITHOUT goals importing it:
  * hook "key_result.saved"  — links the key result to the series chosen in the form (core Link kind "measured_by")
  * template functions for goal pages (present only while this module is enabled):
        data_series_options()        -> series the organization can measure a key result with
        data_kr_check(kr, end_date)  -> the reality verdict of a key result that is linked to a series, or None
"""
from __future__ import annotations

from datetime import date

from flask import current_app, g, url_for

from app.modules.data import bp, reality, service
from app.modules.data.models import Series
from app.extensions import db


def key_result_saved(kr, form, index=None):
    if index is not None:
        vals = form.getlist("kr_series")
        if index >= len(vals):
            return
        raw = vals[index]
    else:
        if "series_id" not in form:
            return                                  # the form had no series field: leave the link as it is
        raw = form.get("series_id")
    try:
        sid = int(raw) if raw else None
    except ValueError:
        sid = None
    service.set_kr_series(kr.org_id, kr.id, sid)
    s = db.session.get(Series, sid) if sid else None
    if s is not None and s.org_id == kr.org_id:
        db.session.flush()
        current_app.extensions["modules"].hook("series.updated", series=[s], user_id=None)     # bring the key result up to the latest data at once


def kr_data(kr, end_date=None):
    """Everything the data module knows about a key result that is measured by a series (None when it is not): the reality verdict and the range history
    supports, where it is likely to end, and how fresh the data is. Goals ask for it through registry.query("kr.data", kr, end_date)."""
    from app.modules.data import realism

    sid = service.linked_series_id(kr.org_id, kr.id)
    s = db.session.get(Series, sid) if sid else None
    if s is None:
        return None
    pts = s.pairs()
    if not pts:
        return None
    today = date.today()
    last = pts[-1][0]
    period_end = date(last.year + (last.month - 1 + s.period_months) // 12, (last.month - 1 + s.period_months) % 12 + 1, 1)
    out = {"series": s, "unit": s.unit, "direction": s.direction, "latest": pts[-1][1], "latest_period": last, "age_days": max(0, (today - period_end).days),
           "periods": len(pts), "level": None, "range": None, "supported": None, "projected": None}
    if end_date and end_date > today:
        rel = False if (s.unit or "").strip() == "%" else None
        v = realism.assess(pts, start=kr.current_value, target=kr.target_value, as_of=today, end_date=end_date, direction=s.direction,
                           period_months=s.period_months, relative=rel)
        out["level"] = v["level"]
        out["required"] = v["required"]
        out["notes"] = v["notes"]
        if v.get("range"):
            out["range"] = v["range"]
            out["supported"] = v["range"]["high"]
        out["projected"] = realism.project(pts, as_of=today, end_date=end_date, direction=s.direction, period_months=s.period_months, relative=rel)
        out["facts"] = v["facts"]
    return out


def kr_branches(kr, months=12):
    """Which branches moved the measure behind a key result (the dashboard's contribution chart), or None."""
    from app.modules.data import dashboard

    sid = service.linked_series_id(kr.org_id, kr.id)
    s = db.session.get(Series, sid) if sid else None
    if s is None or s.dimension is not None:
        return None
    ms = dashboard.measures([x for x in service.org_series(kr.org_id) if x.dataset_id == s.dataset_id])
    return dashboard.build({"kind": "contribution", "measure": str(s.id), "months": months, "branch": None, "title": ""}, ms)


def series_catalog(org_id):
    """The series an AI task may choose from (id, name, unit, direction, latest, dataset)."""
    rows = [{"id": x.id, "name": x.name, "unit": x.unit, "direction": x.direction, "latest": (x.latest[1] if x.latest else None), "dataset": x.dataset.name}
            for x in service.org_series(org_id)]
    return rows or None


def series_levels(series_id, org_id, *, end_date):
    """Three defensible targets for a series up to `end_date` (provider "series.levels")."""
    from app.modules.data import realism

    s = db.session.get(Series, series_id)
    if s is None or s.org_id != org_id or not s.pairs() or end_date is None or end_date <= date.today():
        return None
    start = s.latest[1]
    lv = realism.levels(s.pairs(), start=start, as_of=date.today(), end_date=end_date, direction=s.direction, period_months=s.period_months,
                        relative=False if (s.unit or "").strip() == "%" else None)
    return {"start": start, "unit": s.unit, "direction": s.direction, **(lv or {})} if lv else {"start": start, "unit": s.unit, "direction": s.direction, "insufficient": True}


def series_exists(org_id):
    return True if Series.query.filter_by(org_id=org_id).first() else None


def series_check(series_id, org_id, *, start, target, end_date):
    """Quick verdict for a form that has no key result yet (provider "series.check")."""
    from app.modules.data import realism

    s = db.session.get(Series, series_id) if series_id else None
    if s is None or s.org_id != org_id or end_date is None or end_date <= date.today():
        return None
    v = realism.assess(s.pairs(), start=start, target=target, as_of=date.today(), end_date=end_date, direction=s.direction, period_months=s.period_months,
                       relative=False if (s.unit or "").strip() == "%" else None)
    return {"level": v["level"], "supported": (v.get("range") or {}).get("high"), "series": s}


@bp.app_context_processor
def _template_functions():
    def data_series_options():
        org = g.get("org")
        return service.org_series(org.id) if org else []

    def data_kr_check(kr, end_date):
        sid = service.linked_series_id(kr.org_id, kr.id)
        s = db.session.get(Series, sid) if sid else None
        if s is None or end_date is None or end_date <= date.today():
            return None
        res = reality.check(s, start=kr.current_value, target=kr.target_value, end_date=end_date)
        if res.get("error"):
            return None
        return {"level": res["level"], "tone": res["tone"], "icon": res["icon"], "series": s,
                "url": url_for("data.reality_page", series=s.id, start=kr.current_value, target=kr.target_value, end=end_date.isoformat(), goal=kr.title)}

    def data_kr_series(kr):
        return service.linked_series_id(kr.org_id, kr.id)

    def data_date(iso, style="month"):
        from app.core import formatting
        try:
            return formatting.fmt_date(date.fromisoformat(iso), style)
        except (TypeError, ValueError):
            return "—"

    return {"data_date": data_date, "data_series_options": data_series_options, "data_kr_check": data_kr_check, "data_kr_series": data_kr_series}
