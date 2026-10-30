"""Reports are built as plain tables (title, columns, rows) so the same data renders as a printable
page and as a CSV. Adding a report = adding one builder function and one entry in REPORTS."""
from __future__ import annotations

import csv
import io
from datetime import date

from flask import Response, abort, current_app, g, render_template, request

from app.core import progress as P
from app.core.formatting import fmt_date, fmt_number, fmt_percent, fmt_value
from app.core.i18n import t
from app.core.models import Cycle
from app.core.services import current_cycle
from app.modules.reports import bp


def _on(mid: str) -> bool:
    return current_app.extensions["modules"].is_enabled(mid)


def _name(user) -> str:
    return user.name if user else "—"


def build_progress(cycle_id):
    from app.modules.goals.service import compute_objectives, roots

    views = compute_objectives(g.org)
    cycles = {c.id: c for c in Cycle.query.filter_by(org_id=g.org.id).all()}
    scope = {cycle_id} | {c.id for c in cycles.values() if c.parent_id == cycle_id} if cycle_id else None
    rows = []

    def walk(v, depth):
        if scope is not None and v.obj.cycle_id not in scope:
            return
        o = v.obj
        rows.append({"level": depth, "kind": "objective", "title": o.title, "owner": _name(o.owner), "unit": o.unit.name if o.unit else "—",
                     "progress": v.progress, "expected": v.expected, "status": v.status, "current": "", "target": ""})
        for k in v.krs:
            rows.append({"level": depth + 1, "kind": "kr", "title": k.kr.title, "owner": _name(k.kr.owner), "unit": "", "progress": k.progress,
                         "expected": None, "status": k.status, "current": fmt_value(k.kr.current_value, k.kr.unit_label, k.kr.metric_type),
                         "target": fmt_value(k.kr.target_value, k.kr.unit_label, k.kr.metric_type)})
        for c in sorted(v.children, key=lambda x: x.obj.id):
            walk(c, depth + 1)

    for v in roots(views):
        walk(v, 0)
    obj_rows = [r for r in rows if r["kind"] == "objective"]
    stats = P.status_counts([r["status"] for r in obj_rows])
    return {"kind": "progress", "rows": rows, "stats": stats, "count": len(obj_rows),
            "avg": P.weighted_mean((r["progress"], 1.0) for r in obj_rows) or 0.0}


def build_indicators(_):
    from app.modules.goals.service import compute_indicators

    items = compute_indicators(g.org)
    rows = [{"title": v.ind.name, "owner": _name(v.ind.owner), "latest": fmt_value(v.latest, v.ind.unit_label, v.ind.metric_type),
             "target": fmt_value(v.ind.target_value, v.ind.unit_label, v.ind.metric_type),
             "attainment": v.attainment, "status": v.status, "date": v.latest_date} for v in items]
    return {"kind": "indicators", "rows": rows, "stats": P.status_counts([r["status"] for r in rows]), "count": len(rows)}


def build_initiatives(_):
    from app.modules.initiatives.service import compute

    items = sorted(compute(g.org).values(), key=lambda v: v.obj.end_date or date.max)
    rows = [{"title": v.obj.title, "owner": _name(v.obj.owner), "unit": v.obj.unit.name if v.obj.unit else "—", "state": v.obj.state,
             "progress": v.progress, "status": v.status, "start": v.obj.start_date, "end": v.obj.end_date,
             "milestones": f"{v.done}/{v.total}"} for v in items]
    return {"kind": "initiatives", "rows": rows, "stats": P.status_counts([r["status"] for r in rows]), "count": len(rows)}


def build_briefing(_):
    from app.modules.orgmap.build import build as build_map
    from app.modules.orgmap.views import reading

    m = build_map(g.org)
    return {"kind": "briefing", "m": m, "reading": reading(m), "count": len(m["goals"])}


REPORTS = {
    "briefing": {"module": "goals", "icon": "sitemap", "build": build_briefing, "cycle": False, "csv": False},
    "progress": {"module": "goals", "icon": "target-arrow", "build": build_progress, "cycle": True},
    "indicators": {"module": "goals", "icon": "chart-line", "build": build_indicators, "cycle": False},
    "initiatives": {"module": "initiatives", "icon": "rocket", "build": build_initiatives, "cycle": False},
}


def _available():
    return {k: v for k, v in REPORTS.items() if _on(v["module"])}


@bp.get("/")
def index():
    return render_template("reports/index.html", reports=_available())


def _cycle_arg():
    arg = request.args.get("cycle")
    cur = current_cycle(g.org)
    if arg == "all":
        return None
    return int(arg) if (arg or "").isdigit() else (cur.parent_id or cur.id if cur else None)


@bp.get("/<key>")
def show(key):
    spec = _available().get(key) or abort(404)
    cycle_id = _cycle_arg() if spec["cycle"] else None
    data = spec["build"](cycle_id)
    cycles = Cycle.query.filter_by(org_id=g.org.id).order_by(Cycle.start_date.desc()).all()
    return render_template(f"reports/{key}.html", key=key, data=data, cycles=cycles, cycle_id=cycle_id, spec=spec,
                           cycle=next((c for c in cycles if c.id == cycle_id), None), generated=date.today())


@bp.get("/<key>.csv")
def export(key):
    spec = _available().get(key) or abort(404)
    if spec.get("csv") is False:
        abort(404)
    data = spec["build"](_cycle_arg() if spec["cycle"] else None)
    out = io.StringIO()
    w = csv.writer(out)
    if key == "progress":
        w.writerow([t("reports.cols.type"), t("reports.cols.title"), t("reports.cols.owner"), t("reports.cols.unit"), t("reports.cols.progress"),
                    t("reports.cols.expected"), t("common.status"), t("reports.cols.current"), t("reports.cols.target")])
        for r in data["rows"]:
            w.writerow([t("reports.kind." + r["kind"]), r["title"], r["owner"], r["unit"], round(r["progress"] * 100, 1),
                        "" if r["expected"] is None else round(r["expected"] * 100, 1), t("status." + r["status"]), r["current"], r["target"]])
    elif key == "indicators":
        w.writerow([t("reports.cols.title"), t("reports.cols.owner"), t("reports.cols.latest"), t("reports.cols.target"),
                    t("reports.cols.attainment"), t("common.status"), t("reports.cols.as_of")])
        for r in data["rows"]:
            w.writerow([r["title"], r["owner"], r["latest"], r["target"], "" if r["attainment"] is None else round(r["attainment"] * 100, 1),
                        t("status." + r["status"]), r["date"] or ""])
    else:
        w.writerow([t("reports.cols.title"), t("reports.cols.owner"), t("reports.cols.unit"), t("common.state"), t("reports.cols.progress"),
                    t("common.status"), t("reports.cols.start"), t("reports.cols.end"), t("reports.cols.milestones")])
        for r in data["rows"]:
            w.writerow([r["title"], r["owner"], r["unit"], t("initiatives.state." + r["state"]), round(r["progress"] * 100, 1),
                        t("status." + r["status"]), r["start"] or "", r["end"] or "", r["milestones"]])
    body = "﻿" + out.getvalue()  # BOM: Excel opens Arabic UTF-8 correctly
    return Response(body, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={g.org.slug}-{key}-{date.today()}.csv"})
