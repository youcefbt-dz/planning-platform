"""Institutional reports, printable management views and CSV exports.

Tabular reports share small data builders; the institution briefing assembles a print-first
management document from the same organization-scoped records and progress calculations.
"""
from __future__ import annotations

import csv
import io
from datetime import date

from flask import Response, abort, current_app, g, render_template, request

from app.core import progress as P
from app.core.formatting import fmt_value
from app.core.i18n import t
from app.core.models import Cycle, Link, Membership, OrgUnit
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
    """Build an institution-wide report from persisted organization records.

    Narrative statements are deterministic summaries of the same figures shown below;
    no synthetic metrics or model-written results are inserted into this report.
    """
    from app.modules.goals.service import compute_indicators
    from app.modules.initiatives.service import compute as compute_initiatives
    from app.modules.orgmap.build import build as build_map

    m = build_map(g.org)
    cycle = current_cycle(g.org)
    all_cycles = Cycle.query.filter_by(org_id=g.org.id).all()
    scope_ids = None
    if cycle:
        # Match the strategy map's scope exactly: selected cycle, its parent, and direct children.
        scope_ids = {cycle.id} | {c.id for c in all_cycles if c.parent_id == cycle.id or c.id == cycle.parent_id}

    # Objective and key-result detail, using the exact status/progress calculations used in the UI.
    goals, key_results, risks, factor_rows = [], [], [], []
    for gl in m["goals"]:
        v, obj = gl["view"], gl["obj"]
        result_by_id = {x["kr"].id: x for x in gl["krs"]}
        kr_items = []
        for kv in v.krs:
            kr = kv.kr
            health = result_by_id.get(kr.id, {})
            status = health.get("status", kv.status)
            item = {
                "title": kr.title, "owner": _name(kr.owner), "start": fmt_value(kr.start_value, kr.unit_label, kr.metric_type),
                "current": fmt_value(kr.current_value, kr.unit_label, kr.metric_type),
                "target": fmt_value(kr.target_value, kr.unit_label, kr.metric_type),
                "progress": kv.progress, "status": status, "unit": kr.unit_label or "—",
                "confidence": kr.confidence, "justification": kr.justification,
                "data_period": kr.data_period, "last_update": kv.last_update, "gap": health.get("gap"),
                "gap_display": fmt_value(health.get("gap"), kr.unit_label, kr.metric_type) if health.get("gap") is not None else "—",
                "projected": health.get("row", {}).get("projected") if health.get("row") else None,
                "projected_display": (fmt_value(health["row"]["projected"]["mid"], kr.unit_label, kr.metric_type)
                                      if health.get("row") and health["row"].get("projected") else "—"),
                "factors": [],
            }
            for factor in kr.factors:
                factor_item = {"title": factor.title, "effect": fmt_value(factor.effect, kr.unit_label, kr.metric_type),
                               "status": factor.status, "certainty": factor.certainty, "due": factor.due}
                item["factors"].append(factor_item)
                factor_rows.append({**factor_item, "goal": obj.title, "result": kr.title})
            kr_items.append(item)
            key_results.append({**item, "goal": obj.title})
            if status in ("at_risk", "off_track"):
                risks.append({"goal": obj.title, "result": kr.title, "status": status,
                              "current": item["current"], "target": item["target"], "gap": item["gap_display"], "gap_value": item["gap"],
                              "projected": item["projected_display"], "owner": item["owner"]})
        goals.append({
            "title": obj.title, "parent": obj.parent.title if obj.parent else "", "owner": _name(obj.owner),
            "unit": obj.unit.name if obj.unit else "—", "perspective": obj.perspective,
            "rationale": obj.rationale, "progress": v.progress, "expected": v.expected,
            "status": gl["status"], "last_update": v.last_update, "key_results": kr_items,
        })

    goal_stats = P.status_counts([x["status"] for x in goals])
    kr_stats = P.status_counts([x["status"] for x in key_results])
    goal_avg = P.weighted_mean((x["progress"], 1.0) for x in goals)
    expected_avg = P.weighted_mean((x["expected"], 1.0) for x in goals)

    # Standing KPIs use their latest recorded period; the report never invents a missing reading.
    indicators = []
    for iv in compute_indicators(g.org):
        indicators.append({"title": iv.ind.name, "owner": _name(iv.ind.owner),
                           "unit": iv.ind.unit.name if iv.ind.unit else "—",
                           "latest": fmt_value(iv.latest, iv.ind.unit_label, iv.ind.metric_type),
                           "target": fmt_value(iv.ind.target_value, iv.ind.unit_label, iv.ind.metric_type),
                           "attainment": iv.attainment, "status": iv.status,
                           "date": iv.latest_date, "previous": fmt_value(iv.previous, iv.ind.unit_label, iv.ind.metric_type) if iv.previous is not None else "—",
                           "delta": iv.delta})
    indicator_stats = P.status_counts([x["status"] for x in indicators])

    # Initiatives are scoped to the current planning year and its periods when a cycle exists.
    initiatives = []
    initiative_views = compute_initiatives(g.org).values() if _on("initiatives") else []
    for iv in initiative_views:
        if scope_ids is not None and iv.obj.cycle_id not in scope_ids:
            continue
        initiatives.append({"title": iv.obj.title, "owner": _name(iv.obj.owner),
                            "unit": iv.obj.unit.name if iv.obj.unit else "—", "state": iv.obj.state,
                            "progress": iv.progress, "status": iv.status, "start": iv.obj.start_date,
                            "end": iv.obj.end_date, "done": iv.done, "total": iv.total,
                            "overdue": iv.overdue, "priority": iv.obj.priority})
    initiatives.sort(key=lambda x: (x["end"] or date.max, x["title"]))
    initiative_stats = P.status_counts([x["status"] for x in initiatives])

    risks.sort(key=lambda x: (0 if x["status"] == "off_track" else 1, -(x["gap_value"] or 0)))
    units_count = OrgUnit.query.filter(OrgUnit.org_id == g.org.id, OrgUnit.kind != "company").count()
    members_count = Membership.query.filter_by(org_id=g.org.id).count()
    result_ids = [kv.kr.id for gl in m["goals"] for kv in gl["view"].krs]
    linked_results = (Link.query.with_entities(Link.source_id).filter(
        Link.org_id == g.org.id, Link.source_type == "key_result", Link.target_type == "series", Link.kind == "measured_by",
        Link.source_id.in_(result_ids)).distinct().count() if result_ids else 0)
    total_results = len(key_results)
    profile = m["profile"]
    reading_text = ""
    if goals:
        reading_text = t("reports.briefing.reading_status", on_track=goal_stats["on_track"] + goal_stats["completed"],
                         at_risk=goal_stats["at_risk"], off_track=goal_stats["off_track"])
        total_risk_count = kr_stats["at_risk"] + kr_stats["off_track"]
        if total_risk_count:
            reading_text += " " + t("reports.briefing.reading_risks", count=total_risk_count)
        else:
            reading_text += " " + t("reports.briefing.reading_clear")
    else:
        reading_text = t("reports.briefing.reading_empty")
    return {
        "kind": "briefing", "m": m, "reading": reading_text, "count": len(goals),
        "initiatives_enabled": _on("initiatives"),
        "cycle": cycle, "profile": profile, "goals": goals, "key_results": key_results,
        "goal_stats": goal_stats, "kr_stats": kr_stats, "goal_avg": goal_avg,
        "expected_avg": expected_avg, "indicators": indicators, "indicator_stats": indicator_stats,
        "initiatives": initiatives, "initiative_stats": initiative_stats,
        "risks": risks[:8], "factor_rows": factor_rows,
        "units_count": units_count, "members_count": members_count,
        "linked_results": linked_results, "total_results": total_results,
    }


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
